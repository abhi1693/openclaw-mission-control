# Authentication

Mission Control supports two auth modes via `AUTH_MODE`:

- `local`: shared bearer token auth for self-hosted deployments
- `clerk`: Clerk JWT auth

## Local mode

Backend:

- `AUTH_MODE=local`
- `LOCAL_AUTH_TOKEN=<token>`

Frontend:

- `NEXT_PUBLIC_AUTH_MODE=local`
- Provide the token via the login UI.

## Clerk mode

Backend:

- `AUTH_MODE=clerk`
- `CLERK_SECRET_KEY=<secret>`

Frontend:

- `NEXT_PUBLIC_AUTH_MODE=clerk`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<key>`
