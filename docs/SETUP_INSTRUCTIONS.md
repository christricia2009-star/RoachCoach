# Setup Instructions

## Part 1: Run the iOS App (Mock Data, No Backend Needed)

1. Open Xcode (requires a Mac — this cannot be built/tested on Windows or Linux).
2. File → New → Project → iOS → App.
3. Product Name: `RoachCoachRadar`. Interface: SwiftUI. Language: Swift.
4. In the new project, delete the auto-generated `ContentView.swift` and
   `RoachCoachRadarApp.swift` (you'll replace both).
5. Drag the folders `Models/`, `Views/`, `Services/`, and `Onboarding/`
   `RoachCoachRadarApp.swift` from this zip's `iOS/RoachCoachRadar/` folder
   into your Xcode project navigator. Check "Copy items if needed" and
   "Create groups."
6. Add required Info.plist permission strings (Xcode 15+: select your
   project → target → Info tab → add these rows):
   - `Privacy - Location When In Use Usage Description` →
     "We use your location to show nearby food trucks."
   - `Privacy - Photo Library Usage Description` →
     "Add a photo when reporting a food truck sighting."
7. Select an iPhone simulator and press Run (⌘R).

You should see a live map with 4 sample trucks and sightings, a working
"report a sighting" flow (writes to in-memory mock data), a favorites tab,
a predictions tab, and an owner dashboard tab — all functional against
mock data.

## What's New: Real Polish, Zero Backend Required

These all work today, out of the box, with no server:

- **Animated onboarding** on first launch (3-page intro, skippable by
  tapping through). Reset it anytime by deleting the app from the
  Simulator, or programmatically via `@AppStorage("hasCompletedOnboarding")`.
- **Real local push notifications** — favorite a truck and a genuine
  on-device notification fires ~4 seconds later simulating "this truck was
  just spotted." No APNs certs, no Apple Developer account, no server.
  Grant notification permission when prompted during onboarding.
- **Live distance + walking ETA** to each truck's most recent sighting,
  using your actual (or Simulator-simulated) device location. In the
  Simulator: Debug menu → Features → Location → pick a location to test.
- **Search + cuisine filter chips** on the map screen.
- **"Today's Top Picks" carousel** — horizontally scrollable spotlight of
  the highest-reliability trucks, tap to jump straight to their profile.
- **Animated, pulsing pins** for "Confirmed" sightings on the map.
- **Swift Charts reliability graph** on each truck's profile — a real bar
  chart of sighting activity over the last 14 days (backed by expanded
  mock historical data).
- **Haptic feedback** on favoriting a truck and submitting a sighting.

## Part 1.5: What Actually Needs to Happen for Backend/ to Do Anything

Nothing in `Backend/` runs on its own — it's all functions waiting to be
called from somewhere. Here's the honest checklist, in order:

1. **Decide where it runs.** Since you're using CloudKit (not Postgres)
   for the app's core data, you don't need a hosted server the iOS app
   talks to directly — you need a machine that's usually ON to run
   scheduled Python jobs. Simplest real options, cheapest first:
   - Your own always-on computer or a Raspberry Pi at home
   - A $5-6/month VPS (DigitalOcean, Linode, Fly.io)
   - A scheduled cloud function (AWS Lambda + EventBridge) if you want
     zero always-on hardware — more setup, less to maintain long-term

2. **Install dependencies** (same as before):
   ```
   cd Backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Fill in `.env`** — copy `.env.example` to `.env`. At minimum for the
   CloudKit path: `CLOUDKIT_CONTAINER_ID`, `CLOUDKIT_KEY_ID`,
   `CLOUDKIT_PRIVATE_KEY_PATH` (see `cloudkit_bridge.py` docstring for the
   one-time CloudKit Dashboard setup — generating a server-to-server key).
   Add whichever Phase 3 / LLM provider keys you actually have.

4. **The missing link, now built:** `cloudkit_bridge.py` implements
   Apple's CloudKit Web Services signing scheme so Python can write into
   the same CloudKit database your iOS app already reads from. This is
   the piece that didn't exist before — without it, Phase 3 modules ran
   and returned data that went nowhere.

   Honest caveat: I implemented this from Apple's published spec but
   haven't been able to test it against a live container from this
   environment — your first real call is the actual test. If it fails
   with a signature/auth error, check the response body Caltrans/CloudKit
   sends back; it's usually specific about which check failed.

5. **Run it.** `Backend/scheduler.py` ties the Phase 3 sources together
   on a schedule:
   ```
   python3 scheduler.py --once     # test every job once, see console output
   python3 scheduler.py            # run continuously on the built-in schedule
   ```
   For it to survive reboots/terminal closing on a VPS: run it via
   `systemd` (Linux) or `launchd` (Mac), or the simple version:
   `nohup python3 scheduler.py > scheduler.log 2>&1 &`

6. **One real design decision still open:** the scheduler jobs currently
   just print detections to the console — they don't yet decide how a
   camera detection, a telecom anomaly, or a delivery pickup pin maps onto
   a specific existing `Truck` record (vs. creating a vague, unattributed
   "something's happening here" pin). That's a product decision, not a
   technical gap: do you want unmatched detections to create a review
   queue for a human to confirm which truck it is, or auto-attach to the
   nearest known truck by location? I left this as a clearly marked TODO
   in `scheduler.py` rather than guessing — tell me which you want and
   I'll wire it in.

## Part 2 (Alternative): CloudKit Instead of Postgres (Recommended for a Family/Friends App)

Since this is staying in TestFlight for family/friends, CloudKit is a much
lighter starting point than hosting Postgres — free, no server, and
everyone signed into iCloud shares the same data automatically.

1. In Xcode: select your app target → Signing & Capabilities → "+
   Capability" → add "iCloud" → check "CloudKit".
2. Xcode creates a default container automatically
   (`iCloud.com.yourbundleid.RoachCoachRadar`).
3. In `RootTabView.swift` (and anywhere else referencing
   `MockAPIService.shared`), swap to `CloudKitService.shared` — it
   implements the same `APIServicing` protocol, so nothing else changes.
4. Run the app once — CloudKit's development environment can infer the
   "Truck" and "Sighting" record schema from your first saved records, or
   you can define them upfront at icloud.developer.apple.com.
5. Everyone in the family/friends group needs to be signed into iCloud on
   their device — CloudKit's public database is what makes the sightings
   actually shared across everyone using the app.

Trade-offs vs. Postgres: no PostGIS-grade geospatial queries (fine at this
scale), and the confidence-scoring logic runs client-side instead of
server-side (fine for a small trusted group; revisit if this ever opens up
publicly, since client-side logic is easier to spoof). Full details and
code are in `iOS/RoachCoachRadar/CloudKit/CloudKitService.swift`.

## Part 2 (Original): Full Postgres + FastAPI Backend (For Later, If You Outgrow CloudKit)

1. **Provision a Postgres database.** Easiest options: Railway, Render,
   Supabase, or AWS RDS. Enable the PostGIS extension if your provider
   supports it (`CREATE EXTENSION IF NOT EXISTS postgis;`).
2. Run `Backend/schema.sql` against that database to create the tables.
3. Copy `Backend/.env.example` to `Backend/.env` and fill in:
   - `DATABASE_URL` — connection string from your provider
   - `ANTHROPIC_API_KEY` — from console.anthropic.com, needed for caption parsing
4. In a terminal:
   ```
   cd Backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```
5. Confirm it's running: open `http://localhost:8000/health` — should
   return `{"status": "ok"}`.
6. Deploy it somewhere reachable from the internet (Railway, Render,
   Fly.io, or a VPS) so your iOS app can reach it from a real device.
7. In the iOS project, open `Services/APIService.swift`, replace the
   `baseURL` in `LiveAPIService` with your deployed backend's URL.
8. In `RootTabView.swift` and other views, swap `MockAPIService.shared`
   references to `LiveAPIService.shared`.

## Part 3: Social Scraping (Real Integration Code, Needs Your Credentials)

`Backend/scraping/social_scraper.py` has real, functional request code for
Instagram and X, plus a generic slot for any direct partnership feed.

- **Instagram Graph API — testing on your own account is free, today, no
  App Review**: in your Meta app dashboard, add your own Instagram account
  in the "Instagram Tester" role while the app is in development mode.
  This is a *Meta* requirement — it applies the same whether you ever
  submit to the App Store or stay in TestFlight forever, since it's Meta's
  API, not Apple's. Fetching from OTHER people's accounts (i.e. other
  family members' truck-following accounts, if you expand later) requires
  Advanced Access: Meta App Review + Business Verification, typically 2-6
  weeks — not needed yet for a family app testing on your own account.
- **X (Twitter) API**: no free tier as of Feb 2026 — pay-per-use
  ($0.005/read, $0.015/post created, no monthly minimum). This is billed
  through your own X developer account at developer.x.com — note that a
  SuperGrok or X Premium+ subscription does NOT include this; it's a
  completely separate product with its own billing.
- **Partnership feed**: `fetch_partnership_feed()` is a generic
  placeholder shape — once your partner sends real API docs, adjust the
  endpoint path and response parsing to match theirs.

Do NOT scrape social platforms outside their official APIs/partnership
terms — this can violate ToS and, depending on jurisdiction, laws like the
CFAA.

Once real posts are flowing in, they pipe into
`Backend/scraping/llm_extract.py`, which parses captions into structured
location/time data via whichever LLM provider(s) you've configured (see
Part 3.5 below).

## Part 3.5: LLM Providers — Single, Round-Robin, or Fallback

`Backend/scraping/llm_providers.py` supports three strategies, set via
`.env`:

```
LLM_STRATEGY=single        # or: round_robin, fallback
LLM_PROVIDER=anthropic     # used only in "single" mode
LLM_MODEL=                 # leave blank for a cheap default per provider
ANTHROPIC_API_KEY=...
XAI_API_KEY=...
OPENROUTER_API_KEY=...
```

- **`single`** — always uses one provider. Simplest.
- **`round_robin`** — cycles through every provider that has a key set in
  `.env`, spreading calls across them. Useful for staying under each
  provider's free/cheap-tier rate limits when you have keys for more than
  one at once.
- **`fallback`** — tries providers in priority order (Anthropic → Grok →
  OpenRouter), moving to the next only if the current one errors or
  rate-limits. Good for resilience without needing to think about which
  provider is "active."

You only need ONE provider's key set for the app to work at all — add
more as you get them, and the strategy you pick decides how they're used
together. Notes on cost:
- **SuperGrok Plus does NOT include xAI API credits** — the API is billed
  separately per token via console.x.ai, regardless of any consumer Grok
  subscription you have.
- **OpenRouter** has genuinely free, rate-limited models (~20
  requests/min, 200/day) — good to combine with `round_robin` mode for
  zero-cost testing before committing real spend. Check
  openrouter.ai/models filtered by "free" for current options.
- Grok's cheapest paid tier as of writing is Grok 4.1 Fast (~$0.20/$0.50
  per million input/output tokens). Verify current pricing before relying
  on it long-term — these change often.

