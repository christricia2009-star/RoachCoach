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

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    load_dotenv()
except ImportError:
    pass

sys.path.append(os.path.join(os.path.dirname(__file__), "scraping"))
sys.path.append(os.path.join(os.path.dirname(__file__), "collectors"))
sys.path.append(os.path.join(os.path.dirname(__file__), "phase3"))

from apscheduler.schedulers.blocking import BlockingScheduler

# scheduler.py gets run two different ways that put two different
# directories on sys.path:
#   - `python3 scheduler.py` (GitHub Actions workflow, or any VPS/cron
#     setup) with cwd=backend/ — Python auto-adds backend/ itself to
#     sys.path, so signal_fusion is importable directly, but there's no
#     "backend" package visible (its own parent isn't on the path).
#   - imported as part of the `backend` package (e.g. some future runner
#     that does `from backend import scheduler` from the repo root) —
#     here "backend" IS on the path, and the bare module name isn't
#     necessarily unique/importable the same way.
# Try both so this doesn't break depending on how/where it's invoked.
try:
    from backend import signal_fusion
    from backend.signal_fusion import RawDetection
    from backend import error_tracking
    from backend import cloudkit_bridge
except ModuleNotFoundError:
    import signal_fusion
    from signal_fusion import RawDetection
    import error_tracking
    import cloudkit_bridge

