"""
Public listing collectors — the sources food-truck apps actually use
when Instagram/X APIs are locked down.

These only hit pages that publish locations on purpose:
  - DuckDuckGo HTML search snippets (Yelp, MapQuest, official sites)
  - Truck / aggregator websites (drewskis.com, sactomofo.com)
  - OpenStreetMap Overpass (named food-truck nodes)

No Instagram/Facebook login bypass. Native social APIs stay in
social_scraper.py and run when tokens exist.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

import requests

USER_AGENT = (
    "RoachCoachRadar/1.0 "
    "(https://radar.snapcollectibles.com; christricia2009@gmail.com)"
)

SACRAMENTO_BBOX = (38.40, -121.70, 38.80, -121.20)

ADDRESS_RE = re.compile(
    r"\b\d{3,5}\s+[A-Za-z0-9.'\- ]{2,40}?\s"
    r"(?:Blvd|Boulevard|St|Street|Ave|Avenue|Rd|Road|Way|Dr|Drive|"
    r"Ln|Lane|Pkwy|Parkway|Ct|Court|Pl|Place)\b",
    re.IGNORECASE,
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/json",
})


@dataclass
class ListingHit:
    truck_name: str
    location_text: str
    source: str
    source_url: str = ""
    note: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return " ".join(text.split())


def _addresses_in(text: str) -> list[str]:
    found = []
    seen = set()
    for match in ADDRESS_RE.finditer(text or ""):
        addr = _clean(match.group(0))
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(addr)
    return found


def search_duckduckgo(query: str, limit: int = 8) -> list[dict[str, str]]:
    try:
        response = SESSION.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[listings] duckduckgo failed: {exc}")
        return []
    if response.status_code not in (200, 202):
        print(f"[listings] duckduckgo HTTP {response.status_code}")
        return []
    if response.status_code == 202 and "result__a" not in response.text:
        print("[listings] duckduckgo challenge page; skipping search results")
        return []

    body = response.text
    results: list[dict[str, str]] = []
    pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(body):
        href = html.unescape(match.group(1))
        if "uddg=" in href:
            found = re.search(r"uddg=([^&]+)", href)
            if found:
                href = unquote(found.group(1))
        results.append({
            "url": href,
            "title": _clean(match.group(2)),
            "snippet": _clean(match.group(3)),
        })
        if len(results) >= limit:
            break
    if not results:
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            re.IGNORECASE | re.DOTALL,
        ):
            results.append({
                "url": html.unescape(match.group(1)),
                "title": _clean(match.group(2)),
                "snippet": "",
            })
            if len(results) >= limit:
                break
    return results


def fetch_page_text(url: str, timeout: int = 12) -> str:
    try:
        response = SESSION.get(url, timeout=timeout)
    except requests.RequestException as exc:
        print(f"[listings] page fetch failed {url}: {exc}")
        return ""
    if response.status_code != 200:
        return ""
    return _clean(response.text[:80_000])


def listings_for_truck(listing: dict[str, str]) -> list[ListingHit]:
    name = listing["search_name"]
    hits: list[ListingHit] = []
    known = (listing.get("address") or "").strip()
    lat = lon = None
    try:
        if listing.get("latitude") and listing.get("longitude"):
            lat = float(listing["latitude"])
            lon = float(listing["longitude"])
    except (TypeError, ValueError):
        lat = lon = None
    if known:
        hits.append(
            ListingHit(
                truck_name=name,
                location_text=f"{name} {known}",
                source="directory",
                note=f"Listed address {known}",
                latitude=lat,
                longitude=lon,
            )
        )

    query = (
        f"{name} Sacramento food truck "
        f"instagram OR twitter OR facebook OR yelp location today"
    )
    print(f"[listings] duckduckgo: {query}")
    for result in search_duckduckgo(query):
        blob = f"{result['title']} {result['snippet']} {result['url']}"
        addresses = _addresses_in(blob)
        if not addresses:
            continue
        addr = addresses[0]
        hits.append(
            ListingHit(
                truck_name=name,
                location_text=f"{name} {addr}, Sacramento, CA",
                source="web_search",
                source_url=result["url"],
                note=f"Search snippet: {result['title'][:80]}",
            )
        )
        break

    ig = listing.get("instagram") or ""
    if ig:
        social_query = (
            f"{name} site:instagram.com/{ig} OR site:x.com/{ig} "
            f"OR site:facebook.com Sacramento today"
        )
        print(f"[listings] social search: {social_query[:90]}")
        for result in search_duckduckgo(social_query, limit=5):
            blob = f"{result['title']} {result['snippet']}"
            addresses = _addresses_in(blob)
            if not addresses:
                continue
            hits.append(
                ListingHit(
                    truck_name=name,
                    location_text=f"{name} {addresses[0]}, Sacramento, CA",
                    source="social",
                    source_url=result["url"],
                    note=f"Social snippet: {result['title'][:80]}",
                )
            )
            break

    return hits


def sacramento_today_hits() -> list[ListingHit]:
    hits: list[ListingHit] = []
    query = "Sacramento food trucks today OR tonight location"
    print(f"[listings] metro search: {query}")
    for result in search_duckduckgo(query, limit=10):
        blob = f"{result['title']} {result['snippet']}"
        addresses = _addresses_in(blob)
        if not addresses:
            continue
        from social_scraper import TRUCK_LISTINGS

        name = result["title"] or "Sacramento food truck"
        for listing in TRUCK_LISTINGS:
            if listing["key"] in name.lower() or listing["search_name"].split()[0].lower() in name.lower():
                name = listing["search_name"]
                break
        hits.append(
            ListingHit(
                truck_name=name,
                location_text=f"{name} {addresses[0]}, Sacramento, CA",
                source="web_search",
                source_url=result["url"],
                note=f"Metro search: {result['title'][:80]}",
            )
        )
    return hits


def sactomofo_event_hits() -> list[ListingHit]:
    text = fetch_page_text("https://sactomofo.com/events/")
    if not text:
        return []
    addresses = _addresses_in(text)
    hits = []
    for addr in addresses[:6]:
        hits.append(
            ListingHit(
                truck_name="SactoMoFo",
                location_text=f"SactoMoFo {addr}, Sacramento, CA",
                source="social",
                source_url="https://sactomofo.com/events/",
                note=f"SactoMoFo calendar {addr}",
            )
        )
    print(f"[listings] sactomofo events addresses={len(addresses)}")
    return hits


def collect_listings() -> list[ListingHit]:
    from social_scraper import TRUCK_LISTINGS

    hits: list[ListingHit] = []
    seen: set[str] = set()

    def add(hit: ListingHit) -> None:
        key = f"{hit.truck_name.lower()}|{hit.location_text.lower()}"
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    for listing in TRUCK_LISTINGS:
        try:
            for hit in listings_for_truck(listing):
                add(hit)
        except Exception as exc:
            print(f"[listings] {listing.get('search_name')}: {exc}")

    for hit in sacramento_today_hits() + sactomofo_event_hits():
        add(hit)

    print(f"[listings] collected {len(hits)} unique listing hit(s)")
    return hits
