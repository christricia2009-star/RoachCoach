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

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
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
