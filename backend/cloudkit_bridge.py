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
from datetime import datetime, timedelta, timezone
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
    sort_by: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:

    if not record_type:
        raise ValueError(
            "record_type is required."
        )

    if filters is None:
        filters = []

    query: dict[str, Any] = {
        "recordType": record_type,
        "filterBy": filters,
    }

    if sort_by:
        query["sortBy"] = sort_by

    body = {
        "query": query,
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
#
# IMPORTANT: this paginates until CloudKit stops returning a
# continuationMarker — i.e. until it has walked the ENTIRE result set
# matching `filters`. With no filters (the old default everywhere this
# was called for Sighting/UnmatchedDetection) that means the entire
# table, every call, forever growing. Always pass a real `filters` list
# that bounds the result set (a recency/expiry cutoff at minimum), and
# treat `max_records` as a hard safety valve, not the primary control —
# a safety valve alone still pays for a full unbounded scan up to that
# cap on every call.
# ============================================================

def query_all_records(
    record_type: str,
    filters: Optional[list[dict[str, Any]]] = None,
    batch_size: int = 200,
    sort_by: Optional[list[dict[str, Any]]] = None,
    max_records: Optional[int] = 2000,
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

            query: dict[str, Any] = {
                "recordType": record_type,
                "filterBy": filters,
            }

            if sort_by:
                query["sortBy"] = sort_by

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

        if (
            max_records is not None
            and len(all_records) >= max_records
        ):
            all_records = all_records[:max_records]
            break

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
# UNMATCHED DETECTION HELPERS
#
# THESE WERE DOCUMENTED (backend/UPDATE_README.md claims they were
# "added") BUT NEVER ACTUALLY WRITTEN — signal_fusion.py has been
# calling cloudkit_bridge.save_unmatched_detection() this whole time,
# which raised AttributeError every single call. scheduler.py's job
# wrapper (run_all_once) and main.py's per-detection loop both catch
# and swallow that exception, so every detection that didn't cleanly
# auto-attach to a known truck — i.e. almost all of them, since
# KNOWN_TRUCK_NAMES/DIRECT_ID_MAPPINGS start empty — was silently
# discarded. This is a primary reason the app shows no data: not just
# the live scan timing out, but the background pipeline that's
# supposed to backfill CloudKit every 15 minutes never actually
# persisting anything for the unmatched (majority) case either.
#
# NOTE: the "UnmatchedDetection" record type must exist in the
# CloudKit Dashboard. CloudKit's development environment can usually
# infer a new record type from its first write; if these calls start
# 400/404ing instead, create it manually with fields: source (String),
# latitude (Double), longitude (Double), timestamp (Date/Time),
# rawConfidence (Double), reason (String), textHint (String),
# note (String), status (String), resolvedTruckId (String, optional).
# ============================================================

def get_unmatched_detections(
    window_hours: float = 6.0,
) -> list[dict[str, Any]]:
    """
    Returns UnmatchedDetection records from roughly the last
    `window_hours`, newest first.

    Previously this called query_all_records("UnmatchedDetection") with
    NO filter — an unbounded, full-table pagination on the
    highest-write-volume table in the app (scheduler.py writes a fresh
    batch every 5-30 minutes), on every single radar scan, forever. That
    is fixed here by pushing a recency cutoff into the CloudKit query
    itself via filterBy, so a normal call only ever pages through
    records that are actually still relevant.

    `timestamp` is written as `datetime.isoformat()` (see
    signal_fusion.py / main.py) — an ISO-8601 string, not a native
    CloudKit DATE field — so CloudKit infers a String field and a
    GREATER_THAN_OR_EQUALS comparator does plain lexicographic string
    comparison. That still gives correct chronological ordering here
    because all writers use the same UTC "+00:00"-offset format, so
    string order matches time order (the only wrinkle is
    datetime.isoformat() drops the microseconds component when it's
    exactly zero, which can occasionally misorder two records within
    the same second — irrelevant at a multi-hour window).

    `max_records` stays as a hard safety cap (see query_all_records) so
    a future bug in the cutoff filter can't silently regress this back
    into an unbounded scan.
    """

    cutoff_iso = (
        datetime.now(timezone.utc)
        - timedelta(hours=window_hours)
    ).isoformat()

    filters = [
        {
            "fieldName": "timestamp",
            "comparator": "GREATER_THAN_OR_EQUALS",
            "fieldValue": {
                "value": cutoff_iso,
                "type": "STRING",
            },
        }
    ]

    sort_by = [
        {
            "fieldName": "timestamp",
            "ascending": False,
        }
    ]

    return query_all_records(
        "UnmatchedDetection",
        filters=filters,
        sort_by=sort_by,
        max_records=1000,
    )


def prune_expired_unmatched_detections(
    batch_size: int = 200,
) -> int:
    """
    Deletes UnmatchedDetection records whose expiresAt has already
    passed. Nothing previously called this — expiresAt was written
    (signal_fusion.py) and read/filtered client-side (main.py) but the
    CloudKit table itself never shrank, so every call anywhere that
    scanned it (see get_unmatched_detections above) was paying to pull
    an ever-growing pile of dead records over the network before
    discarding almost all of them locally.

    Meant to be run periodically (see scheduler.py's cron job) rather
    than on the request path. Returns the number of records deleted.
    """

    now_iso = datetime.now(timezone.utc).isoformat()

    filters = [
        {
            "fieldName": "expiresAt",
            "comparator": "LESS_THAN",
            "fieldValue": {
                "value": now_iso,
                "type": "STRING",
            },
        }
    ]

    try:
        expired = query_all_records(
            "UnmatchedDetection",
            filters=filters,
            batch_size=batch_size,
            max_records=None,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "UnmatchedDetection" in message and (
            "NOT_FOUND" in message or "Missing record type" in message
        ):
            print(
                "[cloudkit] UnmatchedDetection record type is missing "
                "in this CloudKit environment. Create it in CloudKit "
                "Dashboard (production) with fields: source (String), "
                "latitude (Double), longitude (Double), timestamp "
                "(String), expiresAt (String), rawConfidence (Double), "
                "reason (String), textHint (String), note (String), "
                "status (String), resolvedTruckId (String). Skipping prune."
            )
            return 0
        raise

    record_names = [
        record.get("recordName")
        for record in expired
        if record.get("recordName")
    ]

    deleted = 0

    for i in range(0, len(record_names), batch_size):

        chunk = record_names[i:i + batch_size]

        delete_records(
            "UnmatchedDetection",
            chunk,
        )

        deleted += len(chunk)

    return deleted


def save_unmatched_detection(
    detection: dict[str, Any],
) -> dict[str, Any]:
    """
    detection is a plain dict, e.g.:

        {
            "id": "...",
            "source": "camera",
            "latitude": 38.5,
            "longitude": -121.4,
            "timestamp": "2026-08-24T20:00:00Z",
            "rawConfidence": 0.5,
            "reason": "...",
            "textHint": "...",
            "note": "...",
            "status": "pending",
        }

    "id", if present, becomes the CloudKit recordName (so the record is
    addressable/updatable later, e.g. by resolve_unmatched_detection);
    everything else is wrapped into CloudKit's {"value": ...} field
    format and written as an UnmatchedDetection record.
    """

    detection = dict(detection)

    record_name = (
        detection.pop("id", None)
        or f"unmatched_{uuid_safe_id()}"
    )

    try:
        return upsert_record(
            record_type="UnmatchedDetection",
            record_name=str(record_name),
            fields=to_cloudkit_fields(detection),
        )
    except RuntimeError as exc:
        message = str(exc)
        if "UnmatchedDetection" in message and (
            "NOT_FOUND" in message or "Missing record type" in message
        ):
            raise RuntimeError(
                "CloudKit production is missing the UnmatchedDetection "
                "record type. Create it in CloudKit Dashboard and deploy "
                "the schema to production. Camera/telecom/unmatched social "
                "signals cannot be saved until that exists."
            ) from exc
        raise


def resolve_unmatched_detection(
    record_name: str,
    resolved_truck_id: str,
) -> dict[str, Any]:
    """
    Marks a pending UnmatchedDetection as resolved to a specific truck.
    Not currently called from anywhere in the app or backend — the
    Owner Dashboard's "pending sightings" review works off Sighting
    records directly today — but kept available for whenever a human
    review queue is wired up against UnmatchedDetection records.
    """

    return upsert_record(
        record_type="UnmatchedDetection",
        record_name=record_name,
        fields=to_cloudkit_fields(
            {
                "status": "resolved",
                "resolvedTruckId": resolved_truck_id,
            }
        ),
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


def to_cloudkit_fields(
    fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Write-side counterpart to cloudkit_field_value(): converts a plain
    {"latitude": 38.5, ...} dict into the {"latitude": {"value": 38.5}, ...}
    shape records/modify requires. None values are dropped rather than
    sent, since CloudKit rejects a field value of null on some types.
    """

    return {
        key: {"value": value}
        for key, value in fields.items()
        if value is not None
    }


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
