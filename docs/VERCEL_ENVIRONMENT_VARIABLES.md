# Vercel Environment Variables

Use Vercel's Environment Variables UI for production secrets.

## Never commit
- API keys
- OAuth client secrets
- bearer tokens
- database passwords
- CloudKit private keys
- AWS secret keys

## Recommended variables

| Variable | Purpose |
|---|---|
| DATABASE_URL | PostgreSQL connection string |
| OPENROUTER_API_KEY | OpenRouter server-side key |
| XAI_API_KEY | xAI/Grok key |
| ANTHROPIC_API_KEY | Anthropic key |
| INSTAGRAM_ACCESS_TOKEN | Authorized Meta/Instagram token |
| X_API_BEARER_TOKEN | Authorized X API bearer token |
| PARTNERSHIP_API_KEY | Authorized partner integration |
| TELECOM_API_KEY | Authorized telecom integration |
| UBER_PARTNER_CLIENT_ID | Authorized Uber integration |
| UBER_PARTNER_CLIENT_SECRET | Authorized Uber integration |
| DOORDASH_PARTNER_API_KEY | Authorized DoorDash integration |
| AWS_ACCESS_KEY_ID | AWS access key if used |
| AWS_SECRET_ACCESS_KEY | AWS secret if used |
| LLM_STRATEGY | e.g. fallback |
| LLM_PROVIDER | e.g. openrouter |
| LLM_MODEL | selected model |
