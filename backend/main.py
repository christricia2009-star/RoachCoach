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
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

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


class RadarScanResultOut(BaseModel):
    id: str
    scanned_at: str
    sources: list[RadarSourceOut]
    cameras: list[RadarCameraOut]
    sightings: list = []  # populated once this route writes real matched
                           # Sighting records; camera/municipal hits below
                           # are raw signal, not confirmed truck matches
    observations: list[RadarObservationOut]
    summary: str
    confidence: float
    engine_version: Optional[str] = "0.1.0-scan-route"
    evidence_count: Optional[int] = None


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
    sys.path.append("phase3")
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
    anthropic_key = h.get("x-rcr-anthropic-key") or os.getenv("ANTHROPIC_API_KEY")
    municipal_url = h.get("x-rcr-municipal-url") or None
    municipal_token = h.get("x-rcr-municipal-token") or None

    sources: list[RadarSourceOut] = []
    cameras_out: list[RadarCameraOut] = []
    observations: list[RadarObservationOut] = []
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # Anchor the phase3 path to this file's own directory instead of
        # the process's current working directory — cwd isn't guaranteed
        # to be the repo root in every deployment target (Vercel included),
        # which is the most likely reason the imports below were failing.
        phase3_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase3")
        if phase3_dir not in sys.path:
            sys.path.append(phase3_dir)

        # ---- Camera vision (Caltrans) ----
        if not anthropic_key:
            sources.append(RadarSourceOut(
                id="camera_vision", name="Traffic Camera Vision", status="skipped",
                detail="No Anthropic API key — add one in Settings > AI Providers."
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
                for cam in nearby:
                    try:
                        result = check_frame_for_truck(cam.current_image_url, anthropic_api_key=anthropic_key)
                    except Exception as e:
                        print(f"camera check failed for {cam.location_name}: {e}")
                        continue
                    if result.get("likely_food_truck_present"):
                        hits += 1
                        conf_map = {"high": 0.85, "medium": 0.6, "low": 0.35}
                        observations.append(RadarObservationOut(
                            id=str(uuid.uuid4()), source="camera",
                            sourceID=cam.location_name, observedAt=now_iso,
                            latitude=cam.latitude, longitude=cam.longitude,
                            text=result.get("reasoning"), sourceURL=cam.current_image_url,
                            rawConfidence=conf_map.get(result.get("confidence"), 0.5),
                            metadata={"estimated_crowd_size": str(result.get("estimated_crowd_size", ""))},
                        ))
                sources.append(RadarSourceOut(
                    id="camera_vision", name="Traffic Camera Vision", status="ok",
                    detail=f"Checked {len(nearby)} camera(s), {hits} likely detection(s)."
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
                    observations.append(RadarObservationOut(
                        id=str(uuid.uuid4()), source="municipal",
                        sourceID=str(p.get("truck_name") or "unknown"), observedAt=now_iso,
                        latitude=payload.latitude, longitude=payload.longitude,  # permit data is rarely geocoded per-row; see note below
                        text=p.get("permitted_location"), rawConfidence=0.4,
                        metadata={"permit_valid_until": str(p.get("permit_valid_until") or "")},
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
                detail="Not wired into /api/radar/scan yet — see phase3/ module of the same purpose."
            ))

        confidence = min(1.0, 0.2 + 0.15 * len(observations)) if observations else 0.0
        summary = (
            f"{len(observations)} signal(s) found across {sum(1 for s in sources if s.status == 'ok')} active source(s)."
            if observations else
            "No signals found in this scan."
        )

        return RadarScanResultOut(
            id=str(uuid.uuid4()),
            scanned_at=now_iso,
            sources=sources,
            cameras=cameras_out,
            sightings=[],
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
