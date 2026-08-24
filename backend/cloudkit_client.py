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

    body_hash = hashlib.sha256(body).digest()

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
            headers=_sign_request(path, body),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise CloudKitError(
            f"CloudKit request exception: {exc}"
        ) from exc

    try:
        data = response.json()
    except Exception as exc:
        raise CloudKitError(
            f"CloudKit returned HTTP {response.status_code} "
            "with a non-JSON response"
        ) from exc

    if response.status_code >= 400:

        reason = (
            data.get("reason")
            or data.get("serverErrorDescription")
            or data.get("serverErrorCode")
            or "CloudKit request failed"
        )

        raise CloudKitError(
            f"CloudKit HTTP {response.status_code}: {reason}"
        )

    if data.get("serverErrorCode"):
        raise CloudKitError(
            f"CloudKit error: "
            f"{data['serverErrorCode']}: "
            f"{data.get('reason', '')}"
        )

    return data


def _field(
    record: dict[str, Any],
    name: str,
    default=None,
):
    fields = record.get("fields", {})

    value = fields.get(name)

    if not isinstance(value, dict):
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

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):

        try:
            text = value.strip()

            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            return datetime.fromisoformat(
                text
            ).timestamp()

        except Exception:
            return 0.0

    return 0.0


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

            record = item.get("record")

            if record:
                records.append(record)

        marker = result.get(
            "continuationMarker"
        )

        if not marker:
            break

        payload[
            "continuationMarker"
        ] = marker

    return records


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
                "menu_highlights": _field(
                    record,
                    "menuHighlights",
                    [],
                ) or [],
                "image_url": _field(
                    record,
                    "imageURL",
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


def fetch_sightings() -> list[dict[str, Any]]:

    # IMPORTANT:
    # Do NOT filter by timestamp in CloudKit.
    #
    # The current CloudKit schema is rejecting the timestamp
    # filter type. Retrieve the records first and filter them
    # locally instead.

    records = query_records(
        "Sighting"
    )

    cutoff = (
        datetime.now(timezone.utc).timestamp()
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

        # If timestamp is present and parseable,
        # enforce the 3-hour window locally.
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
        key=lambda sighting: _timestamp_value(
            sighting.get("timestamp")
        ),
        reverse=True,
    )

    return sightings


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
        key=lambda sighting: _timestamp_value(
            sighting.get("timestamp")
        ),
        reverse=True,
    )

    return sightings
