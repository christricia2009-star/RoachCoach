"""
Social scraping — Phase 1 data source #2.

IMPORTANT:

Instagram Business Discovery is OPTIONAL.

If Meta App Review / Business Verification has not been completed,
RoachCoach continues operating without Instagram Business Discovery.

Only official APIs or partnership-provided feeds are used.

We do NOT bypass Instagram access controls or use unauthorized scraping.
"""

from __future__ import annotations

import json
import os
import re

import requests

from dataclasses import dataclass

from typing import Optional

import datetime

from urllib.parse import unquote

try:
    from dotenv import load_dotenv

    _HERE = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_HERE, "..", ".env"))
    load_dotenv()
except ImportError:
    pass


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
#
# Two token kinds:
#   IGA…  Instagram Login user token  -> graph.instagram.com
#   EAA…  Facebook Login / Page token -> graph.facebook.com
#
# Instagram Login can read the authorized professional account's own
# media today (Tester role, no App Review). Business Discovery of
# *other* food-truck accounts is a Facebook-Login field; IGA tokens
# return "nonexisting field (business_discovery)" and we skip it.

INSTAGRAM_GRAPH_VERSION = "v25.0"

_IG_ACCOUNT_CACHE: Optional[dict] = None
_IG_ACCOUNT_CACHE_TAIL = ""
_IG_TOKEN_REFRESHED = False
_IG_BD_UNSUPPORTED_REASON: Optional[str] = None


def _instagram_access_token() -> str:
    return (os.getenv("INSTAGRAM_ACCESS_TOKEN") or "").strip()


def _instagram_is_login_token(token: str) -> bool:
    return token.upper().startswith("IGA")


def _instagram_graph_base(token: str) -> str:
    if token.upper().startswith("EAA"):
        return f"https://graph.facebook.com/{INSTAGRAM_GRAPH_VERSION}"
    return f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}"


def _facebook_access_token() -> str:
    return unquote(
        (
            os.getenv("FACEBOOK_USER_ACCESS_TOKEN")
            or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
            or ""
        ).strip()
    )


def _business_discovery_credentials() -> tuple[str, str, str]:
    """
    Token + IG user id + Graph host for discovering *other* professional
    accounts (@drewskis, @sactomofo, …).

    That field exists only on Instagram API with Facebook Login:
    an EAA… user token against graph.facebook.com. Instagram Login
    IGA… tokens return "nonexisting field (business_discovery)".
    """
    fb_token = _facebook_access_token()
    ig_token = _instagram_access_token()
    env_id = (os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip()
    account = resolve_instagram_account() if ig_token else None
    ig_id = env_id or ((account or {}).get("user_id") or "")

    if fb_token.upper().startswith("EAA"):
        return (
            fb_token,
            ig_id,
            f"https://graph.facebook.com/{INSTAGRAM_GRAPH_VERSION}",
        )
    if ig_token.upper().startswith("EAA"):
        return (
            ig_token,
            ig_id,
            f"https://graph.facebook.com/{INSTAGRAM_GRAPH_VERSION}",
        )
    if ig_token:
        return ig_token, ig_id, _instagram_graph_base(ig_token)
    return "", ig_id, ""


def _parse_social_timestamp(value: str) -> datetime.datetime:
    raw = (value or "").strip()
    if not raw:
        return datetime.datetime.now(datetime.timezone.utc)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    elif len(raw) >= 5 and raw[-5] in "+-" and raw[-3] != ":":
        raw = raw[:-2] + ":" + raw[-2:]
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _maybe_refresh_instagram_token(token: str) -> str:
    """Extend a long-lived Instagram Login token (valid ~60 days)."""
    global _IG_TOKEN_REFRESHED
    if _IG_TOKEN_REFRESHED or not _instagram_is_login_token(token):
        return token
    _IG_TOKEN_REFRESHED = True
    try:
        response = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token,
            },
            timeout=10,
        )
        if response.status_code == 200:
            new_token = (response.json().get("access_token") or "").strip()
            if new_token:
                os.environ["INSTAGRAM_ACCESS_TOKEN"] = new_token
                expires = response.json().get("expires_in")
                extra = f" (expires_in={expires}s)" if expires else ""
                print(f"[instagram] refreshed long-lived token{extra}")
                return new_token
        print(
            f"[instagram] token refresh skipped "
            f"(HTTP {response.status_code}): "
            f"{(response.text or '')[:160]}"
        )
    except Exception as e:
        print(f"[instagram] token refresh failed: {e}")
    return token


