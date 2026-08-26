# Phase 3: Advanced Signal Fusion — Current Status

Updated status: TestFlight-only (never submitting to the App Store)
removes **Apple's** review requirements, but not **Meta's**, **X's**,
Caltrans', carriers', or delivery platforms' own rules — those are
separate parties with their own terms regardless of how you distribute
your app. Each item below is now marked with its real status.

## 1. California Traffic Camera Vision — ✅ Buildable, no partnership needed
`Backend/collectors/traffic_camera_vision.py` +
`Backend/collectors/california_camera_directory.py`

Real, confirmed integration with Caltrans' official CWWP2 public data feed
— statewide, all 12 districts, ~3,000+ cameras, explicitly published by
Caltrans for third-party use at no charge. No API key needed. Verified
endpoints and field schema directly from Caltrans' own documentation
(cwwp2.dot.ca.gov), current as of August 2026.

**Conditions of Use that matter here:** Caltrans images aren't archived —
don't expect historical lookback. More importantly: *"Bulk streaming
(viewing 10 or more streams simultaneously) is permitted only with a
written agreement with Caltrans Traffic Operations."* The code defaults
`MAX_CONCURRENT_CHECKS = 9` to stay under that threshold. If you get (or
already have) a written bulk-streaming agreement with Caltrans
specifically, raise it — don't raise it without one.

`scan_california_area(lat, lng, radius_miles)` finds nearby in-service
cameras and runs Claude vision detection on each. A new FastAPI endpoint,
`GET /cameras/near`, exposes the camera list (without
running detection, to avoid unnecessary LLM spend) for the app to query
directly.

## 2. Municipal Open Data — ✅ Buildable, no partnership needed
`Backend/collectors/municipal_open_data.py` — unchanged from before. Adjust
field mappings to your specific city's dataset schema.

## 3. Telecom Cell-Tower Load Data — ✅ Buildable, per your carrier agreement
`Backend/collectors/telecom_signal_data.py`. Scoped to `AGREED_SECTOR_IDS` —
populate with the real sector/tower IDs your agreement covers. Treats
output as a low-confidence hint requiring crowdsource/social confirmation,
never a standalone "confirmed" signal.

## 4. Delivery-App Pickup-Pin Data — ✅ Buildable, per your Uber/DoorDash agreements
`Backend/collectors/delivery_pickup_pins.py`. Scoped to
`AGREED_UBER_MERCHANT_IDS` / `AGREED_DOORDASH_STORE_IDS` — populate with
the real merchant/store IDs your written agreements actually cover. The
OAuth2/token flow shown for Uber and the bearer-auth pattern for DoorDash
are the standard shapes for partner APIs — confirm the actual endpoint
paths and field names against the docs your partnership contacts gave
you, since these are illustrative, not pre-confirmed against a live
account.

## 5. Wi-Fi-Based Truck Detection — ⚠️ Consent solves one problem, not the other
`iOS/RoachCoachRadar/Services/WiFiDetectionService.swift` +
`iOS/RoachCoachRadar/Onboarding/WiFiConsentView.swift`

Your note that this is fine "as long as notice is made and accepted"
resolves the **privacy/consent** side. But there's a separate, unrelated
**technical** restriction that consent doesn't touch: iOS does not give
ordinary apps an API to scan for nearby Wi-Fi networks a device hasn't
joined (no equivalent to Android's network scan results). The only thing
buildable without a rare, narrowly-granted Apple entitlement
(NEHotspotHelper — historically reserved for carrier/enterprise cases) is
checking the SSID of whatever network the device is **already connected
to**. That's implemented and consent-gated in the files above — but it
means this feature only fires after someone manually joins a specific
truck's Wi-Fi network themselves, not automatic proximity detection.
Size expectations for this one accordingly — it's a real, working, useful
feature at a smaller scope than the original "detect a truck's SSID as
you walk past" idea.

## How All Sources Plug Into the Existing Data Model

All five feed into the same `sightings` / `scheduled_posts` tables, tagged
with a `source` value (`'traffic_cam'`, `'municipal_open_data'`,
`'telecom_signal'`, `'delivery_pickup'`, `'wifi_detected'`) so the
confidence-scoring logic doesn't need rewriting — just weighted per-source
once you have real accuracy data to tune against.
