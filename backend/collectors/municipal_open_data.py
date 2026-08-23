"""
Phase 3 (partial): municipal open-data polling.

Many cities run their open-data portals on Socrata (data.cityname.gov) or
similar platforms, which expose PUBLIC, no-partnership-needed APIs for
things like parking sensor occupancy, food truck permits, and event
calendars. This is genuinely runnable code, provided you supply your
actual city's real dataset endpoint — every city's schema differs, so the
field-mapping below is illustrative and WILL need adjusting to match your
city's actual column names.

How to find your city's endpoint:
  1. Search "[your city] open data portal" — most run on
     https://data.[cityname].gov or similar.
  2. Look for a dataset called something like "food truck permits",
     "parking occupancy", "smart parking sensors", or "special events".
  3. Socrata datasets expose a JSON API automatically at a URL like:
     https://data.cityname.gov/resource/{dataset-id}.json
     (no API key needed for reasonable query volumes; an app token raises
     your rate limit but isn't required for light use.)
"""

import os
import requests

# Set this to your actual city's Socrata (or similar) dataset endpoint.
# Example shape (NOT a real working endpoint — replace with your city's):
#   https://data.yourcity.gov/resource/abcd-1234.json
MUNICIPAL_DATASET_URL = os.getenv("MUNICIPAL_DATASET_URL", "")

# Optional — raises your rate limit on Socrata-based portals. Not required
# for light polling volume.
MUNICIPAL_APP_TOKEN = os.getenv("MUNICIPAL_APP_TOKEN", "")


def fetch_parking_occupancy() -> list[dict]:
    """
    Polls a municipal open-data endpoint for parking/loading-zone occupancy.
    Field names in the return value are ILLUSTRATIVE — inspect your city's
    actual dataset schema (usually documented on the portal page) and
    adjust the field lookups below to match.
    """
    if not MUNICIPAL_DATASET_URL:
        raise RuntimeError(
            "MUNICIPAL_DATASET_URL not set. Find your city's open-data "
            "dataset URL (see module docstring) and set it in .env."
        )

    headers = {}
    if MUNICIPAL_APP_TOKEN:
        headers["X-App-Token"] = MUNICIPAL_APP_TOKEN

    response = requests.get(MUNICIPAL_DATASET_URL, headers=headers, timeout=10)
    response.raise_for_status()
    raw_rows = response.json()

    # ADJUST these field names to match your city's actual dataset schema.
    return [
        {
            "location_name": row.get("location_name") or row.get("street_name"),
            "latitude": float(row.get("latitude", 0)) or None,
            "longitude": float(row.get("longitude", 0)) or None,
            "occupied": row.get("occupancy_status") == "OCCUPIED",
            "dwell_minutes": row.get("dwell_time_minutes"),
            "raw": row,  # keep the raw row around until field mapping is confirmed
        }
        for row in raw_rows
    ]


def fetch_food_truck_permits() -> list[dict]:
    """
    Some cities publish an actual food truck / mobile vendor permit dataset
    directly — if yours does, this is the highest-signal free source
    available (it's literally which trucks are permitted where, though not
    necessarily live location). Same caveat: adjust field names to match
    your city's real schema.
    """
    if not MUNICIPAL_DATASET_URL:
        raise RuntimeError("MUNICIPAL_DATASET_URL not set — see module docstring.")

    headers = {}
    if MUNICIPAL_APP_TOKEN:
        headers["X-App-Token"] = MUNICIPAL_APP_TOKEN

    response = requests.get(MUNICIPAL_DATASET_URL, headers=headers, timeout=10)
    response.raise_for_status()
    raw_rows = response.json()

    return [
        {
            "truck_name": row.get("business_name") or row.get("vendor_name"),
            "permitted_location": row.get("location_description"),
            "permit_valid_until": row.get("expiration_date"),
            "raw": row,
        }
        for row in raw_rows
    ]


if __name__ == "__main__":
    print("Set MUNICIPAL_DATASET_URL to your city's real open-data endpoint to test this module.")
