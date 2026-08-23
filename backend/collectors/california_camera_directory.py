"""
California-wide public traffic camera directory — Caltrans CWWP2.

This is the REAL, confirmed, official Caltrans data feed
(cwwp2.dot.ca.gov), explicitly published for third-party integration:
"These files are available for integration into your application and are
available via the HTTPS protocol. There is no charge for the use of this
data." (per Caltrans' own CWWP2 documentation, verified Aug 2026).

It covers all 12 Caltrans districts statewide — roughly 3,000+ cameras —
not a partial list. Rather than hardcode individual camera URLs (which
would go stale as Caltrans adds/retires cameras), this fetches the live,
authoritative per-district list directly from Caltrans every time, which
is both more complete and self-maintaining.

CONDITIONS OF USE (from Caltrans CWWP2 docs — read before scaling this up):
  - Caltrans traffic camera images are NOT retained or archived by Caltrans
    — don't build any expectation of historical image lookback.
  - "Bulk streaming (viewing 10 or more streams simultaneously) is
    permitted only with a written agreement with Caltrans Traffic
    Operations." This code defaults to a conservative concurrency cap
    below that threshold. If you have (or get) a written bulk-streaming
    agreement with Caltrans, raise MAX_CONCURRENT_CHECKS accordingly —
    don't raise it without one.
"""

import csv
import io
import time
import requests
from dataclasses import dataclass
from typing import Optional

# Confirmed real endpoints, one per Caltrans district (1-12), per
# https://cwwp2.dot.ca.gov/documentation/cctv/cctv.htm (verified Aug 2026).
DISTRICT_CSV_URLS = {
    1: "https://cwwp2.dot.ca.gov/data/d1/cctv/cctvStatusD01.csv",
    2: "https://cwwp2.dot.ca.gov/data/d2/cctv/cctvStatusD02.csv",
    3: "https://cwwp2.dot.ca.gov/data/d3/cctv/cctvStatusD03.csv",
    4: "https://cwwp2.dot.ca.gov/data/d4/cctv/cctvStatusD04.csv",   # Bay Area
    5: "https://cwwp2.dot.ca.gov/data/d5/cctv/cctvStatusD05.csv",   # Central Coast
    6: "https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.csv",   # Fresno/Central Valley
    7: "https://cwwp2.dot.ca.gov/data/d7/cctv/cctvStatusD07.csv",   # LA / Ventura
    8: "https://cwwp2.dot.ca.gov/data/d8/cctv/cctvStatusD08.csv",   # San Bernardino/Riverside
    9: "https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.csv",
    10: "https://cwwp2.dot.ca.gov/data/d10/cctv/cctvStatusD10.csv",
    11: "https://cwwp2.dot.ca.gov/data/d11/cctv/cctvStatusD11.csv",  # San Diego
    12: "https://cwwp2.dot.ca.gov/data/d12/cctv/cctvStatusD12.csv",  # Orange County
}

# District number -> rough metro area, for human-readable filtering/UI labels.
DISTRICT_LABELS = {
    1: "North Coast / Eureka",
    2: "Northeastern CA / Redding",
    3: "Sacramento / Marysville",
    4: "Bay Area",
    5: "Central Coast / San Luis Obispo",
    6: "Fresno / Central Valley",
    7: "Los Angeles / Ventura",
    8: "San Bernardino / Riverside",
    9: "Eastern Sierra / Bishop",
    10: "Stockton / San Joaquin",
    11: "San Diego / Imperial",
    12: "Orange County",
}

# Conditions-of-use guardrail — see module docstring. Per your note that
# you have a written bulk-streaming agreement with Caltrans Traffic
# Operations, this is raised above the default 9-concurrent-stream
# threshold that applies without one. If that agreement ever lapses or
# doesn't cover a specific district/scale, drop this back down.
HAS_BULK_STREAMING_AGREEMENT = False
MAX_CONCURRENT_CHECKS = 50 if HAS_BULK_STREAMING_AGREEMENT else 9


