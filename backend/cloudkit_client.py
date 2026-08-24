from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


CONTAINER_ID = os.getenv(
    "CLOUDKIT_CONTAINER_ID",
    "iCloud.com.TrueFamily.RoachCoachRadar",
).strip()

ENVIRONMENT = os.getenv(
    "CLOUDKIT_ENVIRONMENT",
    "production",
).strip().lower()

KEY_ID = os.getenv("CLOUDKIT_SERVER_KEY_ID")
PRIVATE_KEY = os.getenv("CLOUDKIT_SERVER_PRIVATE_KEY")


class CloudKitError(RuntimeError):
    pass


def _get_private_key():

    if not KEY_ID:
        raise CloudKitError(
            "CLOUDKIT_SERVER_KEY_ID is not configured"
        )

    if not PRIVATE_KEY:
        raise CloudKitError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not configured"
        )

    pem = PRIVATE_KEY.replace("\\n", "\n").strip()

    try:
        private_key = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
        )

    except Exception as exc:
        raise CloudKitError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not a valid PEM EC private key"
        ) from exc

    if not isinstance(
        private_key,
        ec.EllipticCurvePrivateKey,
    ):
        raise CloudKitError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not an EC private key"
        )

    return private_key


def _endpoint(operation: str) -> str:

    return (
        f"/database/1/"
        f"{CONTAINER_ID}/"
        f"{ENVIRONMENT}/"
        f"public/"
        f"{operation}"
    )


def _sign_request(
    path: str,
    body: bytes,
) -> dict[str, str]:

    private_key = _get_private_key()

    request_date = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    body_hash = hashlib.sha256(
        body
    ).digest()

    body_hash_base64 = base64.b64encode(
        body_hash
    ).decode("ascii")

    message = (
        f"{request_date}:"
        f"{body_hash_base64}:"
        f"{path}"
    ).encode("utf-8")

    signature_der = private_key.sign(
        message,
        ec.ECDSA(hashes.SHA256()),
    )

    signature_base64 = base64.b64encode(
        signature_der
    ).decode("ascii")

    return {
        "Content-Type": "application/json",
        "X-Apple-CloudKit-Request-KeyID": KEY_ID,
        "X-Apple-CloudKit-Request-ISO8601Date": request_date,
        "X-Apple-CloudKit-Request-SignatureV1": signature_base64,
    }


