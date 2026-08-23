# Getting the Signal Pipeline Running via GitHub Actions

## Why this approach, not Vercel

Two real facts pushed this decision, not preference:

1. **Vercel's free/Hobby plan only allows cron jobs once per day.** This
   pipeline needs to run every 5-30 minutes to be useful (checking social
   posts, cameras, telecom signals). Once-daily isn't close to enough.
   Per-minute scheduling exists on Vercel, but only on the paid Pro plan
   ($20/mo).
2. **Vercel Python functions don't keep a process alive.** A function runs
   once per request and shuts down — there's no way to run `scheduler.py`'s
   continuous mode there regardless of plan.

GitHub Actions' scheduled workflows are free (within GitHub's generous
free-tier minutes for a personal repo), run independently of Vercel
entirely, and aren't capped to once-daily. Vercel keeps deploying
`Backend/main.py` (the site/API) exactly as it does now, from the same
repo, completely unaffected by any of this.

## Step 1: Add the files to your repo

Copy these into your existing repo (same paths):
- `.github/workflows/scheduler.yml`
- Everything from the earlier Backend update (`geocoding.py`,
  `signal_fusion.py`, updated `cloudkit_bridge.py`, updated `scheduler.py`)
  if you haven't already merged those in.

```
git add .github/workflows/scheduler.yml Backend/
git commit -m "Add scheduled signal pipeline via GitHub Actions"
git push
```

Pushing to your main branch will NOT trigger a Vercel redeploy issue —
Vercel only cares about the files it actually builds from (your site/API
code); adding a `.github/workflows/` folder doesn't change what Vercel
deploys.

## Step 2: Add secrets to your GitHub repo

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these (only add the ones you actually have values for — the
workflow handles missing ones gracefully via the same runtime checks
already in the Python code):

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `XAI_API_KEY` | your xAI key (if using Grok) |
| `OPENROUTER_API_KEY` | your OpenRouter key (if using it) |
| `LLM_STRATEGY` | `single`, `round_robin`, or `fallback` |
| `LLM_PROVIDER` | `anthropic`, `grok`, or `openrouter` |
| `CLOUDKIT_CONTAINER_ID` | e.g. `iCloud.com.yourbundleid.RoachCoachRadar` |
| `CLOUDKIT_KEY_ID` | from CloudKit Dashboard's server-to-server key |
| `CLOUDKIT_PRIVATE_KEY_B64` | see Step 3 below — NOT the raw .pem content |
| `CLOUDKIT_ENVIRONMENT` | `development` or `production` |
| `HOME_BASE_LATITUDE` / `HOME_BASE_LONGITUDE` | your pilot area's coordinates |
| `TELECOM_API_KEY` / `TELECOM_API_BASE_URL` | if your carrier partnership is ready |
| `UBER_PARTNER_CLIENT_ID` / `_CLIENT_SECRET` / `_API_BASE_URL` | if ready |
| `DOORDASH_PARTNER_API_KEY` / `_API_BASE_URL` | if ready |
| `INSTAGRAM_ACCESS_TOKEN` | from your Instagram Tester setup |
| `X_API_BEARER_TOKEN` | if you're paying for X API access |

## Step 3: Base64-encode your CloudKit private key

GitHub Secrets are single-line text fields, and your CloudKit private key
is a multi-line `.pem` file — encode it first:

```
base64 -i /path/to/your/cloudkit_private_key.pem | tr -d '\n'
```

Copy that entire output as the value of the `CLOUDKIT_PRIVATE_KEY_B64`
secret. The workflow decodes it back into a real file at
`/tmp/cloudkit_key.pem` on every run (see the "Reconstruct CloudKit
private key" step in `scheduler.yml`) — never commit the actual `.pem`
file to the repo itself.

## Step 4: Test it manually before trusting the schedule

GitHub repo → **Actions tab → "Roach Coach Radar - Signal Pipeline"
workflow → Run workflow** (this works because of the `workflow_dispatch`
trigger in the YAML). Watch the log output — it'll show exactly what
`scheduler.py --once` printed, including any geocoding results, fusion
decisions, or CloudKit write errors, in the order they happened.

## Step 5: Let the schedule take over

Once a manual run succeeds, the `cron: "*/15 * * * *"` schedule runs it
automatically every 15 minutes from then on — no further action needed.
Adjust the interval in `scheduler.yml` if you want it more/less frequent
(GitHub's practical floor is around 5 minutes; don't go below that).

## What this does NOT change

Your Vercel deployment of `Backend/main.py` — the FastAPI site/API at
`radar.snapcollectibles.com` — keeps working exactly as it did before.
This workflow is a completely separate, independent process that happens
to live in the same repo and write into the same CloudKit database the
app already reads from.
