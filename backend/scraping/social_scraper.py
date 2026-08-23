"""
Social scraping — Phase 1 data source #2.

You mentioned partnerships are already in place. This file is where those
credentials plug in once you have them. Two integration points below:

  1. Instagram Graph API (INSTAGRAM_ACCESS_TOKEN in .env)
     - Free testing on your OWN account(s): put your Instagram account in
       "Instagram Tester" role in development mode — no App Review needed.
     - Testing on OTHER trucks' accounts (i.e. the real product) requires
       Advanced Access: Meta App Review + Business Verification. Budget
       2-6 weeks for that process; it's free but not fast.

  2. X (Twitter) API (X_API_BEARER_TOKEN in .env)
     - No free tier as of Feb 2026 — it's pay-per-use ($0.005/read,
       $0.015/post created). Light testing volume costs single dollars,
       not thousands, but budget for it.

  3. PARTNERSHIP_API_KEY / PARTNERSHIP_API_BASE_URL (.env)
     - Generic slot for whatever direct data-partnership feed you've
       already lined up (e.g. a truck association, a POS vendor, or a
       regional food-truck network with its own API). Fill in once you
       have the actual key + endpoint docs from that partner.

IMPORTANT: Only use official APIs or partnership-provided data feeds.
Scraping platforms outside their official APIs / terms of service can
violate ToS and, depending on jurisdiction, laws like the CFAA.
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
    source: str  # "instagram" | "x" | "partnership"


# ---------- Instagram Graph API ----------

def fetch_recent_instagram_posts(ig_user_id: str) -> list[RawSocialPost]:
    """
    Requires INSTAGRAM_ACCESS_TOKEN in your environment. Works immediately
    for your own tester-role account(s) in development mode; requires
    Advanced Access (App Review + Business Verification) once you're
    fetching posts from truck owners who aren't testers on your app.
    """
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN not set in environment.")

    url = f"https://graph.instagram.com/{ig_user_id}/media"
    params = {
        "fields": "caption,timestamp,permalink",
        "access_token": token,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json().get("data", [])

    return [
        RawSocialPost(
            truck_handle=ig_user_id,
            caption=item.get("caption", ""),
            posted_at=datetime.datetime.fromisoformat(item["timestamp"]),
            post_url=item.get("permalink", ""),
            source="instagram",
        )
        for item in data
    ]


def fetch_recent_instagram_posts_business_discovery(target_username: str) -> list[RawSocialPost]:
    """
    Business Discovery — reads another PUBLIC Business/Creator account's
    recent posts by USERNAME, without that account needing any role on
    your app at all. This is the right function for trucks that haven't
    connected to you — use fetch_recent_instagram_posts() above only for
    accounts YOU personally manage as a Tester.

    Requires:
      - INSTAGRAM_BUSINESS_ACCOUNT_ID: the numeric ID of YOUR OWN
        Instagram Business/Creator account (the one making the query, not
        the target truck). Get this once via Graph API Explorer after
        converting your account to Business/Creator and connecting it to
        your Meta app.
      - INSTAGRAM_ACCESS_TOKEN: a valid token for that same account.

    Caveat worth knowing: Business Discovery is real and doesn't require
    the target's cooperation, but multiple sources describe it as
    "severely capped" per account per week — exact numbers vary across
    (non-official) sources I found, so watch for 429/throttling responses
    in practice rather than assuming a specific number holds.
    """
    business_account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not business_account_id or not token:
        raise RuntimeError(
            "INSTAGRAM_BUSINESS_ACCOUNT_ID / INSTAGRAM_ACCESS_TOKEN not set. "
            "These are YOUR OWN account's ID + token, used to query other "
            "public accounts via Business Discovery — see function docstring."
        )

    url = f"https://graph.facebook.com/v22.0/{business_account_id}"
    params = {
        "fields": f"business_discovery.username({target_username}){{username,media{{caption,timestamp,permalink}}}}",
        "access_token": token,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    payload = response.json()

    discovery = payload.get("business_discovery", {})
    media_items = discovery.get("media", {}).get("data", [])

    return [
        RawSocialPost(
            truck_handle=target_username,
            caption=item.get("caption", ""),
            posted_at=datetime.datetime.fromisoformat(item["timestamp"]),
            post_url=item.get("permalink", ""),
            source="instagram",
        )
        for item in media_items
    ]


# ---------- X (Twitter) API ----------

def fetch_recent_x_posts(username: str) -> list[RawSocialPost]:
    """
    Requires X_API_BEARER_TOKEN in your environment. Pay-per-use as of
    2026 — no free tier. Budget accordingly even for light testing volume.
    """
    token = os.getenv("X_API_BEARER_TOKEN")
    if not token:
        raise RuntimeError("X_API_BEARER_TOKEN not set in environment.")

    headers = {"Authorization": f"Bearer {token}"}

    user_lookup = requests.get(
        f"https://api.x.com/2/users/by/username/{username}",
        headers=headers,
        timeout=10,
    )
    user_lookup.raise_for_status()
    user_id = user_lookup.json()["data"]["id"]

    tweets = requests.get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        headers=headers,
        params={"tweet.fields": "created_at", "max_results": 10},
        timeout=10,
    )
    tweets.raise_for_status()
    data = tweets.json().get("data", [])

    return [
        RawSocialPost(
            truck_handle=username,
            caption=item.get("text", ""),
            posted_at=datetime.datetime.fromisoformat(item["created_at"]),
            post_url=f"https://x.com/{username}/status/{item['id']}",
            source="x",
        )
        for item in data
    ]


# ---------- Facebook Pages API ----------

def fetch_recent_facebook_page_posts(page_id_or_username: str) -> list[RawSocialPost]:
    """
    Reads a Facebook Page's public posts.

    IMPORTANT — read before using: this requires ONE of two things, and
    "my personal account follows this page" is NOT one of them (that
    capability doesn't exist in the API at all — Meta removed all
    personal-feed/following-list access in 2018 and never brought it back,
    for any app tier):

      1. FACEBOOK_PAGE_ACCESS_TOKEN is a token for a Page YOU (or someone
         who added you as admin/editor) actually manage — free, instant,
         no review. Only works for that specific page.
      2. Your app has "Page Public Content Access" — reading OTHER
         pages you don't manage requires this permission, which requires
         Meta App Review + Business Verification (weeks, not instant).

    There's no per-post distinction in the API between these — the same
    call either works or returns a permissions error depending on which
    of the above is true for the token you're using.
    """
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN not set in environment.")

    url = f"https://graph.facebook.com/v25.0/{page_id_or_username}/feed"
    params = {
        "fields": "message,created_time,permalink_url",
        "access_token": token,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json().get("data", [])

    return [
        RawSocialPost(
            truck_handle=page_id_or_username,
            caption=item.get("message", ""),
            posted_at=datetime.datetime.fromisoformat(item["created_time"]),
            post_url=item.get("permalink_url", ""),
            source="facebook",
        )
        for item in data
        if item.get("message")  # skip posts with no text (photo-only, etc.)
    ]


# ---------- Generic partnership feed ----------

def fetch_partnership_feed() -> list[RawSocialPost]:
    """
    Generic slot for a direct data-partnership API (e.g. a regional food
    truck association or POS vendor with its own feed). Fill in the real
    endpoint shape once you have partner API docs — this is a placeholder
    request pattern, not a working integration for any specific partner.
    """
    api_key = os.getenv("PARTNERSHIP_API_KEY")
    base_url = os.getenv("PARTNERSHIP_API_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError(
            "PARTNERSHIP_API_KEY / PARTNERSHIP_API_BASE_URL not set. "
            "Fill these in once you have the partner's real credentials + endpoint."
        )

    response = requests.get(
        f"{base_url}/locations",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
    # Real shape depends entirely on the partner's API — adjust parsing
    # once you have their actual response schema.
    return []


def fetch_all_known_trucks(instagram_ids: list[str] = None, x_usernames: list[str] = None, instagram_business_discovery_usernames: list[str] = None, facebook_page_ids: list[str] = None) -> list[RawSocialPost]:
    """Iterates over curated lists of truck handles across sources."""
    all_posts: list[RawSocialPost] = []

    for ig_id in (instagram_ids or []):
        try:
            all_posts.extend(fetch_recent_instagram_posts(ig_id))
        except Exception as e:
            print(f"Instagram fetch failed for {ig_id}: {e}")

    for username in (instagram_business_discovery_usernames or []):
        try:
            all_posts.extend(fetch_recent_instagram_posts_business_discovery(username))
        except Exception as e:
            print(f"Instagram Business Discovery fetch failed for @{username}: {e}")

    for page_id in (facebook_page_ids or []):
        try:
            all_posts.extend(fetch_recent_facebook_page_posts(page_id))
        except Exception as e:
            print(f"Facebook Page fetch failed for {page_id}: {e}")

    for handle in (x_usernames or []):
        try:
            all_posts.extend(fetch_recent_x_posts(handle))
        except Exception as e:
            print(f"X fetch failed for {handle}: {e}")

    return all_posts
