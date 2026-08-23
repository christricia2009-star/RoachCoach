# Backend Update: Completing the Social/Signal Pipeline

## What was actually broken

`scheduler.py`'s social scraping job extracted a location as TEXT from
social captions, but never converted it to coordinates, never matched it
to a truck, and never wrote anything anywhere — it printed to a console
that nothing was watching. Same gap existed for camera/telecom/delivery
jobs: they detected things but never called the fusion+write step. This
is why nothing showed up in the app — it has nothing to do with the app
reaching `radar.snapcollectibles.com` directly (it never needs to; the app
reads from CloudKit).

## Files in this update

- **`geocoding.py`** (new) — converts extracted location text into real
  lat/lng using OpenStreetMap's free Nominatim service. Update
  `USER_AGENT` with your real contact info (Nominatim's policy asks for
  this) and `DEFAULT_CITY_CONTEXT` to your actual pilot area.
- **`signal_fusion.py`** (new — this existed in an earlier version of our
  conversation but never made it into your deployed copy) — matches
  detections to known trucks and decides auto-attach vs. human review.
- **`cloudkit_bridge.py`** (updated) — added `save_unmatched_detection()`
  and `resolve_unmatched_detection()`, needed by signal_fusion.py.
- **`scheduler.py`** (rewritten) — every job now actually calls through to
  signal_fusion and writes to CloudKit, instead of printing.

## What YOU still need to fill in before this does anything real

1. **`signal_fusion.py` → `KNOWN_TRUCK_NAMES`** — populate with your real
   truck names and their CloudKit truck IDs (`{"bao bao bus": "the-real-uuid"}`).
   Without this, social posts can never auto-match to a truck by name —
   they'll all land in the review queue instead, which is safe but means
   more manual confirming than necessary.

2. **`signal_fusion.py` → `DIRECT_ID_MAPPINGS`** — populate once you have
   real Uber/DoorDash merchant IDs or telecom sector IDs tied to specific
   trucks.

3. **CloudKit Dashboard: add the `UnmatchedDetection` record type** (it
   doesn't exist yet — CloudKit's development environment can usually
   infer a new record type from the first write, but if `save_unmatched_detection()`
   errors out, define it manually with these fields: `source` (String),
   `latitude` (Double), `longitude` (Double), `timestamp` (Date/Time),
   `rawConfidence` (Double), `reason` (String), `textHint` (String),
   `note` (String), `status` (String), `resolvedTruckId` (String, optional).

4. **`scraping/social_scraper.py`** — still needs real Instagram Tester
   access (free, your own account, see earlier setup notes) or the
   partnership feed, and real handles populated in `scheduler.py`'s
   `instagram_ids` / `x_usernames` lists (currently empty).

## Testing it

```
cd Backend
python3 scheduler.py --once
```

This runs every job once immediately and prints exactly what it's doing
at each step — geocoding results, fusion decisions, and any CloudKit
write errors. Fix errors in the order they appear; a CloudKit auth error
here means `cloudkit_bridge.py`'s env vars aren't set correctly, which is
worth confirming before worrying about anything else.

## What this means for `radar.snapcollectibles.com`

Nothing changes there — the FastAPI backend at that domain (`main.py`) can
keep running for whatever the website uses it for (health checks,
California camera lookups via `/phase3/california-cameras/near`, etc.).
The app was never going to call it directly, and doesn't need to now
either — the scheduler process above is a separate, independent job that
writes straight into CloudKit, which the app already reads from.
