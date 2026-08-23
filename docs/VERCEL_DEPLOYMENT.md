# Roach Coach Radar — New GitHub + Vercel Deployment

## What you are creating

One new GitHub repository and one new Vercel project:

```text
GitHub repository
      ↓ automatic deployment
Vercel
 ├── website: /
 └── Radar API: /api/*
```

The current Vercel Python runtime supports FastAPI with `api/index.py`; the FastAPI app is exposed as the `app` variable. Vercel's current Python-on-Vercel guidance also shows Next.js and FastAPI living together in one project and deploying under one domain.

Official docs:
- https://vercel.com/academy/python-on-vercel/explore-fastapi-starter
- https://vercel.com/academy/python-on-vercel/deploy-to-prod
- https://vercel.com/kb/fastapi

## Step 1 — Create the GitHub repository

On GitHub:
1. Click **New repository**.
2. Name it `RoachCoachRadar`.
3. Choose **Private** while developing.
4. Do NOT initialize it with a README, .gitignore, or license because this ZIP already contains them.
5. Create the repository.

## Step 2 — Put this ZIP on your Mac

Unzip it. You should have a folder named `RoachCoachRadar` containing `app`, `api`, `backend`, `ios`, `docs`, etc.

## Step 3 — Push to GitHub

Open Terminal and change into that folder:

```bash
cd /path/to/RoachCoachRadar
```

Then:

```bash
git init
git branch -M main
git add .
git status
git commit -m "Initial Roach Coach Radar 27.515 Vercel stack"
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/RoachCoachRadar.git
git push -u origin main
```

Replace `YOUR_GITHUB_USERNAME` with your GitHub username.

If GitHub asks for authentication, use GitHub's normal browser/device authentication or Git Credential Manager. **Do not paste a GitHub password or personal access token into this document.**

## Step 4 — Import the repository into Vercel

1. Open Vercel.
2. Choose **Add New → Project**.
3. Import `RoachCoachRadar` from GitHub.
4. Keep the repository root as the project root.
5. Let Vercel detect Next.js.
6. Deploy.

The repository is intentionally arranged so Vercel sees:

```text
app/       → website
api/       → FastAPI Python functions
```

## Step 5 — Add environment variables

In Vercel:

**Project → Settings → Environment Variables**

Add the values from `.env.example` that you actually have and are authorized to use.

At minimum for a database-backed production deployment:

```text
DATABASE_URL
```

And whichever providers you have legitimately connected:

```text
OPENROUTER_API_KEY
XAI_API_KEY
ANTHROPIC_API_KEY
```

Do not commit `.env`.

## Step 6 — Deploy

After adding environment variables, redeploy the production deployment.

## Step 7 — Test

Open:

```text
https://YOUR-VERCEL-DOMAIN/api/health
```

Expected:

```json
{"status":"ok"}
```

Then open the root website:

```text
https://YOUR-VERCEL-DOMAIN/
```

Click **Test Radar Connection**.

## Step 8 — Custom domain

Once the Vercel deployment works, add your desired domain/subdomain in Vercel's Domains settings. Keep GoDaddy as your DNS/email provider if you want; point only the required DNS record(s) to Vercel.

Do not change MX records unless you intentionally want to move email.

## Important architecture note

Vercel is excellent for the HTTP API, website, on-demand scans, and bounded background work. Do not design the system around a permanently running Python process. For continuous ingestion, use Vercel-supported scheduled/queue/background mechanisms or a dedicated worker later if the workload outgrows serverless execution.

The first deployment should therefore prove:

1. Website works.
2. `/api/health` works.
3. `/api/radar/status` works.
4. Database connectivity works when `DATABASE_URL` is configured.
5. `/api/radar/scan` works with a test coordinate.

Only after those pass should we turn on expensive source ingestion and AI analysis.
