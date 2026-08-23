import sys
from pathlib import Path

from fastapi import Request

BACKEND = Path(__file__).resolve().parents[1] / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Import the existing radar application without changing it.
from main import (  # noqa: E402
    RadarObservationOut,
    RadarScanRequestIn,
    app,
    radar_scan,
)

from cloudkit_client import (  # noqa: E402
    CloudKitError,
    fetch_sightings,
    fetch_sightings_for_truck,
    fetch_trucks,
)


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health_compat():
    return {
        "status": "ok",
        "cloudkit": True,
    }


# ---------------------------------------------------------
# Trucks
# ---------------------------------------------------------

@app.get("/trucks")
def trucks_compat():
    try:
        return fetch_trucks()
    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# ---------------------------------------------------------
# Sightings
# ---------------------------------------------------------

@app.get("/sightings")
def sightings_compat():
    try:
        return fetch_sightings()
    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# ---------------------------------------------------------
# Truck-specific sightings
# ---------------------------------------------------------

@app.get("/trucks/{truck_id}/sightings")
def truck_sightings_compat(truck_id: str):
    try:
        return fetch_sightings_for_truck(truck_id)
    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# ---------------------------------------------------------
# Radar compatibility endpoint
# ---------------------------------------------------------

# Existing iOS app calls:
#
# POST /radar/observations
#
# The existing radar engine is retained.

@app.post(
    "/radar/observations",
    response_model=list[RadarObservationOut],
)
def radar_observations_compat(
    payload: RadarScanRequestIn,
    request: Request,
):
    result = radar_scan(
        payload,
        request,
    )

    return result.observations
