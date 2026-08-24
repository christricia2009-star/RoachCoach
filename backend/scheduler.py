"""
Scheduled job runner — the piece that actually needs to run continuously
SOMEWHERE (your own always-on machine, a Raspberry Pi, a cheap VPS, or a
scheduled cloud function).

UPDATED:
- Every job runs its output through signal_fusion.py.
- Results are written to CloudKit.
- Instagram Business Discovery is OPTIONAL.
- Missing Instagram/Meta credentials must NEVER stop the pipeline.

For a family/friends pilot, the simplest real option is to run this on any
computer that's usually on, a Mac mini, Raspberry Pi, VPS, or scheduled
cloud function.
"""

import os
import sys
import time
import datetime
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "scraping"))
sys.path.append(os.path.join(os.path.dirname(__file__), "phase3"))

from apscheduler.schedulers.blocking import BlockingScheduler

from backend import signal_fusion
from backend.signal_fusion import RawDetection


# In-memory pool of recent detections across ALL sources.
#
# Used for corroboration in signal_fusion.py.
#
# Example:
#   telecom anomaly + social post near same place/time
#
# can reinforce one another.
RECENT_DETECTIONS: list[RawDetection] = []

CORROBORATION_RETENTION_MINUTES = 60


def _prune_and_get_recent() -> list[RawDetection]:
    global RECENT_DETECTIONS

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(
            minutes=CORROBORATION_RETENTION_MINUTES
        )
    )

    RECENT_DETECTIONS = [
        d for d in RECENT_DETECTIONS
        if d.timestamp >= cutoff
    ]

    return RECENT_DETECTIONS


def _record_and_process(detection: RawDetection):
    """
    Adds a detection to the shared pool, then runs fusion + CloudKit write.
    """

    recent = _prune_and_get_recent()

    signal_fusion.process_detection(
        detection,
        recent,
    )

    RECENT_DETECTIONS.append(detection)


def job_california_cameras():
    """
    Checks Caltrans cameras near a configured point of interest for
    likely food-truck activity.
    """

    from traffic_camera_vision import scan_california_area

    latitude = float(
        os.getenv(
            "HOME_BASE_LATITUDE",
            "38.5816",
        )
    )

    longitude = float(
        os.getenv(
            "HOME_BASE_LONGITUDE",
            "-121.4944",
        )
    )

    results = scan_california_area(
        latitude,
        longitude,
        radius_miles=5.0,
    )

    for r in results:

        if not r.get("likely_food_truck_present"):
            continue

        confidence_map = {
            "high": 0.7,
            "medium": 0.45,
            "low": 0.2,
        }

        detection = RawDetection(
            source="traffic_cam",

            latitude=r.get(
                "latitude",
                latitude,
            ),

            longitude=r.get(
                "longitude",
                longitude,
            ),

            timestamp=datetime.datetime.now(
                datetime.timezone.utc
            ),

            raw_confidence=confidence_map.get(
                r.get(
                    "confidence",
                    "low",
                ),
                0.2,
            ),

            note=(
                f"Camera at "
                f"{r.get('location_name', 'unknown location')}: "
                f"{r.get('reasoning', '')}"
            ),
        )

        _record_and_process(detection)


def job_telecom_signals():

    from telecom_signal_data import fetch_sector_anomalies

    try:
        anomalies = fetch_sector_anomalies()

    except RuntimeError as e:
        print(
            f"[telecom] skipped — {e}"
        )
        return

    for a in anomalies:

        detection = RawDetection(
            source="telecom_signal",

            latitude=a.latitude,
            longitude=a.longitude,

            timestamp=(
                a.detected_at.replace(
                    tzinfo=datetime.timezone.utc
                )
                if a.detected_at.tzinfo is None
                else a.detected_at
            ),

            # Telecom alone stays capped low.
            # It needs corroboration.
            raw_confidence=min(
                0.5,
                a.anomaly_score * 0.3,
            ),

            source_id=(
                f"telecom:{a.sector_id}"
            ),

            note=(
                f"Sector {a.sector_id} "
                f"load anomaly "
                f"(score {a.anomaly_score:.2f})"
            ),
        )

        _record_and_process(detection)


def job_delivery_pickup_pins():

    from delivery_pickup_pins import fetch_all_pickup_pins

    pins = fetch_all_pickup_pins()

    for pin in pins:

        detection = RawDetection(
            source="delivery_pickup",

            latitude=pin.latitude,
            longitude=pin.longitude,

            timestamp=(
                pin.reported_at.replace(
                    tzinfo=datetime.timezone.utc
                )
                if pin.reported_at.tzinfo is None
                else pin.reported_at
            ),

            raw_confidence=0.6,

            source_id=(
                f"{pin.platform}:{pin.merchant_id}"
            ),

            text_hint=pin.merchant_name,

            note=(
                f"{pin.platform} pickup pin "
                f"for {pin.merchant_name}"
            ),
        )

        _record_and_process(detection)


