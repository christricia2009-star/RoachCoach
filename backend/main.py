"""
Roach Coach Radar — Backend API

CloudKit-backed FastAPI backend for Vercel.

Endpoints:
    GET  /api/health
    GET  /api/trucks
    GET  /api/trucks/{truck_id}/sightings
    GET  /api/sightings
    POST /api/sightings
    GET  /api/phase3/california-cameras/near
    POST /api/radar/scan

CloudKit is the data store.
No PostgreSQL is required.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import uuid
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend import signal_fusion
from backend.signal_fusion import RawDetection
from backend import error_tracking

import cloudkit_bridge

error_tracking.init()


# ============================================================
# APP
# ============================================================

app = FastAPI(title="Roach Coach Radar API")

@app.get("/api/diagnostics/vision")
def vision_diagnostics():
    return {
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "xai_configured": bool(os.getenv("XAI_API_KEY")),
        "x_bearer_configured": bool(os.getenv("X_API_BEARER_TOKEN")),
        "llm_strategy": os.getenv("LLM_STRATEGY") or "(empty)",
        "llm_provider": os.getenv("LLM_PROVIDER") or "(empty)",
        "llm_model": os.getenv("LLM_MODEL") or "(empty)",
    }


# ============================================================
# COLLECTOR PATH
# ============================================================

COLLECTORS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "collectors",
)

if COLLECTORS_DIR not in sys.path:
    sys.path.insert(0, COLLECTORS_DIR)

SCRAPING_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scraping",
)

if SCRAPING_DIR not in sys.path:
    sys.path.insert(0, SCRAPING_DIR)


# ============================================================
# SCHEMAS
# ============================================================

class TruckOut(BaseModel):
    id: str
    name: str
    cuisine_type: Optional[str] = None
    social_links: list[str] = []
    average_confidence_score: float = 0.0
    menu_highlights: list[str] = []
    image_url: Optional[str] = None


# Both SightingIn/SightingOut previously used bare snake_case field
# names with no alias. That's what Sighting.swift's submitSighting()
# POSTs against and what fetchSightings()/fetchSightings(forTruck:)
# decode against — Sighting.swift is camelCase (truckId, photoURL,
# confidenceLevel, expiresAt) with no CodingKeys, so every POST
# /api/sightings 422'd on a missing truck_id, and every GET
# /api/sightings response failed to decode into [Sighting] on a
# missing truckId. RadarSightingOut (below) already emits camelCase
# and matches Sighting.swift fine — these two aliases just bring the
# plain CRUD endpoints in line with that same convention instead of
# inventing a third one. Internal code keeps using the snake_case
# attribute names (sighting.truck_id, etc.) via populate_by_name;
# only the wire format changes.
class SightingIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    truck_id: str = Field(alias="truckId")
    latitude: float
    longitude: float
    reported_by_user_id: Optional[str] = Field(
        default=None, alias="reportedByUserId"
    )
    photo_url: Optional[str] = Field(default=None, alias="photoURL")
    note: Optional[str] = None


class SightingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    truck_id: str = Field(alias="truckId")
    latitude: float
    longitude: float
    note: Optional[str] = None
    confidence_level: str = Field(alias="confidenceLevel")
    timestamp: datetime
    expires_at: datetime = Field(alias="expiresAt")


# ============================================================
# RADAR SCAN SCHEMAS
# ============================================================

class RadarScanRequestIn(BaseModel):
    latitude: float
    longitude: float
    radiusMiles: float = 10.0


class RadarSourceOut(BaseModel):
    id: str
    name: str
    status: str
    detail: str


class RadarCameraOut(BaseModel):
    id: str
    location_name: str
    county: Optional[str] = None
    route: Optional[str] = None
    latitude: float
    longitude: float
    current_image_url: Optional[str] = None
    in_service: bool


class RadarObservationOut(BaseModel):
    id: str
    truckID: Optional[str] = None
    source: str
    sourceID: str
    observedAt: str
    latitude: float
    longitude: float
    text: Optional[str] = None
    sourceURL: Optional[str] = None
    rawConfidence: float
    state: str = "live"
    metadata: dict[str, str] = {}


class RadarSightingOut(BaseModel):
    id: str
    truckId: str
    latitude: float
    longitude: float
    reportedByUserId: Optional[str] = None
    photoURL: Optional[str] = None
    note: Optional[str] = None
    timestamp: str
    confidenceLevel: str
    expiresAt: str


class RadarScanResultOut(BaseModel):
    id: str
    scanned_at: str
    sources: list[RadarSourceOut]
    cameras: list[RadarCameraOut]
    sightings: list[RadarSightingOut] = []
    observations: list[RadarObservationOut]
    summary: str
    confidence: float
    engine_version: Optional[str] = "0.1.0-scan-route"
    evidence_count: Optional[int] = None


# ============================================================
# CLOUDKIT HELPERS
# ============================================================

def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, (int, float)):
        # CloudKit TIMESTAMP fields are returned as milliseconds
        # since the Unix epoch (a plain number), not a string. This
        # is the read-side counterpart of the fix in
        # _get_sighting_records() / create_sighting() below — Sighting
        # records were originally created via native CKRecord writes
        # from the iOS app (Sighting.swift's `timestamp`/`expiresAt`
        # are Swift `Date`), which CloudKit maps to its native
        # TIMESTAMP type. Without this branch, any TIMESTAMP value
        # handed back as a raw int silently fell through to the
        # `datetime.now(timezone.utc)` fallback below — meaning every
        # such sighting would quietly get "now" instead of its real
        # timestamp.
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    if not value:
        return datetime.now(timezone.utc)

    value = str(value)

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except Exception:
        return datetime.now(timezone.utc)


def _cloudkit_record_value(
    record: dict,
    field_name: str,
    default=None,
):
    """
    Extract a CloudKit field value.

    CloudKit records look like:

        {
            "recordName": "...",
            "recordType": "Truck",
            "fields": {
                "name": {
                    "value": "My Truck"
                }
            }
        }
    """

    fields = record.get("fields", {})

    if not isinstance(fields, dict):
        return default

    field = fields.get(field_name)

    if not isinstance(field, dict):
        return default

    return field.get("value", default)


def _cloudkit_records(result) -> list[dict]:
    """
    IMPORTANT:

    cloudkit_bridge.query_records() already returns:

        list[dict]

    It does NOT return:

        {"records": [...]}

    This helper therefore accepts both formats for compatibility.
    """

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        records = result.get("records")

        if isinstance(records, list):
            return records

    return []


def _cloudkit_field(value):
    """
    Convert a normal Python value into the CloudKit server-to-server
    field format expected by records/modify.
    """

    return {
        "value": value
    }


# ============================================================
# CONFIDENCE
# ============================================================

def compute_confidence(
    recent_report_count: int,
    source: str,
    reporter_reputation: int = 0,
) -> str:

    if recent_report_count >= 2:
        return "confirmed"

    if source in ("crowdsource", "social"):
        return "likely"

    return "scheduled"


# ============================================================
# VISION PROVIDERS
# ============================================================

def _resolve_vision_keys(h) -> dict[str, str]:

    keys = {}

    for provider, header_name, env_name in [
        (
            "anthropic",
            "x-rcr-anthropic-key",
            "ANTHROPIC_API_KEY",
        ),
        (
            "grok",
            "x-rcr-xai-key",
            "XAI_API_KEY",
        ),
        (
            "openrouter",
            "x-rcr-openrouter-key",
            "OPENROUTER_API_KEY",
        ),
    ]:

        key = h.get(header_name) or os.getenv(env_name)

        if key:
            keys[provider] = key

    return keys


def _vision_check_with_strategy(
    cam,
    vision_keys: dict[str, str],
    strategy: str,
    preferred_provider: str,
    model_override: Optional[str],
    rr_state: dict,
    check_frame_for_truck,
) -> tuple[dict, str]:

    if not vision_keys:
        raise RuntimeError(
            "No vision provider API keys configured."
        )

    if strategy == "round_robin":

        providers = list(vision_keys.keys())

        provider = providers[
            rr_state["i"] % len(providers)
        ]

        rr_state["i"] += 1

        result = check_frame_for_truck(
            cam.current_image_url,
            provider=provider,
            api_key=vision_keys[provider],
            model=model_override,
        )

        return result, provider

    if strategy == "fallback":

        ordered = [
            preferred_provider
        ] + [
            p
            for p in vision_keys
            if p != preferred_provider
        ]

        ordered = [
            p
            for p in ordered
            if p in vision_keys
        ]

        last_error = None

        for provider in ordered:

            try:

                result = check_frame_for_truck(
                    cam.current_image_url,
                    provider=provider,
                    api_key=vision_keys[provider],
                    model=model_override,
                )

                return result, provider

            except Exception as e:

                error_tracking.report(
                    f"[vision fallback] {provider} failed "
                    f"for {cam.location_name}"
                )

                last_error = e

        raise last_error or RuntimeError(
            "No vision provider available"
        )

    provider = (
        preferred_provider
        if preferred_provider in vision_keys
        else next(iter(vision_keys))
    )

    result = check_frame_for_truck(
        cam.current_image_url,
        provider=provider,
        api_key=vision_keys[provider],
        model=model_override,
    )

    return result, provider


# ============================================================
# CLOUDKIT — TRUCKS
# ============================================================

@app.get(
    "/api/trucks",
    response_model=list[TruckOut],
)
def get_trucks():

    try:

        # query_records() returns a LIST.
        records = cloudkit_bridge.query_records(
            "Truck"
        )

        trucks = []

        for record in _cloudkit_records(records):

            record_name = record.get(
                "recordName",
                str(uuid.uuid4()),
            )

            trucks.append(
                TruckOut(
                    id=record_name,

                    name=_cloudkit_record_value(
                        record,
                        "name",
                        "Unknown Truck",
                    ),

                    cuisine_type=_cloudkit_record_value(
                        record,
                        "cuisineType",
                    ),

                    social_links=_cloudkit_record_value(
                        record,
                        "socialLinks",
                        [],
                    ) or [],

                    average_confidence_score=float(
                        _cloudkit_record_value(
                            record,
                            "averageConfidenceScore",
                            0.0,
                        ) or 0.0
                    ),

                    menu_highlights=_cloudkit_record_value(
                        record,
                        "menuHighlights",
                        [],
                    ) or [],

                    image_url=_cloudkit_record_value(
                        record,
                        "imageURL",
                    ),
                )
            )

        trucks.sort(
            key=lambda x: x.name.lower()
        )

        return trucks

    except Exception as e:

        error_tracking.report("get_trucks failed")

        raise HTTPException(
            status_code=500,
            detail=f"CloudKit Truck query failed: {e}",
        )


# ============================================================
# CLOUDKIT — SIGHTINGS
# ============================================================

def _record_to_sighting(
    record: dict,
) -> SightingOut:

    record_name = record.get(
        "recordName",
        str(uuid.uuid4()),
    )

    truck_id = _cloudkit_record_value(
        record,
        "truckId",
        "",
    )

    latitude = float(
        _cloudkit_record_value(
            record,
            "latitude",
            0,
        ) or 0
    )

    longitude = float(
        _cloudkit_record_value(
            record,
            "longitude",
            0,
        ) or 0
    )

    timestamp = _parse_datetime(
        _cloudkit_record_value(
            record,
            "timestamp",
        )
    )

    expires_at = _parse_datetime(
        _cloudkit_record_value(
            record,
            "expiresAt",
        )
    )

    return SightingOut(
        id=record_name,

        truck_id=str(
            truck_id
        ),

        latitude=latitude,
        longitude=longitude,

        note=_cloudkit_record_value(
            record,
            "note",
        ),

        confidence_level=_cloudkit_record_value(
            record,
            "confidenceLevel",
            "scheduled",
        ),

        timestamp=timestamp,
        expires_at=expires_at,
    )


def _get_sighting_records() -> list[dict]:
    """
    Previously called cloudkit_bridge.query_records("Sighting") with no
    filter, no sort, and the default results_limit (100, capped at
    200) — a single unsorted page. That silently drops real sightings
    once the table passes ~100 records, since "first 100 in whatever
    order CloudKit returns them" has no guaranteed relationship to
    "most recent 100". Fixed by pushing an expiresAt cutoff into the
    query (mirrors the client-side `if expires_at <= now: continue`
    check every caller of this already does) and sorting newest-first,
    via query_all_records so it still pages if there's a legitimate
    backlog — bounded by max_records as a safety cap.

    IMPORTANT — field type:
    Sighting.expiresAt / Sighting.timestamp are native CloudKit
    TIMESTAMP fields (the record type was first created via native
    CKRecord writes from the iOS app, where Swift `Date` maps directly
    to CloudKit's TIMESTAMP type). CloudKit's Web Services query filter
    requires a TIMESTAMP fieldValue to be milliseconds since the Unix
    epoch as a number, with "type": "TIMESTAMP" — NOT an ISO-8601
    string with "type": "STRING". Sending the wrong type here is what
    previously caused CloudKit to reject the whole query with
    "BadRequestException: Invalid value, expected type TIMESTAMP."
    (This is unlike UnmatchedDetection.timestamp, which really is a
    String field, because that table is only ever written by this
    Python backend via .isoformat().)
    """

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    filters = [
        {
            "fieldName": "expiresAt",
            "comparator": "GREATER_THAN",
            "fieldValue": {
                "value": now_ms,
                "type": "TIMESTAMP",
            },
        }
    ]

    sort_by = [
        {
            "fieldName": "timestamp",
            "ascending": False,
        }
    ]

    result = cloudkit_bridge.query_all_records(
        "Sighting",
        filters=filters,
        sort_by=sort_by,
        max_records=500,
    )

    return _cloudkit_records(result)


@app.get(
    "/api/trucks/{truck_id}/sightings",
    response_model=list[SightingOut],
)
def get_truck_sightings(
    truck_id: str,
):

    try:

        records = _get_sighting_records()

        now = datetime.now(timezone.utc)

        results = []

        for record in records:

            record_truck_id = str(
                _cloudkit_record_value(
                    record,
                    "truckId",
                    "",
                )
            )

            if record_truck_id != str(
                truck_id
            ):
                continue

            sighting = _record_to_sighting(
                record
            )

            if sighting.expires_at > now:

                results.append(
                    sighting
                )

        results.sort(
            key=lambda x: x.timestamp,
            reverse=True,
        )

        return results

    except Exception as e:

        error_tracking.report("get_truck_sightings failed")

        raise HTTPException(
            status_code=500,
            detail=(
                "CloudKit Sighting query failed: "
                f"{e}"
            ),
        )


@app.get(
    "/api/sightings",
    response_model=list[SightingOut],
)
def get_active_sightings():

    try:

        records = _get_sighting_records()

        now = datetime.now(timezone.utc)

        results = []

        for record in records:

            sighting = _record_to_sighting(
                record
            )

            if sighting.expires_at > now:

                results.append(
                    sighting
                )

        results.sort(
            key=lambda x: x.timestamp,
            reverse=True,
        )

        return results

    except Exception as e:

        error_tracking.report("get_active_sightings failed")

        raise HTTPException(
            status_code=500,
            detail=(
                "CloudKit Sighting query failed: "
                f"{e}"
            ),
        )


# ============================================================
# CREATE SIGHTING
# ============================================================

@app.post(
    "/api/sightings",
    response_model=SightingOut,
)
def create_sighting(
    sighting: SightingIn,
):

    try:

        recent_records = _get_sighting_records()

        now = datetime.now(timezone.utc)

        recent_count = 0

        for record in recent_records:

            record_truck_id = str(
                _cloudkit_record_value(
                    record,
                    "truckId",
                    "",
                )
            )

            if record_truck_id != str(
                sighting.truck_id
            ):
                continue

            timestamp = _parse_datetime(
                _cloudkit_record_value(
                    record,
                    "timestamp",
                )
            )

            if timestamp > (
                now - timedelta(hours=1)
            ):
                recent_count += 1

        confidence = compute_confidence(
            recent_count,
            source="crowdsource",
        )

        timestamp = now

        expires_at = (
            now + timedelta(hours=3)
        )

        record_id = str(
            uuid.uuid4()
        )

        # ====================================================
        # IMPORTANT CLOUDKIT FIX
        #
        # CloudKit records/modify requires:
        #
        # "field": {
        #     "value": actual_value
        # }
        #
        # Do NOT send plain Python values here.
        #
        # ALSO IMPORTANT: Sighting.timestamp / Sighting.expiresAt are
        # native CloudKit TIMESTAMP fields (see _get_sighting_records()
        # above for why). TIMESTAMP fields must be written as
        # milliseconds since the Unix epoch (an int), not an
        # ISO-8601 string — writing .isoformat() here would silently
        # disagree with the field's real schema type instead of
        # storing a comparable timestamp.
        # ====================================================

        fields = {
            "truckId": _cloudkit_field(
                str(sighting.truck_id)
            ),

            "latitude": _cloudkit_field(
                sighting.latitude
            ),

            "longitude": _cloudkit_field(
                sighting.longitude
            ),

            "confidenceLevel": _cloudkit_field(
                confidence
            ),

            "timestamp": _cloudkit_field(
                int(timestamp.timestamp() * 1000)
            ),

            "expiresAt": _cloudkit_field(
                int(expires_at.timestamp() * 1000)
            ),
        }

        if sighting.reported_by_user_id:

            fields[
                "reportedByUserId"
            ] = _cloudkit_field(
                str(
                    sighting.reported_by_user_id
                )
            )

        if sighting.photo_url:

            fields[
                "photoURL"
            ] = _cloudkit_field(
                sighting.photo_url
            )

        if sighting.note:

            fields[
                "note"
            ] = _cloudkit_field(
                sighting.note
            )

        # Save directly through the bridge using the
        # record-name + fields compatibility form.
        cloudkit_bridge.save_sighting(
            record_id,
            fields,
        )

        return SightingOut(
            id=record_id,

            truck_id=str(
                sighting.truck_id
            ),

            latitude=sighting.latitude,
            longitude=sighting.longitude,

            note=sighting.note,

            confidence_level=confidence,

            timestamp=timestamp,
            expires_at=expires_at,
        )

    except Exception as e:

        error_tracking.report("create_sighting failed")

        raise HTTPException(
            status_code=500,
            detail=(
                "CloudKit Sighting write failed: "
                f"{e}"
            ),
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health_check():

    cloudkit_configured = bool(
        os.getenv("CLOUDKIT_CONTAINER_ID")
        and os.getenv("CLOUDKIT_SERVER_KEY_ID")
        and os.getenv("CLOUDKIT_SERVER_PRIVATE_KEY")
        and os.getenv("CLOUDKIT_ENVIRONMENT")
    )

    return {
        "status": "ok",
        "service": "Roach Coach Radar API",
        "storage": "CloudKit",
        "cloudkit_configured": cloudkit_configured,
        "collectors": "loaded",
    }


# ============================================================
# CALIFORNIA CAMERA DIRECTORY
# ============================================================

@app.get(
    "/api/phase3/california-cameras/near"
)
def california_cameras_near(
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
):

    try:

        from california_camera_directory import (
            fetch_all_california_cameras,
            cameras_near,
        )

        all_cameras = (
            fetch_all_california_cameras()
        )

        nearby = cameras_near(
            all_cameras,
            latitude,
            longitude,
            radius_miles,
        )

        return [
            {
                "location_name":
                    cam.location_name,

                "county":
                    cam.county,

                "route":
                    cam.route,

                "latitude":
                    cam.latitude,

                "longitude":
                    cam.longitude,

                "current_image_url":
                    cam.current_image_url,

                "in_service":
                    cam.in_service,
            }

            for cam in nearby
        ]

    except Exception as e:

        raise HTTPException(
            status_code=503,
            detail=(
                "California camera directory unavailable: "
                f"{type(e).__name__}: {e}"
            ),
        )


# ============================================================
# TELECOM COLLECTOR
# ============================================================

def _run_telecom_source(
    payload: RadarScanRequestIn,
    observations: list[RadarObservationOut],
    detections: list[RawDetection],
) -> RadarSourceOut:

    try:

        from telecom_signal_data import (
            fetch_sector_anomalies,
            AGREED_SECTOR_IDS,
        )

        telecom_key = os.getenv(
            "TELECOM_API_KEY"
        )

        telecom_base = os.getenv(
            "TELECOM_API_BASE_URL"
        )

        if not telecom_key or not telecom_base:

            return RadarSourceOut(
                id="telecom",
                name="Telecom Signal Anomalies",
                status="skipped",
                detail=(
                    "Telecom collector is installed, "
                    "but TELECOM_API_KEY / "
                    "TELECOM_API_BASE_URL "
                    "are not configured."
                ),
            )

        if not AGREED_SECTOR_IDS:

            return RadarSourceOut(
                id="telecom",
                name="Telecom Signal Anomalies",
                status="skipped",
                detail=(
                    "Telecom collector is installed, "
                    "but AGREED_SECTOR_IDS is empty."
                ),
            )

        anomalies = fetch_sector_anomalies()

        count = 0

        for anomaly in anomalies:

            lat_delta = abs(
                anomaly.latitude
                - payload.latitude
            )

            lon_delta = abs(
                anomaly.longitude
                - payload.longitude
            )

            if (
                lat_delta
                > payload.radiusMiles / 69.0
            ):
                continue

            if (
                lon_delta
                > payload.radiusMiles / 50.0
            ):
                continue

            count += 1

            raw_confidence = min(
                0.65,
                max(
                    0.25,
                    0.25
                    + anomaly.anomaly_score * 0.25,
                ),
            )

            observations.append(
                RadarObservationOut(
                    id=str(uuid.uuid4()),
                    source="telecom",
                    sourceID=anomaly.sector_id,
                    observedAt=(
                        anomaly.detected_at.isoformat()
                    ),
                    latitude=anomaly.latitude,
                    longitude=anomaly.longitude,
                    text=(
                        "Cellular sector load anomaly "
                        f"{anomaly.anomaly_score:.2f}"
                    ),
                    rawConfidence=raw_confidence,
                    metadata={
                        "sector_id":
                            anomaly.sector_id,

                        "baseline_load":
                            str(
                                anomaly.baseline_load
                            ),

                        "current_load":
                            str(
                                anomaly.current_load
                            ),

                        "anomaly_score":
                            str(
                                anomaly.anomaly_score
                            ),
                    },
                )
            )

            detections.append(
                RawDetection(
                    source="telecom_signal",
                    latitude=anomaly.latitude,
                    longitude=anomaly.longitude,
                    timestamp=anomaly.detected_at,
                    raw_confidence=raw_confidence,
                    source_id=anomaly.sector_id,
                    note=(
                        "Cellular sector load anomaly "
                        f"score={anomaly.anomaly_score:.2f}"
                    ),
                )
            )

        return RadarSourceOut(
            id="telecom",
            name="Telecom Signal Anomalies",
            status="ok",
            detail=(
                "Collector loaded and returned "
                f"{count} nearby anomaly/anomalies."
            ),
        )

    except Exception as e:

        error_tracking.report("telecom source failed")

        return RadarSourceOut(
            id="telecom",
            name="Telecom Signal Anomalies",
            status="error",
            detail=(
                f"{type(e).__name__}: {e}"
            ),
        )


# ============================================================
# DELIVERY / PICKUP COLLECTOR
# ============================================================

def _run_delivery_source(
    payload: RadarScanRequestIn,
    observations: list[RadarObservationOut],
    detections: list[RawDetection],
) -> RadarSourceOut:

    try:

        from delivery_pickup_pins import (
            fetch_all_pickup_pins,
            AGREED_UBER_MERCHANT_IDS,
            AGREED_DOORDASH_STORE_IDS,
        )

        uber_configured = bool(
            os.getenv(
                "UBER_PARTNER_CLIENT_ID"
            )
            and os.getenv(
                "UBER_PARTNER_CLIENT_SECRET"
            )
            and os.getenv(
                "UBER_PARTNER_API_BASE_URL"
            )
        )

        doordash_configured = bool(
            os.getenv(
                "DOORDASH_PARTNER_API_KEY"
            )
            and os.getenv(
                "DOORDASH_PARTNER_API_BASE_URL"
            )
        )

        if (
            not uber_configured
            and not doordash_configured
        ):

            return RadarSourceOut(
                id="delivery",
                name="Delivery Pickup Pins",
                status="skipped",
                detail=(
                    "Delivery collector is installed, "
                    "but no Uber or DoorDash partner "
                    "credentials are configured."
                ),
            )

        if (
            not AGREED_UBER_MERCHANT_IDS
            and not AGREED_DOORDASH_STORE_IDS
        ):

            return RadarSourceOut(
                id="delivery",
                name="Delivery Pickup Pins",
                status="skipped",
                detail=(
                    "Delivery collector is installed, "
                    "but no agreed merchant/store "
                    "IDs are configured."
                ),
            )

        pins = fetch_all_pickup_pins()

        count = 0

        for pin in pins:

            lat_delta = abs(
                pin.latitude
                - payload.latitude
            )

            lon_delta = abs(
                pin.longitude
                - payload.longitude
            )

            if (
                lat_delta
                > payload.radiusMiles / 69.0
            ):
                continue

            if (
                lon_delta
                > payload.radiusMiles / 50.0
            ):
                continue

            count += 1

            source_id = (
                f"{pin.platform}:"
                f"{pin.merchant_id}"
            )

            observations.append(
                RadarObservationOut(
                    id=str(uuid.uuid4()),
                    source="delivery",
                    sourceID=source_id,
                    observedAt=(
                        pin.reported_at.isoformat()
                    ),
                    latitude=pin.latitude,
                    longitude=pin.longitude,
                    text=pin.merchant_name,
                    rawConfidence=0.55,
                    metadata={
                        "platform":
                            pin.platform,

                        "merchant_id":
                            pin.merchant_id,
                    },
                )
            )

            detections.append(
                RawDetection(
                    source="delivery_pickup",
                    latitude=pin.latitude,
                    longitude=pin.longitude,
                    timestamp=pin.reported_at,
                    raw_confidence=0.55,
                    source_id=source_id,
                    text_hint=pin.merchant_name,
                    note=(
                        f"{pin.platform} pickup location: "
                        f"{pin.merchant_name}"
                    ),
                )
            )

        return RadarSourceOut(
            id="delivery",
            name="Delivery Pickup Pins",
            status="ok",
            detail=(
                "Collector loaded and returned "
                f"{count} nearby pickup pin(s)."
            ),
        )

    except Exception as e:

        error_tracking.report("delivery source failed")

        return RadarSourceOut(
            id="delivery",
            name="Delivery Pickup Pins",
            status="error",
            detail=(
                f"{type(e).__name__}: {e}"
            ),
        )


def _run_social_source(
    payload: RadarScanRequestIn,
    observations: list[RadarObservationOut],
    detections: list[RawDetection],
) -> RadarSourceOut:
    """
    On-demand counterpart to scheduler.py's job_social_scraping() — same
    fetch -> LLM extract -> geocode pipeline, just triggered by a single
    /api/radar/scan call instead of the 30-minute background job, and
    scoped to observations/detections for THIS scan instead of the
    scheduler's own in-memory RECENT_DETECTIONS pool.

    Every underlying source (Instagram Business Discovery, Facebook Page,
    OpenRouter web search) is independently optional — this returns
    status="skipped" only if NONE of them are configured, and a source
    failing never stops the others (same pattern as _run_telecom_source /
    _run_delivery_source above).
    """

    try:

        from social_scraper import (
            fetch_all_known_trucks,
            fetch_web_search_results,
            INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES,
            FACEBOOK_PAGE_IDS,
        )

        from llm_extract import extract_location_from_caption

        from geocoding import geocode

        instagram_configured = bool(
            os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
            and os.getenv("INSTAGRAM_ACCESS_TOKEN")
        )

        facebook_configured = bool(
            os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
            and FACEBOOK_PAGE_IDS
        )

        web_search_configured = bool(
            os.getenv("OPENROUTER_API_KEY")
        )

        if (
            not instagram_configured
            and not facebook_configured
            and not web_search_configured
        ):

            return RadarSourceOut(
                id="social",
                name="Social Scraper",
                status="skipped",
                detail=(
                    "Social collector is installed, but none of "
                    "Instagram Business Discovery "
                    "(INSTAGRAM_BUSINESS_ACCOUNT_ID + "
                    "INSTAGRAM_ACCESS_TOKEN), a Facebook Page "
                    "(FACEBOOK_PAGE_ACCESS_TOKEN + at least one "
                    "configured page ID), or web search "
                    "(OPENROUTER_API_KEY) are configured."
                ),
            )

        posts = fetch_all_known_trucks(
            instagram_business_discovery_usernames=(
                INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES
                if instagram_configured
                else []
            ),
            facebook_page_ids=(
                FACEBOOK_PAGE_IDS
                if facebook_configured
                else []
            ),
        )

        if web_search_configured:

            posts += fetch_web_search_results(
                [
                    name.title()
                    for name in signal_fusion.KNOWN_TRUCK_NAMES.keys()
                ]
            )

        matched = 0
        skipped_no_location = 0

        confidence_map = {
            "high": 0.65,
            "medium": 0.4,
        }

        for post in posts:

            try:
                extracted = extract_location_from_caption(
                    post.caption
                )
            except Exception as e:
                error_tracking.report(
                    f"[social] llm_extract failed for "
                    f"{post.truck_handle}"
                )
                continue

            if extracted.get("confidence") not in (
                "high",
                "medium",
            ):
                continue

            location_text = extracted.get("location_text")

            geocoded = (
                geocode(location_text)
                if location_text
                else None
            )

            if not geocoded:
                skipped_no_location += 1
                continue

            # Filter to the requested scan radius, same as every other
            # source below — no point returning a truck posted about a
            # location 40 miles from where the app is asking.
            lat_delta = abs(geocoded["latitude"] - payload.latitude)
            lon_delta = abs(geocoded["longitude"] - payload.longitude)

            if lat_delta > payload.radiusMiles / 69.0:
                continue
            if lon_delta > payload.radiusMiles / 50.0:
                continue

            matched += 1

            raw_confidence = confidence_map.get(
                extracted["confidence"], 0.4
            )

            posted_at = (
                post.posted_at
                if post.posted_at.tzinfo
                else post.posted_at.replace(tzinfo=timezone.utc)
            )

            observations.append(
                RadarObservationOut(
                    id=str(uuid.uuid4()),
                    source="social",
                    sourceID=f"{post.source}:{post.truck_handle}",
                    observedAt=posted_at.isoformat(),
                    latitude=geocoded["latitude"],
                    longitude=geocoded["longitude"],
                    text=post.caption[:280],
                    sourceURL=post.post_url or None,
                    rawConfidence=raw_confidence,
                    metadata={
                        "platform": post.source,
                        "location_text": location_text or "",
                        "geocoded_display_name": geocoded.get(
                            "display_name", ""
                        ),
                    },
                )
            )

            detections.append(
                RawDetection(
                    source="social",
                    latitude=geocoded["latitude"],
                    longitude=geocoded["longitude"],
                    timestamp=posted_at,
                    raw_confidence=raw_confidence,
                    text_hint=post.caption,
                    note=(
                        f"{post.source} post: "
                        f'"{post.caption[:100]}" -> '
                        f"{geocoded.get('display_name', location_text)}"
                    ),
                )
            )

        return RadarSourceOut(
            id="social",
            name="Social Scraper",
            status="ok",
            detail=(
                f"Checked {len(posts)} post(s)/search result(s); "
                f"{matched} had a location in range, "
                f"{skipped_no_location} had a location we couldn't "
                f"geocode."
            ),
        )

    except Exception as e:

        error_tracking.report("social source failed")

        return RadarSourceOut(
            id="social",
            name="Social Scraper",
            status="error",
            detail=(
                f"{type(e).__name__}: {e}"
            ),
        )


# ============================================================
# RADAR SCAN — CACHED READ PATH (default, fast)
#
# This endpoint used to run the ENTIRE live pipeline synchronously on
# every tap of the "Scan" button: fetch every nearby traffic camera,
# then call an AI vision model on each one SEQUENTIALLY, then fetch
# municipal permits, then the telecom source, then the delivery
# source, then the social source (which itself fetches Instagram/
# Facebook/web-search posts and runs an LLM extraction + geocode call
# PER POST). That's dozens of sequential network/LLM calls stacked
# inside one HTTP request, bounded by Vercel's 60s function limit —
# it was always going to time out under any real-world latency.
#
# backend/scheduler.py already runs this exact pipeline on a schedule
# (every 5-30 min per source, via GitHub Actions / .github/workflows/
# scheduler.yml) and writes results straight into CloudKit. So the
# right job for a button tap is: read what's already there, near this
# point, fast. That's what this does now. The old live-fan-out code is
# still below, gated behind an "x-rcr-live-scan: true" header, for
# manual/debug use — but it's no longer what the app calls by default.
# ============================================================

_DETECTION_SOURCE_TO_OBSERVATION_SOURCE = {
    # RawDetection.source values (written by scheduler.py / main.py's
    # live sources into UnmatchedDetection.source) -> the vocabulary
    # RadarObservationOut.source actually uses, which must in turn be
    # one of RadarObservation.SourceKind's raw values on the iOS side
    # (userReport, social, camera, event, municipal, delivery,
    # schedule, owner, web, telecom) or the WHOLE observations array
    # fails to decode client-side over one bad value.
    "traffic_cam": "camera",
    "camera": "camera",
    "telecom_signal": "telecom",
    "telecom": "telecom",
    "delivery_pickup": "delivery",
    "delivery": "delivery",
    "municipal_permit": "municipal",
    "municipal": "municipal",
    "social": "social",
}

UNMATCHED_DETECTION_WINDOW_HOURS = 6


def _valid_uuid_str(value) -> Optional[str]:
    """
    iOS decodes id / truckId / truckID as Swift's native UUID, which
    fails (and takes the WHOLE array down with it) on anything that
    isn't a canonical UUID string. Guard here rather than trust every
    CloudKit record to be clean — e.g. the blank records the
    save_sighting bug wrote before it was fixed.
    """

    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _within_radius(
    lat: float,
    lon: float,
    payload: "RadarScanRequestIn",
) -> bool:

    lat_delta = abs(lat - payload.latitude)
    lon_delta = abs(lon - payload.longitude)

    return (
        lat_delta <= payload.radiusMiles / 69.0
        and lon_delta <= payload.radiusMiles / 50.0
    )


def _record_to_radar_sighting(
    record: dict,
) -> Optional["RadarSightingOut"]:

    record_id = _valid_uuid_str(record.get("recordName"))
    truck_id = _valid_uuid_str(_cloudkit_record_value(record, "truckId"))

    if not record_id or not truck_id:
        return None

    return RadarSightingOut(
        id=record_id,
        truckId=truck_id,
        latitude=float(_cloudkit_record_value(record, "latitude", 0) or 0),
        longitude=float(_cloudkit_record_value(record, "longitude", 0) or 0),
        reportedByUserId=_valid_uuid_str(
            _cloudkit_record_value(record, "reportedByUserId")
        ),
        photoURL=_cloudkit_record_value(record, "photoURL") or None,
        note=_cloudkit_record_value(record, "note"),
        timestamp=_parse_datetime(
            _cloudkit_record_value(record, "timestamp")
        ).isoformat(),
        confidenceLevel=_cloudkit_record_value(
            record, "confidenceLevel", "scheduled"
        ),
        expiresAt=_parse_datetime(
            _cloudkit_record_value(record, "expiresAt")
        ).isoformat(),
    )


def _record_to_radar_observation(
    record: dict,
) -> Optional[RadarObservationOut]:

    obs_id = _valid_uuid_str(record.get("recordName"))

    if not obs_id:
        return None

    raw_source = str(_cloudkit_record_value(record, "source", "") or "")

    resolved_truck_id = None

    if _cloudkit_record_value(record, "status") == "resolved":
        resolved_truck_id = _valid_uuid_str(
            _cloudkit_record_value(record, "resolvedTruckId")
        )

    return RadarObservationOut(
        id=obs_id,
        truckID=resolved_truck_id,
        source=_DETECTION_SOURCE_TO_OBSERVATION_SOURCE.get(
            raw_source, "web"
        ),
        sourceID=raw_source or "unknown",
        observedAt=_parse_datetime(
            _cloudkit_record_value(record, "timestamp")
        ).isoformat(),
        latitude=float(_cloudkit_record_value(record, "latitude", 0) or 0),
        longitude=float(_cloudkit_record_value(record, "longitude", 0) or 0),
        text=(
            _cloudkit_record_value(record, "textHint")
            or _cloudkit_record_value(record, "note")
            or _cloudkit_record_value(record, "reason")
        ),
        rawConfidence=float(
            _cloudkit_record_value(record, "rawConfidence", 0.3) or 0.3
        ),
        state="live",
        metadata={
            "reason": str(
                _cloudkit_record_value(record, "reason", "") or ""
            ),
            "status": str(
                _cloudkit_record_value(record, "status", "pending")
                or "pending"
            ),
        },
    )


def _cached_radar_scan(
    payload: RadarScanRequestIn,
) -> RadarScanResultOut:

    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    sightings_out: list[RadarSightingOut] = []

    for record in _get_sighting_records():

        expires_at = _parse_datetime(
            _cloudkit_record_value(record, "expiresAt")
        )

        if expires_at <= now:
            continue

        lat = float(_cloudkit_record_value(record, "latitude", 0) or 0)
        lon = float(_cloudkit_record_value(record, "longitude", 0) or 0)

        if not _within_radius(lat, lon, payload):
            continue

        radar_sighting = _record_to_radar_sighting(record)

        if radar_sighting:
            sightings_out.append(radar_sighting)

    observations: list[RadarObservationOut] = []

    cutoff = now - timedelta(hours=UNMATCHED_DETECTION_WINDOW_HOURS)

    try:
        unmatched_records = cloudkit_bridge.get_unmatched_detections(
            window_hours=UNMATCHED_DETECTION_WINDOW_HOURS
        )
    except Exception:
        error_tracking.report("get_unmatched_detections failed")
        unmatched_records = []

    for record in unmatched_records:

        timestamp = _parse_datetime(
            _cloudkit_record_value(record, "timestamp")
        )

        if timestamp < cutoff:
            continue

        lat = float(_cloudkit_record_value(record, "latitude", 0) or 0)
        lon = float(_cloudkit_record_value(record, "longitude", 0) or 0)

        if not _within_radius(lat, lon, payload):
            continue

        observation = _record_to_radar_observation(record)

        if observation:
            observations.append(observation)

    evidence_count = len(sightings_out) + len(observations)

    sources = [
        RadarSourceOut(
            id="cached_snapshot",
            name="Cached Signal Snapshot",
            status="ok",
            detail=(
                f"{len(sightings_out)} sighting(s) and "
                f"{len(observations)} pending signal(s) near this "
                "location, from the scheduled background scan "
                "(runs every 5-30 min per source)."
            ),
        )
    ]

    confidence = (
        min(
            1.0,
            0.2
            + 0.15 * len(observations)
            + 0.1 * len(sightings_out),
        )
        if evidence_count
        else 0.0
    )

    summary = (
        f"{len(sightings_out)} confirmed sighting(s) and "
        f"{len(observations)} unconfirmed signal(s) nearby."
        if evidence_count
        else "No signals found near this location right now."
    )

    return RadarScanResultOut(
        id=str(uuid.uuid4()),
        scanned_at=now_iso,
        sources=sources,
        cameras=[],
        sightings=sightings_out,
        observations=observations,
        summary=summary,
        confidence=confidence,
        evidence_count=evidence_count,
    )


# ============================================================
# RADAR SCAN — LIVE FAN-OUT (debug/manual only; see header gate below)
# ============================================================

@app.post(
    "/api/radar/scan",
    response_model=RadarScanResultOut,
)
def radar_scan(
    payload: RadarScanRequestIn,
    request: Request,
):

    h = request.headers

    live_scan = (
        h.get("x-rcr-live-scan") or ""
    ).strip().lower() in ("1", "true", "yes")

    if not live_scan:

        try:

            return _cached_radar_scan(payload)

        except Exception as e:

            error_tracking.report("cached radar scan failed")

            now = datetime.now(timezone.utc)

            return RadarScanResultOut(
                id=str(uuid.uuid4()),
                scanned_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                sources=[
                    RadarSourceOut(
                        id="cached_snapshot",
                        name="Cached Signal Snapshot",
                        status="error",
                        detail=f"{type(e).__name__}: {e}",
                    )
                ],
                cameras=[],
                sightings=[],
                observations=[],
                summary=(
                    "Scan failed unexpectedly — see server logs."
                ),
                confidence=0.0,
                evidence_count=0,
            )

    # ------------------------------------------------------------
    # Everything below only runs when the caller explicitly opts in
    # via the x-rcr-live-scan header — kept as-is for manual/debug
    # use, not part of the app's default tap-to-scan path anymore.
    # ------------------------------------------------------------

    vision_keys = _resolve_vision_keys(h)

    llm_strategy = (
        h.get("x-rcr-llm-strategy")
        or os.getenv("LLM_STRATEGY")
        or "fallback"
    ).lower()

    llm_provider_pref = (
        h.get("x-rcr-llm-provider")
        or os.getenv("LLM_PROVIDER")
        or "openrouter"
    ).lower()

    llm_model_override = (
        h.get("x-rcr-llm-model")
        or os.getenv("LLM_MODEL")
        or None
    )

    municipal_url = (
        h.get("x-rcr-municipal-url")
        or None
    )

    municipal_token = (
        h.get("x-rcr-municipal-token")
        or None
    )

    sources = []

    cameras_out = []

    observations = []

    detections = []

    sightings_out = []

    now = datetime.now(
        timezone.utc
    )

    now_iso = now.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:

        # ====================================================
        # TRAFFIC CAMERA VISION
        # ====================================================

        if not vision_keys:

            sources.append(
                RadarSourceOut(
                    id="camera_vision",
                    name="Traffic Camera Vision",
                    status="skipped",
                    detail=(
                        "No AI provider key. Add Anthropic, "
                        "xAI/Grok, and/or OpenRouter in Settings."
                    ),
                )
            )

        else:

            try:

                from california_camera_directory import (
                    fetch_all_california_cameras,
                    cameras_near,
                )

                from traffic_camera_vision import (
                    check_frame_for_truck,
                )

                all_cams = (
                    fetch_all_california_cameras()
                )

                nearby = [
                    c
                    for c in cameras_near(
                        all_cams,
                        payload.latitude,
                        payload.longitude,
                        payload.radiusMiles,
                    )
                    if c.in_service
                ]

                nearby = nearby[:6]

                cameras_out = [
                    RadarCameraOut(
                        id=cam.location_name,
                        location_name=cam.location_name,
                        county=cam.county,
                        route=cam.route,
                        latitude=cam.latitude,
                        longitude=cam.longitude,
                        current_image_url=(
                            cam.current_image_url
                        ),
                        in_service=cam.in_service,
                    )
                    for cam in nearby
                ]

                hits = 0

                rr_state = {
                    "i": 0
                }

                providers_used = set()

                for cam in nearby:

                    try:

                        result, provider_used = (
                            _vision_check_with_strategy(
                                cam,
                                vision_keys,
                                llm_strategy,
                                llm_provider_pref,
                                llm_model_override,
                                rr_state,
                                check_frame_for_truck,
                            )
                        )

                        providers_used.add(
                            provider_used
                        )

                    except Exception as e:

                        error_tracking.report(
                            f"camera check failed for "
                            f"{cam.location_name}"
                        )

                        continue

                    if result.get(
                        "likely_food_truck_present"
                    ):

                        hits += 1

                        conf_map = {
                            "high": 0.85,
                            "medium": 0.60,
                            "low": 0.35,
                        }

                        raw_confidence = (
                            conf_map.get(
                                result.get(
                                    "confidence"
                                ),
                                0.50,
                            )
                        )

                        observations.append(
                            RadarObservationOut(
                                id=str(uuid.uuid4()),
                                source="camera",
                                sourceID=(
                                    cam.location_name
                                ),
                                observedAt=now_iso,
                                latitude=cam.latitude,
                                longitude=cam.longitude,
                                text=result.get(
                                    "reasoning"
                                ),
                                sourceURL=(
                                    cam.current_image_url
                                ),
                                rawConfidence=(
                                    raw_confidence
                                ),
                                metadata={
                                    "estimated_crowd_size":
                                        str(
                                            result.get(
                                                "estimated_crowd_size",
                                                "",
                                            )
                                        ),

                                    "vision_provider":
                                        provider_used,
                                },
                            )
                        )

                        detections.append(
                            RawDetection(
                                source="traffic_cam",
                                latitude=cam.latitude,
                                longitude=cam.longitude,
                                timestamp=now,
                                raw_confidence=(
                                    raw_confidence
                                ),
                                source_id=(
                                    cam.location_name
                                ),
                                note=(
                                    f"Camera at "
                                    f"{cam.location_name}: "
                                    f"{result.get('reasoning', '')}"
                                ),
                            )
                        )

                strategy_note = (
                    f"strategy={llm_strategy}, "
                    "provider(s) used: "
                    f"{', '.join(sorted(providers_used)) or 'none'}"
                )

                sources.append(
                    RadarSourceOut(
                        id="camera_vision",
                        name="Traffic Camera Vision",
                        status="ok",
                        detail=(
                            f"Checked {len(nearby)} "
                            f"camera(s), {hits} likely "
                            f"detection(s) "
                            f"({strategy_note})."
                        ),
                    )
                )

            except Exception as e:

                error_tracking.report("camera_vision source failed")

                sources.append(
                    RadarSourceOut(
                        id="camera_vision",
                        name="Traffic Camera Vision",
                        status="error",
                        detail=(
                            f"{type(e).__name__}: {e}"
                        ),
                    )
                )

        # ====================================================
        # MUNICIPAL PERMITS
        # ====================================================

        if not municipal_url:

            sources.append(
                RadarSourceOut(
                    id="municipal",
                    name="Municipal Permits",
                    status="skipped",
                    detail=(
                        "No municipal dataset URL. "
                        "Add one in Settings."
                    ),
                )
            )

        else:

            try:

                from municipal_open_data import (
                    fetch_food_truck_permits,
                )

                permits = fetch_food_truck_permits(
                    dataset_url=municipal_url,
                    app_token=municipal_token,
                )

                for p in permits:

                    truck_name = p.get(
                        "truck_name"
                    )

                    observations.append(
                        RadarObservationOut(
                            id=str(uuid.uuid4()),
                            source="municipal",
                            sourceID=str(
                                truck_name
                                or "unknown"
                            ),
                            observedAt=now_iso,
                            latitude=payload.latitude,
                            longitude=payload.longitude,
                            text=p.get(
                                "permitted_location"
                            ),
                            rawConfidence=0.40,
                            metadata={
                                "permit_valid_until":
                                    str(
                                        p.get(
                                            "permit_valid_until"
                                        )
                                        or ""
                                    ),
                            },
                        )
                    )

                    detections.append(
                        RawDetection(
                            source="municipal_permit",
                            latitude=payload.latitude,
                            longitude=payload.longitude,
                            timestamp=now,
                            raw_confidence=0.40,
                            text_hint=truck_name,
                            note=p.get(
                                "permitted_location"
                            ),
                        )
                    )

                sources.append(
                    RadarSourceOut(
                        id="municipal",
                        name="Municipal Permits",
                        status="ok",
                        detail=(
                            f"Found {len(permits)} "
                            f"permit record(s)."
                        ),
                    )
                )

            except Exception as e:

                error_tracking.report("municipal source failed")

                sources.append(
                    RadarSourceOut(
                        id="municipal",
                        name="Municipal Permits",
                        status="error",
                        detail=(
                            f"{type(e).__name__}: {e}"
                        ),
                    )
                )

        # ====================================================
        # TELECOM
        # ====================================================

        sources.append(
            _run_telecom_source(
                payload,
                observations,
                detections,
            )
        )

        # ====================================================
        # DELIVERY / PICKUP
        # ====================================================

        sources.append(
            _run_delivery_source(
                payload,
                observations,
                detections,
            )
        )

        # ====================================================
        # SOCIAL
        # ====================================================

        sources.append(
            _run_social_source(
                payload,
                observations,
                detections,
            )
        )

        # ====================================================
        # SIGNAL FUSION / CLOUDKIT WRITE-THROUGH
        # ====================================================

        if not detections:

            sources.append(
                RadarSourceOut(
                    id="sighting_write",
                    name="Sighting Write-Through",
                    status="skipped",
                    detail=(
                        "No detections this scan to fuse."
                    ),
                )
            )

        else:

            written = 0
            queued = 0
            errored = 0

            for detection in detections:

                try:

                    result = (
                        signal_fusion.process_detection(
                            detection,
                            detections,
                        )
                    )

                except Exception:

                    error_tracking.report("signal_fusion failed")

                    errored += 1

                    continue

                if result.sighting:

                    written += 1

                    sightings_out.append(
                        RadarSightingOut(
                            **result.sighting
                        )
                    )

                else:

                    queued += 1

            if errored == 0:
                status = "ok"

            elif (
                written == 0
                and queued == 0
            ):
                status = "error"

            else:
                status = "ok"

            detail = (
                f"{written} sighting(s) written "
                "to CloudKit, "
                f"{queued} queued for review"
            )

            if errored:

                detail += (
                    f", {errored} failed"
                )

            sources.append(
                RadarSourceOut(
                    id="sighting_write",
                    name="Sighting Write-Through",
                    status=status,
                    detail=detail + ".",
                )
            )

        # ====================================================
        # RESULT
        # ====================================================

        active_source_count = sum(
            1
            for source in sources
            if source.status == "ok"
        )

        confidence = (
            min(
                1.0,
                0.2
                + 0.15
                * len(observations)
                + 0.1
                * len(sightings_out),
            )
            if observations
            else 0.0
        )

        if observations:

            summary_bits = [
                (
                    f"{len(observations)} signal(s) "
                    "found across "
                    f"{active_source_count} "
                    "active source(s)."
                )
            ]

            if sightings_out:

                summary_bits.append(
                    f"{len(sightings_out)} "
                    "confirmed sighting(s) "
                    "added to the map."
                )

            summary = " ".join(
                summary_bits
            )

        else:

            summary = (
                "No signals found in this scan."
            )

        return RadarScanResultOut(
            id=str(uuid.uuid4()),
            scanned_at=now_iso,
            sources=sources,
            cameras=cameras_out,
            sightings=sightings_out,
            observations=observations,
            summary=summary,
            confidence=confidence,
            evidence_count=len(
                observations
            ),
        )

    except Exception as e:

        print(
            "radar_scan crashed:\n"
            + traceback.format_exc()
        )

        return RadarScanResultOut(
            id=str(uuid.uuid4()),
            scanned_at=now_iso,

            sources=[
                RadarSourceOut(
                    id="scan",
                    name="Radar Scan",
                    status="error",
                    detail=(
                        "Scan failed unexpectedly: "
                        f"{type(e).__name__}: {e}"
                    ),
                )
            ],

            cameras=[],
            sightings=[],
            observations=[],

            summary=(
                "Scan failed unexpectedly — "
                "see server logs."
            ),

            confidence=0.0,
            evidence_count=0,
        )
