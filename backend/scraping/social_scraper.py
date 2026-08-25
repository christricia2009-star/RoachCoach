"""
Social scraping — Phase 1 data source #2.

IMPORTANT:

Instagram Business Discovery is OPTIONAL.

If Meta App Review / Business Verification has not been completed,
RoachCoach continues operating without Instagram Business Discovery.

Only official APIs or partnership-provided feeds are used.

We do NOT bypass Instagram access controls or use unauthorized scraping.
"""

import os

import requests

from dataclasses import dataclass

from typing import Optional

import datetime


@dataclass
class RawSocialPost:

    truck_handle: str

    caption: str

    posted_at: datetime.datetime

    post_url: str

    source: str
    # "instagram" | "x" | "facebook" | "partnership"


# =========================================================================
# INSTAGRAM GRAPH API
# =========================================================================

def fetch_recent_instagram_posts(
    ig_user_id: str,
) -> list[RawSocialPost]:
    """
    Retrieves Instagram media for an Instagram account that the
    configured token is authorized to access.

    Requires:

        INSTAGRAM_ACCESS_TOKEN

    This is for accounts you are authorized to access / tester accounts.
    """

    token = os.getenv(
        "INSTAGRAM_ACCESS_TOKEN"
    )

    if not token:

        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN not set in environment."
        )

    url = (
        f"https://graph.instagram.com/"
        f"{ig_user_id}/media"
    )

    params = {

        "fields": (
            "caption,"
            "timestamp,"
            "permalink"
        ),

        "access_token": token,
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json().get(
        "data",
        [],
    )

    return [

        RawSocialPost(

            truck_handle=ig_user_id,

            caption=item.get(
                "caption",
                "",
            ),

            posted_at=(
                datetime.datetime.fromisoformat(
                    item["timestamp"]
                )
            ),

            post_url=item.get(
                "permalink",
                "",
            ),

            source="instagram",
        )

        for item in data
    ]


# =========================================================================
# INSTAGRAM BUSINESS DISCOVERY
# =========================================================================

def fetch_recent_instagram_posts_business_discovery(
    target_username: str,
) -> list[RawSocialPost]:
    """
    Retrieves recent public posts from another eligible Instagram
    Business/Creator account through Meta Business Discovery.

    IMPORTANT:

    This function is OPTIONAL.

    If:

        INSTAGRAM_BUSINESS_ACCOUNT_ID

    or:

        INSTAGRAM_ACCESS_TOKEN

    is missing, this function returns an EMPTY LIST.

    It does NOT throw an exception.

    This is intentional because Meta App Review / Business Verification
    may still be pending.

    Required for Business Discovery:

        INSTAGRAM_BUSINESS_ACCOUNT_ID
        INSTAGRAM_ACCESS_TOKEN

    INSTAGRAM_BUSINESS_ACCOUNT_ID is the ID of YOUR OWN authorized
    Business/Creator account making the request.

    It is NOT the target food truck's ID.
    """

    business_account_id = os.getenv(
        "INSTAGRAM_BUSINESS_ACCOUNT_ID"
    )

    token = os.getenv(
        "INSTAGRAM_ACCESS_TOKEN"
    )

    # ---------------------------------------------------------------
    # CRITICAL FIX
    #
    # Instagram Business Discovery is optional.
    #
    # Do NOT fail the entire pipeline when Meta credentials are
    # unavailable.
    # ---------------------------------------------------------------

    if (
        not business_account_id
        or not token
    ):

        return []

    url = (
        f"https://graph.facebook.com/"
        f"v22.0/"
        f"{business_account_id}"
    )

    params = {

        "fields": (
            "business_discovery."
            f"username({target_username})"
            "{username,media"
            "{caption,timestamp,permalink}}"
        ),

        "access_token": token,
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    payload = response.json()

    discovery = payload.get(
        "business_discovery",
        {},
    )

    media_items = (
        discovery
        .get(
            "media",
            {},
        )
        .get(
            "data",
            [],
        )
    )

    return [

        RawSocialPost(

            truck_handle=target_username,

            caption=item.get(
                "caption",
                "",
            ),

            posted_at=(
                datetime.datetime.fromisoformat(
                    item["timestamp"]
                )
            ),

            post_url=item.get(
                "permalink",
                "",
            ),

            source="instagram",
        )

        for item in media_items
    ]


# =========================================================================
# X / TWITTER API
# =========================================================================

def fetch_recent_x_posts(
    username: str,
) -> list[RawSocialPost]:
    """
    Requires:

        X_API_BEARER_TOKEN
    """

    token = os.getenv(
        "X_API_BEARER_TOKEN"
    )

    if not token:
        print(
            "[x] X_API_BEARER_TOKEN not set — "
            "skipping native X API, web search will cover x.com."
        )
        return []

    headers = {
        "Authorization":
            f"Bearer {token}"
    }

    user_lookup = requests.get(

        (
            "https://api.x.com/2/users/"
            f"by/username/{username}"
        ),

        headers=headers,

        timeout=10,
    )

    user_lookup.raise_for_status()

    user_id = (
        user_lookup
        .json()["data"]["id"]
    )

    tweets = requests.get(

        (
            f"https://api.x.com/2/users/"
            f"{user_id}/tweets"
        ),

        headers=headers,

        params={
            "tweet.fields":
                "created_at",
            "max_results":
                10,
        },

        timeout=10,
    )

    tweets.raise_for_status()

    data = (
        tweets
        .json()
        .get(
            "data",
            [],
        )
    )

    return [

        RawSocialPost(

            truck_handle=username,

            caption=item.get(
                "text",
                "",
            ),

            posted_at=(
                datetime.datetime.fromisoformat(
                    item["created_at"]
                )
            ),

            post_url=(
                f"https://x.com/"
                f"{username}/status/"
                f"{item['id']}"
            ),

            source="x",
        )

        for item in data
    ]


# =========================================================================
# FACEBOOK PAGES API
# =========================================================================

def fetch_recent_facebook_page_posts(
    page_id_or_username: str,
) -> list[RawSocialPost]:
    """
    Reads Facebook Page posts.

    Requires:

        FACEBOOK_PAGE_ACCESS_TOKEN

    The token must have appropriate authorization for the page/content
    being requested.
    """

    token = os.getenv(
        "FACEBOOK_PAGE_ACCESS_TOKEN"
    )

    if not token:

        raise RuntimeError(
            "FACEBOOK_PAGE_ACCESS_TOKEN "
            "not set in environment."
        )

    url = (
        "https://graph.facebook.com/"
        f"v25.0/"
        f"{page_id_or_username}/feed"
    )

    params = {

        "fields": (
            "message,"
            "created_time,"
            "permalink_url"
        ),

        "access_token": token,
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = (
        response
        .json()
        .get(
            "data",
            [],
        )
    )

    return [

        RawSocialPost(

            truck_handle=page_id_or_username,

            caption=item.get(
                "message",
                "",
            ),

            posted_at=(
                datetime.datetime.fromisoformat(
                    item["created_time"]
                )
            ),

            post_url=item.get(
                "permalink_url",
                "",
            ),

            source="facebook",
        )

        for item in data

        if item.get("message")
    ]


# =========================================================================
# CURATED ACCOUNT LISTS — single source of truth
# =========================================================================
#
# Both scheduler.py (the background job that runs every 30 min) and
# main.py's on-demand POST /api/radar/scan route need the same "which
# accounts do we check" lists. Keeping them here means there's exactly one
# place to add a truck's account instead of two that can silently drift
# out of sync.

INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES: list[str] = [
    "drewskis",
    "thebuckhornbbqtruck",
    "sactomofo",
    "krushroseville",
    "the_potato_truck",
    "alamedatacossac",
    "muchonachossacramento",
    "sactopopuptruck",
    "santacosmx",
    "tacoasac",
    "tacos_gto_",
    "tacomiendofoodtruck",
    "sactacosfoodtruck",
    "thelumpiatruck",
]

# Filled from TRUCK_LISTINGS after that list is defined.
FACEBOOK_PAGE_IDS: list[str] = []

# Full search names + any published listing address we already know.
# Bing/Yelp/website listings are valid radar pins. "Only if posted today"
# made Luna return NOTHING_FOUND while Yelp still shows a street address.
TRUCK_LISTINGS: list[dict[str, str]] = [
    {
        "key": "drewski's",
        "search_name": "Drewski's Hot Rod Kitchen",
        "instagram": "drewskis",
        "x": "drewskis",
        "facebook": "drewskisfoodtrucks",
        "address": "5504 Dudley Blvd, Sacramento, CA",
        "latitude": "38.6659329",
        "longitude": "-121.3868242",
    },
    {
        "key": "buckhorn bbq",
        "search_name": "Buckhorn BBQ Truck",
        "instagram": "thebuckhornbbqtruck",
        "x": "thebuckhornbbqtruck",
        "facebook": "thebuckhornbbqtruck",
        "address": "",
    },
    {
        "key": "sactomofo",
        "search_name": "SactoMoFo",
        "instagram": "sactomofo",
        "x": "sactomofo",
        "facebook": "sactomofo",
        "address": "",
    },
    {
        "key": "krush burger",
        "search_name": "Krush Burger",
        "instagram": "krushroseville",
        "x": "krushroseville",
        "facebook": "krushroseville",
        "address": "",
    },
    {
        "key": "potato patoto",
        "search_name": "Potato Patoto",
        "instagram": "the_potato_truck",
        "x": "the_potato_truck",
        "facebook": "the_potato_truck",
        "address": "",
    },
    {
        "key": "alameda tacos",
        "search_name": "Alameda Tacos Food Truck",
        "instagram": "alamedatacossac",
        "x": "alamedatacossac",
        "facebook": "alamedatacossac",
        "address": "3291 Truxel Rd, Sacramento, CA",
    },
    {
        "key": "mucho nachos",
        "search_name": "Mucho Nachos Sacramento",
        "instagram": "muchonachossacramento",
        "x": "muchonachossacramento",
        "facebook": "muchonachossacramento",
        "address": "",
    },
    {
        "key": "the pop up truck",
        "search_name": "The Pop Up Truck Sacramento",
        "instagram": "sactopopuptruck",
        "x": "sactopopuptruck",
        "facebook": "sactopopuptruck",
        "address": "",
    },
    {
        "key": "santacos",
        "search_name": "SanTacos Sacramento",
        "instagram": "santacosmx",
        "x": "santacosmx",
        "facebook": "santacosmx",
        "address": "",
    },
    {
        "key": "tacoa",
        "search_name": "Tacoa Sacramento",
        "instagram": "tacoasac",
        "x": "tacoasac",
        "facebook": "tacoasac",
        "address": "",
    },
    {
        "key": "tacos gto",
        "search_name": "Tacos GTO Sacramento",
        "instagram": "tacos_gto_",
        "x": "tacos_gto_",
        "facebook": "tacos_gto_",
        "address": "",
    },
    {
        "key": "tacomiendo",
        "search_name": "Tacomiendo Food Truck",
        "instagram": "tacomiendofoodtruck",
        "x": "tacomiendofoodtruck",
        "facebook": "tacomiendofoodtruck",
        "address": "",
    },
    {
        "key": "sac tacos",
        "search_name": "Sac Tacos Foodtruck",
        "instagram": "sactacosfoodtruck",
        "x": "sactacosfoodtruck",
        "facebook": "sactacosfoodtruck",
        "address": "",
    },
    {
        "key": "the lumpia truck",
        "search_name": "The Lumpia Truck Sacramento",
        "instagram": "thelumpiatruck",
        "x": "thelumpiatruck",
        "facebook": "thelumpiatruck",
        "address": "",
    },
]

X_USERNAMES: list[str] = [
    item["x"] for item in TRUCK_LISTINGS if item.get("x")
]
FACEBOOK_PAGE_IDS = [
    item["facebook"] for item in TRUCK_LISTINGS if item.get("facebook")
]


# =========================================================================
# OPENROUTER WEB SEARCH
# =========================================================================

def search_web_for_truck_location(truck_name: str) -> Optional[RawSocialPost]:
    """
    Uses OpenRouter's web-search-augmented completion (see
    llm_providers.web_search_complete) to look up where a specific truck
    is today, instead of relying on that truck having a monitored
    Instagram/Facebook account at all.

    Deliberately returns a RawSocialPost, source="web_search", with the
    model's search-grounded answer sitting in `.caption` — exactly the
    same shape an Instagram/Facebook post takes. That means it flows
    through the EXACT same downstream pipeline (llm_extract.py's
    extract_location_from_caption -> geocoding.py -> signal_fusion.py)
    with no separate code path to maintain.

    Returns None (not an exception) if OPENROUTER_API_KEY isn't set, or if
    the search call itself fails — callers should treat "no result" here
    the same as "this truck has no post today," not as a pipeline error.
    """
    from llm_providers import web_search_complete

    listing = next(
        (
            item for item in TRUCK_LISTINGS
            if item["search_name"] == truck_name
            or item["key"] == truck_name.lower()
        ),
        None,
    )
    instagram = (listing or {}).get("instagram") or ""
    x_handle = (listing or {}).get("x") or ""
    facebook = (listing or {}).get("facebook") or ""

    prompt = (
        f'Search Instagram, X/Twitter, Facebook, Yelp, and the web for the '
        f'Sacramento food truck "{truck_name}". '
        f"Food trucks post TODAY's location on social media to get customers. "
        f"Check these profiles first: "
        f"instagram.com/{instagram or 'search-by-name'}, "
        f"x.com/{x_handle or 'search-by-name'}, "
        f"facebook.com/{facebook or 'search-by-name'}. "
        f"Prefer a today/this-week location from an Instagram, X, or Facebook post. "
        f"If none, use the published Yelp or website address. "
        f"Reply with EXACTLY one line:\n"
        f"FOUND: <street address or place name, city>\n"
        f"or\n"
        f"NOTHING_FOUND"
    )

    try:
        answer = web_search_complete(prompt, max_tokens=250, max_results=5)
    except Exception as e:
        print(f"[web_search] failed for '{truck_name}': {e}")
        return None

    if not answer:
        print(f"[web_search] {truck_name}: empty reply")
        return None

    compact = " ".join(answer.split())
    print(f"[web_search] {truck_name}: {compact[:180]}")

    location = _parse_found_location(answer)
    if not location:
        print(f"[web_search] {truck_name}: no FOUND line (ignored thinking/trace)")
        return None

    return RawSocialPost(
        truck_handle=truck_name,
        caption=location,
        posted_at=datetime.datetime.now(datetime.timezone.utc),
        post_url="",
        source="web_search",
    )


def _parse_found_location(answer: str) -> Optional[str]:
    """Accept a FOUND: place anywhere in the reply. Drop thinking traces."""
    import re

    thinking = (
        "searching for",
        "i need to search",
        "i wonder if",
        "according to the developer",
        "current system date",
        "check platforms",
    )
    match = re.search(
        r"FOUND:\s*(.+)",
        answer.replace("**", ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    found = match.group(1).strip().splitlines()[0].strip()
    lower = found.lower()
    if "nothing_found" in lower:
        return None
    if any(marker in lower for marker in thinking):
        return None
    if len(found) < 4:
        return None
    return found


def fetch_web_search_results(
    truck_names: list[str] | None = None,
) -> list[RawSocialPost]:
    """
    Looks up published listings for each known truck. Uses OpenRouter
    web search first, then the curated Yelp/website address if search
    returns nothing. Independent per truck.
    """
    results: list[RawSocialPost] = []
    listings = TRUCK_LISTINGS
    if truck_names:
        wanted = {name.strip().lower() for name in truck_names}
        listings = [
            item for item in TRUCK_LISTINGS
            if item["key"] in wanted or item["search_name"].lower() in wanted
        ] or [
            {"key": name.lower(), "search_name": name, "address": ""}
            for name in truck_names
        ]

    now = datetime.datetime.now(datetime.timezone.utc)

    for listing in listings:
        name = listing["search_name"]
        post = None
        try:
            post = search_web_for_truck_location(name)
        except Exception as e:
            print(f"[web_search] unexpected failure for '{name}': {e}")

        if post:
            # Keep the truck's real name in the caption so fusion
            # name-matching can attach the detection.
            post.caption = f"{name} {post.caption}"
            results.append(post)
            continue

        address = (listing.get("address") or "").strip()
        if address:
            print(f"[web_search] {name}: using listed address {address}")
            results.append(
                RawSocialPost(
                    truck_handle=name,
                    caption=f"{name} {address}",
                    posted_at=now,
                    post_url="",
                    source="web_search",
                )
            )
            continue

        print(f"[web_search] {name}: no listing yet, will geocode name")
        results.append(
            RawSocialPost(
                truck_handle=name,
                caption=f"{name} Sacramento, CA",
                posted_at=now,
                post_url="",
                source="web_search",
            )
        )

    return results


# =========================================================================
# GENERIC PARTNERSHIP FEED
# =========================================================================

def fetch_partnership_feed() -> list[RawSocialPost]:
    """
    Generic slot for a direct data-partnership API.

    Requires:

        PARTNERSHIP_API_KEY
        PARTNERSHIP_API_BASE_URL
    """

    api_key = os.getenv(
        "PARTNERSHIP_API_KEY"
    )

    base_url = os.getenv(
        "PARTNERSHIP_API_BASE_URL"
    )

    if (
        not api_key
        or not base_url
    ):

        raise RuntimeError(
            "PARTNERSHIP_API_KEY / "
            "PARTNERSHIP_API_BASE_URL "
            "not set. "
            "Fill these in once you have "
            "the partner's real credentials "
            "+ endpoint."
        )

    response = requests.get(

        f"{base_url}/locations",

        headers={
            "Authorization":
                f"Bearer {api_key}"
        },

        timeout=10,
    )

    response.raise_for_status()

    # The actual response structure depends
    # on the partner API.
    return []


# =========================================================================
# FETCH ALL SOCIAL SOURCES
# =========================================================================

def fetch_all_known_trucks(
    instagram_ids: list[str] = None,

    x_usernames: list[str] = None,

    instagram_business_discovery_usernames: list[str] = None,

    facebook_page_ids: list[str] = None,

) -> list[RawSocialPost]:

    """
    Iterates over configured social sources.

    IMPORTANT:

    Every source is independently optional.

    A failure in one source does NOT prevent the other sources from
    running.
    """

    all_posts: list[RawSocialPost] = []

    # -----------------------------------------------------------------
    # INSTAGRAM ACCOUNTS WE DIRECTLY CONTROL / ARE AUTHORIZED TO ACCESS
    # -----------------------------------------------------------------

    for ig_id in (
        instagram_ids or []
    ):

        try:

            all_posts.extend(
                fetch_recent_instagram_posts(
                    ig_id
                )
            )

        except Exception as e:

            print(
                f"Instagram fetch failed "
                f"for {ig_id}: {e}"
            )

    # -----------------------------------------------------------------
    # INSTAGRAM BUSINESS DISCOVERY
    #
    # THIS IS THE IMPORTANT FIX.
    #
    # If Meta credentials aren't available, skip the entire batch.
    # Do not print one failure per truck.
    # -----------------------------------------------------------------

    business_account_id = os.getenv(
        "INSTAGRAM_BUSINESS_ACCOUNT_ID"
    )

    instagram_token = os.getenv(
        "INSTAGRAM_ACCESS_TOKEN"
    )

    if (
        business_account_id
        and instagram_token
    ):

        print(
            "[instagram] "
            "Business Discovery credentials "
            "detected; attempting discovery."
        )

        for username in (
            instagram_business_discovery_usernames
            or []
        ):

            try:

                posts = (
                    fetch_recent_instagram_posts_business_discovery(
                        username
                    )
                )

                all_posts.extend(
                    posts
                )

            except Exception as e:

                # IMPORTANT:
                # Even if Meta credentials exist but a particular
                # account fails, do NOT kill the entire pipeline.
                print(
                    "[instagram] Business Discovery "
                    f"failed for @{username}: {e}"
                )

    else:

        if instagram_business_discovery_usernames:

            print(
                "[instagram] Business Discovery "
                "unavailable — Meta credentials "
                "not configured; continuing "
                "without Instagram."
            )

    # -----------------------------------------------------------------
    # FACEBOOK
    # -----------------------------------------------------------------

    for page_id in (
        facebook_page_ids or []
    ):

        try:

            all_posts.extend(
                fetch_recent_facebook_page_posts(
                    page_id
                )
            )

        except Exception as e:

            print(
                f"Facebook Page fetch failed "
                f"for {page_id}: {e}"
            )

    # -----------------------------------------------------------------
    # X
    # -----------------------------------------------------------------

    for handle in (
        x_usernames or []
    ):

        try:

            all_posts.extend(
                fetch_recent_x_posts(
                    handle
                )
            )

        except Exception as e:

            print(
                f"X fetch failed "
                f"for {handle}: {e}"
            )

    return all_posts