def job_social_scraping():
    """
    Full social pipeline:

        fetch posts
          ↓
        LLM location/time extraction
          ↓
        geocode
          ↓
        signal fusion
          ↓
        CloudKit

    IMPORTANT:

    Instagram Business Discovery is OPTIONAL.

    Meta credentials may not be available while App Review /
    Business Verification is pending.

    Missing Instagram credentials MUST NOT cause the entire
    RoachCoach pipeline to fail.
    """

    from social_scraper import (
        fetch_all_known_trucks,
        fetch_web_search_results,
        INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES,
        FACEBOOK_PAGE_IDS,
    )
    from llm_extract import extract_location_from_caption
    from geocoding import geocode
    from backend.signal_fusion import KNOWN_TRUCK_NAMES

    # Curated account lists now live in social_scraper.py (single source
    # of truth shared with main.py's on-demand /api/radar/scan route) —
    # see INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES / FACEBOOK_PAGE_IDS there.

    # Accounts YOU personally manage as Instagram testers.
    #
    # Leave empty unless you have actual Instagram account IDs.
    instagram_ids: list[str] = []

    # X usernames.
    #
    # Leave empty until X API access is configured.
    x_usernames: list[str] = []

    # ------------------------------------------------------------------
    # FETCH SOCIAL DATA
    # ------------------------------------------------------------------

    posts = fetch_all_known_trucks(
        instagram_ids=instagram_ids,

        x_usernames=x_usernames,

        instagram_business_discovery_usernames=(
            INSTAGRAM_BUSINESS_DISCOVERY_USERNAMES
        ),

        facebook_page_ids=FACEBOOK_PAGE_IDS,
    )

    # ------------------------------------------------------------------
    # WEB SEARCH FALLBACK/SUPPLEMENT
    #
    # Runs an OpenRouter web-search-grounded lookup for every truck we
    # already know by name (same KNOWN_TRUCK_NAMES list signal_fusion.py
    # uses to match captions), regardless of whether that truck has a
    # monitored social account. Skips cleanly (empty list) if
    # OPENROUTER_API_KEY isn't set — see llm_providers.web_search_complete.
    # ------------------------------------------------------------------

    posts += fetch_web_search_results(
        [name.title() for name in KNOWN_TRUCK_NAMES.keys()]
    )

    # ------------------------------------------------------------------
    # PROCESS POSTS
    # ------------------------------------------------------------------

    for post in posts:

        extracted = extract_location_from_caption(
            post.caption
        )

        if extracted.get("confidence") not in (
            "high",
            "medium",
        ):
            continue

        location_text = extracted.get(
            "location_text"
        )

        geocoded = (
            geocode(location_text)
            if location_text
            else None
        )

        if not geocoded:

            print(
                f"[social] could not geocode "
                f"'{location_text}' "
                f"for {post.truck_handle} "
                f"— skipping"
            )

            continue

        confidence_map = {
            "high": 0.65,
            "medium": 0.4,
        }

        detection = RawDetection(

            source="social",

            latitude=geocoded["latitude"],

            longitude=geocoded["longitude"],

            timestamp=(
                post.posted_at.replace(
                    tzinfo=datetime.timezone.utc
                )
                if post.posted_at.tzinfo is None
                else post.posted_at
            ),

            raw_confidence=confidence_map.get(
                extracted["confidence"],
                0.4,
            ),

            text_hint=post.caption,

            note=(
                f"Posted: "
                f"\"{post.caption[:100]}\" "
                f"-> "
                f"{geocoded['display_name']}"
            ),
        )

        _record_and_process(
            detection
        )


def run_all_once():
    """
    Runs every configured job once immediately.

    Useful for GitHub Actions and manual testing.
    """

    for name, fn in JOBS:

        print(
            f"--- running {name} ---"
        )

        try:
            fn()

        except Exception:

            print(
                f"[{name}] failed:"
            )

            traceback.print_exc()


# ----------------------------------------------------------------------
# JOB DEFINITIONS
# ----------------------------------------------------------------------

JOBS = [

    (
        "california_cameras",
        job_california_cameras,
    ),

    (
        "telecom_signals",
        job_telecom_signals,
    ),

    (
        "delivery_pickup_pins",
        job_delivery_pickup_pins,
    ),

    (
        "social_scraping",
        job_social_scraping,
    ),
]


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

if __name__ == "__main__":

    if (
        len(sys.argv) > 1
        and sys.argv[1] == "--once"
    ):

        run_all_once()

    else:

        scheduler = BlockingScheduler()

        scheduler.add_job(
            job_california_cameras,
            "interval",
            minutes=10,
            id="california_cameras",
        )

        scheduler.add_job(
            job_telecom_signals,
            "interval",
            minutes=5,
            id="telecom_signals",
        )

        scheduler.add_job(
            job_delivery_pickup_pins,
            "interval",
            minutes=5,
            id="delivery_pickup_pins",
        )

        scheduler.add_job(
            job_social_scraping,
            "interval",
            minutes=30,
            id="social_scraping",
        )

        print(
            "Scheduler started. "
            "Press Ctrl+C to stop. "
            "Run with --once to test all jobs immediately instead."
        )

        try:

            scheduler.start()

        except (
            KeyboardInterrupt,
            SystemExit,
        ):

            pass
