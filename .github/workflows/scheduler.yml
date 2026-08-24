"""
Scheduled job runner — the piece that actually needs to run continuously
SOMEWHERE (your own always-on machine, a Raspberry Pi, a cheap VPS, or a
scheduled cloud function). Nothing in Backend/ runs itself; this file is
what you'd point a process manager or cron at.

UPDATED: every job now runs its output through signal_fusion.py and
actually writes to CloudKit — previously, jobs (especially social
scraping) extracted data and just printed it, so nothing ever reached the
app. That's fixed here: extract -> geocode (social only) -> fuse -> write.

For a family/friends pilot, the simplest real option is: run this on any
computer that's usually on (your own machine, a Mac mini, a Raspberry Pi)
via `python3 scheduler.py`, and leave it running.

If you outgrow "a machine that's usually on," the same script runs
unchanged on a $5-6/month VPS (DigitalOcean, Linode, Fly.io) — just
`nohup python3 scheduler.py &` or set it up as a systemd service so it
survives reboots.
"""

import os
import sys
import time
import datetime
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "scraping"))
sys.path.append(os.path.join(os.path.dirname(__file__), "phase3"))

from apscheduler.schedulers.blocking import BlockingScheduler

import signal_fusion
from signal_fusion import RawDetection

# In-memory pool of recent detections across ALL sources, used for
# corroboration in signal_fusion.py (e.g. a telecom anomaly + a social post
# near the same place/time reinforce each other). A single long-running
# process is enough for this at family-pilot scale — no separate database
# needed for it. Pruned by age on every job run.
RECENT_DETECTIONS: list[RawDetection] = []
CORROBORATION_RETENTION_MINUTES = 60


def _prune_and_get_recent() -> list[RawDetection]:
    global RECENT_DETECTIONS
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=CORROBORATION_RETENTION_MINUTES)
    RECENT_DETECTIONS = [d for d in RECENT_DETECTIONS if d.timestamp >= cutoff]
    return RECENT_DETECTIONS


def _record_and_process(detection: RawDetection):
    """Adds a detection to the shared pool, then runs fusion + CloudKit write."""
    recent = _prune_and_get_recent()
    signal_fusion.process_detection(detection, recent)
    RECENT_DETECTIONS.append(detection)


def job_california_cameras():
    """Checks Caltrans cameras near a configured point of interest for
    likely truck activity."""
    from traffic_camera_vision import scan_california_area

    latitude = float(os.getenv("HOME_BASE_LATITUDE", "38.5816"))   # Sacramento default
    longitude = float(os.getenv("HOME_BASE_LONGITUDE", "-121.4944"))

    results = scan_california_area(latitude, longitude, radius_miles=5.0)
    for r in results:
        if not r.get("likely_food_truck_present"):
            continue
        confidence_map = {"high": 0.7, "medium": 0.45, "low": 0.2}
        detection = RawDetection(
            source="traffic_cam",
            latitude=r.get("latitude", latitude),
            longitude=r.get("longitude", longitude),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            raw_confidence=confidence_map.get(r.get("confidence", "low"), 0.2),
            note=f"Camera at {r.get('location_name', 'unknown location')}: {r.get('reasoning', '')}",
        )
        _record_and_process(detection)


def job_telecom_signals():
    from telecom_signal_data import fetch_sector_anomalies

    try:
        anomalies = fetch_sector_anomalies()
    except RuntimeError as e:
        print(f"[telecom] skipped — {e}")
        return

    for a in anomalies:
        detection = RawDetection(
            source="telecom_signal",
            latitude=a.latitude,
            longitude=a.longitude,
            timestamp=a.detected_at.replace(tzinfo=datetime.timezone.utc) if a.detected_at.tzinfo is None else a.detected_at,
            raw_confidence=min(0.5, a.anomaly_score * 0.3),  # telecom alone stays capped low — needs corroboration
            source_id=f"telecom:{a.sector_id}",
            note=f"Sector {a.sector_id} load anomaly (score {a.anomaly_score:.2f})",
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
            timestamp=pin.reported_at.replace(tzinfo=datetime.timezone.utc) if pin.reported_at.tzinfo is None else pin.reported_at,
            raw_confidence=0.6,
            source_id=f"{pin.platform}:{pin.merchant_id}",
            text_hint=pin.merchant_name,
            note=f"{pin.platform} pickup pin for {pin.merchant_name}",
        )
        _record_and_process(detection)