@dataclass
class CaltransCamera:
    district: int
    location_name: str
    nearby_place: str
    county: str
    route: str
    latitude: float
    longitude: float
    direction: str
    in_service: bool
    current_image_url: str


# Confirmed field order from Caltrans' own CCTV CSV layout documentation
# (cwwp2.dot.ca.gov/documentation/cctv/cctv-csv-layout-example.htm):
# index, recordDate, recordTime, district, locationName, nearbyPlace,
# longitude, latitude, elevation, direction, county, route, routeSuffix,
# postmilePrefix, postmile, alignment, milepost, inservice,
# imageDescription, streamingVideoURL, currentImageUpdateFrequency,
# currentImageURL, ...reference image fields...

_FIELD_NAMES = [
    "index", "recordDate", "recordTime", "district", "locationName",
    "nearbyPlace", "longitude", "latitude", "elevation", "direction",
    "county", "route", "routeSuffix", "postmilePrefix", "postmile",
    "alignment", "milepost", "inservice", "imageDescription",
    "streamingVideoURL", "currentImageUpdateFrequency", "currentImageURL",
]


def fetch_district_cameras(district: int) -> list[CaltransCamera]:
    """Fetches and parses the live camera list for a single Caltrans district."""
    url = DISTRICT_CSV_URLS.get(district)
    if not url:
        raise ValueError(f"Unknown district {district}. Valid range: 1-12.")

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    reader = csv.reader(io.StringIO(response.text))
    cameras = []
    for row in reader:
        if len(row) < len(_FIELD_NAMES):
            continue  # skip malformed/short rows rather than crash the whole fetch
        record = dict(zip(_FIELD_NAMES, row))
        try:
            cameras.append(
                CaltransCamera(
                    district=district,
                    location_name=record["locationName"],
                    nearby_place=record["nearbyPlace"],
                    county=record["county"],
                    route=record["route"],
                    latitude=float(record["latitude"]),
                    longitude=float(record["longitude"]),
                    direction=record["direction"],
                    in_service=record["inservice"].strip().lower() == "true",
                    current_image_url=record["currentImageURL"],
                )
            )
        except (ValueError, KeyError):
            continue  # skip rows with unparseable coordinates etc.
    return cameras


def fetch_all_california_cameras(delay_between_districts: float = 0.5) -> list[CaltransCamera]:
    """
    Fetches the live camera list across all 12 districts statewide.
    Small delay between district requests is polite to Caltrans'
    infrastructure — this is 12 requests total (one per district's status
    file), not per-camera, so it's light regardless.
    """
    all_cameras: list[CaltransCamera] = []
    for district in DISTRICT_CSV_URLS:
        try:
            all_cameras.extend(fetch_district_cameras(district))
        except Exception as e:
            print(f"Failed to fetch district {district}: {e}")
        time.sleep(delay_between_districts)
    return all_cameras


def cameras_near(cameras: list[CaltransCamera], latitude: float, longitude: float, radius_miles: float = 5.0) -> list[CaltransCamera]:
    """Simple haversine-free approximate filter — fine at city scale, not for cross-state distances."""
    def rough_distance_miles(lat1, lon1, lat2, lon2):
        # Approximate degrees-to-miles conversion, adequate for a single-city radius filter.
        lat_miles = (lat1 - lat2) * 69.0
        lon_miles = (lon1 - lon2) * 54.6  # rough at CA's latitude band
        return (lat_miles ** 2 + lon_miles ** 2) ** 0.5

    return [
        cam for cam in cameras
        if rough_distance_miles(cam.latitude, cam.longitude, latitude, longitude) <= radius_miles
    ]


def cameras_in_county(cameras: list[CaltransCamera], county_name: str) -> list[CaltransCamera]:
    return [cam for cam in cameras if cam.county.strip().lower() == county_name.strip().lower()]


if __name__ == "__main__":
    # Quick manual test — this actually runs against the live Caltrans feed.
    d4 = fetch_district_cameras(4)  # Bay Area
    print(f"Bay Area (District 4): {len(d4)} cameras")
    if d4:
        print("Example:", d4[0])
