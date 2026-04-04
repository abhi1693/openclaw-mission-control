---
description: "Use when working on frontend API calls, Orval-generated files, frontend/orval.config.ts, frontend/src/api/mutator.ts, or backend schema changes that affect the generated client. Covers regeneration, where to make source changes, and when to avoid hand-editing generated output."
name: "Generated API Client"
applyTo: "frontend/src/api/generated/**"
---
# Generated API Client

- Treat `frontend/src/api/generated/` as generated output. Do not hand-edit files there unless the user explicitly asks for a generated-code workaround.
- Make API behavior changes in the source of truth instead: backend routes and schemas, `frontend/orval.config.ts`, or `frontend/src/api/mutator.ts`.
- After contract changes, regenerate the client with `make api-gen` from the repo root or `npm run api:gen` from `frontend/`.
- If regeneration cannot be run in the current environment, state that clearly and prefer changes in non-generated wrappers or source files over manual edits in generated output.

Use this instruction for frontend API tasks even when the immediate file being edited is not under `frontend/src/api/generated/`.