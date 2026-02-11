# Troubleshooting

## Deep dives

- [Troubleshooting deep dive](troubleshooting/README.md)

This is the “quick triage” page. For detailed playbooks and diagnostics, use the deep dive.

## Quick triage

### Frontend loads but shows API errors
- Confirm `NEXT_PUBLIC_API_URL` points to a backend your browser can reach.
- Check backend `/healthz`.

### Frontend keeps redirecting / Clerk errors
- Verify your Clerk keys are set correctly in the frontend environment.
- See: [Deployment guide](deployment/README.md) (Clerk auth notes).

### Backend returns 5xx
- Check DB connectivity (`DATABASE_URL`) and migrations.
- Check backend logs.

## Next
- Promote the most common issues from [Troubleshooting deep dive](troubleshooting/README.md) into this page once we see repeated incidents.
