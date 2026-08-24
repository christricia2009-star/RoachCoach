"""
Roach Coach Radar — CloudKit Bridge

CloudKit backend bridge for:
    iCloud.com.TrueFamily.RoachCoachRadar

Vercel environment variables:

    CLOUDKIT_CONTAINER_ID
    CLOUDKIT_SERVER_KEY_ID
    CLOUDKIT_SERVER_PRIVATE_KEY
    CLOUDKIT_ENVIRONMENT

Supported CloudKit record types:

    Truck
    Sighting

This module uses Apple's CloudKit Web Services server-to-server
authentication and talks directly to the PUBLIC database.

The bridge is intentionally isolated from main.py so the FastAPI
routes can use CloudKit without knowing the authentication details.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import jwt


# ============================================================
# CONFIGURATION
# ============================================================

CLOUDKIT_CONTAINER_ID = os.getenv(
    "CLOUDKIT_CONTAINER_ID",
    "iCloud.com.TrueFamily.RoachCoachRadar",
).strip()

CLOUDKIT_SERVER_KEY_ID = os.getenv(
    "CLOUDKIT_SERVER_KEY_ID",
    "",
).strip()

CLOUDKIT_SERVER_PRIVATE_KEY = os.getenv(
    "CLOUDKIT_SERVER_PRIVATE_KEY",
    "",
)

CLOUDKIT_ENVIRONMENT = os.getenv(
    "CLOUDKIT_ENVIRONMENT",
    "production",
).strip().lower()


# ============================================================
# CLOUDKIT URL
# ============================================================

if CLOUDKIT_ENVIRONMENT == "development":
    CLOUDKIT_DATABASE = "development"
else:
    CLOUDKIT_DATABASE = "production"


CLOUDKIT_BASE_URL = (
    "https://api.apple-cloudkit.com/database/1/"
    f"{CLOUDKIT_CONTAINER_ID}/"
    f"{CLOUDKIT_DATABASE}/public"
)


# ============================================================
# ERRORS
# ============================================================

class CloudKitBridgeError(Exception):
    """Base CloudKit bridge exception."""


class CloudKitConfigurationError(CloudKitBridgeError):
    """CloudKit configuration is missing or invalid."""


class CloudKitAPIError(CloudKitBridgeError):
    """CloudKit returned an API error."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Any] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


# ============================================================
# CONFIGURATION HELPERS
# ============================================================

def _get_private_key() -> str:
    """
    Get the CloudKit server private key.

    Supports:
        1. PEM directly in the environment variable.
        2. Literal \\n characters inside the environment variable.
        3. A file path supplied as the variable value.
    """

    value = CLOUDKIT_SERVER_PRIVATE_KEY.strip()

    if not value:
        raise CloudKitConfigurationError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not configured."
        )

    # Allow an actual file path.
    if (
        not value.startswith("-----BEGIN")
        and os.path.isfile(value)
    ):
        with open(
            value,
            "r",
            encoding="utf-8",
        ) as file:
            value = file.read().strip()

    # Vercel can contain literal \n characters.
    value = value.replace("\\n", "\n")

    return value


def _validate_configuration() -> None:
    if not CLOUDKIT_CONTAINER_ID:
        raise CloudKitConfigurationError(
            "CLOUDKIT_CONTAINER_ID is not configured."
        )

    if not CLOUDKIT_SERVER_KEY_ID:
        raise CloudKitConfigurationError(
            "CLOUDKIT_SERVER_KEY_ID is not configured."
        )

    _get_private_key()


# ============================================================
# CLOUDKIT AUTHENTICATION
# ============================================================

