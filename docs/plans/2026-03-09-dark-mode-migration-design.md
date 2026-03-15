# Dark Mode Migration Design

## Context

Issue #227 added ThemeProvider, ThemeToggle, dark CSS variables, and migrated
DashboardSidebar + UserMenu. The remaining ~80 component files still use
hardcoded Tailwind color classes that ignore the dark theme.

## Scope

Migrate all dashboard/app components to CSS variables. Landing page deferred.

## Color Mapping Table

| Hardcoded class | Replacement |
|---|---|
| `bg-white` | `bg-[var(--surface)]` |
| `bg-slate-50`, `bg-gray-50` | `bg-[var(--surface-muted)]` |
| `bg-slate-100`, `bg-gray-100` | `bg-[var(--surface-muted)]` |
| `bg-slate-200`, `bg-gray-200` | `bg-[var(--surface-strong)]` |
| `text-slate-900`, `text-gray-900` | `text-[var(--text)]` |
| `text-slate-700`, `text-gray-700` | `text-[var(--text)]` |
| `text-slate-600`, `text-gray-600` | `text-[var(--text-muted)]` |
| `text-slate-500`, `text-gray-500` | `text-[var(--text-muted)]` |
| `text-slate-400`, `text-gray-400` | `text-[var(--text-quiet)]` |
| `text-slate-300` | `text-[var(--text-quiet)]` |
| `border-slate-200`, `border-gray-200` | `border-[var(--border)]` |
| `border-slate-300`, `border-gray-300` | `border-[var(--border-strong)]` |
| `divide-slate-200`, `divide-gray-200` | `divide-[var(--border)]` |
| `hover:bg-slate-50/100`, `hover:bg-gray-50/100` | `hover:bg-[var(--surface-muted)]` |
| `placeholder-slate-400/500` | `placeholder-[var(--input-placeholder)]` |
| `ring-slate-*` | `ring-[var(--input-focus-ring)]` |
| `bg-blue-50` (info context) | `bg-[var(--alert-info-bg)]` |
| `bg-red-50` (error context) | `bg-[var(--alert-danger-bg)]` |
| `bg-green-50` (success context) | `bg-[var(--alert-success-bg)]` |
| `bg-amber-50`/`bg-yellow-50` (warn) | `bg-[var(--alert-warning-bg)]` |
| `text-blue-600/700` (accent) | `text-[var(--accent)]` |
| `text-red-600/700` (error) | `text-[var(--danger)]` |
| `text-green-600/700` (success) | `text-[var(--success)]` |
| `text-amber-600/700` (warning) | `text-[var(--warning)]` |
| `border-blue-200` (info) | `border-[var(--alert-info-border)]` |
| `border-red-200` (error) | `border-[var(--alert-danger-border)]` |
| `border-green-200` (success) | `border-[var(--alert-success-border)]` |
| `shadow-sm/md/lg` | `shadow-[var(--shadow-card)]` or `shadow-[var(--shadow-panel)]` |

## Preserve (do not replace)

- `text-white` on colored backgrounds (buttons, gradients, badges)
- `bg-emerald-500`, `bg-rose-500` status dots
- Anything inside `.landing-enterprise` CSS
- Already-migrated files (DashboardSidebar, UserMenu, ThemeToggle)

## Strategy

Process files in parallel batches by domain:
1. UI primitives (button, input, select, dialog, tooltip, etc.)
2. Shared components (tables, shells, layouts)
3. Domain components (boards, agents, gateways, skills, etc.)
4. Page files (app/ routes)

Each file: read, apply contextual mapping, edit in place.
