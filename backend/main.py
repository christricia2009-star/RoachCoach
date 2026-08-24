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
import uuid
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import signal_fusion
from signal_fusion import RawDetection

import cloudkit_bridge


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


class SightingIn(BaseModel):
    truck_id: str
    latitude: float
    longitude: float
    reported_by_user_id: Optional[str] = None
    photo_url: Optional[str] = None
    note: Optional[str] = None


class SightingOut(BaseModel):
    id: str
    truck_id: str
    latitude: float
    longitude: float
    note: Optional[str] = None
    confidence_level: str
    timestamp: datetime
    expires_at: datetime


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

                print(
                    f"[vision fallback] {provider} failed "
                    f"for {cam.location_name}: {e}"
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

        print(
            "get_trucks failed:\n"
            + traceback.format_exc()
        )

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

    # query_records() returns a LIST.
    result = cloudkit_bridge.query_records(
        "Sighting"
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

        print(
            "get_truck_sightings failed:\n"
            + traceback.format_exc()
        )

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

        print(
            "get_active_sightings failed:\n"
            + traceback.format_exc()
        )

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
                timestamp.isoformat()
            ),

            "expiresAt": _cloudkit_field(
                expires_at.isoformat()
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

        print(
            "create_sighting failed:\n"
            + traceback.format_exc()
        )

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

        print(
            "telecom source failed:\n"
            + traceback.format_exc()
        )

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

        print(
            "delivery source failed:\n"
            + traceback.format_exc()
        )

        return RadarSourceOut(
            id="delivery",
            name="Delivery Pickup Pins",
            status="error",
            detail=(
                f"{type(e).__name__}: {e}"
            ),
        )


# ============================================================
# RADAR SCAN
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

    llm_provider_pref = (
        h.get("x-rcr-llm-provider")
        or os.getenv(
            "LLM_PROVIDER",
            "anthropic",
        )
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

                        print(
                            f"camera check failed for "
                            f"{cam.location_name}: {e}"
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

                print(
                    "camera_vision source failed:\n"
                    + traceback.format_exc()
                )

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

                print(
                    "municipal source failed:\n"
                    + traceback.format_exc()
                )

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
            RadarSourceOut(
                id="social",
                name="Social Scraper",
                status="skipped",
                detail=(
                    "Social scraper collector is present "
                    "but is not enabled by this radar route."
                ),
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

                    print(
                        "signal_fusion failed:\n"
                        + traceback.format_exc()
                    )

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
