import json
import os
import sys
from pathlib import Path
from fastapi import Request, HTTPException

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import RadarObservationOut, RadarScanRequestIn, app, radar_scan
from cloudkit_client import CloudKitError, fetch_sightings, fetch_sightings_for_truck, fetch_trucks, upsert_trucks

@app.get("/health")
def health_compat():
    return {"status": "ok", "cloudkit": True}

@app.get("/trucks")
def trucks_compat():
    try:
        return fetch_trucks()
    except CloudKitError as exc:
        return {"error": "CloudKit unavailable", "detail": str(exc)}

@app.get("/sightings")
def sightings_compat():
    try:
        return fetch_sightings()
    except CloudKitError as exc:
        return {"error": "CloudKit unavailable", "detail": str(exc)}

@app.get("/trucks/{truck_id}/sightings")
def truck_sightings_compat(truck_id: str):
    try:
        return fetch_sightings_for_truck(truck_id)
    except CloudKitError as exc:
        return {"error": "CloudKit unavailable", "detail": str(exc)}

# Canonical radar route: POST.
@app.post("/radar/observations", response_model=list[RadarObservationOut])
def radar_observations_compat(payload: RadarScanRequestIn, request: Request):
    return radar_scan(payload, request).observations

# Compatibility route for deployments/client builds that prepend /api.
@app.post("/api/radar/observations", response_model=list[RadarObservationOut])
def radar_observations_api_compat(payload: RadarScanRequestIn, request: Request):
    return radar_scan(payload, request).observations

# Compatibility GET route. The current iOS source uses POST, but accepting GET
# prevents an older TestFlight build from receiving HTTP 405 while the backend
# is being rolled forward. Query parameters use the same names as the POST body.
@app.get("/radar/observations", response_model=list[RadarObservationOut])
def radar_observations_get_compat(
    request: Request,
    latitude: float,
    longitude: float,
    radiusMiles: float = 10.0,
):
    payload = RadarScanRequestIn(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles)
    return radar_scan(payload, request).observations

@app.get("/api/radar/observations", response_model=list[RadarObservationOut])
def radar_observations_api_get_compat(
    request: Request,
    latitude: float,
    longitude: float,
    radiusMiles: float = 10.0,
):
    payload = RadarScanRequestIn(latitude=latitude, longitude=longitude, radiusMiles=radiusMiles)
    return radar_scan(payload, request).observations

@app.post("/admin/import-trucks")
async def import_trucks(request: Request):
    expected_token = os.getenv("IMPORT_ADMIN_TOKEN")
    if not expected_token:
        raise HTTPException(status_code=500, detail="IMPORT_ADMIN_TOKEN is not configured")
    if request.headers.get("X-Import-Token") != expected_token:
        raise HTTPException(status_code=401, detail="Invalid import token")

    data_file = Path(__file__).resolve().parents[1] / "data" / "sacramento_trucks.json"
    if not data_file.exists():
        raise HTTPException(status_code=404, detail=f"Truck seed file not found: {data_file}")
    try:
        with data_file.open("r", encoding="utf-8") as file:
            trucks = json.load(file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid truck JSON: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to read truck JSON: {exc}")

    if not isinstance(trucks, list):
        raise HTTPException(status_code=500, detail="sacramento_trucks.json must contain a JSON array")
    if not trucks:
        return {"status": "empty", "environment": os.getenv("CLOUDKIT_ENVIRONMENT", "production"), "requested": 0, "successful": 0, "failed": 0, "errors": []}

    try:
        results = upsert_trucks(trucks)
    except CloudKitError as exc:
        raise HTTPException(status_code=502, detail=f"CloudKit import failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Truck import failed: {exc}")

    successful = failed = 0
    errors = []
    for result in results:
        if not isinstance(result, dict):
            failed += 1
            errors.append({"recordName": None, "reason": "Invalid CloudKit batch response", "serverErrorCode": None, "record": None, "raw": result})
            continue
        records = result.get("records", []) if isinstance(result.get("records", []), list) else []
        batch_errors = result.get("errors", []) if isinstance(result.get("errors", []), list) else []
        for item in records:
            if isinstance(item, dict) and isinstance(item.get("record"), dict):
                successful += 1
            elif isinstance(item, dict) and item.get("recordName") and item.get("recordType") and isinstance(item.get("fields"), dict) and not item.get("reason") and not item.get("serverErrorCode"):
                successful += 1
            else:
                failed += 1
                errors.append({"recordName": item.get("recordName") if isinstance(item, dict) else None, "reason": item.get("reason") if isinstance(item, dict) else "Invalid CloudKit record response", "serverErrorCode": item.get("serverErrorCode") if isinstance(item, dict) else None, "record": item.get("record") if isinstance(item, dict) else None, "raw": item})
        for item in batch_errors:
            failed += 1
            errors.append({"recordName": item.get("recordName") if isinstance(item, dict) else None, "reason": item.get("reason") if isinstance(item, dict) else str(item), "serverErrorCode": item.get("serverErrorCode") if isinstance(item, dict) else None, "record": item.get("record") if isinstance(item, dict) else None, "raw": item})

    accounted = successful + failed
    if accounted < len(trucks):
        failed += len(trucks) - accounted
        errors.append({"recordName": None, "reason": f"CloudKit response accounted for {accounted} of {len(trucks)} requested records", "serverErrorCode": None, "record": None, "raw": results})

    return {"status": "success" if failed == 0 else "partial", "environment": os.getenv("CLOUDKIT_ENVIRONMENT", "production"), "requested": len(trucks), "successful": successful, "failed": failed, "errors": errors}
