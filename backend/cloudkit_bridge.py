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

    query: dict[str, Any] = {
        "recordType": record_type,
    }

    if filters:
        query["filterBy"] = filters

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
            }

            if filters:
                query["filterBy"] = filters

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

    # CloudKit lookup returns HTTP 200 with a stub per missing name
    # ({"recordName", "serverErrorCode": "NOT_FOUND", "reason": ...}).
    # Treat those as misses, not empty records with zero totals.
    return _usable_cloudkit_records(result.get("records", []))


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
# MENU ITEM HELPERS
#
# Requires the MenuItem record type (see cloudkit_schema.txt). Unlike
# Sighting.timestamp/expiresAt, MenuItem.createdAt/updatedAt aren't
# filtered on here, so they're fine as native CloudKit Date fields.
# ============================================================

def get_menu_items_for_truck(
    truck_id: str,
    only_available: bool = False,
) -> list[dict[str, Any]]:

    filters = [
        {
            "fieldName": "truckID",
            "comparator": "EQUALS",
            "fieldValue": {
                "value": str(truck_id),
                "type": "STRING",
            },
        }
    ]

    if only_available:
        filters.append(
            {
                "fieldName": "isAvailable",
                "comparator": "EQUALS",
                "fieldValue": {
                    "value": 1,
                    "type": "INT64",
                },
            }
        )

    sort_by = [
        {
            "fieldName": "sortOrder",
            "ascending": True,
        }
    ]

    result = query_all_records(
        "MenuItem",
        filters=filters,
        sort_by=sort_by,
        max_records=500,
    )

    return _as_record_list(result)


def get_menu_item(record_name: str) -> Optional[dict[str, Any]]:

    records = lookup_records(
        "MenuItem",
        [record_name],
    )

    return records[0] if records else None


