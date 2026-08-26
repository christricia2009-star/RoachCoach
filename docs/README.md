# Roach Coach Radar

Centralized, check-in-free food truck location tracking. Crowdsourcing +
social scraping instead of requiring trucks to manually check in.

## What's Actually in This Zip

**Fully working, runs today:**
- `iOS/` — Complete SwiftUI app. Runs immediately in the iOS Simulator with
  mock data. No backend, API keys, or accounts needed to try it.

**Code-complete, but requires setup to actually run:**
- `Backend/main.py` — FastAPI server. Needs a real PostgreSQL database to
  connect to (see SETUP_INSTRUCTIONS.md).
- `Backend/scraping/llm_extract.py` — Fully functional Claude API caption
  parser. Needs your own `ANTHROPIC_API_KEY`.

**Stubbed — shows the intended shape, not functional without external access:**
- `Backend/scraping/social_scraper.py` — needs real Instagram/X API
  credentials or a data partnership. Scraping outside official APIs can
  violate platform terms of service — don't do that.
- iOS `` folder — truck owner dashboard, reputation scoring,
  predictive scheduling. UI and logic scaffolds only; not wired to a live
  backend yet.

**Documentation only, no code:**
- `ARCHITECTURE.md` — the "advanced signal fusion" ideas (POS
  pickup-pin data, smart-parking sensors, computer vision on traffic cams,
  Wi-Fi SSID detection). These require business partnerships and real data
  access agreements that don't exist yet — there's nothing to scaffold in
  code until those deals are in place.

## Quick Start (Try the App Right Now)

1. Open Xcode → File → New → Project → iOS → App
2. Name it "RoachCoachRadar", interface: SwiftUI, language: Swift
3. Delete the default `ContentView.swift` Xcode generates
4. Drag the entire contents of the `iOS/RoachCoachRadar/` folder from
   this zip into your new project (check "Copy items if needed")
5. Add these two capabilities/permissions (see SETUP_INSTRUCTIONS.md for
   exact steps):
   - Location permission (Info.plist)
   - Photo library permission (Info.plist)
6. Build and run in the Simulator — you'll see the map with sample truck
   sightings immediately.

## Full Backend Setup

See `SETUP_INSTRUCTIONS.md` for step-by-step instructions to actually
deploy the backend, connect a database, and wire the iOS app to it instead
of the mock data.

## Cost Reality Check

This zip gets you a working prototype for free (just your time). Turning
this into a real multi-city product with a live backend, real scraping, and
support staff costs real money — see the cost breakdown in the original
project spec. Nothing in this zip requires spending money until you choose
to deploy the backend and buy API credits.

## OVER-THE-TOP RADAR PACK — August 2026

The current iOS folder now includes:
- Live CloudKit as the default data source instead of mock data.
- Radar Command Center with animated sweep, GPS lock, active/confirmed/hotspot/confidence metrics.
- Automatic hotspot clustering from active sightings.
- Nearest-contact ranking and distance awareness.
- Radar Command detail screen with threat/confidence gauge.
- Persistent Watchlist using UserDefaults, with swipe-to-unfollow.
- Live CloudKit Sighting query subscription for visual push alerts when sightings are created/updated.
- Pull-to-refresh plus parallel truck/sighting loading.
- More aggressive search across truck name and cuisine.
- Location recenter button and live timestamp.
- Fresh-report notification after submitting a sighting.

### Xcode capabilities/permissions
Keep the existing CloudKit + Location + Photos configuration. The CloudKit capability supplies the push entitlement used by CloudKit subscriptions. Notification permission is requested by onboarding. Maps itself does not require a separate capability.

### CloudKit schema
No additional record types are required for this feature pack. It uses the deployed `Truck` and `Sighting` types and existing fields. The subscription is created programmatically in the development/public database at app launch.

## Phase 4 — Over-the-Top Intelligence

Added: prediction engine, scout XP/reputation, geofenced watch zones, local photo triage, radar intelligence UI, heatmap summaries, and optional CloudKit photo/reputation/prediction schema extensions.
