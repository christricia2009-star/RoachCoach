"""
California-wide public traffic camera directory.

Primary source:
    Caltrans Commercial Wholesale Web Portal 2 (CWWP2)

The collector retrieves live Caltrans CCTV data by district and
normalizes it into a stable CaltransCamera object for Roach Coach Radar.

Important:
    Caltrans has changed/expanded the CCTV CSV schema over time.
    This implementation parses by column name instead of relying on
    fixed column positions.

Primary feed:
    https://cwwp2.dot.ca.gov/data/dN/cctv/cctvStatusDNN.csv

Fallback:
    Caltrans ArcGIS CCTV FeatureServer.

The fallback is useful when a CWWP2 district feed is temporarily
unavailable or changes format.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


# ============================================================
# CALTRANS DISTRICT FEEDS
# ============================================================

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


# ============================================================
# CALTRANS ARCGIS FALLBACK
# ============================================================

ARCGIS_CCTV_URL = (
    "https://caltrans-gis.dot.ca.gov/"
    "arcgis/rest/services/CHhighway/CCTV/"
    "FeatureServer/0/query"
)


# ============================================================
# REQUEST SETTINGS
# ============================================================

REQUEST_TIMEOUT = 30

USER_AGENT = (
    "RoachCoachRadar/1.0 "
    "(Caltrans public CCTV data integration)"
)


# ============================================================
# CAMERA LIMITS
# ============================================================

# Keep this at 9 unless you have the required Caltrans
# written agreement for bulk streaming.
HAS_BULK_STREAMING_AGREEMENT = False

MAX_CONCURRENT_CHECKS = (
    50 if HAS_BULK_STREAMING_AGREEMENT else 9
)


# ============================================================
# CAMERA MODEL
# ============================================================

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

    # Live HLS/video URL if supplied.
    stream_url: Optional[str] = None

    # Previous still images.
    previous_image_urls: list[str] = field(
        default_factory=list
    )

    # Additional metadata.
    image_description: Optional[str] = None

    image_update_frequency: Optional[str] = None

    elevation: Optional[str] = None

    route_suffix: Optional[str] = None

    postmile_prefix: Optional[str] = None

    postmile: Optional[str] = None

    alignment: Optional[str] = None

    milepost: Optional[str] = None


# ============================================================
# HELPERS
# ============================================================

def _clean(value: Any) -> str:
    """
    Normalize a CSV/API value to a clean string.
    """

    if value is None:
        return ""

    return str(value).strip()


def _is_valid_url(value: str) -> bool:
    """
    Return True for HTTP/HTTPS URLs.
    """

    value = _clean(value)

    return (
        value.startswith("http://")
        or value.startswith("https://")
    )


def _to_float(value: Any) -> Optional[float]:
    """
    Safely convert a value to float.
    """

    value = _clean(value)

    if not value:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool:
    """
    Normalize Caltrans inService/inservice values.

    Caltrans feeds have historically used variations such as:

        true
        True
        TRUE
        1
        yes
        y

    Treat those as in service.
    """

    value = _clean(value).lower()

    return value in {
        "true",
        "1",
        "yes",
        "y",
        "inservice",
        "in service",
    }


def _first_value(
    record: dict[str, Any],
    *names: str,
) -> str:
    """
    Return the first non-empty value matching any of the
    supplied field names.
    """

    for name in names:
        value = _clean(record.get(name))

        if value:
            return value

    return ""


def _normalize_header(value: str) -> str:
    """
    Normalize Caltrans field names.

    Handles things such as:

        index
        index_
        inService
        inservice
        Postmile_Suffix
    """

    value = _clean(value)

    value = value.replace("\ufeff", "")

    return value.strip()


def _build_record_from_row(
    headers: list[str],
    row: list[str],
) -> dict[str, str]:
    """
    Build a dictionary from a CSV row.

    Extra columns are preserved.
    Missing columns become empty strings.
    """

    record: dict[str, str] = {}

    for index, header in enumerate(headers):

        normalized_header = _normalize_header(header)

        if not normalized_header:
            continue

        value = (
            row[index]
            if index < len(row)
            else ""
        )

        record[normalized_header] = _clean(value)

    return record


# ============================================================
# PREVIOUS IMAGE EXTRACTION
# ============================================================

def _extract_previous_images(
    record: dict[str, Any],
) -> list[str]:
    """
    Extract Caltrans reference/previous image URLs.

    Caltrans commonly provides fields such as:

        referenceImage1UpdateAgoURL
        referenceImage2UpdatesAgoURL
        ...
        referenceImage12UpdatesAgoURL

    Some historical feeds use slightly different naming.

    We inspect field names instead of depending on a fixed
    column position.
    """

    candidates: list[tuple[int, str]] = []

    for key, raw_value in record.items():

        key_lower = _clean(key).lower()

        if "referenceimage" not in key_lower:
            continue

        if "url" not in key_lower:
            continue

        value = _clean(raw_value)

        if not _is_valid_url(value):
            continue

        # Determine ordering from the field name.
        number = 999

        digits = ""

        for character in key_lower:

            if character.isdigit():
                digits += character

        if digits:
            try:
                number = int(digits)
            except ValueError:
                number = 999

        candidates.append(
            (
                number,
                value,
            )
        )

    candidates.sort(
        key=lambda item: item[0]
    )

    return [
        value
        for _, value in candidates[:12]
    ]


# ============================================================
# CSV CAMERA PARSER
# ============================================================

def _camera_from_record(
    record: dict[str, Any],
    district: int,
) -> Optional[CaltransCamera]:
    """
    Convert one Caltrans CSV/API record into a camera.

    This is intentionally based on field names rather than
    column positions.
    """

    latitude_value = _first_value(
        record,
        "latitude",
        "Latitude",
        "LATITUDE",
    )

    longitude_value = _first_value(
        record,
        "longitude",
        "Longitude",
        "LONGITUDE",
    )

    latitude = _to_float(
        latitude_value
    )

    longitude = _to_float(
        longitude_value
    )

    if latitude is None or longitude is None:
        return None

    # California sanity check.
    if not (
        32.0 <= latitude <= 43.0
        and -125.0 <= longitude <= -113.0
    ):
        return None

    current_image_url = _first_value(
        record,
        "currentImageURL",
        "currentImageUrl",
        "current_image_url",
    )

    # We need an actual image to perform computer vision.
    if not _is_valid_url(current_image_url):
        return None

    location_name = _first_value(
        record,
        "locationName",
        "location_name",
        "LocationName",
    )

    nearby_place = _first_value(
        record,
        "nearbyPlace",
        "nearby_place",
    )

    county = _first_value(
        record,
        "county",
        "County",
    )

    route = _first_value(
        record,
        "route",
        "Route",
    )

    direction = _first_value(
        record,
        "direction",
        "Direction",
    )

    service_value = _first_value(
        record,
        "inService",
        "inservice",
        "in_service",
    )

    stream_url = _first_value(
        record,
        "streamingVideoURL",
        "streamingVideoUrl",
        "stream_url",
    )

    image_description = _first_value(
        record,
        "imageDescription",
        "image_description",
    )

    image_update_frequency = _first_value(
        record,
        "currentImageUpdateFrequency",
        "current_image_update_frequency",
    )

    elevation = _first_value(
        record,
        "elevation",
        "Elevation",
    )

    route_suffix = _first_value(
        record,
        "routeSuffix",
        "route_suffix",
    )

    postmile_prefix = _first_value(
        record,
        "postmilePrefix",
        "postmile_prefix",
    )

    postmile = _first_value(
        record,
        "postmile",
        "Postmile",
    )

    alignment = _first_value(
        record,
        "alignment",
        "Alignment",
    )

    milepost = _first_value(
        record,
        "milepost",
        "Milepost",
    )

    previous_images = _extract_previous_images(
        record
    )

    return CaltransCamera(
        district=district,
        location_name=location_name
        or f"Caltrans District {district} Camera",
        nearby_place=nearby_place,
        county=county,
        route=route,
        latitude=latitude,
        longitude=longitude,
        direction=direction,
        in_service=_to_bool(
            service_value
        ),
        current_image_url=current_image_url,
        stream_url=(
            stream_url
            if _is_valid_url(stream_url)
            else None
        ),
        previous_image_urls=previous_images,
        image_description=(
            image_description
            or None
        ),
        image_update_frequency=(
            image_update_frequency
            or None
        ),
        elevation=elevation or None,
        route_suffix=route_suffix or None,
        postmile_prefix=(
            postmile_prefix or None
        ),
        postmile=postmile or None,
        alignment=alignment or None,
        milepost=milepost or None,
    )


# ============================================================
# CSV FETCH
# ============================================================

def fetch_district_cameras(
    district: int,
) -> list[CaltransCamera]:
    """
    Fetch and parse the live Caltrans CCTV CSV for one district.

    The parser uses the CSV header row, which protects against
    schema changes such as Caltrans adding recordEpoch.
    """

    url = DISTRICT_CSV_URLS.get(
        district
    )

    if not url:
        raise ValueError(
            f"Unknown district {district}. "
            "Valid range: 1-12."
        )

    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv,*/*",
        },
    )

    response.raise_for_status()

    # Handle UTF-8 BOM automatically.
    text = response.content.decode(
        "utf-8-sig",
        errors="replace",
    )

    if not text.strip():
        raise RuntimeError(
            f"Caltrans District {district} "
            "returned an empty CSV."
        )

    reader = csv.reader(
        io.StringIO(text)
    )

    try:
        headers = next(reader)
    except StopIteration:
        raise RuntimeError(
            f"Caltrans District {district} "
            "CSV contained no rows."
        )

    headers = [
        _normalize_header(header)
        for header in headers
    ]

    # Verify this is actually a CCTV feed.
    normalized_headers = {
        header.lower()
        for header in headers
    }

    if "latitude" not in normalized_headers:
        raise RuntimeError(
            f"Caltrans District {district} CSV "
            "does not contain a latitude column. "
            f"Headers: {headers}"
        )

    if "longitude" not in normalized_headers:
        raise RuntimeError(
            f"Caltrans District {district} CSV "
            "does not contain a longitude column. "
            f"Headers: {headers}"
        )

    cameras: list[CaltransCamera] = []

    skipped_rows = 0

    for row in reader:

        if not row:
            continue

        record = _build_record_from_row(
            headers,
            row,
        )

        camera = _camera_from_record(
            record,
            district,
        )

        if camera is None:
            skipped_rows += 1
            continue

        cameras.append(camera)

    print(
        f"Caltrans District {district}: "
        f"parsed {len(cameras)} cameras "
        f"(skipped {skipped_rows} rows)"
    )

    return cameras


# ============================================================
# ARCGIS FALLBACK
# ============================================================

def _fetch_arcgis_cameras(
    district: Optional[int] = None,
) -> list[CaltransCamera]:
    """
    Fetch CCTV data from the Caltrans ArcGIS FeatureServer.

    This is a fallback for CWWP2 CSV failures.

    The ArcGIS service is statewide, so when a district is supplied
    we filter the returned records locally.
    """

    params = {
        "where": (
            f"district={district}"
            if district is not None
            else "1=1"
        ),
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": "2000",
    }

    response = requests.get(
        ARCGIS_CCTV_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            "Caltrans ArcGIS returned an error: "
            + str(data["error"])
        )

    features = data.get(
        "features",
        [],
    )

    cameras: list[CaltransCamera] = []

    for feature in features:

        attributes = feature.get(
            "attributes",
            {},
        )

        if not isinstance(
            attributes,
            dict,
        ):
            continue

        record = {
            str(key): value
            for key, value in attributes.items()
        }

        record["inService"] = _first_value(
            record,
            "inService",
            "inservice",
        )

        camera_district_value = _first_value(
            record,
            "district",
        )

        try:
            camera_district = int(
                float(camera_district_value)
            )
        except (
            TypeError,
            ValueError,
        ):
            camera_district = (
                district or 0
            )

        if (
            district is not None
            and camera_district != district
        ):
            continue

        camera = _camera_from_record(
            record,
            camera_district,
        )

        if camera is None:
            continue

        cameras.append(camera)

    print(
        f"Caltrans ArcGIS fallback"
        f"{' district ' + str(district) if district else ''}: "
        f"{len(cameras)} cameras"
    )

    return cameras


# ============================================================
# ALL CALIFORNIA CAMERAS
# ============================================================

def fetch_all_california_cameras(
    delay_between_districts: float = 0.25,
) -> list[CaltransCamera]:
    """
    Fetch live cameras across all 12 Caltrans districts.

    Each district is attempted through CWWP2 first.

    If the CWWP2 feed fails or returns zero usable cameras,
    the Caltrans ArcGIS CCTV service is used as a fallback.

    This prevents one broken district feed from killing the
    entire California camera directory.
    """

    all_cameras: list[CaltransCamera] = []

    for district in DISTRICT_CSV_URLS:

        district_cameras: list[
            CaltransCamera
        ] = []

        # ----------------------------------------------------
        # PRIMARY: CWWP2 CSV
        # ----------------------------------------------------

        try:

            district_cameras = (
                fetch_district_cameras(
                    district
                )
            )

        except Exception as exc:

            print(
                f"Caltrans District {district} "
                f"CSV failed: "
                f"{type(exc).__name__}: {exc}"
            )

        # ----------------------------------------------------
        # FALLBACK: ARCGIS
        # ----------------------------------------------------

        if not district_cameras:

            try:

                district_cameras = (
                    _fetch_arcgis_cameras(
                        district
                    )
                )

            except Exception as exc:

                print(
                    f"Caltrans District {district} "
                    f"ArcGIS fallback failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        all_cameras.extend(
            district_cameras
        )

        if delay_between_districts > 0:
            time.sleep(
                delay_between_districts
            )

    print(
        f"Caltrans statewide camera directory: "
        f"{len(all_cameras)} cameras"
    )

    return all_cameras


# ============================================================
# GEOGRAPHIC FILTER
# ============================================================

def cameras_near(
    cameras: list[CaltransCamera],
    latitude: float,
    longitude: float,
    radius_miles: float = 5.0,
) -> list[CaltransCamera]:
    """
    Return cameras within the requested approximate radius.

    The calculation is intentionally lightweight because this
    function is used as a pre-filter before expensive AI vision.
    """

    if radius_miles <= 0:
        return []

    # Approximate miles per degree around California.
    LAT_MILES_PER_DEGREE = 69.0
    LON_MILES_PER_DEGREE = 54.6

    results: list[CaltransCamera] = []

    for camera in cameras:

        lat_miles = (
            camera.latitude - latitude
        ) * LAT_MILES_PER_DEGREE

        lon_miles = (
            camera.longitude - longitude
        ) * LON_MILES_PER_DEGREE

        distance = (
            lat_miles ** 2
            + lon_miles ** 2
        ) ** 0.5

        if distance <= radius_miles:
            results.append(camera)

    return results


# ============================================================
# COUNTY FILTER
# ============================================================

def cameras_in_county(
    cameras: list[CaltransCamera],
    county_name: str,
) -> list[CaltransCamera]:
    """
    Return cameras matching a county name.
    """

    target = (
        county_name
        .strip()
        .lower()
    )

    return [
        camera
        for camera in cameras
        if camera.county
        .strip()
        .lower()
        == target
    ]


# ============================================================
# SIMPLE DISTANCE HELPER
# ============================================================

def approximate_distance_miles(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    """
    Approximate distance between two California coordinates.
    """

    lat_miles = (
        latitude1 - latitude2
    ) * 69.0

    lon_miles = (
        longitude1 - longitude2
    ) * 54.6

    return (
        lat_miles ** 2
        + lon_miles ** 2
    ) ** 0.5


# ============================================================
# TEST / DEBUG
# ============================================================

if __name__ == "__main__":

    print(
        "Testing Caltrans District 3..."
    )

    cameras = fetch_district_cameras(3)

    print(
        f"District 3 cameras: "
        f"{len(cameras)}"
    )

    if cameras:

        camera = cameras[0]

        print()
        print(
            "First camera:"
        )

        print(
            "Location:",
            camera.location_name,
        )

        print(
            "County:",
            camera.county,
        )

        print(
            "Route:",
            camera.route,
        )

        print(
            "Latitude:",
            camera.latitude,
        )

        print(
            "Longitude:",
            camera.longitude,
        )

        print(
            "In service:",
            camera.in_service,
        )

        print(
            "Current image:",
            camera.current_image_url,
        )

        print(
            "Stream:",
            camera.stream_url,
        )

        print(
            "Previous images:",
            len(
                camera.previous_image_urls
            ),
        )

        nearby = cameras_near(
            cameras,
            38.7071,
            -121.2811,
            25,
        )

        print()
        print(
            "Cameras within 25 miles "
            "of Citrus Heights:",
            len(nearby),
        )

        for item in nearby[:10]:

            print(
                f"  {item.location_name} | "
                f"{item.latitude}, "
                f"{item.longitude} | "
                f"{item.route}"
            )
