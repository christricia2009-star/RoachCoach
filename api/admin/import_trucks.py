import json
import sys
from pathlib import Path

from fastapi import HTTPException, Request

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA_FILE = ROOT / "data" / "sacramento_trucks.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cloudkit_client import CloudKitError, upsert_trucks


async def handler(request: Request):

    if request.method != "POST":
        raise HTTPException(
            status_code=405,
            detail="POST required",
        )

    token = request.headers.get(
        "X-Import-Token"
    )

    expected = __import__("os").environ.get(
        "IMPORT_ADMIN_TOKEN"
    )

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="IMPORT_ADMIN_TOKEN is not configured",
        )

    if not token or token != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid import token",
        )

    if not DATA_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Missing {DATA_FILE}",
        )

    try:
        with DATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            trucks = json.load(f)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read truck JSON: {exc}",
        )

    if not isinstance(trucks, list):
        raise HTTPException(
            status_code=500,
            detail="Truck JSON must be an array",
        )

    try:

        results = upsert_trucks(trucks)

    except CloudKitError as exc:

        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {exc}",
        )

    successful = 0
    failed = 0
    errors = []

    for result in results:

        for item in result.get(
            "records",
            [],
        ):

            if item.get("record"):

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

    return {
        "status": (
            "success"
            if failed == 0
            else "partial"
        ),
        "requested": len(trucks),
        "successful": successful,
        "failed": failed,
        "errors": errors,
    }


# Vercel Python entrypoint
app = handler
