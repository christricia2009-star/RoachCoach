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

        raise RuntimeError(
            "X_API_BEARER_TOKEN not set in environment."
        )

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
