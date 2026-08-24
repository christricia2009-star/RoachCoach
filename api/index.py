import json
import os
import sys
from pathlib import Path

from fastapi import Request, HTTPException

BACKEND = Path(__file__).resolve().parents[1] / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import (
    RadarObservationOut,
    RadarScanRequestIn,
    app,
    radar_scan,
)

from cloudkit_client import (
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
# RADAR
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


# =========================================================
# ONE-TIME CLOUDKIT TRUCK IMPORT
# =========================================================

@app.post("/admin/import-trucks")
async def import_trucks(request: Request):

    # -----------------------------------------------------
    # Protect the importer
    # -----------------------------------------------------

    expected_token = os.getenv(
        "IMPORT_ADMIN_TOKEN"
    )

    if not expected_token:

        raise HTTPException(
            status_code=500,
            detail=(
                "IMPORT_ADMIN_TOKEN "
                "is not configured"
            ),
        )

    supplied_token = request.headers.get(
        "X-Import-Token"
    )

    if supplied_token != expected_token:

        raise HTTPException(
            status_code=401,
            detail="Invalid import token",
        )

    # -----------------------------------------------------
    # Locate seed JSON
    # -----------------------------------------------------

    data_file = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "sacramento_trucks.json"
    )

    if not data_file.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                "Truck seed file not found: "
                f"{data_file}"
            ),
        )

    # -----------------------------------------------------
    # Read JSON
    # -----------------------------------------------------

    try:

        with data_file.open(
            "r",
            encoding="utf-8",
        ) as file:

            trucks = json.load(file)

    except json.JSONDecodeError as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Invalid truck JSON: "
                f"{exc}"
            ),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to read truck JSON: "
                f"{exc}"
            ),
        )

    # -----------------------------------------------------
    # Validate JSON structure
    # -----------------------------------------------------

    if not isinstance(
        trucks,
        list,
    ):

        raise HTTPException(
            status_code=500,
            detail=(
                "sacramento_trucks.json "
                "must contain a JSON array"
            ),
        )

    if not trucks:

        return {
            "status": "empty",
            "requested": 0,
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

    # -----------------------------------------------------
    # Write to CloudKit
    # -----------------------------------------------------

    try:

        results = upsert_trucks(
            trucks
        )

    except CloudKitError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "CloudKit import failed: "
                f"{exc}"
            ),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Truck import failed: "
                f"{exc}"
            ),
        )

    # -----------------------------------------------------
    # Process CloudKit results
    # -----------------------------------------------------

    successful = 0
    failed = 0
    errors = []

    for result in results:

        for item in result.get(
            "records",
            [],
        ):

            record = item.get(
                "record"
            )

            if record:

                successful += 1

            else:

                failed += 1

                errors.append(
                    {
                        "recordName":
                            item.get(
                                "recordName"
                            ),

                        "reason":
                            item.get(
                                "reason"
                            ),

                        "serverErrorCode":
                            item.get(
                                "serverErrorCode"
                            ),
                    }
                )

    # -----------------------------------------------------
    # Return import summary
    # -----------------------------------------------------

    return {
        "status": (
            "success"
            if failed == 0
            else "partial"
        ),

        "environment": os.getenv(
            "CLOUDKIT_ENVIRONMENT",
            "production",
        ),

        "requested": len(
            trucks
        ),

        "successful": successful,

        "failed": failed,

        "errors": errors,
    }
