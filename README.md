# Roach Coach Radar — Vercel + GitHub Starter

This repository is designed to be a **brand-new GitHub repository and Vercel project** for Roach Coach Radar.

It contains:
- `app/` — a minimal Next.js command center site
- `api/index.py` — Vercel's FastAPI entrypoint
- `backend/` — the Level 27.515 Radar backend
- `ios/` — the current iOS source
- `docs/` — project documentation

Vercel currently supports FastAPI through `api/index.py` and can deploy the frontend and Python API under one project/domain. See the official Vercel documentation linked in `docs/VERCEL_DEPLOYMENT.md`.

## Security
Never commit real API keys, CloudKit secrets, database passwords, partner secrets, or tokens. Put server-side secrets into Vercel Environment Variables.


## Vercel build mode
This repository intentionally uses JavaScript, not TypeScript. There is no `tsconfig.json`, `.ts`, or `.tsx` application source. Vercel should use the repository root and the `npm run build` command.
