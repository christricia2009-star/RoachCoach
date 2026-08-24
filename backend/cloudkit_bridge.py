"""
CloudKit Bridge
Roach Coach Radar

Server-to-server CloudKit Web Services bridge.

Required environment variables:

    CLOUDKIT_CONTAINER_ID
    CLOUDKIT_SERVER_KEY_ID
    CLOUDKIT_SERVER_PRIVATE_KEY
    CLOUDKIT_ENVIRONMENT

Example:

    CLOUDKIT_CONTAINER_ID=iCloud.com.TrueFamily.RoachCoachRadar
    CLOUDKIT_SERVER_KEY_ID=XXXXXXXXXX
    CLOUDKIT_SERVER_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----
    ...
    -----END EC PRIVATE KEY-----"
    CLOUDKIT_ENVIRONMENT=production

IMPORTANT:
CloudKit server-to-server keys access the PUBLIC database.
"""

import os
import json
import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


# ============================================================
# CONFIGURATION
# ============================================================

CLOUDKIT_BASE_URL = "https://api.apple-cloudkit.com"

CLOUDKIT_CONTAINER_ID = os.getenv(
    "CLOUDKIT_CONTAINER_ID"
)

CLOUDKIT_SERVER_KEY_ID = os.getenv(
    "CLOUDKIT_SERVER_KEY_ID"
)

CLOUDKIT_SERVER_PRIVATE_KEY = os.getenv(
    "CLOUDKIT_SERVER_PRIVATE_KEY"
)

CLOUDKIT_ENVIRONMENT = os.getenv(
    "CLOUDKIT_ENVIRONMENT",
    "production",
).lower()


# ============================================================
# VALIDATION
# ============================================================

def _validate_configuration() -> None:
    missing = []

    if not CLOUDKIT_CONTAINER_ID:
        missing.append("CLOUDKIT_CONTAINER_ID")

    if not CLOUDKIT_SERVER_KEY_ID:
        missing.append("CLOUDKIT_SERVER_KEY_ID")

    if not CLOUDKIT_SERVER_PRIVATE_KEY:
        missing.append("CLOUDKIT_SERVER_PRIVATE_KEY")

    if not CLOUDKIT_ENVIRONMENT:
        missing.append("CLOUDKIT_ENVIRONMENT")

    if missing:
        raise RuntimeError(
            "Missing CloudKit environment variable(s): "
            + ", ".join(missing)
        )

    if CLOUDKIT_ENVIRONMENT not in (
        "development",
        "production",
    ):
        raise RuntimeError(
            "CLOUDKIT_ENVIRONMENT must be "
            "'development' or 'production'."
        )


# ============================================================
# PRIVATE KEY LOADING
# ============================================================

def _load_private_key():
    """
    Load the EC private key from CLOUDKIT_SERVER_PRIVATE_KEY.

    Supports PEM stored directly in the environment variable.
    Also handles escaped \\n characters, which are common when
    storing multiline secrets in Vercel.
    """

    _validate_configuration()

    key_text = CLOUDKIT_SERVER_PRIVATE_KEY

    if not key_text:
        raise RuntimeError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is empty."
        )

    # Vercel/environment variables sometimes contain literal
    # backslash-n characters rather than real newlines.
    key_text = key_text.replace("\\n", "\n").strip()

    key_bytes = key_text.encode("utf-8")

    try:
        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
        )
    except Exception as exc:
        raise RuntimeError(
            "Unable to load CLOUDKIT_SERVER_PRIVATE_KEY. "
            "Make sure the complete EC private key PEM was "
            "copied into the environment variable, including "
            "BEGIN/END lines."
        ) from exc

    if not isinstance(
        private_key,
        ec.EllipticCurvePrivateKey,
    ):
        raise RuntimeError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is not an EC private key."
        )

    return private_key


# ============================================================
# DATE
# ============================================================

def _cloudkit_date() -> str:
    """
    CloudKit requires ISO-8601 UTC time without milliseconds.

    Example:
        2026-08-24T16:30:00Z
    """

    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ============================================================
# REQUEST BODY HASH
# ============================================================

def _body_hash(body: bytes) -> str:
    """
    CloudKit signature uses the Base64 encoded SHA-256
    hash of the request body.
    """

    digest = hashlib.sha256(body).digest()

    return base64.b64encode(digest).decode("ascii")


# ============================================================
# SIGNATURE
# ============================================================

def _sign_request(
    date_string: str,
    body: bytes,
    path: str,
) -> str:
    """
    Create the CloudKit server-to-server ECDSA signature.

    CloudKit signing payload:

        [date]:[base64 SHA256(body)]:[web service path]

    Apple requires the resulting ECDSA signature to be
    Base64 encoded.
    """

    private_key = _load_private_key()

    body_hash = _body_hash(body)

    message = (
        f"{date_string}:"
        f"{body_hash}:"
        f"{path}"
    )

    signature = private_key.sign(
        message.encode("utf-8"),
        ec.ECDSA(hashes.SHA256()),
    )

    return base64.b64encode(signature).decode("ascii")


# ============================================================
# PATH BUILDER
# ============================================================

def _path(operation: str) -> str:
    """
    Build the CloudKit Web Services path.

    Example:

        /database/1/iCloud.com.TrueFamily.RoachCoachRadar/
        production/public/records/modify
    """

    _validate_configuration()

    container = CLOUDKIT_CONTAINER_ID.strip()

    if not container.startswith("iCloud."):
        raise RuntimeError(
            "CLOUDKIT_CONTAINER_ID should normally begin with "
            "'iCloud.'. Received: "
            + container
        )

    operation = operation.lstrip("/")

    return (
        f"/database/1/"
        f"{container}/"
        f"{CLOUDKIT_ENVIRONMENT}/"
        f"public/"
        f"{operation}"
    )


# ============================================================
# GENERIC REQUEST
# ============================================================

def cloudkit_request(
    operation: str,
    body: Optional[dict[str, Any]] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Make an authenticated CloudKit Web Services request.
    """

    _validate_configuration()

    path = _path(operation)

    if body is None:
        body = {}

    body_bytes = json.dumps(
        body,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    date_string = _cloudkit_date()

    signature = _sign_request(
        date_string,
        body_bytes,
        path,
    )

    headers = {
        "Content-Type": "text/plain",
        "Accept": "application/json",

        "X-Apple-CloudKit-Request-KeyID":
            CLOUDKIT_SERVER_KEY_ID,

        "X-Apple-CloudKit-Request-ISO8601Date":
            date_string,

        "X-Apple-CloudKit-Request-SignatureV1":
            signature,
    }

    url = CLOUDKIT_BASE_URL + path

    response = requests.post(
        url,
        headers=headers,
        data=body_bytes,
        timeout=timeout,
    )

    # CloudKit normally returns JSON even for errors.
    try:
        response_json = response.json()
    except ValueError:
        response_json = {
            "error": response.text
        }

    if not response.ok:
        raise RuntimeError(
            "CloudKit request failed "
            f"(HTTP {response.status_code}): "
            f"{json.dumps(response_json)}"
        )

    return response_json


# ============================================================
# HEALTH / AUTH TEST
# ============================================================

def cloudkit_test() -> dict[str, Any]:
    """
    Test the server-to-server credentials by querying the
    public database.

    This does NOT modify data.
    """

    result = cloudkit_request(
        "records/query",
        {
            "query": {
                "recordType": "Truck",
                "filterBy": [],
            },
            "resultsLimit": 1,
        },
    )

    return result


# ============================================================
# QUERY RECORDS
# ============================================================

def query_records(
    record_type: str,
    filters: Optional[list[dict[str, Any]]] = None,
    results_limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Query records from the CloudKit public database.
    """

    if not record_type:
        raise ValueError(
            "record_type is required."
        )

    if filters is None:
        filters = []

    body = {
        "query": {
            "recordType": record_type,
            "filterBy": filters,
        },
        "resultsLimit": min(
            max(results_limit, 1),
            200,
        ),
    }

    result = cloudkit_request(
        "records/query",
        body,
    )

    return result.get("records", [])


# ============================================================
# QUERY ALL RECORDS
# ============================================================

def query_all_records(
    record_type: str,
    filters: Optional[list[dict[str, Any]]] = None,
    batch_size: int = 200,
) -> list[dict[str, Any]]:
    """
    Query records using CloudKit cursors.

    Continues until CloudKit stops returning a continuation
    cursor.
    """

    if filters is None:
        filters = []

    all_records: list[dict[str, Any]] = []

    cursor: Optional[str] = None

    while True:

        query: dict[str, Any] = {
            "recordType": record_type,
            "filterBy": filters,
        }

        if cursor:
            body = {
                "resultsLimit": min(
                    max(batch_size, 1),
                    200,
                ),
                "continuationMarker": cursor,
            }
        else:
            body = {
                "query": query,
                "resultsLimit": min(
                    max(batch_size, 1),
                    200,
                ),
            }

        result = cloudkit_request(
            "records/query",
            body,
        )

        records = result.get(
            "records",
            [],
        )

        all_records.extend(records)

        cursor = result.get(
            "continuationMarker"
        )

        if not cursor:
            break

    return all_records


# ============================================================
# LOOKUP RECORDS
# ============================================================

def lookup_records(
    record_type: str,
    record_names: list[str],
) -> list[dict[str, Any]]:
    """
    Lookup specific CloudKit records by recordName.
    """

    if not record_names:
        return []

    records = [
        {
            "recordType": record_type,
            "recordName": name,
        }
        for name in record_names
    ]

    result = cloudkit_request(
        "records/lookup",
        {
            "records": records,
        },
    )

    return result.get(
        "records",
        [],
    )


# ============================================================
# CREATE / UPDATE RECORDS
# ============================================================

def save_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Save/create/update CloudKit records.

    Each record should look like:

        {
            "recordType": "Truck",
            "recordName": "truck_123",
            "fields": {
                "name": {
                    "value": "Taco Truck"
                }
            }
        }
    """

    if not records:
        return {
            "records": []
        }

    return cloudkit_request(
        "records/modify",
        {
            "operations": [
                {
                    "operationType": "create",
                    "record": record,
                }
                for record in records
            ]
        },
    )


# ============================================================
# UPSERT RECORD
# ============================================================

def upsert_record(
    record_type: str,
    record_name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Create or update a CloudKit record.

    Uses forceUpdate so the record can be written even when
    it already exists.
    """

    record = {
        "recordType": record_type,
        "recordName": record_name,
        "fields": fields,
    }

    result = cloudkit_request(
        "records/modify",
        {
            "operations": [
                {
                    "operationType": "forceUpdate",
                    "record": record,
                }
            ]
        },
    )

    return result


# ============================================================
# DELETE RECORDS
# ============================================================

def delete_records(
    record_type: str,
    record_names: list[str],
) -> dict[str, Any]:
    """
    Delete records from the public database.
    """

    if not record_names:
        return {
            "records": []
        }

    operations = []

    for record_name in record_names:
        operations.append(
            {
                "operationType": "forceDelete",
                "record": {
                    "recordType": record_type,
                    "recordName": record_name,
                },
            }
        )

    return cloudkit_request(
        "records/modify",
        {
            "operations": operations
        },
    )


# ============================================================
# TRUCK HELPERS
# ============================================================

def get_trucks() -> list[dict[str, Any]]:
    """
    Retrieve all Truck records.
    """

    return query_all_records(
        "Truck"
    )


def get_truck(
    record_name: str,
) -> Optional[dict[str, Any]]:
    """
    Retrieve one Truck by record name.
    """

    records = lookup_records(
        "Truck",
        [record_name],
    )

    return records[0] if records else None


# ============================================================
# SIGHTING HELPERS
# ============================================================

def get_sightings() -> list[dict[str, Any]]:
    """
    Retrieve all Sighting records.
    """

    return query_all_records(
        "Sighting"
    )


def get_sighting(
    record_name: str,
) -> Optional[dict[str, Any]]:
    """
    Retrieve one Sighting by record name.
    """

    records = lookup_records(
        "Sighting",
        [record_name],
    )

    return records[0] if records else None


def save_sighting(
    record_name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Write a Sighting record.
    """

    return upsert_record(
        record_type="Sighting",
        record_name=record_name,
        fields=fields,
    )


# ============================================================
# GENERIC CLOUDKIT RECORD CONVERTER
# ============================================================

def cloudkit_field_value(
    field: Optional[dict[str, Any]],
    default: Any = None,
) -> Any:
    """
    Extract the value from a CloudKit field.

    CloudKit fields are returned as:

        {
            "value": ...
        }

    This helper makes consuming those fields easier.
    """

    if not field:
        return default

    return field.get(
        "value",
        default,
    )


def record_field(
    record: dict[str, Any],
    field_name: str,
    default: Any = None,
) -> Any:
    """
    Read a field from a CloudKit record.
    """

    fields = record.get(
        "fields",
        {},
    )

    return cloudkit_field_value(
        fields.get(field_name),
        default,
    )


# ============================================================
# ENVIRONMENT INFO
# ============================================================

def cloudkit_config_status() -> dict[str, Any]:
    """
    Safe configuration diagnostic.

    NEVER returns the private key.
    """

    return {
        "configured": bool(
            CLOUDKIT_CONTAINER_ID
            and CLOUDKIT_SERVER_KEY_ID
            and CLOUDKIT_SERVER_PRIVATE_KEY
        ),
        "container_id": CLOUDKIT_CONTAINER_ID,
        "key_id_configured": bool(
            CLOUDKIT_SERVER_KEY_ID
        ),
        "private_key_configured": bool(
            CLOUDKIT_SERVER_PRIVATE_KEY
        ),
        "environment": CLOUDKIT_ENVIRONMENT,
        "public_database": True,
    }


# ============================================================
# DEBUG SELF TEST
# ============================================================

if __name__ == "__main__":

    print(
        json.dumps(
            cloudkit_config_status(),
            indent=2,
        )
    )

    try:

        result = cloudkit_test()

        print(
            json.dumps(
                {
                    "success": True,
                    "cloudkit": result,
                },
                indent=2,
                default=str,
            )
        )

    except Exception as exc:

        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                },
                indent=2,
            )
        )
