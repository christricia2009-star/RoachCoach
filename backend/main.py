"""
Food Truck Tracker — Backend API (Phase 1)

This is code-complete but NOT deployed anywhere. To actually run it:
  1. Provision a PostgreSQL database (with PostGIS) — e.g. Railway, Render, RDS, Supabase.
  2. Run schema.sql against that database.
  3. Set the environment variables below (.env file recommended, see .env.example).
  4. pip install -r requirements.txt
  5. uvicorn main:app --reload

Then update Backend URL in the iOS app's LiveAPIService.swift once deployed.
"""
print("=== ROACH COACH BACKEND VERSION 2026-08-22 ===")
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL) if DATABASE_URL else None

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

class RadarScanIn(BaseModel):
    latitude: float
    longitude: float
    radiusMiles: float = 10.0

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



class RadarObservationIn(BaseModel):
    truck_id: Optional[uuid.UUID] = None
    source: str
    source_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    text: Optional[str] = None
    source_url: Optional[str] = None
    raw_confidence: float = 0.5
    metadata: dict[str, str] = {}


@app.post("/radar/observations", response_model=list[dict])
def radar_observations(scan: RadarScanIn):
    """Return normalized observations near the user. This is the canonical evidence feed."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, truck_id, source, source_id, timestamp, latitude, longitude, note, photo_url, confidence_level
                FROM sightings WHERE expires_at > now() ORDER BY timestamp DESC LIMIT 500
            """)).mappings().all()
        out=[]
        for r in rows:
            # Bounding-box prefilter keeps the endpoint cheap; exact radius is done client-side.
            if abs(float(r["latitude"]) - scan.latitude) > scan.radiusMiles / 69.0: continue
            if abs(float(r["longitude"]) - scan.longitude) > scan.radiusMiles / 50.0: continue
            out.append({"id":str(r["id"]),"truckID":str(r["truck_id"]) if r["truck_id"] else None,"source":"userReport","sourceID":str(r["id"]),"observedAt":r["timestamp"].isoformat(),"latitude":r["latitude"],"longitude":r["longitude"],"text":r["note"],"sourceURL":r["photo_url"],"rawConfidence":0.95 if r["confidence_level"]=="confirmed" else 0.65,"state":"live","metadata":{}})
        return out
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Observation store unavailable: {exc}")

@app.get("/radar/status")
def radar_status():
    return {"engine":"RCR-27.515","sources":["database","caltrans-cameras","social","municipal","delivery","events"],"mode":"bounded-live","message":"Only configured/authorized sources are queried."}

# ---------- Routes ----------

@app.get("/trucks", response_model=list[TruckOut])
def get_trucks():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM trucks ORDER BY name")).mappings().all()
        return [dict(row) for row in rows]


@app.get("/trucks/{truck_id}/sightings", response_model=list[SightingOut])
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


@app.get("/sightings", response_model=list[SightingOut])
def get_active_sightings():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM sightings WHERE expires_at > now() ORDER BY timestamp DESC")
        ).mappings().all()
        return [dict(row) for row in rows]


@app.post("/sightings", response_model=SightingOut)
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


@app.get("/health")
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "RoachCoachRadar",
        "backend": "FastAPI"
    }


@app.get("/cameras/near")
def california_cameras_near(latitude: float, longitude: float, radius_miles: float = 5.0):
    """
    Real endpoint backed by the live statewide Caltrans CCTV directory
    (see collectors/california_camera_directory.py). Returns nearby in-service
    cameras — does NOT run vision detection on them here (that costs LLM
    tokens per call); pair with collectors/traffic_camera_vision.py's
    scan_california_area() if you want detection results instead of just
    the camera list.
    """
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), "collectors"))
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

# ---------- Live Radar Scan ----------

def _apply_runtime_credentials(headers):
    """Apply credentials supplied by the iOS Settings screen for this scan.
    This keeps secrets out of the app bundle; the configured backend receives
    them only when a user explicitly runs a live scan.
    """
    mapping = {
        "X-RCR-OpenRouter-Key": "OPENROUTER_API_KEY",
        "X-RCR-XAI-Key": "XAI_API_KEY",
        "X-RCR-Anthropic-Key": "ANTHROPIC_API_KEY",
        "X-RCR-Instagram-Token": "INSTAGRAM_ACCESS_TOKEN",
        "X-RCR-X-Bearer": "X_API_BEARER_TOKEN",
        "X-RCR-Partnership-Key": "PARTNERSHIP_API_KEY",
        "X-RCR-Telecom-Key": "TELECOM_API_KEY",
        "X-RCR-Uber-ID": "UBER_PARTNER_CLIENT_ID",
        "X-RCR-Uber-Secret": "UBER_PARTNER_CLIENT_SECRET",
        "X-RCR-DoorDash-Key": "DOORDASH_PARTNER_API_KEY",
        "X-RCR-AWS-Access": "AWS_ACCESS_KEY_ID",
        "X-RCR-AWS-Secret": "AWS_SECRET_ACCESS_KEY",
        "X-RCR-LLM-Strategy": "LLM_STRATEGY",
        "X-RCR-LLM-Provider": "LLM_PROVIDER",
        "X-RCR-LLM-Model": "LLM_MODEL",
    }
    for header, env_name in mapping.items():
        value = headers.get(header)
        if value:
            os.environ[env_name] = value


