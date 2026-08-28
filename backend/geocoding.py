"""
Geocoding — converts extracted location TEXT ("the brewery on 5th") into
real latitude/longitude. This was the missing link in the social scraping
pipeline: llm_extract.py pulls out location text, but nothing turned that
into coordinates a Sighting record could actually use.

Uses OpenStreetMap's Nominatim — free, no API key needed, appropriate for
a family/friends pilot's request volume. Nominatim's usage policy requires:
  - Max 1 request/second (enforced below with a sleep)
  - A real User-Agent identifying your app (set below — update the contact
    email to yours; Nominatim's policy asks for a way to reach you if your
    usage needs attention)
  - No heavy/commercial bulk use — this is fine for occasional caption
    geocoding, not for geocoding millions of addresses

If you outgrow this, Google's Geocoding API or Apple's MapKit server-side
geocoding are the usual upgrades — both need billing set up, unlike this.
"""

from __future__ import annotations

import re
import time
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = (
    "RoachCoachRadar/1.0 "
    "(https://radar.snapcollectibles.com; christricia2009@gmail.com)"
)

DEFAULT_CITY_CONTEXT = "Sacramento, CA"

# Greater Sacramento (includes Roseville, Yuba City, Davis, Folsom).
# Reject Nominatim/Photon hits that snap to another state/country.
REGION_LAT = (38.0, 39.8)
REGION_LON = (-122.5, -120.4)

_UNUSABLE = {
    "i", "a", "the", "yes", "no", "none", "unknown", "n/a", "here",
    "today", "tonight", "now", "open", "closed",
}

# City / county names that must not become a map pin by themselves.
# Neighborhood / park aliases (Eufay, Wheeler Ranch) stay geocodable.
_CITY_ONLY = {
    "plumas lake", "olivehurst", "marysville", "yuba city", "wheatland",
    "linda", "live oak", "sutter", "yuba county", "sutter county",
    "sacramento", "roseville", "elk grove", "folsom", "rancho cordova",
    "citrus heights", "west sacramento", "davis", "woodland", "lincoln",
    "rocklin", "san francisco", "oakland", "san jose", "berkeley",
    "alameda", "santa clara", "daly city", "fremont", "palo alto",
    "sunnyvale", "redding", "chico", "red bluff", "eureka", "arcata",
    "humboldt", "shasta", "oroville", "paradise", "tahoe", "truckee",
    "reno", "sparks", "south lake tahoe", "incline village", "kings beach",
    "fresno", "stockton", "modesto", "bakersfield", "visalia", "clovis",
    "merced", "turlock", "madera", "dinuba", "hanford", "santa cruz",
    "monterey", "salinas", "watsonville", "capitola", "carmel",
    "pacific grove", "seaside", "california", "ca", "norcal",
    "greater sacramento", "sacramento county",
}
_CITY_STRIP = re.compile(
    r",?\s*(ca|california|usa|united states)\s*$",
    re.IGNORECASE,
)

_last_request_time = 0.0


def usable_location_text(location_text: str | None) -> str | None:
    """Drop junk like 'I' or a full LLM paragraph before hitting Nominatim."""
    if not location_text:
        return None
    text = " ".join(str(location_text).split())
    if not text:
        return None
    if len(text) > 140:
        text = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip() or text[:140]
        text = text[:140]
    lowered = text.lower().strip(" .,;:\"'")
    if len(lowered) < 4 or lowered in _UNUSABLE:
        return None
    return text


def is_city_only(location_text: str | None) -> bool:
    """True when the text is just a city/county, not a park or street."""
    text = usable_location_text(location_text)
    if not text:
        return True
    lowered = _CITY_STRIP.sub("", text.lower()).strip(" .,;:-")
    lowered = re.sub(r"\s+", " ", lowered)
    if lowered in _CITY_ONLY:
        return True
    return False


def _throttle() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()


def _nominatim(query: str) -> dict | None:
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[geocode] nominatim request failed: {exc}")
        return None
    if response.status_code != 200:
        print(f"[geocode] nominatim HTTP {response.status_code}")
        return None
    try:
        results = response.json()
    except ValueError:
        return None
    if not results:
        return None
    top = results[0]
    return _in_region({
        "latitude": float(top["lat"]),
        "longitude": float(top["lon"]),
        "display_name": top.get("display_name", query),
    })


def _photon(query: str) -> dict | None:
    try:
        response = requests.get(
            PHOTON_URL,
            params={"q": query, "limit": 1},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[geocode] photon request failed: {exc}")
        return None
    if response.status_code != 200:
        print(f"[geocode] photon HTTP {response.status_code}")
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    features = payload.get("features") or []
    if not features:
        return None
    coords = (features[0].get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    properties = features[0].get("properties") or {}
    label = properties.get("name") or query
    return _in_region({
        "latitude": float(coords[1]),
        "longitude": float(coords[0]),
        "display_name": str(properties.get("label") or label),
    })


def _in_region(result: dict | None) -> dict | None:
    if not result:
        return None
    lat = result["latitude"]
    lon = result["longitude"]
    if not (REGION_LAT[0] <= lat <= REGION_LAT[1] and REGION_LON[0] <= lon <= REGION_LON[1]):
        print(
            f"[geocode] rejected out-of-area {result.get('display_name')!r} "
            f"({lat:.4f}, {lon:.4f})"
        )
        return None
    return result


STREET_RE = re.compile(
    r"\b\d{3,5}\s+[A-Za-z0-9.'\- ]{2,40}?\s"
    r"(?:Blvd|Boulevard|St|Street|Ave|Avenue|Rd|Road|Way|Dr|Drive|"
    r"Ln|Lane|Pkwy|Parkway|Ct|Court|Pl|Place)\b",
    re.IGNORECASE,
)


def _nominatim_structured(
    street: str,
    city: str = "Sacramento",
    state: str = "California",
) -> dict | None:
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "street": street,
                "city": city,
                "state": state,
                "country": "USA",
                "format": "json",
                "limit": 1,
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"[geocode] nominatim structured failed: {exc}")
        return None
    if response.status_code != 200:
        print(f"[geocode] nominatim structured HTTP {response.status_code}")
        return None
    try:
        results = response.json()
    except ValueError:
        return None
    if not results:
        return None
    top = results[0]
    return _in_region({
        "latitude": float(top["lat"]),
        "longitude": float(top["lon"]),
        "display_name": top.get("display_name", street),
    })


def geocode(location_text: str, city_context: str = None) -> dict | None:
    """
    Returns {"latitude": float, "longitude": float, "display_name": str}
    or None if nothing matched. Never raises — a 403/timeout must not
    kill the social pipeline.
    """
    cleaned = usable_location_text(location_text)
    if not cleaned:
        print(f"[geocode] skipped unusable location {location_text!r}")
        return None

    context = city_context or DEFAULT_CITY_CONTEXT
    queries = [cleaned]
    if context.lower() not in cleaned.lower():
        queries.append(f"{cleaned}, {context}")

    street_match = STREET_RE.search(cleaned)
    street = street_match.group(0) if street_match else None
    if street:
        queries.insert(0, street)
        if f"{street}, {context}" not in queries:
            queries.insert(1, f"{street}, {context}")

    for query in queries:
        _throttle()
        result = _photon(query) or _nominatim(query)
        if result:
            return result

    if street:
        _throttle()
        result = _nominatim_structured(street)
        if result:
            return result

    print(f"[geocode] no match for {cleaned!r}")
    return None


if __name__ == "__main__":
    # Live test against the real Nominatim service.
    result = geocode("the brewery on 5th")
    print(result)
