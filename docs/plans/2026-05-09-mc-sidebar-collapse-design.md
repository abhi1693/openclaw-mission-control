# MC Sidebar Collapse — Design

**Date:** 2026-05-09
**Scope:** Add desktop-only collapse-to-icons toggle to `DashboardSidebar`. Mobile drawer behavior preserved.

## Goal

Operator wants more horizontal space when needed. When collapsed, the sidebar shows only the icons; on hover, a tooltip reveals the menu name. Toggle is a chevron in the same row as the existing "Navigation" header.

## Decisions

| Area | Choice |
|---|---|
| Toggle location | Chevron button inline with "Navigation" header (same row) |
| Persistence | `localStorage` under key `mc.sidebar.collapsed` |
| Tooltips | `@radix-ui/react-tooltip` (already in `package.json`) |
| Hydration approach | Render expanded on server, switch to localStorage value on mount (one-frame flash accepted) |
| Mobile | Unchanged — existing drawer pattern; chevron `hidden md:flex` |

## Architecture

### State

`isCollapsed: boolean` lives in `DashboardShell.tsx` alongside the existing `sidebarOpen`. Default `false`. Persisted via a new hook `useSidebarCollapsed` in `frontend/src/lib/use-sidebar-collapsed.ts`.

`DashboardShell` writes `data-sidebar-collapsed="true|false"` on the root `<div>`. `DashboardSidebar` reads via prop.

### Hook

```ts
// frontend/src/lib/use-sidebar-collapsed.ts
export function useSidebarCollapsed(): [boolean, (next: boolean) => void] {
  // initial: false (server render); on mount, read localStorage and update
  // setter writes localStorage and updates state
}
```

Unit test (Vitest, in `use-sidebar-collapsed.test.tsx`):
- defaults to `false`
- reads localStorage value on mount
- writes localStorage on change

### Component changes — `DashboardSidebar.tsx`

1. Accept new `collapsed: boolean` and `onToggleCollapsed: () => void` props.
2. Sidebar root width: `md:w-[260px]` ↔ `md:w-[64px]`. Add `transition-[width] duration-200`.
3. Replace the standalone "Navigation" `<p>` with a flex row containing:
   - `<p>` (label, `sr-only` when collapsed)
   - `<button>` chevron (`hidden md:flex`, swaps `PanelLeftClose` / `PanelLeftOpen`)
4. Extract `<NavLink>` helper inside the same file (icon, label, href, active, collapsed → wraps in Radix Tooltip when collapsed).
5. Section headers (`Overview`/`Boards`/`Settings`) become `sr-only` when collapsed; group spacing preserved.
6. Status footer dot stays; the text label moves into a Radix Tooltip on the dot.
7. Wrap the whole sidebar (or shell) in `<TooltipProvider delayDuration={150}>`.

### Mobile preservation

- `data-sidebar-collapsed` only affects `md:` styles. Below `md`, the existing drawer (`data-sidebar=open|closed`) takes precedence.
- Chevron toggle button has `hidden md:flex`.
- All `NavLink` tooltips conditionally render only when `collapsed === true`, which can never be the case on mobile.

## Tests

1. **Unit** — `frontend/src/lib/use-sidebar-collapsed.test.tsx` (Vitest)
2. **E2E** — `frontend/cypress/e2e/desktop_sidebar_collapse.cy.ts` (Cypress)
   - Desktop viewport: chevron visible, click collapses sidebar, labels become `sr-only`, hover shows tooltip
   - Reload preserves collapsed state
   - Mobile viewport: chevron hidden, drawer toggle still functional

## YAGNI / scope guards

- No keyboard shortcut (defer until asked)
- No label fade animation (only width transitions)
- No auto-collapse heuristic
- `NavLink` helper stays local to `DashboardSidebar.tsx`

## Files touched

- `frontend/src/lib/use-sidebar-collapsed.ts` (new)
- `frontend/src/lib/use-sidebar-collapsed.test.tsx` (new)
- `frontend/src/components/templates/DashboardShell.tsx`
- `frontend/src/components/organisms/DashboardSidebar.tsx`
- `frontend/cypress/e2e/desktop_sidebar_collapse.cy.ts` (new)
