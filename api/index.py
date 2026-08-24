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

    expected_token = os.getenv("IMPORT_ADMIN_TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=500,
            detail="IMPORT_ADMIN_TOKEN is not configured",
        )

    supplied_token = request.headers.get("X-Import-Token")

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
            detail=f"Invalid truck JSON: {exc}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read truck JSON: {exc}",
        )

    # -----------------------------------------------------
    # Validate JSON structure
    # -----------------------------------------------------

    if not isinstance(trucks, list):
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
            "environment": os.getenv(
                "CLOUDKIT_ENVIRONMENT",
                "production",
            ),
            "requested": 0,
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

    # -----------------------------------------------------
    # Write to CloudKit
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Process CloudKit results
    #
    # CloudKit can return successful records in either:
    #
    #   {"record": {...}}
    #
    # OR directly as:
    #
    #   {"recordName": "...", "recordType": "Truck", ...}
    #
    # Your production response is the second format.
    # -----------------------------------------------------

    successful = 0
    failed = 0
    errors = []

    for result in results:

        if not isinstance(result, dict):
            failed += 1

            errors.append({
                "recordName": None,
                "reason": "Invalid CloudKit batch response",
                "serverErrorCode": None,
                "record": None,
                "raw": result,
            })

            continue

        batch_records = result.get("records", [])
        batch_errors = result.get("errors", [])

        if not isinstance(batch_records, list):
            batch_records = []

        if not isinstance(batch_errors, list):
            batch_errors = []

        # -------------------------------------------------
        # Process records
        # -------------------------------------------------

        for item in batch_records:

            if not isinstance(item, dict):
                failed += 1

                errors.append({
                    "recordName": None,
                    "reason": "Invalid CloudKit record response",
                    "serverErrorCode": None,
                    "record": None,
                    "raw": item,
                })

                continue

            # -------------------------------------------------
            # FORMAT 1:
            #
            # {
            #   "record": {...}
            # }
            # -------------------------------------------------

            nested_record = item.get("record")

            if isinstance(nested_record, dict):
                successful += 1
                continue

            # -------------------------------------------------
            # FORMAT 2:
            #
            # {
            #   "recordName": "...",
            #   "recordType": "Truck",
            #   "fields": {...},
            #   "reason": null,
            #   "serverErrorCode": null
            # }
            #
            # This is the format your production CloudKit
            # response is actually returning.
            # -------------------------------------------------

            record_name = item.get("recordName")
            record_type = item.get("recordType")
            fields = item.get("fields")

            reason = item.get("reason")
            server_error_code = item.get("serverErrorCode")

            if (
                record_name
                and record_type
                and isinstance(fields, dict)
                and not reason
                and not server_error_code
            ):
                successful += 1
                continue

            # -------------------------------------------------
            # Anything else is an actual failure.
            # -------------------------------------------------

            failed += 1

            errors.append({
                "recordName": record_name,
                "reason": reason,
                "serverErrorCode": server_error_code,
                "record": nested_record,
                "raw": item,
            })

        # -------------------------------------------------
        # Process explicit CloudKit errors
        # -------------------------------------------------

        for item in batch_errors:

            failed += 1

            if isinstance(item, dict):
                errors.append({
                    "recordName": item.get("recordName"),
                    "reason": item.get("reason"),
                    "serverErrorCode": item.get(
                        "serverErrorCode"
                    ),
                    "record": item.get("record"),
                    "raw": item,
                })

            else:
                errors.append({
                    "recordName": None,
                    "reason": str(item),
                    "serverErrorCode": None,
                    "record": None,
                    "raw": item,
                })

        # -------------------------------------------------
        # Empty CloudKit response
        # -------------------------------------------------

        if not batch_records and not batch_errors:
            errors.append({
                "recordName": None,
                "reason": (
                    "CloudKit returned no records or errors"
                ),
                "serverErrorCode": None,
                "record": None,
                "raw": result,
            })

    # -----------------------------------------------------
    # Make sure accounting matches the requested count.
    # -----------------------------------------------------

    accounted = successful + failed

    if accounted < len(trucks):

        missing = len(trucks) - accounted

        failed += missing

        errors.append({
            "recordName": None,
            "reason": (
                "CloudKit response accounted for "
                f"{accounted} of "
                f"{len(trucks)} requested records"
            ),
            "serverErrorCode": None,
            "record": None,
            "raw": results,
        })

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
        "requested": len(trucks),
        "successful": successful,
        "failed": failed,
        "errors": errors,
    }