## Part 3.75: Phase 3 — Full Current Status

See `ARCHITECTURE.md` for the complete breakdown. Summary:

- **California traffic cameras** — ✅ live and real, no partnership needed.
  Backed by Caltrans' official public CWWP2 feed (all 12 districts,
  ~3,000+ cameras statewide, verified directly from their docs). New
  endpoint: `GET /cameras/near?latitude=X&longitude=Y`.
  Respects Caltrans' own conditions of use — capped at 9 concurrent camera
  checks unless you have a written bulk-streaming agreement with them
  specifically (separate from any other agreements you have).
- **Municipal open data** — ✅ real code, needs your city's dataset URL.
- **Telecom signal data** — ✅ real code, scoped to your carrier agreement's
  sector IDs.
- **Delivery pickup pins (Uber/DoorDash)** — ✅ real code, scoped to your
  partnership's merchant/store IDs. Confirm actual endpoint paths against
  your partnership docs — the code uses standard partner-API patterns as
  a starting shape.
- **Wi-Fi detection** — ⚠️ built and consent-gated
  (`WiFiConsentView.swift` → Owner Dashboard → Detection Settings), but
  scoped smaller than the original idea: iOS only allows checking the
  currently-connected network's SSID, not scanning nearby unconnected
  networks. Consent handles the privacy side; this technical limit is
  separate and unrelated to consent.

## Part 4: Push Notifications (Optional, Requires Apple Developer Account)

1. Enroll in the Apple Developer Program ($99/year) if you haven't.
2. In Xcode, enable the "Push Notifications" capability on your app target.
3. Generate an APNs authentication key in the Apple Developer portal.
4. Add server-side logic (not included in this zip) to send push payloads
   via APNs when a followed truck gets a new "confirmed" sighting — this
   requires an APNs client library on the backend (e.g. `aioapns` for Python).

## Part 5: Customer Support (Operational, Not Code)

There's no code component to this — it's a process:
- Start with a shared inbox (e.g. a Google Group or Help Scout) and an FAQ
  page for common questions (how sightings work, how to claim a truck, etc.).
- Add an in-app "Report a problem" button (simple mailto: link or a form
  POST to a `/support` endpoint) once you have real users.
- Only hire dedicated support staff once volume justifies it — most early
  apps handle this with founder time for the first several months.

## Part 6: Phase 3 (Advanced Signal Fusion)

Not code-scaffolded because there's nothing to build without real data
partnerships in place first. See `ARCHITECTURE.md` for what each
idea would require and how it would plug into the existing architecture
once/if you pursue those deals.
