# Troubleshooting

This is the “symptom → checks → likely fixes” page.

For deeper playbooks, see:
- [Troubleshooting deep dive](troubleshooting/README.md)

## Triage map

| Symptom | Fast checks | Likely fix |
|---|---|---|
| UI loads but API calls fail / Activity feed blank | Browser devtools shows `/api/v1/*` failures; check backend `/healthz` | Fix `NEXT_PUBLIC_API_URL` (must be browser-reachable) |
| UI redirects / Clerk errors | Is `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` set? Are Clerk redirects correct? | Unset keys for local dev without Clerk; configure real keys for prod |
| Backend `/healthz` fails | Is backend container/process running? check backend logs | Fix crash loop: env vars, DB connectivity, migrations |
| Backend returns 5xx | Check DB connectivity (`DATABASE_URL`), DB logs | Fix DB outage/misconfig; re-run migrations if needed |
| Browser shows CORS errors | Compare `CORS_ORIGINS` vs frontend origin | Add frontend origin to `CORS_ORIGINS` |

## Common checks

### 1) Verify backend health

```bash
curl -f http://localhost:8000/healthz
```

### 2) Verify frontend can reach backend

- Ensure `NEXT_PUBLIC_API_URL` matches the backend URL the browser can reach.

### 3) Check logs

```bash
docker compose -f compose.yml --env-file .env logs -f --tail=200 backend
```

## Next

If you hit a recurring incident, promote it from the deep-dive page into this triage map.
