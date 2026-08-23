"""
Food Truck Tracker — Backend API (Phase 1)

Deployed on Vercel at https://radar.snapcollectibles.com. To run locally
instead:
  1. Provision a PostgreSQL database (with PostGIS) — e.g. Railway, Render, RDS, Supabase.
  2. Run schema.sql against that database.
  3. Set the environment variables below (.env file recommended, see .env.example).
  4. pip install -r requirements.txt
  5. uvicorn main:app --reload

The app's Radar Backend URL (Settings > Radar Backend) points at whichever
deployment you want it to use — the app reads this route directly for
/api/radar/scan and /api/health; trucks/sightings display data still
comes from CloudKit (CloudKitService.swift), not from this file. See
BackendUpdate/UPDATE_README.md for the full data-flow picture.
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

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/foodtrucks")
engine = create_engine(DATABASE_URL)

app = FastAPI(title="Roach Coach Radar API")


# ---------- Schemas ----------

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


# ---------- Confidence Scoring ----------

def compute_confidence(recent_report_count: int, source: str, reporter_reputation: int = 0) -> str:
    """
    Simple starting heuristic — tune this once you have real usage data.

    - 2+ independent reports in the last hour => confirmed
    - a single crowdsourced report, or a fresh social post => likely
    - schedule-based / permit data with no live confirmation => scheduled
    """
    if recent_report_count >= 2:
        return "confirmed"
    if source in ("crowdsource", "social"):
        return "likely"
    return "scheduled"


# ---------- Radar Scan Schemas ----------
# Field names below are chosen to match the Swift structs in
# RoachCoachRadar/Services/RadarScanService.swift EXACTLY, since neither
# JSONEncoder.apiEncoder nor JSONDecoder.apiDecoder apply any key
# conversion (no .convertToSnakeCase) — only RadarScanResult itself has
# explicit CodingKeys (snake_case at the top level); everything nested
# is matched by literal Swift property name, including odd casing like
# "truckID" and "sourceID".

class RadarScanRequestIn(BaseModel):
    latitude: float
    longitude: float
    radiusMiles: float = 10.0


class RadarSourceOut(BaseModel):
    id: str
    name: str
    status: str  # "ok" | "skipped" | "error"
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
    source: str  # RadarObservation.SourceKind raw value, e.g. "camera", "municipal"
    sourceID: str
    observedAt: str  # ISO8601
    latitude: float
    longitude: float
    text: Optional[str] = None
    sourceURL: Optional[str] = None
    rawConfidence: float
    state: str = "live"
    metadata: dict[str, str] = {}


class RadarSightingOut(BaseModel):
    # Field names match Models/Sighting.swift's Codable properties
    # EXACTLY (no CodingKeys there => no snake_case conversion), same
    # rule as RadarObservationOut above. confidenceLevel must be one of
    # the Swift ConfidenceLevel enum's raw values: "Confirmed" | "Likely"
    # | "Scheduled" — see signal_fusion.process_detection for why that
    # casing matters.
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
    sightings: list[RadarSightingOut] = []  # real Sighting records this scan
                                             # wrote to CloudKit via
                                             # signal_fusion — these are
                                             # confirmed truck matches, as
                                             # opposed to the raw signal in
                                             # `observations` below
    observations: list[RadarObservationOut]
    summary: str
    confidence: float
    engine_version: Optional[str] = "0.1.0-scan-route"
    evidence_count: Optional[int] = None


# ---------- Radar Scan: multi-provider vision wiring ----------
# Wires Grok/xAI and OpenRouter into the camera-vision source, in addition
# to Anthropic, honoring the app's Settings > AI Providers > Strategy
# picker (APIKeyStore.llmStrategy, sent as the X-RCR-LLM-Strategy header —
# same "single" | "round_robin" | "fallback" modes as
# scraping/llm_providers.py, reimplemented here per-scan-request instead
# of as a long-lived process global, since round_robin's rotation and
# fallback's try-next-provider only need to make sense across the handful
# of camera calls within a SINGLE scan, not across the server's lifetime.

def _resolve_vision_keys(h) -> dict[str, str]:
    """Provider -> API key, for whichever providers have a key available —
    per-request header first (matches the app's "the configured backend
    receives only the credentials needed for that scan" design), server
    env var as a fallback for local/CLI testing. Dict order also doubles
    as priority order for "fallback" and "single" strategies below."""
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


def _vision_check_with_strategy(cam, vision_keys: dict[str, str], strategy: str,
                                 preferred_provider: str, model_override: Optional[str],
                                 rr_state: dict, check_frame_for_truck) -> tuple[dict, str]:
    """Runs check_frame_for_truck for one camera per the configured
    strategy. Returns (result_dict, provider_actually_used); raises if no
    provider could produce a result, so the caller's per-camera try/except
    can log-and-skip that camera without killing the whole scan."""
    if strategy == "round_robin":
        providers = list(vision_keys.keys())
        provider = providers[rr_state["i"] % len(providers)]
        rr_state["i"] += 1
        result = check_frame_for_truck(cam.current_image_url, provider=provider,
                                        api_key=vision_keys[provider], model=model_override)
        return result, provider

    if strategy == "fallback":
        ordered = [preferred_provider] + [p for p in vision_keys if p != preferred_provider]
        ordered = [p for p in ordered if p in vision_keys]
        last_error = None
        for provider in ordered:
            try:
                result = check_frame_for_truck(cam.current_image_url, provider=provider,
                                                api_key=vision_keys[provider], model=model_override)
                return result, provider
            except Exception as e:
                print(f"[vision fallback] {provider} failed for {cam.location_name} ({e}), trying next provider…")
                last_error = e
                continue
        raise last_error or RuntimeError("No vision provider available")

    # "single" — always the configured provider; if the app picked a
    # provider it didn't actually give us a key for, fall back to
    # whichever key IS available rather than skipping the camera entirely.
    provider = preferred_provider if preferred_provider in vision_keys else next(iter(vision_keys))
    result = check_frame_for_truck(cam.current_image_url, provider=provider,
                                    api_key=vision_keys[provider], model=model_override)
    return result, provider


# ---------- Routes ----------

@app.get("/api/trucks", response_model=list[TruckOut])
def get_trucks():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM trucks ORDER BY name")).mappings().all()
        return [dict(row) for row in rows]


@app.get("/api/trucks/{truck_id}/sightings", response_model=list[SightingOut])
def get_truck_sightings(truck_id: uuid.UUID):
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM sightings
                WHERE truck_id = :truck_id AND expires_at > now()
                ORDER BY timestamp DESC
            """),
            {"truck_id": str(truck_id)}
        ).mappings().all()
        return [dict(row) for row in rows]


