import sys
from pathlib import Path

from fastapi import Request

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import (  # noqa: E402
    RadarObservationOut,
    RadarScanRequestIn,
    SightingOut,
    TruckOut,
    app,
    get_active_sightings,
    get_trucks,
    radar_scan,
)


# Compatibility routes for the already-shipped iOS app.
# Keep these server-side so the existing iOS binary does not need to change.

@app.get("/health")
def health_compat():
    return {"status": "ok"}


@app.get("/trucks", response_model=list[TruckOut])
def trucks_compat():
    return get_trucks()


@app.get("/sightings", response_model=list[SightingOut])
def sightings_compat():
    return get_active_sightings()


@app.post("/radar/observations", response_model=list[RadarObservationOut])
def radar_observations_compat(
    payload: RadarScanRequestIn,
    request: Request
):
    # The current radar engine returns a full RadarScanResultOut.
    # The existing iOS BackendRadarSource expects only [RadarObservation].
    result = radar_scan(payload, request)
    return result.observations
