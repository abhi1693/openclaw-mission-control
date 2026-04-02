---
description: "Use when changing FastAPI routes, backend services, SQLModel models, Pydantic schemas, or backend pytest coverage. Covers strict typing, keeping business logic out of route handlers, and updating tests with behavior changes."
name: "Backend Python Changes"
applyTo: "backend/app/**/*.py, backend/tests/**/*.py"
---
# Backend Python Changes

- Keep contract changes aligned across routes, schemas, services, and models instead of patching only one layer.
- Prefer business logic in `backend/app/services/` or existing helper layers rather than expanding route handlers with workflow logic.
- Preserve strict typing: avoid introducing `Any`, loosely typed payload dictionaries, or untyped helper returns when a schema or model type fits.
- When behavior changes, add or update focused pytest coverage in `backend/tests/`, especially for API, auth, security, or regression-sensitive flows.
- Keep edits narrow and consistent with existing module boundaries, then run targeted backend checks when practical and state clearly if they were not run.