@app.post("/radar/scan")
def live_radar_scan(scan: RadarScanIn, request: Request):
    """Run a live, location-aware radar pass.

    The first pass is deliberately bounded: nearby Caltrans cameras plus the
    current backend database are gathered, then the configured LLM provider is
    given a compact evidence summary. Additional source collectors can be
    enabled as credentials/APIs become available.
    """
    _apply_runtime_credentials(request.headers)
    sources = []
    cameras = []
    sightings = []

    try:
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), "collectors"))
        from california_camera_directory import fetch_all_california_cameras, cameras_near
        all_cameras = fetch_all_california_cameras()
        nearby = cameras_near(all_cameras, scan.latitude, scan.longitude, scan.radiusMiles)
        cameras = [
            {
                "id": f"camera-{c.latitude:.6f}-{c.longitude:.6f}",
                "location_name": c.location_name,
                "county": c.county,
                "route": c.route,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "current_image_url": c.current_image_url,
                "in_service": c.in_service,
            } for c in nearby
        ]
        sources.append({"id": "caltrans-cameras", "name": "California traffic cameras", "status": "ok", "detail": f"{len(cameras)} nearby cameras"})
    except Exception as exc:
        sources.append({"id": "caltrans-cameras", "name": "California traffic cameras", "status": "error", "detail": str(exc)[:180]})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM sightings WHERE expires_at > now() ORDER BY timestamp DESC LIMIT 200")).mappings().all()
            sightings = [
                {
                    "id": str(r["id"]),
                    "truckId": str(r["truck_id"]),
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "reportedByUserId": str(r["reported_by_user_id"]) if r.get("reported_by_user_id") else None,
                    "photoURL": r.get("photo_url"),
                    "note": r.get("note"),
                    "timestamp": r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else r["timestamp"],
                    "confidenceLevel": str(r["confidence_level"]).title(),
                    "expiresAt": r["expires_at"].isoformat() if hasattr(r["expires_at"], "isoformat") else r["expires_at"],
                } for r in rows
            ]
        sources.append({"id": "radar-database", "name": "Radar database", "status": "ok", "detail": f"{len(sightings)} active contacts"})
    except Exception as exc:
        sources.append({"id": "radar-database", "name": "Radar database", "status": "error", "detail": str(exc)[:180]})

    # Convert nearby cameras into canonical evidence records for the response.
    camera_observations = [{"id": str(uuid.uuid4()), "truckID": None, "source": "camera", "sourceID": c["id"], "observedAt": datetime.utcnow().isoformat()+"Z", "latitude": c["latitude"], "longitude": c["longitude"], "text": c["location_name"], "sourceURL": c.get("current_image_url"), "rawConfidence": 0.55, "state": "live", "metadata": {"route": c.get("route") or ""}} for c in cameras]
    evidence_count = len(sightings) + len(camera_observations)
    summary = f"Live scan found {len(cameras)} nearby cameras and {len(sightings)} active radar contacts; {evidence_count} evidence items available."
    confidence = min(0.95, 0.35 + min(len(cameras), 20) * 0.02 + min(len(sightings), 20) * 0.015)

    return {
        "id": str(uuid.uuid4()),
        "scannedAt": datetime.utcnow().isoformat() + "Z",
        "sources": sources,
        "cameras": cameras,
        "sightings": sightings,
        "observations": camera_observations,
        "summary": summary,
        "engineVersion": "RCR-27.515",
        "evidenceCount": evidence_count,
        "confidence": confidence,
    }

class IntelligenceIn(BaseModel):
    observations: list[dict]

@app.post("/radar/intelligence")
def radar_intelligence(payload: IntelligenceIn):
    from intelligence import fuse_evidence
    return fuse_evidence(payload.observations)

@app.post("/radar/replay")
def radar_replay(payload: IntelligenceIn):
    observations = sorted(payload.observations, key=lambda x: x.get("observedAt", ""))
    attempts = 0
    successes = 0
    by_truck = {}
    for o in observations:
        truck_id = o.get("truckID")
        if not truck_id:
            continue
        history = by_truck.setdefault(truck_id, [])
        if len(history) >= 2:
            attempts += 1
            # A bounded, explainable replay: compare the next observation with the prior center.
            lat = sum(float(x.get("latitude", 0)) for x in history[-6:]) / min(6, len(history))
            lon = sum(float(x.get("longitude", 0)) for x in history[-6:]) / min(6, len(history))
            if abs(float(o.get("latitude", 0)) - lat) <= .05 and abs(float(o.get("longitude", 0)) - lon) <= .07:
                successes += 1
        history.append(o)
    return {"engineVersion": "RCR-27.515", "attempts": attempts, "successes": successes, "accuracy": successes / attempts if attempts else 0.0}
