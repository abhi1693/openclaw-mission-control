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

### `WEBHOOK_MAX_PAYLOAD_BYTES`

- **Default:** `1048576` (1 MiB)
- **Purpose:** Maximum accepted inbound webhook payload size before the API returns `413 Content Too Large`.

### `RATE_LIMIT_BACKEND`

- **Default:** `memory`
- **Allowed values:** `memory`, `redis`
- **Purpose:** Selects whether rate limits are tracked per-process in memory or shared through Redis.

### `RATE_LIMIT_REDIS_URL`

- **Default:** _(blank)_
- **When required:** `RATE_LIMIT_BACKEND=redis` and `RQ_REDIS_URL` is not set
- **Purpose:** Redis connection string used for shared rate limits.
- **Fallback:** If blank and Redis rate limiting is enabled, the backend falls back to `RQ_REDIS_URL`.

### `TRUSTED_PROXIES`

- **Default:** _(blank)_
- **Purpose:** Comma-separated list of trusted reverse-proxy IPs or CIDRs used to honor `Forwarded` / `X-Forwarded-For` client IP headers.
- **Gotcha:** Leave this blank unless the direct peer is a proxy you control.

## Security response headers

These environment variables control security headers added to every API response. Set any variable to blank (`""`) to disable the corresponding header.

### `SECURITY_HEADER_X_CONTENT_TYPE_OPTIONS`

- **Default:** `nosniff`
- **Purpose:** Prevents browsers from MIME-type sniffing responses.

### `SECURITY_HEADER_X_FRAME_OPTIONS`

- **Default:** `DENY`
- **Purpose:** Prevents the API from being embedded in iframes.
- **Note:** If your deployment embeds the API in an iframe, set this to `SAMEORIGIN` or blank.

### `SECURITY_HEADER_REFERRER_POLICY`

- **Default:** `strict-origin-when-cross-origin`
- **Purpose:** Controls how much referrer information is sent with requests.

### `SECURITY_HEADER_PERMISSIONS_POLICY`

- **Default:** _(blank — disabled)_
- **Purpose:** Restricts browser features (camera, microphone, etc.) when set.
