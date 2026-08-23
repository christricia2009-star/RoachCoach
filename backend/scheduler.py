"""
Scheduled job runner — the piece that actually needs to run continuously
SOMEWHERE (your own always-on machine, a Raspberry Pi, a cheap VPS, or a
scheduled cloud function). Nothing in Backend/ runs itself; this file is
what you'd point a process manager or cron at.

For a family/friends pilot, the simplest real option is: run this on any
computer that's usually on (your own machine, a Mac mini, a Raspberry Pi)
via `python3 scheduler.py`, and leave it running. It polls each configured
signal source on its own interval and pushes results into CloudKit via
cloudkit_bridge.py.

If you outgrow "a machine that's usually on," the same script runs
unchanged on a $5-6/month VPS (DigitalOcean, Linode, Fly.io) — just
`nohup python3 scheduler.py &` or set it up as a systemd service so it
survives reboots.
"""

import os
import sys
import time
import uuid
import datetime
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "scraping"))
sys.path.append(os.path.join(os.path.dirname(__file__), "collectors"))

from apscheduler.schedulers.blocking import BlockingScheduler

import cloudkit_bridge

# Each entry: (job name, function to call, interval in minutes)
# Populated conservatively — uncomment/add sources as you actually have
# real credentials and IDs filled in for them (see .env.example).

def job_california_cameras():
    """Checks Caltrans cameras near a configured point of interest for
    likely truck activity, writes low-confidence hint sightings to CloudKit."""
    from traffic_camera_vision import scan_california_area

    # Set these to wherever your family's testing area actually is.
    latitude = float(os.getenv("HOME_BASE_LATITUDE", "38.5816"))   # Sacramento default
    longitude = float(os.getenv("HOME_BASE_LONGITUDE", "-121.4944"))

    results = scan_california_area(latitude, longitude, radius_miles=5.0)
    for r in results:
        if r.get("likely_food_truck_present") and r.get("confidence") != "low":
            print(f"[california_cameras] possible truck at {r.get('location_name')}")
            # NOTE: this writes a generic "possible activity" hint, not tied
            # to a specific Truck record — decide how you want unmatched
            # camera detections to surface in the app (e.g. a review queue)
            # before wiring this straight into the Sighting table for real.


def job_telecom_signals():
    from telecom_signal_data import fetch_sector_anomalies, to_scheduled_post_candidates

    try:
        anomalies = fetch_sector_anomalies()
        candidates = to_scheduled_post_candidates(anomalies)
        for c in candidates:
            print(f"[telecom] anomaly hint at {c['extracted_latitude']},{c['extracted_longitude']}")
    except RuntimeError as e:
        print(f"[telecom] skipped — {e}")


def job_delivery_pickup_pins():
    from delivery_pickup_pins import fetch_all_pickup_pins

    pins = fetch_all_pickup_pins()
    for pin in pins:
        print(f"[delivery] {pin.platform} pin for {pin.merchant_name} at {pin.latitude},{pin.longitude}")
        # Same note as above — decide how a pickup pin maps to an existing
        # Truck record (by name match? a manual mapping table?) before
        # writing straight into Sighting.


def job_social_scraping():
    from social_scraper import fetch_all_known_trucks
    from llm_extract import extract_location_from_caption

    # Populate with real handles once you have Instagram Tester access set
    # up for the trucks in your pilot.
    instagram_ids: list[str] = []
    x_usernames: list[str] = []

    posts = fetch_all_known_trucks(instagram_ids=instagram_ids, x_usernames=x_usernames)
    for post in posts:
        extracted = extract_location_from_caption(post.caption)
        if extracted.get("confidence") in ("high", "medium"):
            print(f"[social] {post.truck_handle}: {extracted}")
            # Same integration note — map the extracted location text to
            # actual lat/lng (e.g. via a geocoding call) before writing a
            # real Sighting record.


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
