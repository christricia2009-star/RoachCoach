"""
CloudKit Bridge
Roach Coach Radar

Server-to-server CloudKit Web Services bridge.

Required environment variables:

    CLOUDKIT_CONTAINER_ID
    CLOUDKIT_SERVER_KEY_ID
    CLOUDKIT_SERVER_PRIVATE_KEY
    CLOUDKIT_ENVIRONMENT

CloudKit server-to-server keys access the PUBLIC database.
"""

import os
import json
import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

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
# PRIVATE KEY
# ============================================================

def _load_private_key():
    """
    Load the EC private key from the environment.

    Handles both:
      - real multiline PEM
      - literal \\n characters from Vercel
    """

    _validate_configuration()

    key_text = CLOUDKIT_SERVER_PRIVATE_KEY

    if not key_text:
        raise RuntimeError(
            "CLOUDKIT_SERVER_PRIVATE_KEY is empty."
        )

    # Convert literal backslash-n sequences into newlines.
    key_text = key_text.replace("\\n", "\n").strip()

    # Remove accidental surrounding quotes.
    if (
        len(key_text) >= 2
        and key_text[0] == '"'
        and key_text[-1] == '"'
    ):
        key_text = key_text[1:-1].strip()

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
            "copied into the Vercel environment variable, "
            "including BEGIN/END lines."
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
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ============================================================
# BODY HASH
# ============================================================

def _body_hash(body: bytes) -> str:
    digest = hashlib.sha256(body).digest()

    return base64.b64encode(
        digest
    ).decode("ascii")


# ============================================================
# SIGN REQUEST
# ============================================================

def _sign_request(
    date_string: str,
    body: bytes,
    path: str,
) -> str:

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

    return base64.b64encode(
        signature
    ).decode("ascii")


# ============================================================
# PATH
# ============================================================

def _path(operation: str) -> str:

    _validate_configuration()

    container = CLOUDKIT_CONTAINER_ID.strip()

    if not container.startswith("iCloud."):
        raise RuntimeError(
            "CLOUDKIT_CONTAINER_ID should normally begin "
            "with 'iCloud.'. Received: "
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
# GENERIC CLOUDKIT REQUEST
# ============================================================

def cloudkit_request(
    operation: str,
    body: Optional[dict[str, Any]] = None,
    timeout: int = 30,
) -> dict[str, Any]:

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
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Apple-CloudKit-Request-KeyID":
            CLOUDKIT_SERVER_KEY_ID,
        "X-Apple-CloudKit-Request-ISO8601Date":
            date_string,
        "X-Apple-CloudKit-Request-SignatureV1":
            signature,
    }

    url = CLOUDKIT_BASE_URL + path

    try:
        response = requests.post(
            url,
            headers=headers,
            data=body_bytes,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"CloudKit network request failed: {exc}"
        ) from exc

    try:
        response_json = response.json()
    except ValueError:
        response_json = {
            "error": response.text
        }

    if not response.ok:

        error_payload = json.dumps(
            response_json,
            default=str,
        )

        raise RuntimeError(
            "CloudKit request failed "
            f"(HTTP {response.status_code}): "
            f"{error_payload}"
        )

    return response_json


# ============================================================
# HEALTH / AUTH TEST
# ============================================================

def cloudkit_test() -> dict[str, Any]:
    """
    Non-destructive CloudKit authentication test.
    """

    return cloudkit_request(
        "records/query",
        {
            "query": {
                "recordType": "Truck",
                "filterBy": [],
            },
            "resultsLimit": 1,
        },
    )


# ============================================================
# QUERY RECORDS
# ============================================================

def query_records(
    record_type: str,
    filters: Optional[list[dict[str, Any]]] = None,
    results_limit: int = 100,
) -> list[dict[str, Any]]:

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

    return result.get(
        "records",
        [],
    )


# ============================================================
# QUERY ALL RECORDS
# ============================================================

def query_all_records(
    record_type: str,
    filters: Optional[list[dict[str, Any]]] = None,
    batch_size: int = 200,
) -> list[dict[str, Any]]:

    if filters is None:
        filters = []

    all_records: list[dict[str, Any]] = []

    cursor: Optional[str] = None

    while True:

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
                "query": {
                    "recordType": record_type,
                    "filterBy": filters,
                },
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
# SAVE RECORDS
# ============================================================

def save_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:

    if not records:
        return {
            "records": []
        }

    operations = []

    for record in records:

        operations.append(
            {
                "operationType": "create",
                "record": record,
            }
        )

    return cloudkit_request(
        "records/modify",
        {
            "operations": operations,
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

    record = {
        "recordType": record_type,
        "recordName": record_name,
        "fields": fields,
    }

    return cloudkit_request(
        "records/modify",
        {
            "operations": [
                {
                    "operationType": "forceUpdate",
                    "record": record,
                }
            ],
        },
    )


# ============================================================
# DELETE RECORDS
# ============================================================

def delete_records(
    record_type: str,
    record_names: list[str],
) -> dict[str, Any]:

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
            "operations": operations,
        },
    )


# ============================================================
# TRUCK HELPERS
# ============================================================

def get_trucks() -> list[dict[str, Any]]:

    return query_all_records(
        "Truck"
    )


def get_truck(
    record_name: str,
) -> Optional[dict[str, Any]]:

    records = lookup_records(
        "Truck",
        [record_name],
    )

    return records[0] if records else None


# ============================================================
# SIGHTING HELPERS
# ============================================================

def get_sightings() -> list[dict[str, Any]]:

    return query_all_records(
        "Sighting"
    )


def get_sighting(
    record_name: str,
) -> Optional[dict[str, Any]]:

    records = lookup_records(
        "Sighting",
        [record_name],
    )

    return records[0] if records else None


# ============================================================
# SAVE SIGHTING
# ============================================================

def save_sighting(
    record_or_name,
    fields: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Save a Sighting.

    Supports BOTH forms:

    1.
        save_sighting(
            "sighting_123",
            {
                "truckId": {"value": "..."}
            }
        )

    2. Main.py can pass a complete CloudKit record:

        save_sighting({
            "recordType": "Sighting",
            "recordName": "sighting_123",
            "fields": {...}
        })

    This compatibility is intentional.
    """

    # --------------------------------------------------------
    # FORM 1:
    # save_sighting(record_name, fields)
    # --------------------------------------------------------

    if isinstance(record_or_name, str):

        record_name = record_or_name

        if fields is None:
            fields = {}

        return upsert_record(
            record_type="Sighting",
            record_name=record_name,
            fields=fields,
        )

    # --------------------------------------------------------
    # FORM 2:
    # save_sighting(full_record)
    # --------------------------------------------------------

    if isinstance(record_or_name, dict):

        record = dict(record_or_name)

        record_type = record.get(
            "recordType",
            "Sighting",
        )

        record_name = record.get(
            "recordName"
        )

        record_fields = record.get(
            "fields",
            {},
        )

        if not record_name:
            record_name = (
                f"sighting_{uuid_safe_id()}"
            )

        return upsert_record(
            record_type=record_type,
            record_name=record_name,
            fields=record_fields,
        )

    raise TypeError(
        "save_sighting() expects either "
        "(record_name, fields) or a complete "
        "CloudKit record dictionary."
    )


# ============================================================
# SAFE ID
# ============================================================

def uuid_safe_id() -> str:
    """
    Generate a CloudKit-safe record suffix.
    """

    import uuid

    return uuid.uuid4().hex


# ============================================================
# CLOUDKIT FIELD HELPERS
# ============================================================

def cloudkit_field_value(
    field: Optional[dict[str, Any]],
    default: Any = None,
) -> Any:

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

    fields = record.get(
        "fields",
        {},
    )

    return cloudkit_field_value(
        fields.get(field_name),
        default,
    )


# ============================================================
# RECORD NORMALIZATION
# ============================================================

def normalize_record(
    record: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert a CloudKit record into a convenient dictionary
    while preserving the original record metadata.
    """

    normalized = {
        "recordName": record.get(
            "recordName"
        ),
        "recordType": record.get(
            "recordType"
        ),
        "fields": record.get(
            "fields",
            {},
        ),
    }

    for field_name, field in record.get(
        "fields",
        {},
    ).items():

        if isinstance(field, dict):

            normalized[field_name] = field.get(
                "value"
            )

        else:

            normalized[field_name] = field

    return normalized


# ============================================================
# ENVIRONMENT STATUS
# ============================================================

def cloudkit_config_status() -> dict[str, Any]:
    """
    Safe diagnostic.

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