def resolve_instagram_account() -> Optional[dict]:
    """
    Resolve the authorized Instagram professional account.

    For Instagram Login (IGA…) tokens this calls GET /me and fills
    INSTAGRAM_BUSINESS_ACCOUNT_ID when it is missing.

    For Facebook Login (EAA…) tokens /me is a Facebook user, so we
    require INSTAGRAM_BUSINESS_ACCOUNT_ID to already be set.
    """
    global _IG_ACCOUNT_CACHE, _IG_ACCOUNT_CACHE_TAIL

    token = _instagram_access_token()
    if not token:
        return None

    tail = token[-12:]
    if _IG_ACCOUNT_CACHE and _IG_ACCOUNT_CACHE_TAIL == tail:
        return _IG_ACCOUNT_CACHE

    env_id = (os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip()

    if token.upper().startswith("EAA"):
        if not env_id:
            print(
                "[instagram] Facebook Login token set but "
                "INSTAGRAM_BUSINESS_ACCOUNT_ID is empty."
            )
            return None
        account = {
            "user_id": env_id,
            "id": env_id,
            "username": "",
            "account_type": "",
            "media_count": None,
        }
        _IG_ACCOUNT_CACHE = account
        _IG_ACCOUNT_CACHE_TAIL = tail
        return account

    url = f"{_instagram_graph_base(token)}/me"
    try:
        response = requests.get(
            url,
            params={
                "fields": "user_id,username,id,account_type,media_count",
                "access_token": token,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"[instagram] /me failed: {e}")
        return None

    user_id = (
        str(payload.get("user_id") or "").strip()
        or env_id
        or str(payload.get("id") or "").strip()
    )
    if not user_id:
        print("[instagram] /me returned no user_id")
        return None

    account = {
        "user_id": user_id,
        "id": str(payload.get("id") or user_id),
        "username": str(payload.get("username") or ""),
        "account_type": str(payload.get("account_type") or ""),
        "media_count": payload.get("media_count"),
    }
    if not env_id:
        os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"] = user_id
    _IG_ACCOUNT_CACHE = account
    _IG_ACCOUNT_CACHE_TAIL = tail
    print(
        f"[instagram] authorized @{account['username'] or user_id} "
        f"({account.get('account_type') or 'account'})"
    )
    return account


def _posts_from_media_items(
    items: list,
    truck_handle: str,
) -> list[RawSocialPost]:
    posts: list[RawSocialPost] = []
    for item in items or []:
        posts.append(
            RawSocialPost(
                truck_handle=truck_handle,
                caption=item.get("caption") or "",
                posted_at=_parse_social_timestamp(
                    item.get("timestamp") or ""
                ),
                post_url=item.get("permalink") or "",
                source="instagram",
            )
        )
    return posts


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
    token = _instagram_access_token()
    if not token:
        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN not set in environment."
        )

    handle = (ig_user_id or "").strip()
    if not handle:
        return []

    account = resolve_instagram_account()
    display = handle
    if account and handle in (
        account.get("user_id"),
        account.get("id"),
        "me",
    ):
        display = account.get("username") or handle

    url = f"{_instagram_graph_base(token)}/{handle}/media"
    response = requests.get(
        url,
        params={
            "fields": "caption,timestamp,permalink,media_type",
            "limit": 25,
            "access_token": token,
        },
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("data") or []
    posts = _posts_from_media_items(items, display)
    print(f"[instagram] @{display}: {len(posts)} post(s)")
    return posts


def fetch_recent_instagram_posts_business_discovery(
    target_username: str,
) -> list[RawSocialPost]:
    """
    Retrieves recent public posts from another eligible Instagram
    Business/Creator account through Meta Business Discovery.

    Optional. Missing credentials, Instagram Login tokens that do
    not expose this field, or a single-account failure all return
    an empty list instead of raising.
    """
    global _IG_BD_UNSUPPORTED_REASON

    if _IG_BD_UNSUPPORTED_REASON:
        return []

    token, business_account_id, graph_base = _business_discovery_credentials()

    if not business_account_id or not token or not graph_base:
        return []

    username = (target_username or "").lstrip("@").strip()
    if not username:
        return []

    url = f"{graph_base}/{business_account_id}"
    params = {
        "fields": (
            "business_discovery.username("
            f"{username}"
            "){username,media.limit(8){caption,timestamp,permalink}}"
        ),
        "access_token": token,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        body = response.text or ""
        if response.status_code >= 400:
            lowered = body.lower()
            if (
                "nonexisting field" in lowered
                or (
                    "business_discovery" in lowered
                    and "does not exist" in lowered
                )
            ):
                _IG_BD_UNSUPPORTED_REASON = (
                    "Business Discovery is not available on this "
                    "Instagram Login token. Own-account media still "
                    "works; other trucks keep using web search."
                )
                print(f"[instagram] {_IG_BD_UNSUPPORTED_REASON}")
                return []
            if (
                "(#10)" in body
                or "does not have permission" in lowered
                or "pages_read_engagement" in lowered
                or "error_subcode\":33" in lowered
                or "does not exist" in lowered
            ):
                _IG_BD_UNSUPPORTED_REASON = (
                    "Business Discovery needs a Facebook Login EAA… "
                    "token with instagram_basic, instagram_manage_insights, "
                    "and pages_read_engagement; the IG professional "
                    "account must be connected to a Facebook Page this "
                    "user can manage. App Review Advanced Access is "
                    "required to list accounts you do not manage."
                )
                print(f"[instagram] {_IG_BD_UNSUPPORTED_REASON}")
                return []
            print(
                f"[instagram] Business Discovery failed for "
                f"@{username} (HTTP {response.status_code}): "
                f"{body[:200]}"
            )
            return []
        payload = response.json()
    except Exception as e:
        print(
            f"[instagram] Business Discovery failed for "
            f"@{username}: {e}"
        )
        return []

    discovery = payload.get("business_discovery") or {}
    media_items = (
        (discovery.get("media") or {}).get("data") or []
    )
    handle = discovery.get("username") or username
    posts = _posts_from_media_items(media_items, handle)
    if posts:
        print(
            f"[instagram] discovery @{handle}: {len(posts)} post(s)"
        )
    return posts


# =========================================================================
# X / TWITTER API
# =========================================================================

# Set on 401/402/403/429 so a dead or unpaid token does not hammer
# every handle in the list (each call can still consume credits).
_X_DISABLED_REASON: Optional[str] = None
_X_MISSING_TOKEN_WARNED = False


def _x_bearer_token() -> str:
    # Developer portal / copy-paste sometimes URL-encodes / and =.
    return unquote((os.getenv("X_API_BEARER_TOKEN") or "").strip())


def _disable_x_api(status: int, detail: str) -> None:
    global _X_DISABLED_REASON
    _X_DISABLED_REASON = detail
    print(
        f"[x] disabling native X API for this process "
        f"(HTTP {status}): {detail}"
    )


def fetch_recent_x_posts(
    username: str,
) -> list[RawSocialPost]:
    """
    Requires:

        X_API_BEARER_TOKEN

    Official app-only read of a public account's recent posts.
    Missing token, unpaid credits (HTTP 402), or a missing handle
    skip this source — they do not fail the rest of the pipeline.
    """

    global _X_MISSING_TOKEN_WARNED

    if _X_DISABLED_REASON:
        return []

    token = _x_bearer_token()

    if not token:
        if not _X_MISSING_TOKEN_WARNED:
            print(
                "[x] X_API_BEARER_TOKEN not set — "
                "skipping native X API, web search will cover x.com."
            )
            _X_MISSING_TOKEN_WARNED = True
        return []

    handle = username.lstrip("@").strip()
    if not handle:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "RoachCoachRadar/1.0",
    }

    user_lookup = requests.get(
        f"https://api.x.com/2/users/by/username/{handle}",
        headers=headers,
        timeout=10,
    )

    if user_lookup.status_code in (401, 402, 403, 429):
        _disable_x_api(
            user_lookup.status_code,
            (user_lookup.text or "")[:240] or user_lookup.reason,
        )
        return []

    if user_lookup.status_code == 404:
        print(f"[x] no such user @{handle} — skip")
        return []

    user_lookup.raise_for_status()
    user_id = user_lookup.json()["data"]["id"]

    tweets = requests.get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        headers=headers,
        params={
            "tweet.fields": "created_at",
            "max_results": 10,
            "exclude": "retweets,replies",
        },
        timeout=10,
    )

    if tweets.status_code in (401, 402, 403, 429):
        _disable_x_api(
            tweets.status_code,
            (tweets.text or "")[:240] or tweets.reason,
        )
        return []

    tweets.raise_for_status()

    data = tweets.json().get("data", []) or []

    posts: list[RawSocialPost] = []
    for item in data:
        created = item.get("created_at") or ""
        try:
            posted_at = datetime.datetime.fromisoformat(
                created.replace("Z", "+00:00")
            )
        except ValueError:
            posted_at = datetime.datetime.now(datetime.timezone.utc)

        posts.append(
            RawSocialPost(
                truck_handle=handle,
                caption=item.get("text", "") or "",
                posted_at=posted_at,
                post_url=(
                    f"https://x.com/{handle}/status/{item.get('id', '')}"
                ),
                source="x",
            )
        )

    print(f"[x] @{handle}: {len(posts)} post(s)")
    return posts


# =========================================================================
# FACEBOOK PAGES API
# =========================================================================
#
# Public posts from *other* business pages need Page Public Content Access
# (App Review + Business Verification) and a Facebook user/page token
# (EAA…). Instagram Login IGA… tokens and Instagram-only app secrets
# cannot call graph.facebook.com.

_FB_DISABLED_REASON: Optional[str] = None
_FB_MISSING_TOKEN_WARNED = False


def _disable_facebook_api(status: int, detail: str) -> None:
    global _FB_DISABLED_REASON
    _FB_DISABLED_REASON = detail
    print(
        f"[facebook] disabling native Facebook API for this process "
        f"(HTTP {status}): {detail}"
    )


def fetch_recent_facebook_page_posts(
    page_id_or_username: str,
) -> list[RawSocialPost]:
    """
    Reads Facebook Page posts (or the page's listed address if posts
    are not readable yet).

    Requires FACEBOOK_USER_ACCESS_TOKEN or FACEBOOK_PAGE_ACCESS_TOKEN.
    Missing token, permission errors, or a dead token skip this source.
    """
    global _FB_MISSING_TOKEN_WARNED

    if _FB_DISABLED_REASON:
        return []

    token = _facebook_access_token()
    if not token:
        if not _FB_MISSING_TOKEN_WARNED:
            print(
                "[facebook] no FACEBOOK_USER_ACCESS_TOKEN / "
                "FACEBOOK_PAGE_ACCESS_TOKEN — skipping page posts. "
                "Need a Facebook Login EAA… token (not the Instagram "
                "IGA… token) plus Page Public Content Access for "
                "pages you do not manage."
            )
            _FB_MISSING_TOKEN_WARNED = True
        return []

    handle = (page_id_or_username or "").lstrip("@").strip()
    if not handle:
        return []

    base = f"https://graph.facebook.com/{INSTAGRAM_GRAPH_VERSION}/{handle}"

    for edge in ("posts", "feed"):
        response = requests.get(
            f"{base}/{edge}",
            params={
                "fields": "message,created_time,permalink_url",
                "limit": 10,
                "access_token": token,
            },
            timeout=10,
        )
        if response.status_code in (401, 403):
            _disable_facebook_api(
                response.status_code,
                (response.text or "")[:240] or response.reason,
            )
            return []
        if response.status_code >= 400:
            body = response.text or ""
            lowered = body.lower()
            if (
                "pages_read_engagement" in lowered
                or "page public content access" in lowered
                or "page public metadata access" in lowered
            ):
                _disable_facebook_api(
                    response.status_code,
                    "Facebook Page reads need pages_read_engagement "
                    "or Page Public Content Access. This token only "
                    "has instagram_manage_comments + public_profile."
                    if "instagram_manage_comments" in lowered
                    else body[:240],
                )
                return []
            print(
                f"[facebook] {handle}/{edge} HTTP "
                f"{response.status_code}: {body[:160]}"
            )
            continue

        data = response.json().get("data") or []
        posts: list[RawSocialPost] = []
        for item in data:
            message = item.get("message") or ""
            if not message:
                continue
            posts.append(
                RawSocialPost(
                    truck_handle=handle,
                    caption=message,
                    posted_at=_parse_social_timestamp(
                        item.get("created_time") or ""
                    ),
                    post_url=item.get("permalink_url") or "",
                    source="facebook",
                )
            )
        if posts:
            print(f"[facebook] {handle}: {len(posts)} post(s)")
            return posts

    # Posts are locked without App Review. Page location/about is
    # sometimes still readable and is better than a web-search guess.
    meta = requests.get(
        base,
        params={
            "fields": (
                "name,about,website,single_line_address,"
                "location{city,street,zip,state}"
            ),
            "access_token": token,
        },
        timeout=10,
    )
    if meta.status_code in (401, 403):
        _disable_facebook_api(
            meta.status_code,
            (meta.text or "")[:240] or meta.reason,
        )
        return []
    if meta.status_code >= 400:
        return []

    payload = meta.json()
    location = payload.get("location") or {}
    parts = [
        location.get("street"),
        location.get("city"),
        location.get("state"),
        location.get("zip"),
        payload.get("single_line_address"),
    ]
    address = ", ".join(part for part in parts if part)
    if not address:
        return []
    name = payload.get("name") or handle
    print(f"[facebook] {handle}: using listed address {address}")
    return [
        RawSocialPost(
            truck_handle=handle,
            caption=f"{name} {address}",
            posted_at=datetime.datetime.now(datetime.timezone.utc),
            post_url=payload.get("website") or "",
            source="facebook",
        )
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
        "x": "drewskishotrod",
        "facebook": "drewskisfoodtrucks",
        "address": "5504 Dudley Blvd, Sacramento, CA",
        "latitude": "38.6659329",
        "longitude": "-121.3868242",
    },
    {
        "key": "buckhorn bbq",
        "search_name": "Buckhorn BBQ Truck",
        "instagram": "thebuckhornbbqtruck",
        "x": "",
        "facebook": "thebuckhornbbqtruck",
        "address": "",
    },
    {
        "key": "sactomofo",
        "search_name": "SactoMoFo",
        "instagram": "sactomofo",
        "x": "SactoMoFo",
        "facebook": "sactomofo",
        "address": "",
    },
    {
        "key": "krush burger",
        "search_name": "Krush Burger",
        "instagram": "krushroseville",
        "x": "",
        "facebook": "krushroseville",
        "address": "",
    },
    {
        "key": "potato patoto",
        "search_name": "Potato Patoto",
        "instagram": "the_potato_truck",
        "x": "",
        "facebook": "the_potato_truck",
        "address": "",
    },
    {
        "key": "alameda tacos",
        "search_name": "Alameda Tacos Food Truck",
        "instagram": "alamedatacossac",
        "x": "",
        "facebook": "alamedatacossac",
        "address": "3291 Truxel Rd, Sacramento, CA",
    },
    {
        "key": "mucho nachos",
        "search_name": "Mucho Nachos Sacramento",
        "instagram": "muchonachossacramento",
        "x": "",
        "facebook": "muchonachossacramento",
        "address": "",
    },
    {
        "key": "the pop up truck",
        "search_name": "The Pop Up Truck Sacramento",
        "instagram": "sactopopuptruck",
        "x": "",
        "facebook": "sactopopuptruck",
        "address": "",
    },
    {
        "key": "santacos",
        "search_name": "SanTacos Sacramento",
        "instagram": "santacosmx",
        "x": "",
        "facebook": "santacosmx",
        "address": "",
    },
    {
        "key": "tacoa",
        "search_name": "Tacoa Sacramento",
        "instagram": "tacoasac",
        "x": "",
        "facebook": "tacoasac",
        "address": "",
    },
    {
        "key": "tacos gto",
        "search_name": "Tacos GTO Sacramento",
        "instagram": "tacos_gto_",
        "x": "",
        "facebook": "tacos_gto_",
        "address": "",
    },
    {
        "key": "tacomiendo",
        "search_name": "Tacomiendo Food Truck",
        "instagram": "tacomiendofoodtruck",
        "x": "",
        "facebook": "tacomiendofoodtruck",
        "address": "",
    },
    {
        "key": "sac tacos",
        "search_name": "Sac Tacos Foodtruck",
        "instagram": "sactacosfoodtruck",
        "x": "",
        "facebook": "sactacosfoodtruck",
        "address": "",
    },
    {
        "key": "the lumpia truck",
        "search_name": "The Lumpia Truck Sacramento",
        "instagram": "thelumpiatruck",
        "x": "TheLumpiaTruck",
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

_HANDLE_RE = re.compile(r"^[a-z0-9._]{2,30}$")
_LIVE_CATALOG: Optional[list[dict]] = None


def instagram_handle_from_text(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    text = text.split("?")[0].rstrip("/")
    lower = text.lower()
    if "instagram.com/" in lower:
        part = lower.split("instagram.com/", 1)[1]
        handle = part.split("/")[0].lstrip("@")
        if handle in ("p", "reel", "reels", "stories", "explore", "tv"):
            return None
        return handle if _HANDLE_RE.match(handle) else None
    if lower.startswith("@"):
        handle = lower[1:]
        return handle if _HANDLE_RE.match(handle) else None
    if "://" in lower or "facebook.com" in lower or "x.com/" in lower:
        return None
    handle = lower.lstrip("@")
    return handle if _HANDLE_RE.match(handle) else None


def guessed_instagram_handle(name: str) -> Optional[str]:
    slug = re.sub(r"[''`´]", "", (name or "").lower())
    slug = re.sub(r"[^a-z0-9]+", "", slug)
    if slug in ("foodtruck", "foodtrucks", "sacramento", "truck"):
        return None
    return slug if _HANDLE_RE.match(slug) and len(slug) >= 4 else None


def _ck_value(record: dict, field: str, default=None):
    fields = record.get("fields") or {}
    if not isinstance(fields, dict):
        return default
    item = fields.get(field)
    if isinstance(item, dict):
        return item.get("value", default)
    return default


def _catalog_add(by_key: dict[str, dict], entry: dict) -> None:
    key = (entry.get("key") or entry.get("search_name") or "").strip().lower()
    if not key:
        return
    existing = by_key.get(key)
    if existing is None:
        by_key[key] = entry
        return
    if entry.get("id") and not existing.get("id"):
        existing["id"] = entry["id"]
    for field in ("instagram", "facebook", "x", "search_name"):
        if entry.get(field) and not existing.get(field):
            existing[field] = entry[field]
    merged = list(existing.get("instagram_all") or [])
    for handle in entry.get("instagram_all") or []:
        if handle and handle not in merged:
            merged.append(handle)
    existing["instagram_all"] = merged


def load_live_truck_catalog(*, refresh: bool = False) -> list[dict]:
    """
    Union of curated listings, sacramento_trucks.json, and live CloudKit
    Truck records. Instagram handles come from socialLinks when present,
    otherwise a best-effort slug of the truck name.
    """
    global _LIVE_CATALOG
    if _LIVE_CATALOG is not None and not refresh:
        return _LIVE_CATALOG

    by_key: dict[str, dict] = {}

    for item in TRUCK_LISTINGS:
        ig = (item.get("instagram") or "").strip().lstrip("@").lower()
        _catalog_add(by_key, {
            "id": "",
            "key": item["key"],
            "search_name": item["search_name"],
            "instagram": ig,
            "instagram_all": [ig] if ig else [],
            "facebook": (item.get("facebook") or "").strip(),
            "x": (item.get("x") or "").strip(),
        })

    json_paths = [
        os.path.join(os.path.dirname(__file__), "..", "data", "sacramento_trucks.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "sacramento_trucks.json"),
    ]
    for path in json_paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                rows = json.load(handle)
            for row in rows or []:
                name = str((row or {}).get("name") or "").strip()
                if not name:
                    continue
                igs = []
                for link in row.get("socialLinks") or []:
                    parsed = instagram_handle_from_text(str(link))
                    if parsed:
                        igs.append(parsed)
                guess = guessed_instagram_handle(name)
                if guess and guess not in igs:
                    igs.append(guess)
                _catalog_add(by_key, {
                    "id": "",
                    "key": name.lower(),
                    "search_name": name,
                    "instagram": igs[0] if igs else "",
                    "instagram_all": igs,
                    "facebook": "",
                    "x": "",
                })
            print(f"[social] loaded {len(rows)} seed truck(s) from {path}")
        except Exception as exc:
            print(f"[social] seed json {path}: {exc}")
        break

    try:
        import cloudkit_bridge

        records = cloudkit_bridge.get_trucks()
        print(f"[social] CloudKit returned {len(records)} Truck record(s)")
        for rec in records:
            name = str(_ck_value(rec, "name") or "").strip()
            truck_id = str(rec.get("recordName") or "").strip()
            links = _ck_value(rec, "socialLinks") or []
            if isinstance(links, str):
                links = [links]
            igs: list[str] = []
            facebook = ""
            x_handle = ""
            for raw in links or []:
                text = str(raw)
                parsed = instagram_handle_from_text(text)
                if parsed and parsed not in igs:
                    igs.append(parsed)
                lower = text.lower()
                if "facebook.com/" in lower and not facebook:
                    facebook = lower.split("facebook.com/", 1)[1].split("/")[0].split("?")[0]
                if ("x.com/" in lower or "twitter.com/" in lower) and not x_handle:
                    host = "x.com/" if "x.com/" in lower else "twitter.com/"
                    x_handle = lower.split(host, 1)[1].split("/")[0].split("?")[0]
            if not igs:
                guess = guessed_instagram_handle(name)
                if guess:
                    igs.append(guess)
            if name:
                _catalog_add(by_key, {
                    "id": truck_id,
                    "key": name.lower(),
                    "search_name": name,
                    "instagram": igs[0] if igs else "",
                    "instagram_all": igs,
                    "facebook": facebook,
                    "x": x_handle,
                })
    except Exception as exc:
        print(f"[social] CloudKit truck catalog unavailable: {exc}")

    _LIVE_CATALOG = list(by_key.values())
    ig_count = sum(1 for item in _LIVE_CATALOG if item.get("instagram_all"))
    print(
        f"[social] truck catalog: {len(_LIVE_CATALOG)} truck(s), "
        f"{ig_count} Instagram handle(s) to discover"
    )
    return _LIVE_CATALOG


def register_trucks_for_fusion(catalog: list[dict] | None = None) -> int:
    try:
        import signal_fusion
    except ModuleNotFoundError:
        try:
            from backend import signal_fusion
        except ModuleNotFoundError:
            print("[social] signal_fusion not importable; skip name map")
            return 0

    catalog = catalog or load_live_truck_catalog()
    for item in catalog:
        truck_id = (item.get("id") or "").strip()
        name = (item.get("search_name") or "").strip()
        if not truck_id or not name:
            continue
        keys = {name.lower(), (item.get("key") or "").lower()}
        for handle in item.get("instagram_all") or []:
            keys.add(handle.lower())
        if item.get("facebook"):
            keys.add(str(item["facebook"]).lower())
        for key in keys:
            if key:
                signal_fusion.KNOWN_TRUCK_NAMES[key] = truck_id
    print(
        f"[social] fusion map now has "
        f"{len(signal_fusion.KNOWN_TRUCK_NAMES)} name/handle key(s)"
    )
    return len(signal_fusion.KNOWN_TRUCK_NAMES)


def all_instagram_discovery_usernames(
    catalog: list[dict] | None = None,
) -> list[str]:
    catalog = catalog or load_live_truck_catalog()
    seen: set[str] = set()
    out: list[str] = []
    for handle in INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES:
        item = (handle or "").lower().lstrip("@").strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    for row in catalog:
        for handle in row.get("instagram_all") or []:
            item = (handle or "").lower().lstrip("@").strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def all_facebook_page_ids(catalog: list[dict] | None = None) -> list[str]:
    catalog = catalog or load_live_truck_catalog()
    seen: set[str] = set()
    out: list[str] = []
    for page in FACEBOOK_PAGE_IDS:
        item = (page or "").strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    for row in catalog:
        item = (row.get("facebook") or "").strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def listing_keys_for_handle(handle: str) -> list[str]:
    needle = (handle or "").lower().lstrip("@").strip()
    if not needle:
        return []
    keys: list[str] = []
    for item in TRUCK_LISTINGS:
        aliases = {
            (item.get("instagram") or "").lower(),
            (item.get("facebook") or "").lower(),
            (item.get("x") or "").lower(),
            item["key"],
            item["search_name"].lower(),
        }
        if needle in aliases:
            keys.append(item["key"])
    for row in _LIVE_CATALOG or []:
        aliases = {
            (row.get("instagram") or "").lower(),
            (row.get("facebook") or "").lower(),
            (row.get("x") or "").lower(),
            (row.get("key") or ""),
            (row.get("search_name") or "").lower(),
        }
        aliases.update((row.get("instagram_all") or []))
        if needle in {alias.lower() for alias in aliases if alias}:
            key = row.get("key") or (row.get("search_name") or "").lower()
            if key and key not in keys:
                keys.append(key)
    return keys


def native_social_covered_keys(posts: list[RawSocialPost]) -> set[str]:
    """Listing keys that already have an Instagram or Facebook post."""
    covered: set[str] = set()
    for post in posts:
        if post.source not in ("instagram", "facebook"):
            continue
        if not (post.caption or post.post_url):
            continue
        covered.update(listing_keys_for_handle(post.truck_handle))
    return covered


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

    authorized_ids = list(instagram_ids or [])
    token = _instagram_access_token()
    if token:
        _maybe_refresh_instagram_token(token)
    account = resolve_instagram_account() if _instagram_access_token() else None
    if account:
        for candidate in (
            account.get("user_id"),
            account.get("id"),
        ):
            if candidate and candidate not in authorized_ids:
                authorized_ids.append(candidate)
                break

    for ig_id in authorized_ids:
        try:
            all_posts.extend(fetch_recent_instagram_posts(ig_id))
        except Exception as e:
            print(f"Instagram fetch failed for {ig_id}: {e}")

    # -----------------------------------------------------------------
    # INSTAGRAM BUSINESS DISCOVERY
    #
    # Optional. Instagram Login (IGA…) tokens typically do not expose
    # this field; Facebook Login (EAA…) tokens might. A miss never
    # stops the rest of the pipeline.
    # -----------------------------------------------------------------

    bd_token, bd_id, bd_host = _business_discovery_credentials()
    if bd_token and bd_id and instagram_business_discovery_usernames:
        kind = "Facebook Login" if bd_token.upper().startswith("EAA") else "Instagram Login"
        print(
            f"[instagram] attempting Business Discovery via {kind} "
            f"for {len(instagram_business_discovery_usernames)} handle(s)."
        )
        for username in instagram_business_discovery_usernames or []:
            try:
                all_posts.extend(
                    fetch_recent_instagram_posts_business_discovery(username)
                )
            except Exception as e:
                print(
                    "[instagram] Business Discovery "
                    f"failed for @{username}: {e}"
                )
    elif instagram_business_discovery_usernames:
        print(
            "[instagram] Business Discovery unavailable — need a "
            "Facebook Login EAA… token (FACEBOOK_USER_ACCESS_TOKEN) "
            "with instagram_basic + instagram_manage_insights + "
            "pages_read_engagement. The current Instagram Login "
            "token cannot list @drewskis / @sactomofo."
        )

    # -----------------------------------------------------------------
    # FACEBOOK
    # -----------------------------------------------------------------

    facebook_ids = list(facebook_page_ids or [])
    if facebook_ids and not _facebook_access_token():
        print(
            "[facebook] skipping "
            f"{len(facebook_ids)} business page(s) — no Facebook "
            "Login token. Instagram Login cannot read Facebook pages."
        )
        facebook_ids = []

    for page_id in facebook_ids:
        try:
            all_posts.extend(fetch_recent_facebook_page_posts(page_id))
        except Exception as e:
            print(f"Facebook Page fetch failed for {page_id}: {e}")

    # -----------------------------------------------------------------
    # X — only for trucks Instagram/Facebook did not already cover.
    # -----------------------------------------------------------------

    covered = native_social_covered_keys(all_posts)
    for handle in x_usernames or []:
        keys = listing_keys_for_handle(handle)
        if keys and all(key in covered for key in keys):
            print(f"[x] skip @{handle} — already have IG/FB")
            continue
        try:
            all_posts.extend(fetch_recent_x_posts(handle))
        except Exception as e:
            print(f"X fetch failed for {handle}: {e}")

    return all_posts


def diagnose_instagram(
    discovery_usernames: list[str] | None = None,
) -> dict:
    """
    Live check used by GET /api/diagnostics/instagram and
    `python3 scraping/social_scraper.py`. Never returns the token.
    """
    token = _instagram_access_token()
    if not token:
        return {
            "ok": False,
            "configured": False,
            "error": "INSTAGRAM_ACCESS_TOKEN is not set",
        }

    account = resolve_instagram_account()
    if not account:
        return {
            "ok": False,
            "configured": True,
            "token_kind": (
                "instagram_login"
                if _instagram_is_login_token(token)
                else "facebook_login"
            ),
            "error": "token did not resolve an Instagram professional account",
        }

    try:
        posts = fetch_recent_instagram_posts(account["user_id"])
        own_error = None
    except Exception as e:
        posts = []
        own_error = f"{type(e).__name__}: {e}"

    discovery: list[dict] = []
    sample = discovery_usernames
    if sample is None:
        sample = INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES[:2]
    for username in sample:
        try:
            found = fetch_recent_instagram_posts_business_discovery(username)
            entry = {
                "username": username,
                "ok": True,
                "posts": len(found),
            }
        except Exception as e:
            entry = {
                "username": username,
                "ok": False,
                "posts": 0,
                "error": str(e)[:240],
            }
        if _IG_BD_UNSUPPORTED_REASON:
            entry["ok"] = False
            entry["error"] = _IG_BD_UNSUPPORTED_REASON
        elif entry.get("ok") and entry.get("posts") == 0:
            entry["ok"] = False
            entry["error"] = "no posts returned"
        discovery.append(entry)

    return {
        "ok": own_error is None,
        "configured": True,
        "token_kind": (
            "instagram_login"
            if _instagram_is_login_token(token)
            else "facebook_login"
        ),
        "username": account.get("username") or "",
        "user_id": account.get("user_id") or "",
        "account_type": account.get("account_type") or "",
        "media_count": account.get("media_count"),
        "own_post_count": len(posts),
        "own_posts": [
            {
                "handle": post.truck_handle,
                "posted_at": post.posted_at.isoformat(),
                "permalink": post.post_url,
                "caption": (post.caption or "")[:180],
            }
            for post in posts[:10]
        ],
        "own_error": own_error,
        "business_discovery": discovery,
        "business_discovery_supported": not bool(_IG_BD_UNSUPPORTED_REASON),
        "can_list_other_accounts": (
            any(item.get("posts") for item in discovery)
            and not bool(_IG_BD_UNSUPPORTED_REASON)
        ),
        "next_step": (
            None
            if (not _instagram_is_login_token(token)
                or _facebook_access_token().upper().startswith("EAA"))
            else (
                "This Instagram Login token can only read @"
                f"{account.get('username') or 'your-account'}. "
                "To list @drewskis / @sactomofo you need Instagram API "
                "with Facebook Login: connect the IG professional account "
                "to a Facebook Page, generate an EAA user token with "
                "instagram_basic, instagram_manage_insights, and "
                "pages_read_engagement, store it as "
                "FACEBOOK_USER_ACCESS_TOKEN, then submit Meta App Review "
                "for Advanced Access (Business Verification). Meta does "
                "not allow Instagram Login tokens to discover other "
                "professional accounts."
            )
        ),
    }


def diagnose_facebook(
    page_ids: list[str] | None = None,
) -> dict:
    """Live Facebook Page check. Never returns the token."""
    token = _facebook_access_token()
    if not token:
        return {
            "ok": False,
            "configured": False,
            "token_kind": None,
            "error": (
                "FACEBOOK_USER_ACCESS_TOKEN / FACEBOOK_PAGE_ACCESS_TOKEN "
                "is not set"
            ),
            "next_step": (
                "Generate a Facebook Login user or Page token (starts "
                "with EAA, not IGA) in a Meta app that uses Instagram "
                "API with Facebook Login. Reading other trucks' Pages "
                "also needs the Page Public Content Access feature "
                "approved in App Review."
            ),
            "pages": [],
        }

    sample = page_ids if page_ids is not None else FACEBOOK_PAGE_IDS[:2]
    pages: list[dict] = []
    for page in sample:
        try:
            found = fetch_recent_facebook_page_posts(page)
            pages.append({
                "page": page,
                "ok": True,
                "posts": len(found),
            })
        except Exception as e:
            pages.append({
                "page": page,
                "ok": False,
                "posts": 0,
                "error": str(e)[:240],
            })
        if _FB_DISABLED_REASON:
            pages[-1]["ok"] = False
            pages[-1]["error"] = _FB_DISABLED_REASON
            break

    return {
        "ok": any(item.get("posts") for item in pages),
        "configured": True,
        "token_kind": (
            "facebook_login"
            if token.upper().startswith("EAA")
            else "unknown"
        ),
        "pages": pages,
        "disabled_reason": _FB_DISABLED_REASON,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(
        {
            "instagram": diagnose_instagram(),
            "facebook": diagnose_facebook(),
        },
        indent=2,
        default=str,
    ))
