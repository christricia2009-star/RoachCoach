"""
California-wide public traffic camera directory — Caltrans CWWP2.

Uses the official Caltrans CWWP2 CCTV CSV feeds.

The CSV format includes:
    index
    recordDate
    recordTime
    recordEpoch
    district
    locationName
    nearbyPlace
    longitude
    latitude
    elevation
    direction
    county
    route
    routeSuffix
    postmilePrefix
    postmile
    alignment
    milepost
    inService
    imageDescription
    streamingVideoURL
    currentImageUpdateFrequency
    currentImageURL
    referenceImageUpdateFrequency
    referenceImage1UpdatesAgoURL
    ...
    referenceImage12UpdatesAgoURL

This module intentionally fetches the live district directories rather
than maintaining a hardcoded list of individual cameras.
"""

import csv
import io
import math
import time
import requests

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Caltrans CWWP2 district CCTV feeds
# ---------------------------------------------------------------------------

DISTRICT_CSV_URLS = {
    1: "https://cwwp2.dot.ca.gov/data/d1/cctv/cctvStatusD01.csv",
    2: "https://cwwp2.dot.ca.gov/data/d2/cctv/cctvStatusD02.csv",
    3: "https://cwwp2.dot.ca.gov/data/d3/cctv/cctvStatusD03.csv",
    4: "https://cwwp2.dot.ca.gov/data/d4/cctv/cctvStatusD04.csv",
    5: "https://cwwp2.dot.ca.gov/data/d5/cctv/cctvStatusD05.csv",
    6: "https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.csv",
    7: "https://cwwp2.dot.ca.gov/data/d7/cctv/cctvStatusD07.csv",
    8: "https://cwwp2.dot.ca.gov/data/d8/cctv/cctvStatusD08.csv",
    9: "https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.csv",
    10: "https://cwwp2.dot.ca.gov/data/d10/cctv/cctvStatusD10.csv",
    11: "https://cwwp2.dot.ca.gov/data/d11/cctv/cctvStatusD11.csv",
    12: "https://cwwp2.dot.ca.gov/data/d12/cctv/cctvStatusD12.csv",
}


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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Keep this below the bulk-streaming threshold unless you actually have
# written authorization covering simultaneous streaming at a higher level.
#
# NOTE:
# Fetching the CSV directory itself is lightweight. This limit is primarily
# used by the vision scanner when deciding how many camera images to inspect.
HAS_BULK_STREAMING_AGREEMENT = False

MAX_CONCURRENT_CHECKS = 9 if not HAS_BULK_STREAMING_AGREEMENT else 50


# ---------------------------------------------------------------------------
# CSV field layout
# ---------------------------------------------------------------------------

# IMPORTANT:
# Caltrans currently includes recordEpoch after recordTime and uses
# "inService" with a capital S.
#
# The previous parser omitted recordEpoch and used "inservice", which shifted
# every subsequent field and caused every camera row to be discarded.

