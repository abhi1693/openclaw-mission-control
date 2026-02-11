# Testing

This repo uses a mix of unit tests and Cypress end-to-end (E2E) tests.

## Cypress E2E: conventions (stories)

Write E2E tests as **user stories** describing what a user does (and does not do):

- Prefer descriptive spec names like:
  - `As a signed-in user, I can view my activity feed (happy path)`
  - `As a signed-out user, I get redirected to sign-in (negative path)`
  - `As a user, invalid API URL shows an error state (negative path)`
- Include **both**:
  - **Positive/happy path** (expected successful flow)
  - **Negative paths** (missing inputs, unauthenticated access, invalid states)

Keep each spec focused on one story/flow; avoid long “mega specs”.

## Cypress E2E: Clerk auth (official implementation)

Hard requirements:
- **No auth bypass** in E2E.
- Use Clerk’s **official Cypress support** via `@clerk/testing`.

Implementation in this repo:
- `frontend/cypress.config.ts` calls `clerkSetup()`.
- `frontend/cypress/support/e2e.ts` imports and registers commands:
  - `addClerkCommands({ Cypress, cy })`
- Tests can use:
  - `cy.clerkLoaded()`
  - `cy.clerkSignIn(...)` / `cy.clerkSignOut(...)`

See also: [E2E auth notes](../e2e-auth.md).

### Test user (non-secret)

- Email: `jane+clerk_test@example.com`
- OTP: `424242`

## Required environment variables

### Local E2E (running Cypress yourself)

You typically need:

- `NEXT_PUBLIC_API_URL` (required)
  - Must be reachable from the **browser** (host), not just from inside Docker.
  - Examples:
    - Local backend: `http://localhost:8000`
    - CI E2E job (frontend dev server): `http://localhost:3000` (see workflow)

- Clerk env (values should come from your Clerk app; **do not commit secrets**):
  - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (required for the app)
  - `CLERK_SECRET_KEY` (required for Clerk testing tokens)

- Cypress Clerk test user identifier (non-secret, repo default is OK):
  - `CYPRESS_CLERK_TEST_EMAIL` (defaults to `jane+clerk_test@example.com` in CI)

Note: Cypress automatically maps `CYPRESS_FOO=bar` into `Cypress.env('FOO')`.

### CI artifacts on E2E failures (required)

For E2E failures, always upload Cypress artifacts so failures are debuggable from CI:

- `frontend/cypress/screenshots/**`
- `frontend/cypress/videos/**`

(Our GitHub Actions workflow already uploads these as an artifact for every E2E run.)

## Running Cypress locally

From repo root:

```bash
make frontend-sync

# in one terminal
cd frontend
npm run dev -- --hostname 0.0.0.0 --port 3000

# in another terminal
cd frontend
npm run e2e -- --browser chrome
```

If you hit Clerk-related bot detection or sign-in failures, re-check the Clerk testing env vars above.