def save_menu_item(
    record_name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:

    return upsert_record(
        record_type="MenuItem",
        record_name=record_name,
        fields=fields,
    )


def delete_menu_item(record_name: str) -> dict[str, Any]:

    return delete_records(
        "MenuItem",
        [record_name],
    )


# ============================================================
# ORDER HELPERS
#
# Requires the Order record type (see cloudkit_schema.txt). Ordering
# is done on createdAtMs (Int64) rather than createdAt (Date) so the
# same STRING/TIMESTAMP filter restriction noted throughout this file
# doesn't bite here — Int64 supports GREATER_THAN/LESS_THAN cleanly.
# ============================================================

def get_orders_for_truck(
    truck_id: str,
    statuses: Optional[list[str]] = None,
    max_records: int = 200,
) -> list[dict[str, Any]]:
    """Owner Order Board query: all orders for a truck, optionally
    restricted to a set of active statuses, newest first."""

    filters = [
        {
            "fieldName": "truckID",
            "comparator": "EQUALS",
            "fieldValue": {
                "value": str(truck_id),
                "type": "STRING",
            },
        }
    ]

    # CloudKit's Web Services query has no IN comparator; when the
    # caller wants to exclude terminal states (completed/cancelled) we
    # over-fetch on truckID alone and filter status in Python instead
    # of trying to encode an OR-of-EQUALS here.

    sort_by = [
        {
            "fieldName": "createdAtMs",
            "ascending": False,
        }
    ]

    result = query_all_records(
        "Order",
        filters=filters,
        sort_by=sort_by,
        max_records=max_records,
    )

    records = _as_record_list(result)

    if statuses:
        wanted = set(statuses)
        records = [
            r for r in records
            if cloudkit_field_value(r.get("fields", {}).get("status"), "") in wanted
        ]

    return records


def get_order(record_name: str) -> Optional[dict[str, Any]]:

    records = lookup_records(
        "Order",
        [record_name],
    )

    return records[0] if records else None


def save_order(
    record_name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:

    return upsert_record(
        record_type="Order",
        record_name=record_name,
        fields=fields,
    )


def update_order_status(
    record_name: str,
    status: str,
    updated_at_iso: Optional[str] = None,
) -> dict[str, Any]:

    fields: dict[str, Any] = {
        "status": {"value": status},
    }

    if updated_at_iso:
        fields["updatedAt"] = {"value": updated_at_iso}

    return upsert_record(
        record_type="Order",
        record_name=record_name,
        fields=fields,
    )


def update_order_payment(
    record_name: str,
    payment_provider: Optional[str] = None,
    payment_status: Optional[str] = None,
    payment_intent_id: Optional[str] = None,
    order_status: Optional[str] = None,
    updated_at_iso: Optional[str] = None,
) -> dict[str, Any]:
    """Patches the payment side of an Order record (provider, status,
    the processor's own reference id) independently of
    update_order_status(), since a payment webhook and an owner tapping
    'Accept' both need to touch the same record without clobbering each
    other's fields."""

    fields: dict[str, Any] = {}

    if payment_provider is not None:
        fields["paymentProvider"] = {"value": payment_provider}
    if payment_status is not None:
        fields["paymentStatus"] = {"value": payment_status}
    if payment_intent_id is not None:
        fields["paymentIntentID"] = {"value": payment_intent_id}
    if order_status is not None:
        fields["status"] = {"value": order_status}
    if updated_at_iso:
        fields["updatedAt"] = {"value": updated_at_iso}

    return upsert_record(
        record_type="Order",
        record_name=record_name,
        fields=fields,
    )


def _usable_cloudkit_records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    usable: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("serverErrorCode") or record.get("reason"):
            continue
        usable.append(record)
    return usable


def _as_record_list(result: Any) -> list[dict[str, Any]]:
    """Same compatibility shim as main.py's _cloudkit_records(), kept
    here too since query_all_records() output is consumed directly by
    the helpers above without going through main.py first."""

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        records = result.get("records")
        if isinstance(records, list):
            return records

    return []


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

def _unmatched_status_filter() -> list[dict[str, Any]]:
    """EQUALS is valid on STRING. Empty filterBy makes CloudKit query
    recordName, which 400s unless that index exists."""
    return [
        {
            "fieldName": "status",
            "comparator": "EQUALS",
            "fieldValue": {
                "value": "pending",
                "type": "STRING",
            },
        }
    ]


def _as_datetime(value: Any) -> Optional[datetime]:
    """Parse a CloudKit String ISO timestamp or TIMESTAMP millis."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_unmatched_detections(
    window_hours: float = 6.0,
) -> list[dict[str, Any]]:
    """
    Returns UnmatchedDetection records from roughly the last
    `window_hours`, newest first.

    CloudKit STRING fields cannot use LESS_THAN / GREATER_THAN filters
    (HTTP 400). timestamp and expiresAt were created as String, so the
    recency cutoff is applied in Python after a bounded fetch.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    try:
        records = query_all_records(
            "UnmatchedDetection",
            filters=_unmatched_status_filter(),
            max_records=1000,
        )
    except RuntimeError as exc:
        message = str(exc)
        print(
            f"[cloudkit] get_unmatched_detections skipped: {message}"
        )
        print(
            "[cloudkit] Add Queryable indexes on "
            "UnmatchedDetection.recordName and UnmatchedDetection.status "
            "in Development, then Deploy to Production."
        )
        return []

    recent: list[dict[str, Any]] = []
    for record in records:
        timestamp = _as_datetime(record_field(record, "timestamp"))
        if timestamp is None or timestamp < cutoff:
            continue
        recent.append(record)

    recent.sort(
        key=lambda record: _as_datetime(
            record_field(record, "timestamp")
        ) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    return recent


def prune_expired_unmatched_detections(
    batch_size: int = 200,
) -> int:
    """
    Deletes UnmatchedDetection records whose expiresAt has already
    passed. CloudKit STRING fields reject LESS_THAN, so expiry is
    evaluated in Python after a bounded fetch.
    """

    try:
        records = query_all_records(
            "UnmatchedDetection",
            filters=_unmatched_status_filter(),
            batch_size=batch_size,
            max_records=2000,
        )
    except RuntimeError as exc:
        message = str(exc)
        print(
            f"[cloudkit] prune_unmatched_detections skipped: {message}"
        )
        print(
            "[cloudkit] In CloudKit Dashboard (Development then Deploy), "
            "add Queryable indexes on UnmatchedDetection.recordName and "
            "UnmatchedDetection.status, then deploy to Production."
        )
        return 0

    now = datetime.now(timezone.utc)
    expired_names: list[str] = []

    for record in records:
        record_name = record.get("recordName")
        if not record_name:
            continue
        expires_at = _as_datetime(record_field(record, "expiresAt"))
        if expires_at is None:
            timestamp = _as_datetime(record_field(record, "timestamp"))
            if timestamp is not None:
                expires_at = timestamp + timedelta(hours=3)
        if expires_at is None or expires_at > now:
            continue
        expired_names.append(record_name)

    deleted = 0

    for i in range(0, len(expired_names), batch_size):

        chunk = expired_names[i:i + batch_size]

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