def _request(
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:

    path = _endpoint(operation)

    body = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    url = (
        "https://api.apple-cloudkit.com"
        + path
    )

    try:

        response = requests.post(
            url,
            data=body,
            headers=_sign_request(
                path,
                body,
            ),
            timeout=30,
        )

    except requests.RequestException as exc:

        raise CloudKitError(
            f"CloudKit request exception: {exc}"
        ) from exc

    try:

        data = response.json()

    except Exception as exc:

        raise CloudKitError(
            f"CloudKit returned HTTP "
            f"{response.status_code} "
            "with a non-JSON response"
        ) from exc

    if response.status_code >= 400:

        reason = (
            data.get("reason")
            or data.get(
                "serverErrorDescription"
            )
            or data.get(
                "serverErrorCode"
            )
            or "CloudKit request failed"
        )

        raise CloudKitError(
            f"CloudKit HTTP "
            f"{response.status_code}: "
            f"{reason}"
        )

    if data.get("serverErrorCode"):

        raise CloudKitError(
            "CloudKit error: "
            f"{data['serverErrorCode']}: "
            f"{data.get('reason', '')}"
        )

    return data


# =========================================================
# CLOUDKIT FIELD HELPERS
# =========================================================

def _field(
    record: dict[str, Any],
    name: str,
    default=None,
):

    fields = record.get(
        "fields",
        {},
    )

    value = fields.get(name)

    if not isinstance(
        value,
        dict,
    ):
        return default

    return value.get(
        "value",
        default,
    )


def _timestamp_value(
    value: Any,
) -> float:

    if value is None:
        return 0.0

    if isinstance(
        value,
        (int, float),
    ):
        return float(value)

    if isinstance(
        value,
        str,
    ):

        try:

            text = value.strip()

            if text.endswith("Z"):
                text = (
                    text[:-1]
                    + "+00:00"
                )

            return datetime.fromisoformat(
                text
            ).timestamp()

        except Exception:

            return 0.0

    return 0.0


# =========================================================
# CLOUDKIT QUERY
# =========================================================

def query_records(
    record_type: str,
    *,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:

    query: dict[str, Any] = {
        "recordType": record_type,
    }

    if filters:
        query["filterBy"] = filters

    payload: dict[str, Any] = {
        "resultsLimit": limit,
        "query": query,
    }

    records: list[dict[str, Any]] = []

    while True:

        result = _request(
            "records/query",
            payload,
        )

        for item in result.get(
            "records",
            [],
        ):

            record = item.get(
                "record"
            )

            if record:
                records.append(
                    record
                )

        marker = result.get(
            "continuationMarker"
        )

        if not marker:
            break

        payload[
            "continuationMarker"
        ] = marker

    return records


# =========================================================
# TRUCK READ
# =========================================================

def fetch_trucks() -> list[dict[str, Any]]:

    records = query_records(
        "Truck"
    )

    trucks = []

    for record in records:

        record_id = record.get(
            "recordName"
        )

        if not record_id:
            continue

        trucks.append(
            {
                "id": record_id,

                "name": _field(
                    record,
                    "name",
                    "",
                ),

                "cuisine_type": _field(
                    record,
                    "cuisineType",
                    "",
                ),

                "social_links": _field(
                    record,
                    "socialLinks",
                    [],
                ) or [],

                "average_confidence_score": float(
                    _field(
                        record,
                        "averageConfidenceScore",
                        0.0,
                    ) or 0.0
                ),

                "average_wait_minutes": int(
                    _field(
                        record,
                        "averageWaitMinutes",
                        0,
                    ) or 0
                ),

                "rating": float(
                    _field(
                        record,
                        "rating",
                        0.0,
                    ) or 0.0
                ),

                "menu_highlights": _field(
                    record,
                    "menuHighlights",
                    [],
                ) or [],

                "image_url": _field(
                    record,
                    "imageURL",
                ),

                "menu": _field(
                    record,
                    "menu",
                    "",
                ),
            }
        )

    trucks.sort(
        key=lambda truck: str(
            truck.get(
                "name",
                "",
            )
        ).lower()
    )

    return trucks


# =========================================================
# SIGHTINGS READ
# =========================================================

def fetch_sightings() -> list[dict[str, Any]]:

    records = query_records(
        "Sighting"
    )

    cutoff = (
        datetime.now(
            timezone.utc
        ).timestamp()
        - (3 * 60 * 60)
    )

    sightings = []

    for record in records:

        record_id = record.get(
            "recordName"
        )

        truck_id = _field(
            record,
            "truckId",
        )

        if not record_id or not truck_id:
            continue

        timestamp = _field(
            record,
            "timestamp",
        )

        timestamp_epoch = _timestamp_value(
            timestamp
        )

        if timestamp_epoch > 0:

            if timestamp_epoch < cutoff:
                continue

        sightings.append(
            {
                "id": record_id,

                "truck_id": truck_id,

                "latitude": float(
                    _field(
                        record,
                        "latitude",
                        0.0,
                    ) or 0.0
                ),

                "longitude": float(
                    _field(
                        record,
                        "longitude",
                        0.0,
                    ) or 0.0
                ),

                "note": _field(
                    record,
                    "note",
                ),

                "photo_url": _field(
                    record,
                    "photoURL",
                ),

                "confidence_level": _field(
                    record,
                    "confidenceLevel",
                    "Likely",
                ),

                "timestamp": timestamp,

                "expires_at": _field(
                    record,
                    "expiresAt",
                ),
            }
        )

    sightings.sort(
        key=lambda sighting:
            _timestamp_value(
                sighting.get(
                    "timestamp"
                )
            ),
        reverse=True,
    )

    return sightings


# =========================================================
# TRUCK SIGHTINGS READ
# =========================================================

def fetch_sightings_for_truck(
    truck_id: str,
) -> list[dict[str, Any]]:

    filters = [
        {
            "fieldName": "truckId",

            "comparator": "EQUALS",

            "fieldValue": {
                "value": truck_id,
                "type": "STRING",
            },
        }
    ]

    records = query_records(
        "Sighting",
        filters=filters,
    )

    sightings = []

    for record in records:

        record_id = record.get(
            "recordName"
        )

        if not record_id:
            continue

        timestamp = _field(
            record,
            "timestamp",
        )

        sightings.append(
            {
                "id": record_id,

                "truck_id": _field(
                    record,
                    "truckId",
                ),

                "latitude": float(
                    _field(
                        record,
                        "latitude",
                        0.0,
                    ) or 0.0
                ),

                "longitude": float(
                    _field(
                        record,
                        "longitude",
                        0.0,
                    ) or 0.0
                ),

                "note": _field(
                    record,
                    "note",
                ),

                "photo_url": _field(
                    record,
                    "photoURL",
                ),

                "confidence_level": _field(
                    record,
                    "confidenceLevel",
                    "Likely",
                ),

                "timestamp": timestamp,

                "expires_at": _field(
                    record,
                    "expiresAt",
                ),
            }
        )

    sightings.sort(
        key=lambda sighting:
            _timestamp_value(
                sighting.get(
                    "timestamp"
                )
            ),
        reverse=True,
    )

    return sightings


# =========================================================
# TRUCK IMPORT / UPSERT
# =========================================================

def _string(value: Any) -> str:

    if value is None:
        return ""

    return str(value).strip()


def _double(value: Any) -> float:

    if value is None:
        return 0.0

    try:
        return float(value)

    except Exception:
        return 0.0


def _int64(value: Any) -> int:

    if value is None:
        return 0

    try:
        return int(value)

    except Exception:
        return 0


def _string_list(value: Any) -> list[str]:

    if value is None:
        return []

    if isinstance(
        value,
        str,
    ):

        if not value.strip():
            return []

        return [
            value.strip()
        ]

    if isinstance(
        value,
        list,
    ):

        return [
            str(item).strip()
            for item in value
            if item is not None
            and str(item).strip()
        ]

    return []


def _normalize_truck(
    truck: dict[str, Any],
) -> dict[str, Any]:

    name = _string(
        truck.get("name")
    )

    if not name:
        raise ValueError(
            "Truck is missing required name"
        )

    return {
        "name": name,

        "cuisineType": _string(
            truck.get(
                "cuisineType"
            )
        ),

        "imageURL": _string(
            truck.get(
                "imageURL"
            )
        ),

        "menu": _string(
            truck.get(
                "menu"
            )
        ),

        "menuHighlights": _string_list(
            truck.get(
                "menuHighlights"
            )
        ),

        "socialLinks": _string_list(
            truck.get(
                "socialLinks"
            )
        ),

        "averageConfidenceScore":
            _double(
                truck.get(
                    "averageConfidenceScore",
                    0.0,
                )
            ),

        "averageWaitMinutes":
            _int64(
                truck.get(
                    "averageWaitMinutes",
                    0,
                )
            ),

        "rating":
            _double(
                truck.get(
                    "rating",
                    0.0,
                )
            ),
    }


def _truck_record_name(
    name: str,
) -> str:

    normalized = (
        name
        .strip()
        .casefold()
    )

    digest = hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        "truck_"
        + digest[:32]
    )


def upsert_trucks(
    trucks: list[dict[str, Any]],
    chunk_size: int = 50,
) -> list[dict[str, Any]]:

    if not isinstance(
        trucks,
        list,
    ):
        raise ValueError(
            "Truck import must be a list"
        )

    normalized_trucks = [
        _normalize_truck(
            truck
        )
        for truck in trucks
    ]

    responses = []

    for start in range(
        0,
        len(normalized_trucks),
        chunk_size,
    ):

        chunk = normalized_trucks[
            start:
            start + chunk_size
        ]

        operations = []

        for truck in chunk:

            record_name = (
                _truck_record_name(
                    truck["name"]
                )
            )

            fields = {

                "name": {
                    "value":
                        truck["name"]
                },

                "cuisineType": {
                    "value":
                        truck[
                            "cuisineType"
                        ]
                },

                "imageURL": {
                    "value":
                        truck[
                            "imageURL"
                        ]
                },

                "menu": {
                    "value":
                        truck[
                            "menu"
                        ]
                },

                "menuHighlights": {
                    "value":
                        truck[
                            "menuHighlights"
                        ]
                },

                "socialLinks": {
                    "value":
                        truck[
                            "socialLinks"
                        ]
                },

                "averageConfidenceScore": {
                    "value":
                        truck[
                            "averageConfidenceScore"
                        ]
                },

                "averageWaitMinutes": {
                    "value":
                        truck[
                            "averageWaitMinutes"
                        ]
                },

                "rating": {
                    "value":
                        truck[
                            "rating"
                        ]
                },
            }

            operations.append(
                {
                    "operationType":
                        "forceReplace",

                    "record": {

                        "recordName":
                            record_name,

                        "recordType":
                            "Truck",

                        "fields":
                            fields,
                    },
                }
            )

        result = _request(
            "records/modify",
            {
                "operations":
                    operations
            },
        )

        responses.append(
            result
        )

    return responses
