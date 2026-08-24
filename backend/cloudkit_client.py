from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


CONTAINER_ID = os.getenv(
    "CLOUDKIT_CONTAINER_ID",
    "iCloud.com.TrueFamily.RoachCoachRadar",
)

ENVIRONMENT = os.getenv(
    "CLOUDKIT_ENVIRONMENT",
    "production",
).lower()

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
        return serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
        )
    except Exception as exc:
        raise CloudKitError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not a valid PEM EC private key"
        ) from exc


def _sign_request(path: str, body: bytes) -> dict[str, str]:
    now = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    body_hash = base64.b64encode(
        hashlib.sha256(body).digest()
    ).decode("ascii")

    message = f"{now}:{body_hash}:{path}".encode("utf-8")

    # Apple CloudKit Server-to-Server authentication uses
    # the ECDSA signature generated from the complete message.
    #
    # IMPORTANT:
    # Keep the DER-encoded ECDSA signature intact.
    # Do NOT convert it to raw r||s bytes.

    signature_der = _get_private_key().sign(
        message,
        ec.ECDSA(hashes.SHA256()),
    )

    signature = base64.b64encode(
        signature_der
    ).decode("ascii")

    return {
        "Content-Type": "application/json",
        "X-Apple-CloudKit-Request-KeyID": KEY_ID,
        "X-Apple-CloudKit-Request-ISO8601Date": now,
        "X-Apple-CloudKit-Request-SignatureV1": signature,
    }


def _endpoint(operation: str) -> str:
    return (
        f"/database/1/"
        f"{quote(CONTAINER_ID, safe='')}/"
        f"{ENVIRONMENT}/"
        f"public/"
        f"{operation}"
    )


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

    url = f"https://api.apple-cloudkit.com{path}"

    response = requests.post(
        url,
        data=body,
        headers=_sign_request(path, body),
        timeout=20,
    )

    try:
        data = response.json()
    except Exception as exc:
        raise CloudKitError(
            f"CloudKit returned HTTP {response.status_code}"
        ) from exc

    if response.status_code >= 400:
        reason = (
            data.get("reason")
            or data.get("serverErrorCode")
            or data.get("serverErrorDescription")
            or "CloudKit request failed"
        )

        raise CloudKitError(
            f"CloudKit HTTP {response.status_code}: {reason}"
        )

    if data.get("serverErrorCode"):
        raise CloudKitError(
            f"CloudKit error: {data['serverErrorCode']}: "
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

    return value.get("value", default)


def query_records(
    record_type: str,
    *,
    filters: list[dict[str, Any]] | None = None,
    sort_by: list[dict[str, Any]] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:

    query: dict[str, Any] = {
        "recordType": record_type,
    }

    if filters:
        query["filterBy"] = filters

    if sort_by:
        query["sortBy"] = sort_by

    payload = {
        "resultsLimit": limit,
        "query": query,
    }

    records: list[dict[str, Any]] = []

    while True:
        result = _request(
            "records/query",
            payload,
        )

        for item in result.get("records", []):
            record = item.get("record")

            if record:
                records.append(record)

        marker = result.get("continuationMarker")

        if not marker:
            break

        payload["continuationMarker"] = marker

    return records


def fetch_trucks() -> list[dict[str, Any]]:
    records = query_records(
        "Truck",
        sort_by=[
            {
                "fieldName": "name",
                "ascending": True,
            }
        ],
    )

    trucks = []

    for record in records:
        record_id = record.get("recordName")

        if not record_id:
            continue

        trucks.append(
            {
                "id": record_id,
                "name": _field(record, "name", ""),
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

    return trucks


def fetch_sightings() -> list[dict[str, Any]]:
    cutoff = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - 3 * 60 * 60,
        timezone.utc,
    )

    cutoff_string = (
        cutoff.isoformat()
        .replace("+00:00", "Z")
    )

    filters = [
        {
            "fieldName": "timestamp",
            "comparator": "GREATER_THAN",
            "fieldValue": {
                "value": cutoff_string,
                "type": "TIMESTAMP",
            },
        }
    ]

    records = query_records(
        "Sighting",
        filters=filters,
        sort_by=[
            {
                "fieldName": "timestamp",
                "ascending": False,
            }
        ],
    )

    sightings = []

    for record in records:
        record_id = record.get("recordName")
        truck_id = _field(record, "truckId")

        if not record_id or not truck_id:
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
                "note": _field(record, "note"),
                "photo_url": _field(
                    record,
                    "photoURL",
                ),
                "confidence_level": _field(
                    record,
                    "confidenceLevel",
                    "Likely",
                ),
                "timestamp": _field(
                    record,
                    "timestamp",
                ),
                "expires_at": _field(
                    record,
                    "expiresAt",
                ),
            }
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
        sort_by=[
            {
                "fieldName": "timestamp",
                "ascending": False,
            }
        ],
    )

    result = []

    for record in records:
        record_id = record.get("recordName")

        if not record_id:
            continue

        result.append(
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
                "timestamp": _field(
                    record,
                    "timestamp",
                ),
                "expires_at": _field(
                    record,
                    "expiresAt",
                ),
            }
        )

    return result
