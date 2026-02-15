# Configuration reference

This page collects the most important config values.

## Root `.env` (Compose)

See `.env.example` for defaults and required values.

### `NEXT_PUBLIC_API_URL`

- **Where set:** `.env` (frontend container environment)
- **Purpose:** Public URL the browser uses to call the backend.
- **Gotcha:** Must be reachable from the *browser* (host), not a Docker network alias.

### `LOCAL_AUTH_TOKEN`

- **Where set:** `.env` (backend)
- **When required:** `AUTH_MODE=local`
- **Policy:** Must be non-placeholder and at least 50 characters.
