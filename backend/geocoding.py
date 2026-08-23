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

import time
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RoachCoachRadar/1.0 (contact: your-email@example.com)"  # update this

# City/area bias — geocoding "the brewery on 5th" with no city context is
# unreliable. Set this to your actual pilot area so short/ambiguous
# location text resolves to the right place instead of a random 5th
# Street somewhere else in the world.
DEFAULT_CITY_CONTEXT = "Sacramento, CA"

_last_request_time = 0.0


def geocode(location_text: str, city_context: str = None) -> dict | None:
    """
    Returns {"latitude": float, "longitude": float, "display_name": str}
    or None if nothing matched. Rate-limits itself to Nominatim's 1 req/sec
    policy automatically.
    """
    global _last_request_time

    if not location_text or not location_text.strip():
        return None

    context = city_context or DEFAULT_CITY_CONTEXT
    query = f"{location_text}, {context}"

    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    response = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    _last_request_time = time.time()
    response.raise_for_status()

    results = response.json()
    if not results:
        return None

    top = results[0]
    return {
        "latitude": float(top["lat"]),
        "longitude": float(top["lon"]),
        "display_name": top.get("display_name", location_text),
    }


if __name__ == "__main__":
    # Live test against the real Nominatim service.
    result = geocode("the brewery on 5th")
    print(result)