@app.get("/api/sightings", response_model=list[SightingOut])
def get_active_sightings():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM sightings WHERE expires_at > now() ORDER BY timestamp DESC")
        ).mappings().all()
        return [dict(row) for row in rows]


@app.post("/api/sightings", response_model=SightingOut)
def create_sighting(sighting: SightingIn):
    with engine.connect() as conn:
        # Count other recent reports for the same truck to compute confidence
        recent_count = conn.execute(
            text("""
                SELECT COUNT(*) FROM sightings
                WHERE truck_id = :truck_id AND timestamp > now() - interval '1 hour'
            """),
            {"truck_id": str(sighting.truck_id)}
        ).scalar()

        confidence = compute_confidence(recent_count or 0, source="crowdsource")
        expires_at = datetime.utcnow() + timedelta(hours=3)

        result = conn.execute(
            text("""
                INSERT INTO sightings
                    (truck_id, latitude, longitude, reported_by_user_id, photo_url, note, confidence_level, expires_at, source)
                VALUES
                    (:truck_id, :lat, :lng, :user_id, :photo_url, :note, :confidence, :expires_at, 'crowdsource')
                RETURNING *
            """),
            {
                "truck_id": str(sighting.truck_id),
                "lat": sighting.latitude,
                "lng": sighting.longitude,
                "user_id": str(sighting.reported_by_user_id) if sighting.reported_by_user_id else None,
                "photo_url": sighting.photo_url,
                "note": sighting.note,
                "confidence": confidence,
                "expires_at": expires_at,
            }
        ).mappings().first()
        conn.commit()

        if not result:
            raise HTTPException(status_code=500, detail="Failed to create sighting")
        return dict(result)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/phase3/california-cameras/near")