_FIELD_NAMES = [
    "index",
    "recordDate",
    "recordTime",
    "recordEpoch",
    "district",
    "locationName",
    "nearbyPlace",
    "longitude",
    "latitude",
    "elevation",
    "direction",
    "county",
    "route",
    "routeSuffix",
    "postmilePrefix",
    "postmile",
    "alignment",
    "milepost",
    "inService",
    "imageDescription",
    "streamingVideoURL",
    "currentImageUpdateFrequency",
    "currentImageURL",
    "referenceImageUpdateFrequency",
    "referenceImage1UpdatesAgoURL",
    "referenceImage2UpdatesAgoURL",
    "referenceImage3UpdatesAgoURL",
    "referenceImage4UpdatesAgoURL",
    "referenceImage5UpdatesAgoURL",
    "referenceImage6UpdatesAgoURL",
    "referenceImage7UpdatesAgoURL",
    "referenceImage8UpdatesAgoURL",
    "referenceImage9UpdatesAgoURL",
    "referenceImage10UpdatesAgoURL",
    "referenceImage11UpdatesAgoURL",
    "referenceImage12UpdatesAgoURL",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

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
    streaming_video_url: Optional[str] = None
    image_update_frequency: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_bool(value: str) -> bool:
    """Safely parse Caltrans boolean values."""

    if value is None:
        return False

    return value.strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def _parse_optional_float(value: str) -> Optional[float]:
    """Safely parse an optional numeric value."""

    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _clean(value: Optional[str]) -> str:
    """Normalize a CSV string."""

    if value is None:
        return ""

    return value.strip()


def _parse_camera_row(
    row: list[str],
    district: int,
) -> Optional[CaltransCamera]:
    """
    Convert one Caltrans CSV row into a CaltransCamera.

    Returns None for malformed rows instead of allowing one bad camera
    record to break the entire district.
    """

    if len(row) < len(_FIELD_NAMES):
        return None

    record = dict(zip(_FIELD_NAMES, row))

    try:
        latitude = float(record["latitude"])
        longitude = float(record["longitude"])
    except (ValueError, TypeError, KeyError):
        return None

    # Basic coordinate sanity check.
    if not (-90 <= latitude <= 90):
        return None

    if not (-180 <= longitude <= 180):
        return None

    location_name = _clean(record.get("locationName"))

    # A camera without a location name isn't useful to the app.
    if not location_name:
        location_name = f"Caltrans Camera {record.get('index', 'unknown')}"

    image_url = _clean(record.get("currentImageURL"))

    # A directory record without an image isn't useful for the vision
    # collector, but we keep it in the directory so callers can still
    # inspect the metadata.
    return CaltransCamera(
        district=district,
        location_name=location_name,
        nearby_place=_clean(record.get("nearbyPlace")),
        county=_clean(record.get("county")),
        route=_clean(record.get("route")),
        latitude=latitude,
        longitude=longitude,
        direction=_clean(record.get("direction")),
        in_service=_parse_bool(record.get("inService")),
        current_image_url=image_url,
        streaming_video_url=_clean(
            record.get("streamingVideoURL")
        ) or None,
        image_update_frequency=_parse_optional_float(
            record.get("currentImageUpdateFrequency")
        ),
    )


# ---------------------------------------------------------------------------
# Fetch one district
# ---------------------------------------------------------------------------

def fetch_district_cameras(
    district: int,
    timeout: int = 15,
) -> list[CaltransCamera]:
    """
    Fetch the live Caltrans CCTV directory for one district.

    Example:

        cameras = fetch_district_cameras(3)

    District 3 covers the Sacramento / Marysville area.
    """

    url = DISTRICT_CSV_URLS.get(district)

    if not url:
        raise ValueError(
            f"Unknown district {district}. Valid range is 1-12."
        )

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "RoachCoachRadar/1.0",
            "Accept": "text/csv,*/*",
        },
    )

    response.raise_for_status()

    # Caltrans currently publishes UTF-8-compatible CSV.
    text_data = response.content.decode(
        "utf-8-sig",
        errors="replace",
    )

    reader = csv.reader(io.StringIO(text_data))

    cameras: list[CaltransCamera] = []

    first_row = True

    for row in reader:
        if not row:
            continue

        # Skip a header row if Caltrans ever returns one in addition to
        # the expected positional layout.
        if first_row:
            first_row = False

            if row[0].strip().lower() == "index":
                continue

        camera = _parse_camera_row(
            row,
            district,
        )

        if camera is not None:
            cameras.append(camera)

    return cameras


# ---------------------------------------------------------------------------
# Fetch all California cameras
# ---------------------------------------------------------------------------

def fetch_all_california_cameras(
    delay_between_districts: float = 0.25,
) -> list[CaltransCamera]:
    """
    Fetch the live CCTV directory for all 12 Caltrans districts.

    This makes one lightweight CSV request per district.
    """

    all_cameras: list[CaltransCamera] = []

    for district in DISTRICT_CSV_URLS:
        try:
            cameras = fetch_district_cameras(district)

            print(
                f"[Caltrans] District {district} "
                f"({DISTRICT_LABELS.get(district, 'Unknown')}): "
                f"{len(cameras)} cameras"
            )

            all_cameras.extend(cameras)

        except Exception as exc:
            print(
                f"[Caltrans] Failed to fetch district "
                f"{district}: {type(exc).__name__}: {exc}"
            )

        if delay_between_districts > 0:
            time.sleep(delay_between_districts)

    print(
        f"[Caltrans] Total cameras loaded: {len(all_cameras)}"
    )

    return all_cameras