def job_social_scraping():
    """
    Full pipeline, now actually complete: fetch posts -> LLM-extract
    location/time -> geocode the location text into real coordinates ->
    fuse (name-match against known trucks + corroboration) -> write to
    CloudKit (auto-attached Sighting or a review-queue UnmatchedDetection).
    """
    from social_scraper import fetch_all_known_trucks
    from llm_extract import extract_location_from_caption
    from geocoding import geocode

    # Populated from web searches of real Sacramento & Plumas Lake-vicinity
    # trucks (Aug 2026). VERIFY these are still active before relying on
    # them — business listings go stale fast, which is the whole reason
    # this app exists. Only CONFIRMED handles (found directly on Instagram
    # with follower counts/bio, not guessed from a business name) are
    # listed here — see UNVERIFIED_LEADS below for names found via
    # Yelp/directories with no confirmed handle yet.
    instagram_business_discovery_usernames: list[str] = [
        "drewskis",                 # Drewski's Hot Rod Kitchen — Sacramento
        "thebuckhornbbqtruck",      # Buckhorn BBQ Truck — Sacramento
        "sactomofo",                # SactoMoFo — event organizer/aggregator, posts about many trucks
        "krushroseville",           # Krush Burger — Roseville; original Sac location shows closed on Yelp
        "the_potato_truck",         # Potato Patoto — Yuba City, near Plumas Lake
        "alamedatacossac",          # Alameda Tacos Food Truck — Sacramento
        "muchonachossacramento",    # Mucho Nachos & Tacos — Sacramento
        "sactopopuptruck",         # The Pop Up Truck (grilled cheese) — Sacramento
        "santacosmx",               # SanTacos — Sacramento
        "tacoasac",                 # Tacoa Sacramento (Tacos & Tequila)
        "tacos_gto_",               # Tacos GTO — Sacramento
        "tacomiendofoodtruck",      # Tacomiendo — Sacramento
        "sactacosfoodtruck",        # Sac Tacos Foodtruck — Sacramento
        "thelumpiatruck",           # The Lumpia Truck (Filipino) — Sacramento
    ]

    # UNVERIFIED_LEADS — real business names found via Yelp/directory
    # listings, but I could not confirm an exact Instagram handle for these
    # (guessing risks silently pulling data from the wrong account). Look
    # these up manually and add to the list above once confirmed:
    #   iLava Hawaiian Barbecue, Cichy Co., Locos Only, She Got Rolls,
    #   Yummi BBQ, JoJo's Hawaiian Fried Chicken, Tasty Hawaiian BBQ,
    #   Kado's Asian Grill, Local Kine Shave Ice, Shaka Grindz,
    #   Island Fin Poke, Hele On To Hawaii, Sim's Bar-B-Que, Allen BBQ,
    #   Taqueria Hernandez (Plumas Lake specifically)

    instagram_ids: list[str] = []  # only for accounts YOU manage as a Tester — see social_scraper.py
    x_usernames: list[str] = []

    # Facebook Page posts — requires EITHER a Page Access Token for a page
    # you actually manage/admin, OR Meta App Review + Business
    # Verification for Page Public Content Access (reading pages you don't
    # manage). Your personal account following these trucks does not
    # unlock this — see social_scraper.py's docstring. Empty until one of
    # those is actually true; add page IDs/usernames once it is.
    facebook_page_ids: list[str] = []

    posts = fetch_all_known_trucks(
        instagram_ids=instagram_ids,
        x_usernames=x_usernames,
        instagram_business_discovery_usernames=instagram_business_discovery_usernames,
        facebook_page_ids=facebook_page_ids,
    )
    for post in posts:
        extracted = extract_location_from_caption(post.caption)
        if extracted.get("confidence") not in ("high", "medium"):
            continue

        location_text = extracted.get("location_text")
        geocoded = geocode(location_text) if location_text else None
        if not geocoded:
            print(f"[social] could not geocode '{location_text}' for {post.truck_handle} — skipping")
            continue

        confidence_map = {"high": 0.65, "medium": 0.4}
        detection = RawDetection(
            source="social",
            latitude=geocoded["latitude"],
            longitude=geocoded["longitude"],
            timestamp=post.posted_at.replace(tzinfo=datetime.timezone.utc) if post.posted_at.tzinfo is None else post.posted_at,
            raw_confidence=confidence_map.get(extracted["confidence"], 0.4),
            text_hint=post.caption,  # signal_fusion name-matches against KNOWN_TRUCK_NAMES using this
            note=f"Posted: \"{post.caption[:100]}\" -> {geocoded['display_name']}",
        )
        _record_and_process(detection)


def run_all_once():
    """Runs every configured job once immediately — useful for testing
    each pipeline manually before trusting the schedule."""
    for name, fn in JOBS:
        print(f"--- running {name} ---")
        try:
            fn()
        except Exception:
            print(f"[{name}] failed:")
            traceback.print_exc()


JOBS = [
    ("california_cameras", job_california_cameras),
    ("telecom_signals", job_telecom_signals),
    ("delivery_pickup_pins", job_delivery_pickup_pins),
    ("social_scraping", job_social_scraping),
]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_all_once()
    else:
        scheduler = BlockingScheduler()
        scheduler.add_job(job_california_cameras, "interval", minutes=10, id="california_cameras")
        scheduler.add_job(job_telecom_signals, "interval", minutes=5, id="telecom_signals")
        scheduler.add_job(job_delivery_pickup_pins, "interval", minutes=5, id="delivery_pickup_pins")
        scheduler.add_job(job_social_scraping, "interval", minutes=30, id="social_scraping")
        print("Scheduler started. Press Ctrl+C to stop. Run with --once to test all jobs immediately instead.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass
