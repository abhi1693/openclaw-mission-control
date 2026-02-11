# Frontend API client and auth integration

This page documents the frontend integration points you’ll touch when changing how the UI talks to the backend or how auth is applied.

## Related docs

- [Architecture](05-architecture.md)
- [Configuration](06-configuration.md)
- [API reference](07-api-reference.md)

## API base URL

The frontend uses `NEXT_PUBLIC_API_URL` as the single source of truth for where to send API requests.

- Code: `frontend/src/lib/api-base.ts`
- Behavior:
  - reads `process.env.NEXT_PUBLIC_API_URL`
  - normalizes by trimming trailing slashes
  - throws early if missing/invalid

In Docker Compose, `compose.yml` sets `NEXT_PUBLIC_API_URL` both:
- as a **build arg** (for `next build`), and
- as a **runtime env var**.

## API client layout

### Generated client

- Location: `frontend/src/api/generated/*`
- Generator: **Orval**
  - Config: `frontend/orval.config.ts`
  - Script: `cd frontend && npm run api:gen`
  - Convenience target: `make api-gen`

By default, Orval reads the backend OpenAPI schema from:
- `ORVAL_INPUT` (if set), otherwise
- `http://127.0.0.1:8000/openapi.json`

Output details (from `orval.config.ts`):
- Mode: `tags-split`
- Target index: `frontend/src/api/generated/index.ts`
- Schemas: `frontend/src/api/generated/model`
- Client: `react-query`
- All requests go through the custom mutator below.

### Custom fetch / mutator

All generated requests go through:

- Code: `frontend/src/api/mutator.ts`
- What it does:
  - resolves `NEXT_PUBLIC_API_URL` and builds the full request URL
  - sets `Content-Type: application/json` when there’s a body
  - injects `Authorization: Bearer <token>` when a Clerk session token is available
  - converts non-2xx responses into a typed `ApiError` (status + parsed response)

## Auth enablement and token injection

### Clerk enablement (publishable key gating)

Clerk is enabled in the frontend only when `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` looks valid.

- Gating helper (dependency-free): `frontend/src/auth/clerkKey.ts`
- UI-safe wrappers/hooks: `frontend/src/auth/clerk.tsx`
  - provides `SignedIn`, `SignedOut`, `SignInButton`, `SignOutButton`, `useUser`, and `useAuth`
  - returns safe fallbacks when Clerk is disabled (to allow secretless builds/prerender)

### Token injection

When the UI makes an API request, the mutator attempts to read a token from the Clerk session:

- Code: `frontend/src/api/mutator.ts` (`resolveClerkToken()`)
- If a token is available, the request includes:
  - `Authorization: Bearer <token>`

### Route protection (middleware)

Request-time route protection is implemented via Next.js middleware:

- Code: `frontend/src/proxy.ts`
- Behavior:
  - when Clerk is enabled: uses `clerkMiddleware()` to enforce auth on non-public routes
  - when Clerk is disabled: passes all requests through

## Common workflows

### Update the backend API and regenerate the client

1. Run the backend so OpenAPI is available:

```bash
# from repo root
cp backend/.env.example backend/.env
make backend-migrate
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

2. Regenerate the client:

```bash
# from repo root
make api-gen

# or from frontend/
ORVAL_INPUT=http://127.0.0.1:8000/openapi.json npm run api:gen
```

3. Review diffs under `frontend/src/api/generated/*`.

