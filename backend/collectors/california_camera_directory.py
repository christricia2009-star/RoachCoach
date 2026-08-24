"""
California-wide public traffic camera directory — Caltrans CWWP2.

Fetches the live official Caltrans CCTV CSV feeds and preserves the
complete camera information needed by Roach Coach Radar, including:

- Current still image
- Previous still images (-1 through -12)
- Streaming HLS URL
- Camera metadata
"""

import csv
import io
import time
import requests

from dataclasses import dataclass, field
from typing import Optional


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


# Keep this at 9 unless you have the required Caltrans written agreement.
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

    # Current still image.
    current_image_url: str

    # Live HLS stream.
    stream_url: Optional[str] = None

    # Previous still images supplied by Caltrans.
    previous_image_urls: list[str] = field(default_factory=list)

    # Additional useful Caltrans metadata.
    image_description: Optional[str] = None
    image_update_frequency: Optional[str] = None
    elevation: Optional[str] = None
    route_suffix: Optional[str] = None
    postmile_prefix: Optional[str] = None
    postmile: Optional[str] = None
    alignment: Optional[str] = None
    milepost: Optional[str] = None


# Known fixed portion of Caltrans CSV.
#
# The fields after currentImageURL are the reference-image URLs:
#
#   referenceImageURL1
#   referenceImageURL2
#   ...
#   referenceImageURL12
#
# Some district feeds can contain additional fields, so we simply preserve
# the first 12 reference URLs that occur after currentImageURL.
_FIELD_NAMES = [
    "index",
    "recordDate",
    "recordTime",
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
    "inservice",
    "imageDescription",
    "streamingVideoURL",
    "currentImageUpdateFrequency",
    "currentImageURL",
]


def _clean(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.strip()


def _is_valid_url(value: str) -> bool:
    value = _clean(value)
    return value.startswith("http://") or value.startswith("https://")


def _extract_previous_images(row: list[str]) -> list[str]:
    """
    Extract all Caltrans previous/reference image URLs after the known
    current-image column.

    We intentionally don't depend on exact column names because the live
    Caltrans CSV layout can contain additional fields.
    """

    if len(row) <= len(_FIELD_NAMES):
        return []

    candidates = row[len(_FIELD_NAMES):]

    urls: list[str] = []

    for value in candidates:
        value = _clean(value)

        if _is_valid_url(value):
            lower = value.lower()

            # We only want the reference/previous still-image URLs here.
            if lower.endswith(".jpg") or lower.endswith(".jpeg") or lower.endswith(".png"):
                urls.append(value)

    return urls[:12]


def fetch_district_cameras(district: int) -> list[CaltransCamera]:
    """Fetch and parse the live camera list for one Caltrans district."""

    url = DISTRICT_CSV_URLS.get(district)

    if not url:
        raise ValueError(
            f"Unknown district {district}. Valid range: 1-12."
        )

    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": "RoachCoachRadar/1.0"
        },
    )

    response.raise_for_status()

    reader = csv.reader(io.StringIO(response.text))

    cameras: list[CaltransCamera] = []

    for row in reader:
        if len(row) < len(_FIELD_NAMES):
            continue

        record = dict(zip(_FIELD_NAMES, row))

        try:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
        except (ValueError, TypeError):
            continue

        current_image_url = _clean(record["currentImageURL"])

        # Skip records without a usable camera image.
        if not current_image_url:
            continue

        previous_images = _extract_previous_images(row)

        camera = CaltransCamera(
            district=district,
            location_name=_clean(record["locationName"]),
            nearby_place=_clean(record["nearbyPlace"]),
            county=_clean(record["county"]),
            route=_clean(record["route"]),
            latitude=latitude,
            longitude=longitude,
            direction=_clean(record["direction"]),
            in_service=_clean(record["inservice"]).lower() == "true",
            current_image_url=current_image_url,
            stream_url=_clean(record["streamingVideoURL"]) or None,
            previous_image_urls=previous_images,
            image_description=_clean(record["imageDescription"]) or None,
            image_update_frequency=_clean(
                record["currentImageUpdateFrequency"]
            ) or None,
            elevation=_clean(record["elevation"]) or None,
            route_suffix=_clean(record["routeSuffix"]) or None,
            postmile_prefix=_clean(record["postmilePrefix"]) or None,
            postmile=_clean(record["postmile"]) or None,
            alignment=_clean(record["alignment"]) or None,
            milepost=_clean(record["milepost"]) or None,
        )

        cameras.append(camera)

    return cameras


def fetch_all_california_cameras(
    delay_between_districts: float = 0.5,
) -> list[CaltransCamera]:
    """
    Fetch live cameras across all 12 Caltrans districts.
    """

    all_cameras: list[CaltransCamera] = []

    for district in DISTRICT_CSV_URLS:
        try:
            cameras = fetch_district_cameras(district)
            all_cameras.extend(cameras)

            print(
                f"Caltrans District {district}: "
                f"{len(cameras)} cameras"
            )

        except Exception as exc:
            print(
                f"Failed to fetch Caltrans District "
                f"{district}: {exc}"
            )

        time.sleep(delay_between_districts)

    return all_cameras


def cameras_near(
    cameras: list[CaltransCamera],
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
) -> list[CaltransCamera]:
    """
    Return cameras inside an approximate radius.

    This is intentionally lightweight because the endpoint is used as a
    geographic pre-filter.
    """

    def rough_distance_miles(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:

        lat_miles = (lat1 - lat2) * 69.0

        # Approximate longitude miles around California.
        lon_miles = (lon1 - lon2) * 54.6

        return (
            lat_miles ** 2 +
            lon_miles ** 2
        ) ** 0.5

    return [
        camera
        for camera in cameras
        if rough_distance_miles(
            camera.latitude,
            camera.longitude,
            latitude,
            longitude,
        ) <= radius_miles
    ]


def cameras_in_county(
    cameras: list[CaltransCamera],
    county_name: str,
) -> list[CaltransCamera]:

    target = county_name.strip().lower()

    return [
        camera
        for camera in cameras
        if camera.county.strip().lower() == target
    ]


if __name__ == "__main__":
    cameras = fetch_district_cameras(3)

    print(
        f"District 3: {len(cameras)} cameras"
    )

    if cameras:
        camera = cameras[0]

        print("Location:", camera.location_name)
        print("Current:", camera.current_image_url)
        print("Stream:", camera.stream_url)
        print(
            "Previous images:",
            len(camera.previous_image_urls),
        )

        for index, url in enumerate(
            camera.previous_image_urls,
            start=1,
        ):
            print(f"Previous {index}: {url}")
