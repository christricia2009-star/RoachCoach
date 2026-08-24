#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATA_FILE = ROOT / "data" / "sacramento_trucks.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cloudkit_client import CloudKitError, upsert_trucks


def main():

    print()
    print("=" * 60)
    print("ROACH COACH RADAR - CLOUDKIT TRUCK IMPORT")
    print("=" * 60)
    print()

    container = os.getenv(
        "CLOUDKIT_CONTAINER_ID",
        "iCloud.com.TrueFamily.RoachCoachRadar",
    )

    environment = os.getenv(
        "CLOUDKIT_ENVIRONMENT",
        "production",
    )

    print(f"Container:   {container}")
    print(f"Environment: {environment}")
    print(f"Data file:   {DATA_FILE}")
    print()

    if not DATA_FILE.exists():

        print("ERROR:")
        print(f"Truck data file does not exist:")
        print(DATA_FILE)
        return 1

    try:

        with DATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            trucks = json.load(file)

    except json.JSONDecodeError as exc:

        print("ERROR: Invalid JSON")
        print(exc)
        return 1

    except Exception as exc:

        print("ERROR reading truck file:")
        print(exc)
        return 1

    if not isinstance(
        trucks,
        list,
    ):

        print(
            "ERROR: sacramento_trucks.json "
            "must contain a JSON array."
        )

        return 1

    print(
        f"Found {len(trucks)} truck records "
        "to import."
    )

    print()

    if not trucks:

        print(
            "Nothing to import."
        )

        return 0

    print(
        "CloudKit import starting..."
    )

    print()

    try:

        responses = upsert_trucks(
            trucks
        )

    except CloudKitError as exc:

        print()
        print("CLOUDKIT IMPORT FAILED")
        print()
        print(exc)
        return 1

    except Exception as exc:

        print()
        print("IMPORT FAILED")
        print()
        print(exc)
        return 1

    processed = 0
    failed = 0

    for response in responses:

        for item in response.get(
            "records",
            [],
        ):

            record = item.get(
                "record"
            )

            if record:

                processed += 1

                record_name = record.get(
                    "recordName",
                    "",
                )

                print(
                    f"  ✓ {record_name}"
                )

            else:

                failed += 1

                print(
                    "  ✗ CloudKit record failed:"
                )

                print(
                    json.dumps(
                        item,
                        indent=2,
                    )
                )

    print()
    print("=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print()
    print(
        f"Requested: {len(trucks)}"
    )
    print(
        f"Processed: {processed}"
    )
    print(
        f"Failed:    {failed}"
    )
    print()

    if failed:

        print(
            "Some records failed."
        )

        return 1

    print(
        "All truck records were successfully "
        "written to CloudKit."
    )

    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