# ---------------------------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------------------------

def distance_miles(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    """
    Calculate great-circle distance between two coordinates.

    Returns miles.
    """

    earth_radius_miles = 3958.7613

    lat1 = math.radians(latitude1)
    lat2 = math.radians(latitude2)

    delta_lat = math.radians(latitude2 - latitude1)
    delta_lon = math.radians(longitude2 - longitude1)

    a = (
        math.sin(delta_lat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius_miles * c


# ---------------------------------------------------------------------------
# Find nearby cameras
# ---------------------------------------------------------------------------

def cameras_near(
    cameras: list[CaltransCamera],
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
) -> list[CaltransCamera]:
    """
    Return cameras within radius_miles of the supplied coordinate.

    Results are sorted nearest-first.
    """

    if radius_miles < 0:
        raise ValueError("radius_miles cannot be negative")

    nearby: list[tuple[float, CaltransCamera]] = []

    for camera in cameras:
        distance = distance_miles(
            latitude,
            longitude,
            camera.latitude,
            camera.longitude,
        )

        if distance <= radius_miles:
            nearby.append(
                (distance, camera)
            )

    nearby.sort(
        key=lambda item: item[0]
    )

    return [
        camera
        for _, camera in nearby
    ]


# ---------------------------------------------------------------------------
# County filtering
# ---------------------------------------------------------------------------

def cameras_in_county(
    cameras: list[CaltransCamera],
    county_name: str,
) -> list[CaltransCamera]:
    """
    Return cameras in a specific county.
    """

    target = county_name.strip().lower()

    return [
        camera
        for camera in cameras
        if camera.county.strip().lower() == target
    ]


# ---------------------------------------------------------------------------
# Service filtering
# ---------------------------------------------------------------------------

def active_cameras(
    cameras: list[CaltransCamera],
) -> list[CaltransCamera]:
    """
    Return cameras currently marked in service and having a current image
    URL.
    """

    return [
        camera
        for camera in cameras
        if camera.in_service
        and bool(camera.current_image_url)
    ]


# ---------------------------------------------------------------------------
# Convenience function for radar
# ---------------------------------------------------------------------------

def find_active_cameras_near(
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
    max_cameras: Optional[int] = None,
) -> list[CaltransCamera]:
    """
    Fetch all California cameras, filter to active cameras near the
    requested location, and optionally cap the result count.
    """

    cameras = fetch_all_california_cameras()

    nearby = cameras_near(
        cameras,
        latitude,
        longitude,
        radius_miles,
    )

    nearby = [
        camera
        for camera in nearby
        if camera.in_service
        and camera.current_image_url
    ]

    if max_cameras is not None:
        nearby = nearby[:max_cameras]

    return nearby


# ---------------------------------------------------------------------------
# Local test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("==========================================")
    print(" Roach Coach Radar - Caltrans CCTV Test")
    print("==========================================")
    print()

    # Sacramento test coordinate.
    latitude = 38.7071
    longitude = -121.2811

    print(
        f"Searching near "
        f"{latitude}, {longitude}"
    )
    print()

    try:
        district_3 = fetch_district_cameras(3)

        print()
        print(
            f"District 3 cameras loaded: "
            f"{len(district_3)}"
        )

        nearby = cameras_near(
            district_3,
            latitude,
            longitude,
            radius_miles=20,
        )

        active = [
            camera
            for camera in nearby
            if camera.in_service
            and camera.current_image_url
        ]

        print(
            f"Nearby cameras within 20 miles: "
            f"{len(nearby)}"
        )

        print(
            f"Nearby active cameras with images: "
            f"{len(active)}"
        )

        print()

        for camera in active[:10]:
            distance = distance_miles(
                latitude,
                longitude,
                camera.latitude,
                camera.longitude,
            )

            print(
                f"{distance:.2f} mi | "
                f"{camera.location_name} | "
                f"{camera.county} | "
                f"{camera.route} | "
                f"{camera.latitude}, "
                f"{camera.longitude}"
            )

            print(
                f"    Image: "
                f"{camera.current_image_url}"
            )

    except Exception as exc:
        print(
            f"TEST FAILED: "
            f"{type(exc).__name__}: {exc}"
        )
        raise
