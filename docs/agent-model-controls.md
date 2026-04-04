# Agent Model Controls

Per-agent model assignment, fallback policy, and runtime sync for OpenClaw Mission Control.

## Features

### Per-Agent Model Assignment
- **Manual selection**: Admins assign a specific model to any agent via the UI or API
- **Auto mode**: Falls back to recommendation engine (gateway profile-aware)
- **Effective model**: Resolved from manual selection → recommendation → global default

### Fallback Policy
- **Generated fallback chain**: Automatically built from catalog (budget + general tiers)
- **Manual override**: Full-list replacement with `none`, `append`, or `replace` modes
- **Effective chain assembly**: Merges generated + manual entries based on override mode

### Recommendation Engine
- Role-fit mapping: `coding` → Coder profile, `budget-sensitive` → Budget profile, otherwise → General
- Gateway profile-aware: Reads from `GatewayModelProfileDefaults` (General/Coder/Budget slots)
- Fallback-to-General: Optional profiles (Coder/Budget) fall back to General when unset
- `"default"` sentinel: Maps to OpenClaw runtime-configured default

### Runtime Sync Bridge
- On model assignment change, writes `agents.list[n].model.primary` in `openclaw.json`
- Agents pick up the new model on next turn — no restart required
- `RuntimeSyncResult` in response payload: `synced | failed | skipped` with error detail
- Best-effort: MC DB assignment always succeeds regardless of sync outcome

### Dynamic Model Catalog
- `GET /api/v1/mission-control/agents/model-catalog` with capability filtering
- In-memory from `catalog-seed.json`; clean upgrade path to DB table
- Frontend: 60s staleTime + manual refresh, outage-resilient `useRef` cache

### Gateway Model Profile Defaults
- Separate DB table: `gateway_model_profile_defaults`
- Three slots: General, Coder, Budget (all optional)
- UI panel on Gateway detail page

## API Endpoints

### Model Assignment
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/mission-control/agents/{id}/model-assignment` | Get aggregate assignment |
| PATCH | `/api/v1/mission-control/agents/{id}/model-assignment/primary` | Set/clear primary model |
| PUT | `/api/v1/mission-control/agents/{id}/model-assignment/fallback-override` | Override fallback chain |
| POST | `/api/v1/mission-control/agents/{id}/model-assignment/recommendation:regenerate` | Regenerate recommendation |

### Model Catalog
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/mission-control/agents/model-catalog` | List available models (filterable) |

### Gateway Model Profiles
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/gateways/{id}/model-profile-defaults` | Get profile defaults |
| PATCH | `/api/v1/gateways/{id}/model-profile-defaults` | Update profile defaults |

## UI Components

### Agent Detail → Model Controls Panel
<!-- Screenshot placeholder: Agent model controls panel showing primary model selector, fallback chain, and recommendation status -->

- Primary model: Edit dialog with mode toggle (Auto/Manual) and model dropdown
- Fallback policy: Override/Reset with effective chain display
- Recommendation: Regenerate button with explanation display
- Catalog: Model count badge with refresh button
- Validation: Config status indicator (valid/warning/error)

### Gateway Detail → Model Profiles Panel
<!-- Screenshot placeholder: Gateway model profiles panel showing General/Coder/Budget profile selectors -->

- Three profile slots with model dropdowns
- `"default"` sentinel option in each slot
- Save/reset controls

## Database Schema

### Tables
- `agent_model_profile` — Per-agent assignment state (primary, recommendation, effective, fallback override mode)
- `agent_model_fallback_entry` — Fallback chain entries (generated + manual, ordered)
- `agent_model_recommendation_run` — Recommendation audit trail
- `gateway_model_profile_defaults` — Per-gateway General/Coder/Budget profile slots

### Migrations
- `aa10c1f9b2d4` — Model controls tables
- `bb20d2e1c3f5` — Gateway model profile defaults (depends on `aa10c1f9b2d4`)

## Architecture Decisions

1. **Admin intent separated from recommendation state** — Manual selections are never overwritten by recommendation refresh
2. **Typed fallback entries** — Not a single opaque JSON blob; supports validation, ordering, and clean assembly
3. **Single aggregate read payload** — One response shape for all reads and writes; no client-side merge drift
4. **Full-list replacement for fallback overrides** — Reduces ordering/race bugs vs. incremental edits
5. **In-memory catalog** — From `catalog-seed.json`; clean upgrade path to DB table when scale demands it
6. **Runtime sync is best-effort** — MC DB is source of truth; file-write failures reported in response, never block assignment
