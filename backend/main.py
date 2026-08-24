"""
Food Truck Tracker — Backend API

Deployed on Vercel at https://radar.snapcollectibles.com.

The Radar Backend URL points at /api/radar/scan and /api/health.
Trucks/sightings display data still comes from CloudKit.

Collectors live in:
    backend/collectors/

Currently wired:
    - California / Caltrans traffic cameras
    - Traffic-camera computer vision
    - Municipal food-truck permits
    - Telecom signal anomalies
    - Delivery / pickup pins
"""

import os
import sys
import uuid
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

import signal_fusion
from signal_fusion import RawDetection

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/foodtrucks",
)

engine = create_engine(DATABASE_URL)

app = FastAPI(title="Roach Coach Radar API")


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
    id: uuid.UUID
    name: str
    cuisine_type: Optional[str]
    social_links: Optional[list[str]] = []
    average_confidence_score: float
    menu_highlights: Optional[list[str]] = []
    image_url: Optional[str]


class SightingIn(BaseModel):
    truck_id: uuid.UUID
    latitude: float
    longitude: float
    reported_by_user_id: Optional[uuid.UUID] = None
    photo_url: Optional[str] = None
    note: Optional[str] = None


class SightingOut(BaseModel):
    id: uuid.UUID
    truck_id: uuid.UUID
    latitude: float
    longitude: float
    note: Optional[str]
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
# CONFIDENCE SCORING
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
        ("anthropic", "x-rcr-anthropic-key", "ANTHROPIC_API_KEY"),
        ("grok", "x-rcr-xai-key", "XAI_API_KEY"),
        ("openrouter", "x-rcr-openrouter-key", "OPENROUTER_API_KEY"),
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
        raise RuntimeError("No vision provider API keys configured.")

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
            p for p in vision_keys
            if p != preferred_provider
        ]

        ordered = [
            p for p in ordered
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
                    f"[vision fallback] {provider} failed for "
                    f"{cam.location_name}: {e}"
                )

                last_error = e

        raise last_error or RuntimeError(
            "No vision provider available"
        )

    # single
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
# BASIC ROUTES
# ============================================================

@app.get("/api/trucks", response_model=list[TruckOut])
def get_trucks():

    with engine.connect() as conn:

        rows = conn.execute(
            text(
                "SELECT * FROM trucks ORDER BY name"
            )
        ).mappings().all()

        return [dict(row) for row in rows]


@app.get(
    "/api/trucks/{truck_id}/sightings",
    response_model=list[SightingOut],
)
def get_truck_sightings(truck_id: uuid.UUID):

    with engine.connect() as conn:

        rows = conn.execute(
            text(
                """
                SELECT *
                FROM sightings
                WHERE truck_id = :truck_id
                  AND expires_at > now()
                ORDER BY timestamp DESC
                """
            ),
            {
                "truck_id": str(truck_id)
            },
        ).mappings().all()

        return [dict(row) for row in rows]


@app.get(
    "/api/sightings",
    response_model=list[SightingOut],
)
def get_active_sightings():

    with engine.connect() as conn:

        rows = conn.execute(
            text(
                """
                SELECT *
                FROM sightings
                WHERE expires_at > now()
                ORDER BY timestamp DESC
                """
            )
        ).mappings().all()

        return [dict(row) for row in rows]


@app.post(
    "/api/sightings",
    response_model=SightingOut,
)
def create_sighting(sighting: SightingIn):

    with engine.connect() as conn:

        recent_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sightings
                WHERE truck_id = :truck_id
                  AND timestamp > now() - interval '1 hour'
                """
            ),
            {
                "truck_id": str(sighting.truck_id)
            },
        ).scalar()

        confidence = compute_confidence(
            recent_count or 0,
            source="crowdsource",
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=3)
        )

        result = conn.execute(
            text(
                """
                INSERT INTO sightings
                    (
                        truck_id,
                        latitude,
                        longitude,
                        reported_by_user_id,
                        photo_url,
                        note,
                        confidence_level,
                        expires_at,
                        source
                    )
                VALUES
                    (
                        :truck_id,
                        :lat,
                        :lng,
                        :user_id,
                        :photo_url,
                        :note,
                        :confidence,
                        :expires_at,
                        'crowdsource'
                    )
                RETURNING *
                """
            ),
            {
                "truck_id": str(sighting.truck_id),
                "lat": sighting.latitude,
                "lng": sighting.longitude,
                "user_id": (
                    str(sighting.reported_by_user_id)
                    if sighting.reported_by_user_id
                    else None
                ),
                "photo_url": sighting.photo_url,
                "note": sighting.note,
                "confidence": confidence,
                "expires_at": expires_at,
            },
        ).mappings().first()

        conn.commit()

        if not result:
            raise HTTPException(
                status_code=500,
                detail="Failed to create sighting",
            )

        return dict(result)


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "Roach Coach Radar API",
        "collectors": "loaded",
    }


# ============================================================
# CALIFORNIA CAMERA DIRECTORY
# ============================================================

@app.get("/api/phase3/california-cameras/near")
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

        all_cameras = fetch_all_california_cameras()

        nearby = cameras_near(
            all_cameras,
            latitude,
            longitude,
            radius_miles,
        )

        return [
            {
                "location_name": cam.location_name,
                "county": cam.county,
                "route": cam.route,
                "latitude": cam.latitude,
                "longitude": cam.longitude,
                "current_image_url": cam.current_image_url,
                "in_service": cam.in_service,
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

        telecom_key = os.getenv("TELECOM_API_KEY")
        telecom_base = os.getenv("TELECOM_API_BASE_URL")

        if not telecom_key or not telecom_base:

            return RadarSourceOut(
                id="telecom",
                name="Telecom Signal Anomalies",
                status="skipped",
                detail=(
                    "Telecom collector is installed, but "
                    "TELECOM_API_KEY / TELECOM_API_BASE_URL "
                    "are not configured."
                ),
            )

        if not AGREED_SECTOR_IDS:

            return RadarSourceOut(
                id="telecom",
                name="Telecom Signal Anomalies",
                status="skipped",
                detail=(
                    "Telecom collector is installed, but "
                    "AGREED_SECTOR_IDS is empty."
                ),
            )

        anomalies = fetch_sector_anomalies()

        count = 0

        for anomaly in anomalies:

            # Restrict observations to requested radar radius.
            lat_delta = abs(
                anomaly.latitude - payload.latitude
            )

            lon_delta = abs(
                anomaly.longitude - payload.longitude
            )

            if lat_delta > payload.radiusMiles / 69.0:
                continue

            if lon_delta > payload.radiusMiles / 50.0:
                continue

            count += 1

            observations.append(
                RadarObservationOut(
                    id=str(uuid.uuid4()),
                    truckID=None,
                    source="telecom",
                    sourceID=anomaly.sector_id,
                    observedAt=anomaly.detected_at.isoformat(),
                    latitude=anomaly.latitude,
                    longitude=anomaly.longitude,
                    text=(
                        f"Cellular sector load anomaly "
                        f"{anomaly.anomaly_score:.2f}"
                    ),
                    sourceURL=None,
                    rawConfidence=min(
                        0.65,
                        max(
                            0.25,
                            0.25
                            + anomaly.anomaly_score * 0.25,
                        ),
                    ),
                    state="live",
                    metadata={
                        "sector_id": anomaly.sector_id,
                        "baseline_load": str(
                            anomaly.baseline_load
                        ),
                        "current_load": str(
                            anomaly.current_load
                        ),
                        "anomaly_score": str(
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
                    raw_confidence=min(
                        0.65,
                        max(
                            0.25,
                            0.25
                            + anomaly.anomaly_score * 0.25,
                        ),
                    ),
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
                f"Collector loaded and returned "
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
            detail=f"{type(e).__name__}: {e}",
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
            os.getenv("UBER_PARTNER_CLIENT_ID")
            and os.getenv("UBER_PARTNER_CLIENT_SECRET")
            and os.getenv("UBER_PARTNER_API_BASE_URL")
        )

        doordash_configured = bool(
            os.getenv("DOORDASH_PARTNER_API_KEY")
            and os.getenv("DOORDASH_PARTNER_API_BASE_URL")
        )

        if not uber_configured and not doordash_configured:

            return RadarSourceOut(
                id="delivery",
                name="Delivery Pickup Pins",
                status="skipped",
                detail=(
                    "Delivery collector is installed, but "
                    "no Uber or DoorDash partner credentials "
                    "are configured."
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
                    "Delivery collector is installed, but "
                    "no agreed merchant/store IDs are configured."
                ),
            )

        pins = fetch_all_pickup_pins()

        count = 0

        for pin in pins:

            lat_delta = abs(
                pin.latitude - payload.latitude
            )

            lon_delta = abs(
                pin.longitude - payload.longitude
            )

            if lat_delta > payload.radiusMiles / 69.0:
                continue

            if lon_delta > payload.radiusMiles / 50.0:
                continue

            count += 1

            observations.append(
                RadarObservationOut(
                    id=str(uuid.uuid4()),
                    truckID=None,
                    source="delivery",
                    sourceID=(
                        f"{pin.platform}:{pin.merchant_id}"
                    ),
                    observedAt=pin.reported_at.isoformat(),
                    latitude=pin.latitude,
                    longitude=pin.longitude,
                    text=pin.merchant_name,
                    sourceURL=None,
                    rawConfidence=0.55,
                    state="live",
                    metadata={
                        "platform": pin.platform,
                        "merchant_id": pin.merchant_id,
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
                    source_id=(
                        f"{pin.platform}:{pin.merchant_id}"
                    ),
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
                f"Collector loaded and returned "
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
            detail=f"{type(e).__name__}: {e}",
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
        or os.getenv("LLM_STRATEGY", "fallback")
    ).lower()

    llm_provider_pref = (
        h.get("x-rcr-llm-provider")
        or os.getenv("LLM_PROVIDER", "anthropic")
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

    sources: list[RadarSourceOut] = []
    cameras_out: list[RadarCameraOut] = []
    observations: list[RadarObservationOut] = []
    detections: list[RawDetection] = []
    sightings_out: list[RadarSightingOut] = []

    now = datetime.now(timezone.utc)

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
                        current_image_url=cam.current_image_url,
                        in_service=cam.in_service,
                    )
                    for cam in nearby
                ]

                hits = 0
                rr_state = {"i": 0}
                providers_used: set[str] = set()

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

                        raw_confidence = conf_map.get(
                            result.get("confidence"),
                            0.50,
                        )

                        observations.append(
                            RadarObservationOut(
                                id=str(uuid.uuid4()),
                                source="camera",
                                sourceID=cam.location_name,
                                observedAt=now_iso,
                                latitude=cam.latitude,
                                longitude=cam.longitude,
                                text=result.get(
                                    "reasoning"
                                ),
                                sourceURL=(
                                    cam.current_image_url
                                ),
                                rawConfidence=raw_confidence,
                                metadata={
                                    "estimated_crowd_size": str(
                                        result.get(
                                            "estimated_crowd_size",
                                            "",
                                        )
                                    ),
                                    "vision_provider": (
                                        provider_used
                                    ),
                                },
                            )
                        )

                        detections.append(
                            RawDetection(
                                source="traffic_cam",
                                latitude=cam.latitude,
                                longitude=cam.longitude,
                                timestamp=now,
                                raw_confidence=raw_confidence,
                                source_id=cam.location_name,
                                note=(
                                    f"Camera at "
                                    f"{cam.location_name}: "
                                    f"{result.get('reasoning', '')}"
                                ),
                            )
                        )

                strategy_note = (
                    f"strategy={llm_strategy}, "
                    f"provider(s) used: "
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
                                truck_name or "unknown"
                            ),
                            observedAt=now_iso,
                            latitude=payload.latitude,
                            longitude=payload.longitude,
                            text=p.get(
                                "permitted_location"
                            ),
                            rawConfidence=0.40,
                            metadata={
                                "permit_valid_until": str(
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
            elif written == 0 and queued == 0:
                status = "error"
            else:
                status = "ok"

            detail = (
                f"{written} sighting(s) written "
                f"to CloudKit, "
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
                + 0.15 * len(observations)
                + 0.1 * len(sightings_out),
            )
            if observations
            else 0.0
        )

        if observations:

            summary_bits = [
                (
                    f"{len(observations)} signal(s) "
                    f"found across "
                    f"{active_source_count} "
                    f"active source(s)."
                )
            ]

            if sightings_out:

                summary_bits.append(
                    f"{len(sightings_out)} "
                    f"confirmed sighting(s) "
                    f"added to the map."
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
            evidence_count=len(observations),
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
                        f"Scan failed unexpectedly: "
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
