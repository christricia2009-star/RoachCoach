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


def fetch_all_known_trucks(instagram_ids: list[str] = None, x_usernames: list[str] = None) -> list[RawSocialPost]:
    """Iterates over curated lists of truck handles across sources."""
    all_posts: list[RawSocialPost] = []

    for ig_id in (instagram_ids or []):
        try:
            all_posts.extend(fetch_recent_instagram_posts(ig_id))
        except Exception as e:
            print(f"Instagram fetch failed for {ig_id}: {e}")

    for handle in (x_usernames or []):
        try:
            all_posts.extend(fetch_recent_x_posts(handle))
        except Exception as e:
            print(f"X fetch failed for {handle}: {e}")

    return all_posts
