import json
import sys
from pathlib import Path

from fastapi import Request, HTTPException

BACKEND = Path(__file__).resolve().parents[1] / "backend"
ROOT = Path(__file__).resolve().parents[1]
TRUCK_DATA = ROOT / "data" / "sacramento_trucks.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Existing radar application.
from main import (  # noqa: E402
    RadarObservationOut,
    RadarScanRequestIn,
    app,
    radar_scan,
)

# CloudKit.
from cloudkit_client import (  # noqa: E402
    CloudKitError,
    fetch_sightings,
    fetch_sightings_for_truck,
    fetch_trucks,
    upsert_trucks,
)


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health_compat():
    return {
        "status": "ok",
        "cloudkit": True,
    }


# =========================================================
# TRUCKS
# =========================================================

@app.get("/trucks")
def trucks_compat():
    try:
        return fetch_trucks()

    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# =========================================================
# SIGHTINGS
# =========================================================

@app.get("/sightings")
def sightings_compat():
    try:
        return fetch_sightings()

    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# =========================================================
# TRUCK-SPECIFIC SIGHTINGS
# =========================================================

@app.get("/trucks/{truck_id}/sightings")
def truck_sightings_compat(truck_id: str):
    try:
        return fetch_sightings_for_truck(truck_id)

    except CloudKitError as exc:
        return {
            "error": "CloudKit unavailable",
            "detail": str(exc),
        }


# =========================================================
# CLOUDKIT TRUCK IMPORT
# =========================================================
#
# POST /admin/import-trucks
#
# Reads:
#
# data/sacramento_trucks.json
#
# and writes/updates Truck records in CloudKit.
#
# The endpoint is protected by:
#
# IMPORT_ADMIN_TOKEN
#
# Vercel environment variable.
#
# Send:
#
# X-Admin-Token: <same value>
#
# =========================================================

@app.post("/admin/import-trucks")
def import_trucks(request: Request):

    configured_token = (
        __import__("os")
        .environ.get("IMPORT_ADMIN_TOKEN")
    )

    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="IMPORT_ADMIN_TOKEN is not configured",
        )

    supplied_token = request.headers.get(
        "X-Admin-Token"
    )

    if supplied_token != configured_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid import token",
        )

    if not TRUCK_DATA.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Truck seed file not found: "
                f"{TRUCK_DATA}"
            ),
        )

    try:
        with TRUCK_DATA.open(
            "r",
            encoding="utf-8",
        ) as file:
            trucks = json.load(file)

    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid truck JSON: {exc}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read truck JSON: {exc}",
        )

    if not isinstance(trucks, list):
        raise HTTPException(
            status_code=500,
            detail="Truck JSON must contain an array",
        )

    try:
        results = upsert_trucks(trucks)

    except CloudKitError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CloudKit import failed: {exc}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Truck import failed: {exc}",
        )

    processed = 0
    errors = []

    for result in results:

        for record_result in result.get(
            "records",
            [],
        ):

            record = record_result.get(
                "record"
            )

            if record:
                processed += 1
                continue

            error = {
                "recordName": record_result.get(
                    "recordName"
                ),
                "reason": record_result.get(
                    "reason"
                ),
                "serverErrorCode":
                    record_result.get(
                        "serverErrorCode"
                    ),
            }

            errors.append(error)

    return {
        "status": (
            "ok"
            if not errors
            else "partial"
        ),
        "environment": (
            __import__("os")
            .environ.get(
                "CLOUDKIT_ENVIRONMENT",
                "production",
            )
        ),
        "container": (
            __import__("os")
            .environ.get(
                "CLOUDKIT_CONTAINER_ID",
                "iCloud.com.TrueFamily.RoachCoachRadar",
            )
        ),
        "source": str(TRUCK_DATA),
        "requested": len(trucks),
        "processed": processed,
        "errors": errors,
    }


# =========================================================
# RADAR COMPATIBILITY ENDPOINT
# =========================================================
#
# Existing iOS app calls:
#
# POST /radar/observations
#
# Keep the existing radar engine.
# =========================================================

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
