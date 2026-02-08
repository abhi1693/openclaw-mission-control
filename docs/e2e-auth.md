# E2E auth (Cypress)

Hard requirement: **no auth bypass** for Cypress E2E.

- Cypress tests must use real Clerk sign-in.
- CI should inject Clerk keys into the Cypress job environment.

Test account (non-secret):
- email: `jane+clerk_test@example.com`
- OTP: `424242`