def _create_server_token() -> str:
    """
    Create the CloudKit server-to-server JWT.

    CloudKit server-to-server keys use the CloudKit key ID as
    the JWT subject and the key ID as the JWT header kid.

    The signing key must be the ES256 private key supplied by
    Apple's CloudKit server-to-server key configuration.
    """

    _validate_configuration()

    private_key = _get_private_key()

    now = int(time.time())

    payload = {
        "sub": CLOUDKIT_SERVER_KEY_ID,
        "iat": now,
        "exp": now + 3600,
    }

    headers = {
        "kid": CLOUDKIT_SERVER_KEY_ID,
        "typ": "JWT",
    }

    try:
        token = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers=headers,
        )
    except Exception as exc:
        raise CloudKitConfigurationError(
            "Unable to create CloudKit authentication token: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {_create_server_token()}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ============================================================
# HTTP
# ============================================================

def _request(
    method: str,
    endpoint: str,
    body: Optional[dict[str, Any]] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:

    url = (
        CLOUDKIT_BASE_URL.rstrip("/")
        + "/"
        + endpoint.lstrip("/")
    )

    try:
        response = httpx.request(
            method=method,
            url=url,
            headers=_headers(),
            json=body,
            timeout=timeout,
        )
    except Exception as exc:
        raise CloudKitAPIError(
            "CloudKit network request failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        response_data = response.json()
    except Exception:
        response_data = response.text

    if response.status_code < 200 or response.status_code >= 300:

        detail = response_data

        if isinstance(response_data, dict):
            detail = (
                response_data.get("reason")
                or response_data.get("message")
                or response_data.get("errors")
                or response_data
            )

        raise CloudKitAPIError(
            (
                f"CloudKit HTTP {response.status_code}: "
                f"{detail}"
            ),
            status_code=response.status_code,
            response_data=response_data,
        )

    if isinstance(response_data, dict):
        return response_data

    return {}


# ============================================================
# FIELD HELPERS
# ============================================================

def _string_field(value: Any) -> dict[str, Any]:
    return {
        "value": str(value),
    }


def _double_field(value: Any) -> dict[str, Any]:
    return {
        "value": float(value),
    }


def _int_field(value: Any) -> dict[str, Any]:
    return {
        "value": int(value),
    }


def _bool_field(value: Any) -> dict[str, Any]:
    return {
        "value": bool(value),
    }


def _timestamp_field(
    value: datetime,
) -> dict[str, Any]:

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    value = value.astimezone(timezone.utc)

    return {
        "value": value.isoformat(),
    }


def _reference_field(
    record_name: str,
) -> dict[str, Any]:

    return {
        "value": {
            "recordName": str(record_name),
            "action": "NONE",
        }
    }


def _field_value(
    fields: dict[str, Any],
    name: str,
    default: Any = None,
) -> Any:

    field = fields.get(name)

    if not isinstance(field, dict):
        return default

    return field.get(
        "value",
        default,
    )


# ============================================================
# RECORD HELPERS
# ============================================================

def _make_record(
    record_type: str,
    record_name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:

    return {
        "record": {
            "recordType": record_type,
            "recordName": record_name,
            "fields": fields,
        }
    }


def _new_record_name(
    prefix: str,
) -> str:

    return (
        f"{prefix}_"
        f"{uuid.uuid4().hex}"
    )


# ============================================================
# HEALTH
# ============================================================

def health_check() -> dict[str, Any]:
    """
    CloudKit connectivity test.

    This performs a small Truck query rather than merely checking
    that environment variables exist.
    """

    try:

        _validate_configuration()

        records = query_records(
            "Truck",
            limit=1,
        )

        return {
            "status": "ok",
            "cloudkit": "connected",
            "container": CLOUDKIT_CONTAINER_ID,
            "environment": CLOUDKIT_ENVIRONMENT,
            "database": "public",
            "truck_query": "ok",
            "records_returned": len(records),
        }

    except Exception as exc:

        return {
            "status": "error",
            "cloudkit": "error",
            "container": CLOUDKIT_CONTAINER_ID,
            "environment": CLOUDKIT_ENVIRONMENT,
            "database": "public",
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
        }


# ============================================================
# GENERIC QUERY
# ============================================================

def query_records(
    record_type: str,
    *,
    predicate: Optional[dict[str, Any]] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:

    limit = max(
        1,
        min(int(limit), 200),
    )

    query: dict[str, Any] = {
        "recordType": record_type,
    }

    if predicate:
        query["filterBy"] = predicate

    body = {
        "query": query,
        "resultsLimit": limit,
    }

    result = _request(
        "POST",
        "records/query",
        body,
    )

    return result.get(
        "records",
        [],
    )


# ============================================================
# LOOKUP
# ============================================================

def lookup_record(
    record_type: str,
    record_name: str,
) -> Optional[dict[str, Any]]:

    result = _request(
        "POST",
        "records/lookup",
        {
            "records": [
                {
                    "recordName": str(record_name),
                    "desiredKeys": [
                        "*"
                    ],
                }
            ]
        },
    )

    records = result.get(
        "records",
        [],
    )

    if not records:
        return None

    return records[0]


# ============================================================
# TRUCKS
# ============================================================

def get_trucks(
    limit: int = 200,
) -> list[dict[str, Any]]:

    records = query_records(
        "Truck",
        limit=limit,
    )

    trucks = []

    for record in records:

        fields = record.get(
            "fields",
            {},
        )

        trucks.append(
            {
                "id": record.get(
                    "recordName"
                ),
                "name": _field_value(
                    fields,
                    "name",
                    "Unknown Truck",
                ),
                "cuisine_type": _field_value(
                    fields,
                    "cuisine_type",
                ),
                "social_links": _field_value(
                    fields,
                    "social_links",
                    [],
                ),
                "average_confidence_score": float(
                    _field_value(
                        fields,
                        "average_confidence_score",
                        0.0,
                    )
                    or 0.0
                ),
                "menu_highlights": _field_value(
                    fields,
                    "menu_highlights",
                    [],
                ),
                "image_url": _field_value(
                    fields,
                    "image_url",
                ),
            }
        )

    trucks.sort(
        key=lambda truck: (
            truck.get("name")
            or ""
        ).lower()
    )

    return trucks


def get_truck(
    truck_id: str,
) -> Optional[dict[str, Any]]:

    record = lookup_record(
        "Truck",
        truck_id,
    )

    if not record:
        return None

    fields = record.get(
        "fields",
        {},
    )

    return {
        "id": record.get(
            "recordName"
        ),
        "name": _field_value(
            fields,
            "name",
            "Unknown Truck",
        ),
        "cuisine_type": _field_value(
            fields,
            "cuisine_type",
        ),
        "social_links": _field_value(
            fields,
            "social_links",
            [],
        ),
        "average_confidence_score": float(
            _field_value(
                fields,
                "average_confidence_score",
                0.0,
            )
            or 0.0
        ),
        "menu_highlights": _field_value(
            fields,
            "menu_highlights",
            [],
        ),
        "image_url": _field_value(
            fields,
            "image_url",
        ),
    }


# ============================================================
# SIGHTINGS
# ============================================================

def _parse_timestamp(
    value: Any,
) -> Optional[datetime]:

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        result = value
    else:
        text_value = str(value)

        try:
            result = datetime.fromisoformat(
                text_value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=timezone.utc
        )

    return result.astimezone(
        timezone.utc
    )


def _sighting_from_record(
    record: dict[str, Any],
) -> dict[str, Any]:

    fields = record.get(
        "fields",
        {},
    )

    truck_id = _field_value(
        fields,
        "truck_id",
    )

    # Support both a normal STRING field and a
    # CloudKit REFERENCE field.
    if isinstance(
        truck_id,
        dict,
    ):
        truck_id = truck_id.get(
            "recordName"
        )

    reported_by_user_id = _field_value(
        fields,
        "reported_by_user_id",
    )

    if isinstance(
        reported_by_user_id,
        dict,
    ):
        reported_by_user_id = (
            reported_by_user_id.get(
                "recordName"
            )
        )

    return {
        "id": record.get(
            "recordName"
        ),
        "truck_id": truck_id,
        "latitude": float(
            _field_value(
                fields,
                "latitude",
                0.0,
            )
            or 0.0
        ),
        "longitude": float(
            _field_value(
                fields,
                "longitude",
                0.0,
            )
            or 0.0
        ),
        "reported_by_user_id": (
            reported_by_user_id
        ),
        "photo_url": _field_value(
            fields,
            "photo_url",
        ),
        "note": _field_value(
            fields,
            "note",
        ),
        "timestamp": _field_value(
            fields,
            "timestamp",
        ),
        "confidence_level": _field_value(
            fields,
            "confidence_level",
            "scheduled",
        ),
        "expires_at": _field_value(
            fields,
            "expires_at",
        ),
        "source": _field_value(
            fields,
            "source",
            "unknown",
        ),
    }


def get_sightings(
    *,
    truck_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:

    # We intentionally query all active-ish records and perform
    # expiry filtering in Python. This avoids depending on a
    # particular CloudKit query index configuration.
    records = query_records(
        "Sighting",
        limit=limit,
    )

    now = datetime.now(
        timezone.utc
    )

    sightings = []

    for record in records:

        sighting = _sighting_from_record(
            record
        )

        if truck_id:
            if str(
                sighting.get("truck_id")
            ) != str(truck_id):
                continue

        expires_at = _parse_timestamp(
            sighting.get(
                "expires_at"
            )
        )

        if (
            expires_at is not None
            and expires_at <= now
        ):
            continue

        sightings.append(
            sighting
        )

    sightings.sort(
        key=lambda item: (
            item.get("timestamp")
            or ""
        ),
        reverse=True,
    )

    return sightings


def get_active_sightings(
    limit: int = 200,
) -> list[dict[str, Any]]:

    return get_sightings(
        limit=limit
    )


# ============================================================
# CREATE SIGHTING
# ============================================================

def create_sighting(
    *,
    truck_id: str,
    latitude: float,
    longitude: float,
    reported_by_user_id: Optional[str] = None,
    photo_url: Optional[str] = None,
    note: Optional[str] = None,
    confidence_level: str = "likely",
    expires_at: Optional[datetime] = None,
    source: str = "crowdsource",
    record_name: Optional[str] = None,
) -> dict[str, Any]:

    now = datetime.now(
        timezone.utc
    )

    if expires_at is None:
        expires_at = (
            now
            + timedelta(hours=3)
        )

    record_name = (
        record_name
        or _new_record_name(
            "sighting"
        )
    )

    fields: dict[str, Any] = {
        "truck_id": _string_field(
            truck_id
        ),
        "latitude": _double_field(
            latitude
        ),
        "longitude": _double_field(
            longitude
        ),
        "timestamp": _timestamp_field(
            now
        ),
        "confidence_level": _string_field(
            confidence_level
        ),
        "expires_at": _timestamp_field(
            expires_at
        ),
        "source": _string_field(
            source
        ),
    }

    if reported_by_user_id:
        fields[
            "reported_by_user_id"
        ] = _string_field(
            reported_by_user_id
        )

    if photo_url:
        fields[
            "photo_url"
        ] = _string_field(
            photo_url
        )

    if note:
        fields[
            "note"
        ] = _string_field(
            note
        )

    result = _request(
        "POST",
        "records/modify",
        {
            "operations": [
                _make_record(
                    "Sighting",
                    record_name,
                    fields,
                )
            ]
        },
    )

    records = result.get(
        "records",
        [],
    )

    if not records:
        raise CloudKitAPIError(
            "CloudKit did not return the created Sighting."
        )

    return _sighting_from_record(
        records[0]
    )


# ============================================================
# RADAR WRITE-THROUGH
# ============================================================

def write_radar_sighting(
    *,
    truck_id: str,
    latitude: float,
    longitude: float,
    confidence_level: str,
    source: str,
    note: Optional[str] = None,
    source_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> dict[str, Any]:

    if not truck_id:
        raise CloudKitBridgeError(
            "truck_id is required to create a CloudKit Sighting."
        )

    if timestamp is None:
        timestamp = datetime.now(
            timezone.utc
        )

    if expires_at is None:
        expires_at = (
            timestamp
            + timedelta(hours=3)
        )

    combined_note = note

    if source_id:
        source_suffix = (
            f"[source_id={source_id}]"
        )

        if combined_note:
            combined_note = (
                f"{combined_note} "
                f"{source_suffix}"
            )
        else:
            combined_note = source_suffix

    return create_sighting(
        truck_id=str(truck_id),
        latitude=latitude,
        longitude=longitude,
        note=combined_note,
        confidence_level=confidence_level,
        expires_at=expires_at,
        source=source,
    )


# ============================================================
# GENERIC RECORD WRITE
# ============================================================

def save_record(
    *,
    record_type: str,
    record_name: Optional[str] = None,
    fields: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:

    record_name = (
        record_name
        or _new_record_name(
            record_type.lower()
        )
    )

    result = _request(
        "POST",
        "records/modify",
        {
            "operations": [
                _make_record(
                    record_type,
                    record_name,
                    fields or {},
                )
            ]
        },
    )

    records = result.get(
        "records",
        [],
    )

    if not records:
        raise CloudKitAPIError(
            f"CloudKit did not return the "
            f"{record_type} record."
        )

    return records[0]


# ============================================================
# DELETE
# ============================================================

def delete_record(
    record_type: str,
    record_name: str,
) -> bool:

    result = _request(
        "POST",
        "records/modify",
        {
            "operations": [
                {
                    "operationType": "delete",
                    "record": {
                        "recordType": record_type,
                        "recordName": str(
                            record_name
                        ),
                    },
                }
            ]
        },
    )

    return bool(
        result.get(
            "records"
        )
    )


# ============================================================
# CONFIGURATION STATUS
# ============================================================

def configuration_status() -> dict[str, Any]:

    return {
        "container": CLOUDKIT_CONTAINER_ID,
        "environment": CLOUDKIT_ENVIRONMENT,
        "database": "public",
        "key_id_configured": bool(
            CLOUDKIT_SERVER_KEY_ID
        ),
        "private_key_configured": bool(
            CLOUDKIT_SERVER_PRIVATE_KEY
        ),
        "base_url": CLOUDKIT_BASE_URL,
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "CloudKitBridgeError",
    "CloudKitConfigurationError",
    "CloudKitAPIError",
    "CLOUDKIT_CONTAINER_ID",
    "CLOUDKIT_ENVIRONMENT",
    "CLOUDKIT_BASE_URL",
    "health_check",
    "configuration_status",
    "query_records",
    "lookup_record",
    "get_trucks",
    "get_truck",
    "get_sightings",
    "get_active_sightings",
    "create_sighting",
    "write_radar_sighting",
    "save_record",
    "delete_record",
]