error_tracking.init()


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

    enabled = (os.getenv("RUN_CAMERA_VISION") or "").strip().lower()
    if enabled not in ("1", "true", "yes"):
        print(
            "[cameras] skipped — 9 vision calls per run are expensive. "
            "Set RUN_CAMERA_VISION=true to enable."
        )
        return

    from traffic_camera_vision import scan_california_area

    # `os.getenv(name, default)`'s default only kicks in when the
    # variable is completely UNSET — if a GitHub Actions secret is
    # referenced (env: HOME_BASE_LATITUDE: ${{ secrets.HOME_BASE_LATITUDE }})
    # but that secret was never actually added in the repo's Settings,
    # the env var still gets created, just as an empty string, so the
    # default silently never applies and float('') raises ValueError.
    # `or` catches both "unset" and "set but empty" the same way.
    latitude = float(
        os.getenv("HOME_BASE_LATITUDE") or "38.5816"
    )

    longitude = float(
        os.getenv("HOME_BASE_LONGITUDE") or "-121.4944"
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
        native_social_covered_keys,
        load_live_truck_catalog,
        register_trucks_for_fusion,
        all_instagram_discovery_usernames,
        all_facebook_page_ids,
        X_USERNAMES,
        TRUCK_LISTINGS,
    )
    from llm_extract import extract_location_from_caption
    from geocoding import geocode, usable_location_text

    # KNOWN_TRUCK_NAMES already imported at module level (see the
    # try/except import block near the top of this file) as
    # `signal_fusion.KNOWN_TRUCK_NAMES` — reuse that instead of a second,
    # separately-resolved import here.

    catalog = load_live_truck_catalog(refresh=True)
    register_trucks_for_fusion(catalog)
    ig_handles = all_instagram_discovery_usernames(catalog)
    fb_pages = all_facebook_page_ids(catalog)
    print(
        f"[social] discovering {len(ig_handles)} Instagram handle(s) "
        f"and {len(fb_pages)} Facebook page(s) across "
        f"{len(catalog)} known truck(s)"
    )

    # Own Instagram professional account is auto-resolved from
    # INSTAGRAM_ACCESS_TOKEN via GET /me. Extra tester IDs can go here.
    instagram_ids: list[str] = []

    x_usernames: list[str] = list(X_USERNAMES)

    # ------------------------------------------------------------------
    # FETCH SOCIAL DATA
    # ------------------------------------------------------------------

    posts = fetch_all_known_trucks(
        instagram_ids=instagram_ids,

        x_usernames=x_usernames,

        instagram_business_discovery_usernames=ig_handles,

        facebook_page_ids=fb_pages,
    )

    print(
        f"[social] account fetch returned {len(posts)} post(s)"
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

    per_truck = (os.getenv("PER_TRUCK_WEB_SEARCH") or "").strip().lower()
    if per_truck in ("1", "true", "yes"):
        covered = native_social_covered_keys(posts)
        missing = [
            item["search_name"]
            for item in TRUCK_LISTINGS
            if item["key"] not in covered
        ]
        if missing:
            web_posts = fetch_web_search_results(missing)
            print(
                f"[social] web_search for {len(missing)} truck(s) "
                f"without IG/FB returned {len(web_posts)} result(s)"
            )
            posts += web_posts
        else:
            print(
                "[social] skipped web search — Instagram/Facebook "
                "already covered every known truck."
            )
    else:
        print(
            "[social] skipped per-truck OpenRouter web-search "
            "(PER_TRUCK_WEB_SEARCH not set). Instagram/Facebook "
            "are the primary sources; public_listings does one "
            "cheaper JSON search for the rest."
        )

    # ------------------------------------------------------------------
    # PROCESS POSTS
    # ------------------------------------------------------------------

    for post in posts:

        print(
            f"[social] {post.truck_handle} caption: "
            f"{(post.caption or '')[:180]!r}"
        )

        try:
            extracted = extract_location_from_caption(
                post.caption
            )
        except Exception:
            error_tracking.report(
                f"[social] llm_extract failed for {post.truck_handle}"
            )
            extracted = {
                "confidence": "none",
                "location_text": None,
            }

        print(
            f"[social] {post.truck_handle}: "
            f"confidence={extracted.get('confidence')} "
            f"location={extracted.get('location_text')!r}"
        )

        if extracted.get("confidence") not in (
            "high",
            "medium",
        ):
            if post.source == "web_search" and post.caption:
                extracted = {
                    "confidence": "medium",
                    "location_text": usable_location_text(
                        extracted.get("location_text")
                    ) or usable_location_text(post.caption),
                }
                print(
                    f"[social] {post.truck_handle}: "
                    "using web_search caption as location"
                )
            else:
                print(
                    f"[social] {post.truck_handle}: skipped "
                    f"(confidence {extracted.get('confidence')})"
                )
                continue

        location_text = usable_location_text(
            extracted.get("location_text")
        )

        try:
            geocoded = (
                geocode(location_text)
                if location_text
                else None
            )
        except Exception:
            error_tracking.report(
                f"[social] geocode failed for {post.truck_handle}"
            )
            geocoded = None

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

            text_hint=f"{post.truck_handle} {post.caption}",

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


def job_public_listings():
    """
    DuckDuckGo + official sites + SactoMoFo calendar.
    This is the listing path that does not depend on Meta/X tokens.
    """

    from public_listings import collect_listings
    from geocoding import geocode

    hits = collect_listings()
    print(f"[listings] processing {len(hits)} hit(s)")

    for hit in hits:
        if hit.latitude is not None and hit.longitude is not None:
            latitude = hit.latitude
            longitude = hit.longitude
        else:
            address = hit.location_text
            if hit.truck_name and address.startswith(hit.truck_name):
                address = address[len(hit.truck_name):].strip(" ,")
            geocoded = geocode(address or hit.location_text)
            if not geocoded:
                print(
                    f"[listings] could not geocode {hit.location_text!r} "
                    f"for {hit.truck_name}"
                )
                continue
            latitude = geocoded["latitude"]
            longitude = geocoded["longitude"]

        detection = RawDetection(
            source="social",
            latitude=latitude,
            longitude=longitude,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            raw_confidence=0.7,
            text_hint=hit.location_text,
            note=hit.note or f"{hit.source}: {hit.location_text}",
        )
        _record_and_process(detection)


def job_prune_unmatched_detections():
    """
    Deletes expired UnmatchedDetection records from CloudKit.

    Previously nothing did this: expiresAt was written on every
    detection (see signal_fusion.py) and filtered out client-side on
    read, but the CloudKit table itself only ever grew, since nothing
    ever called delete. Every read (get_unmatched_detections, used on
    every /api/radar/scan) was paying to pull that ever-growing pile
    over the network before discarding almost all of it. Piggybacks on
    the same scheduler that already writes to this table every 5-30
    minutes.
    """

    deleted = cloudkit_bridge.prune_expired_unmatched_detections()

    print(
        f"[prune_unmatched_detections] deleted {deleted} "
        "expired record(s)"
    )


def run_all_once():
    """
    Runs every configured job once immediately.

    Useful for GitHub Actions and manual testing.
    Exits non-zero if any job raised, so a green Actions check
    actually means the pipeline finished without a crash.
    """

    print(
        "[cost] cameras="
        + ((os.getenv("RUN_CAMERA_VISION") or "off"))
        + " per_truck_web_search="
        + ((os.getenv("PER_TRUCK_WEB_SEARCH") or "off"))
        + " duckduckgo="
        + ("off" if (os.getenv("SKIP_DUCKDUCKGO") or "1") not in ("0", "false", "no") else "on")
        + " — default is one OpenRouter JSON listing call + free directory pins"
    )

    failed = []

    for name, fn in JOBS:

        print(
            f"--- running {name} ---"
        )

        try:
            fn()

        except Exception:

            error_tracking.report(
                f"[{name}] failed"
            )
            failed.append(name)

    if failed:
        print(
            "Pipeline finished with failed job(s): "
            + ", ".join(failed)
        )
        sys.exit(1)


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

    (
        "public_listings",
        job_public_listings,
    ),

    (
        "prune_unmatched_detections",
        job_prune_unmatched_detections,
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

        scheduler.add_job(
            job_public_listings,
            "interval",
            minutes=20,
            id="public_listings",
        )

        # expiresAt is set 3 hours out (signal_fusion.py) — pruning
        # hourly keeps the table from ever accumulating more than
        # ~1 batch cycle worth of dead records.
        scheduler.add_job(
            job_prune_unmatched_detections,
            "interval",
            hours=1,
            id="prune_unmatched_detections",
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