def california_cameras_near(latitude: float, longitude: float, radius_miles: float = 5.0):
    """
    Real endpoint backed by the live statewide Caltrans CCTV directory
    (see phase3/california_camera_directory.py). Returns nearby in-service
    cameras — does NOT run vision detection on them here (that costs LLM
    tokens per call); pair with phase3/traffic_camera_vision.py's
    scan_california_area() if you want detection results instead of just
    the camera list.
    """
    import sys
    # NOTE: the actual module lives in collectors/, not a "phase3/" dir —
    # this append previously pointed at a directory that doesn't exist in
    # this repo, so the import below always raised ModuleNotFoundError.
    collectors_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collectors")
    if collectors_dir not in sys.path:
        sys.path.append(collectors_dir)
    from california_camera_directory import fetch_all_california_cameras, cameras_near

    all_cameras = fetch_all_california_cameras()
    nearby = cameras_near(all_cameras, latitude, longitude, radius_miles)
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


@app.post("/api/radar/scan", response_model=RadarScanResultOut)
def radar_scan(payload: RadarScanRequestIn, request: Request):
    """
    Backs the app's "SCAN NOW" button (RadarScanService.scan). Runs the
    phase3 signal sources that are wired up so far and returns a single
    fused result.

    SCOPE — only 2 of the 5 phase3 sources are wired in here right now:
      - Caltrans camera vision (traffic_camera_vision.py)
      - Municipal food-truck permits (municipal_open_data.py)
    Telecom, delivery-pickup, and social-scraper sources exist as modules
    (phase3/telecom_signal_data.py, delivery_pickup_pins.py,
    scraping/social_scraper.py) but aren't called from this route yet —
    they're reported below as "skipped" sources rather than silently
    omitted, so the app can show the user why. Wire them in the same
    pattern as the two below when ready.

    Per-request credentials: the app sends the user's own provider keys
    as headers (see APIKeyStore.headers() / X-RCR-* names below) rather
    than this server holding secrets — matches the Settings screen's
    "the configured backend receives only the credentials needed for
    that scan" copy.

    RESILIENCE (patched): the phase3 imports used to run unconditionally
    at the top of this function, before checking whether the request even
    had the keys needed to use them. If a phase3/ module failed to import
    in the deployed environment, the whole request threw an unhandled
    exception and FastAPI returned a bare 500 with no detail — every scan
    failed the same way regardless of input (confirmed via `curl -i`
    against production: HTTP/2 500, generic Vercel "Internal Server
    Error" body, no traceback). Each phase3 import is now scoped to its
    own try/except next to the source that uses it, and the whole
    function body has a final fallback, so a broken/unreachable module
    degrades to one "error" source entry in a normal 200 response instead
    of crashing the endpoint outright.
    """
    h = request.headers
    vision_keys = _resolve_vision_keys(h)           # provider -> key, for anthropic/grok/openrouter
    llm_strategy = (h.get("x-rcr-llm-strategy") or os.getenv("LLM_STRATEGY", "fallback")).lower()
    llm_provider_pref = (h.get("x-rcr-llm-provider") or os.getenv("LLM_PROVIDER", "anthropic")).lower()
    llm_model_override = h.get("x-rcr-llm-model") or os.getenv("LLM_MODEL") or None
    municipal_url = h.get("x-rcr-municipal-url") or None
    municipal_token = h.get("x-rcr-municipal-token") or None

    sources: list[RadarSourceOut] = []
    cameras_out: list[RadarCameraOut] = []
    observations: list[RadarObservationOut] = []
    detections: list[RawDetection] = []  # signal_fusion input — one per
                                          # observation below, written to
                                          # CloudKit near the end of this
                                          # function
    sightings_out: list[RadarSightingOut] = []
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # Anchor the collectors/ path to this file's own directory instead
        # of the process's current working directory — cwd isn't
        # guaranteed to be the repo root in every deployment target
        # (Vercel included), which is the most likely reason the imports
        # below were failing.
        collectors_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collectors")
        if collectors_dir not in sys.path:
            sys.path.append(collectors_dir)

        # ---- Camera vision (Caltrans) — now multi-provider ----
        if not vision_keys:
            sources.append(RadarSourceOut(
                id="camera_vision", name="Traffic Camera Vision", status="skipped",
                detail="No AI provider key — add Anthropic, xAI (Grok), and/or OpenRouter in Settings > AI Providers."
            ))
        else:
            try:
                from california_camera_directory import fetch_all_california_cameras, cameras_near
                from traffic_camera_vision import check_frame_for_truck

                all_cams = fetch_all_california_cameras()
                nearby = [c for c in cameras_near(all_cams, payload.latitude, payload.longitude, payload.radiusMiles) if c.in_service]
                # Cap how many cameras get an LLM vision call per scan — this
                # costs real money per camera; a tighter cap than the module
                # default keeps a single scan predictable. Raise if you want
                # to spend more per scan than this.
                nearby = nearby[:6]

                cameras_out = [
                    RadarCameraOut(
                        id=cam.location_name, location_name=cam.location_name,
                        county=cam.county, route=cam.route,
                        latitude=cam.latitude, longitude=cam.longitude,
                        current_image_url=cam.current_image_url, in_service=cam.in_service,
                    )
                    for cam in nearby
                ]

                hits = 0
                rr_state = {"i": 0}
                providers_used: set[str] = set()
                for cam in nearby:
                    try:
                        result, provider_used = _vision_check_with_strategy(
                            cam, vision_keys, llm_strategy, llm_provider_pref,
                            llm_model_override, rr_state, check_frame_for_truck,
                        )
                        providers_used.add(provider_used)
                    except Exception as e:
                        print(f"camera check failed for {cam.location_name}: {e}")
                        continue
                    if result.get("likely_food_truck_present"):
                        hits += 1
                        conf_map = {"high": 0.85, "medium": 0.6, "low": 0.35}
                        raw_confidence = conf_map.get(result.get("confidence"), 0.5)
                        observations.append(RadarObservationOut(
                            id=str(uuid.uuid4()), source="camera",
                            sourceID=cam.location_name, observedAt=now_iso,
                            latitude=cam.latitude, longitude=cam.longitude,
                            text=result.get("reasoning"), sourceURL=cam.current_image_url,
                            rawConfidence=raw_confidence,
                            metadata={
                                "estimated_crowd_size": str(result.get("estimated_crowd_size", "")),
                                "vision_provider": provider_used,
                            },
                        ))
                        # Feed the same hit into signal fusion so a
                        # confident match becomes a real Sighting record —
                        # see the write-through block below. Vision alone
                        # rarely carries a truck NAME, so this mostly
                        # relies on corroboration with municipal permits
                        # (which do) unless you add OCR/logo recognition.
                        detections.append(RawDetection(
                            source="traffic_cam",
                            latitude=cam.latitude, longitude=cam.longitude,
                            timestamp=now,
                            raw_confidence=raw_confidence,
                            source_id=cam.location_name,
                            note=f"Camera at {cam.location_name}: {result.get('reasoning', '')}",
                        ))
                strategy_note = f"strategy={llm_strategy}, provider(s) used: {', '.join(sorted(providers_used)) or 'none'}"
                sources.append(RadarSourceOut(
                    id="camera_vision", name="Traffic Camera Vision", status="ok",
                    detail=f"Checked {len(nearby)} camera(s), {hits} likely detection(s) ({strategy_note})."
                ))
            except Exception as e:
                print(f"camera_vision source failed: {traceback.format_exc()}")
                sources.append(RadarSourceOut(
                    id="camera_vision", name="Traffic Camera Vision", status="error",
                    detail=f"{type(e).__name__}: {e}"
                ))

        # ---- Municipal food-truck permits ----
        if not municipal_url:
            sources.append(RadarSourceOut(
                id="municipal", name="Municipal Permits", status="skipped",
                detail="No municipal dataset URL — add one in Settings > Municipal/Signal/Delivery."
            ))
        else:
            try:
                from municipal_open_data import fetch_food_truck_permits

                permits = fetch_food_truck_permits(dataset_url=municipal_url, app_token=municipal_token)
                for p in permits:
                    truck_name = p.get("truck_name")
                    observations.append(RadarObservationOut(
                        id=str(uuid.uuid4()), source="municipal",
                        sourceID=str(truck_name or "unknown"), observedAt=now_iso,
                        latitude=payload.latitude, longitude=payload.longitude,  # permit data is rarely geocoded per-row; see note below
                        text=p.get("permitted_location"), rawConfidence=0.4,
                        metadata={"permit_valid_until": str(p.get("permit_valid_until") or "")},
                    ))
                    # Unlike camera hits, permit rows usually DO carry the
                    # truck's actual name — pass it as text_hint so
                    # signal_fusion can name-match it against
                    # KNOWN_TRUCK_NAMES and auto-attach a real Sighting
                    # instead of always landing in the review queue.
                    detections.append(RawDetection(
                        source="municipal_permit",
                        latitude=payload.latitude, longitude=payload.longitude,
                        timestamp=now,
                        raw_confidence=0.4,
                        text_hint=truck_name,
                        note=p.get("permitted_location"),
                    ))
                sources.append(RadarSourceOut(
                    id="municipal", name="Municipal Permits", status="ok",
                    detail=f"Found {len(permits)} permit record(s)."
                ))
            except Exception as e:
                print(f"municipal source failed: {traceback.format_exc()}")
                sources.append(RadarSourceOut(
                    id="municipal", name="Municipal Permits", status="error",
                    detail=f"{type(e).__name__}: {e}"
                ))

        # ---- Not-yet-wired sources — reported honestly rather than omitted ----
        for source_id, name in [
            ("telecom", "Telecom Signal Anomalies"),
            ("delivery", "Delivery Pickup Pins"),
            ("social", "Social Scraper"),
        ]:
            sources.append(RadarSourceOut(
                id=source_id, name=name, status="skipped",
                detail="Not wired into /api/radar/scan yet — see collectors/ module of the same purpose."
            ))

        # ---- Signal fusion write-through: turn confident hits into real
        # Sighting records (map pins), everything else into an
        # UnmatchedDetection for the Owner Dashboard's review queue. This
        # is what previously left `sightings` hardcoded to []: raw
        # observations were returned to the app, but nothing ever wrote a
        # Sighting anywhere the map reads from. ----
        if not detections:
            sources.append(RadarSourceOut(
                id="sighting_write", name="Sighting Write-Through", status="skipped",
                detail="No detections this scan to fuse."
            ))
        else:
            written = 0
            queued = 0
            errored = 0
            for detection in detections:
                try:
                    result = signal_fusion.process_detection(detection, detections)
                except Exception as e:
                    print(f"signal_fusion failed for a detection: {traceback.format_exc()}")
                    errored += 1
                    continue
                if result.sighting:
                    written += 1
                    sightings_out.append(RadarSightingOut(**result.sighting))
                else:
                    queued += 1
            status = "ok" if errored == 0 else ("error" if written == 0 and queued == 0 else "ok")
            detail = f"{written} sighting(s) written to CloudKit, {queued} queued for review"
            if errored:
                detail += f", {errored} failed (likely CLOUDKIT_CONTAINER_ID/KEY_ID not configured server-side — see cloudkit_bridge.py)"
            sources.append(RadarSourceOut(id="sighting_write", name="Sighting Write-Through", status=status, detail=detail + "."))

        confidence = min(1.0, 0.2 + 0.15 * len(observations) + 0.1 * len(sightings_out)) if observations else 0.0
        summary_bits = [f"{len(observations)} signal(s) found across {sum(1 for s in sources if s.status == 'ok')} active source(s)."]
        if sightings_out:
            summary_bits.append(f"{len(sightings_out)} confirmed sighting(s) added to the map.")
        summary = " ".join(summary_bits) if observations else "No signals found in this scan."

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
        # Final safety net: something broke outside the per-source blocks
        # above (e.g. the sys.path setup itself). Log the full traceback
        # server-side for debugging, but still hand the client a normal
        # 200 response instead of a bare 500 — the app's SCAN NOW alert
        # will now show a real detail string instead of a generic
        # NSURLErrorDomain -1011 with no information.
        print(f"radar_scan crashed outside per-source handling: {traceback.format_exc()}")
        return RadarScanResultOut(
            id=str(uuid.uuid4()),
            scanned_at=now_iso,
            sources=[RadarSourceOut(
                id="scan", name="Radar Scan", status="error",
                detail=f"Scan failed unexpectedly: {type(e).__name__}: {e}"
            )],
            cameras=[],
            sightings=[],
            observations=[],
            summary="Scan failed unexpectedly — see server logs.",
            confidence=0.0,
            evidence_count=0,
        )
