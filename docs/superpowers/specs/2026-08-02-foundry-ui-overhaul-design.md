# Foundry Dashboard UI/UX Overhaul — Design

## Summary

Foundry's dashboard (`frontend/`) is a React 18 + Tailwind v3 app with no design-token layer and no shared UI primitives — every one of its 8 pages and ~14 components inlines its own Tailwind `slate-*`/`orange-*` classes directly. This mirrors the same overhaul already completed on WatchTower (a sibling AI-orchestration dashboard): move onto the user's own design system — **"DS for akshayguleria.com"** (claude.ai/design project `d67e7e16-2592-454b-bd45-945efaf7829e`), a shadcn/ui "new-york"/Neutral system with grayscale-by-default oklch tokens, Geist type, and 87 dependency-free React primitives.

Unlike WatchTower, Foundry has **no existing primitives to preserve for backward compatibility** — there is no `components/ui/` directory at all. This simplifies Phase 1's scope: it's a pure net-new build (tokens, ported primitives, shell), not a restyle-in-place of existing bespoke components. Also unlike WatchTower at the point its overhaul started, Foundry currently has **no light mode at all** (dark-only, no toggle) — this overhaul adds one, matching the DS's actual dual-theme capability and WatchTower's now-completed approach.

Phase 1 (Foundation) delivers tokens, theme (dark-default with a real toggle), a sidebar shell replacing the current top nav, and the DS primitives a page-migration phase will need. Page content migration (moving the 8 existing pages onto the new primitives) is a separate, later plan — same two-phase split used for WatchTower, for the same reason: each phase should ship independently reviewable, and 3,500+ lines of page code doesn't fit one plan's literal-code requirement.

## Goals

- Replace ad-hoc `slate-*`/`orange-*` Tailwind classes with the DS's oklch token system.
- Add real light/dark theming (dark default) — a capability Foundry doesn't have today.
- Build a `components/ui/` primitives directory from scratch, populated with DS-ported components scoped to what the later page-migration phase will actually need (confirmed by grepping real usage, not guessed).
- Replace the top nav with a DS sidebar shell.
- Install `@playwright/test` for browser-level verification (Foundry already has vitest + Testing Library for component tests — Playwright is added alongside it, not replacing it, per the user's explicit choice to match WatchTower's approach).

## Non-Goals

- Migrating the 8 existing pages' internal markup (`PortfolioHomePage`, `QueuePage`, `ProjectsPage`, `ProjectDetailPage`, `RunsHomePage`, `RunDetailPage`, `KnowledgePage`, `FleetPage`, `MetricsPage`, `PacksPage`) or their ~14 components (`ArtifactCard`, `DagView`, `DemoModeToggle`, `EventFeed`, `GateCard`, `KgGraphView`, `MemoryBrowser`, `MetricsSummary`, `NewProjectForm`, `NewRunForm`, `ProjectLifecycleButtons`, `Ribbon`, `UnitDrawer`) — Phase 2, a separate plan.
- Replacing or modifying Foundry's existing vitest/Testing Library suite (`*.test.tsx` files) — those keep working exactly as-is; Playwright is additive.
- Any backend (`src/foundry/`) change. Frontend-only, matching the WatchTower overhaul's scope discipline.

## Architecture

### 1. Token layer

New `frontend/src/tokens/` directory (parallel structure to what WatchTower ended up with) holding the DS's oklch color/typography/spacing/radius/shadow tokens plus self-hosted Geist/Geist Mono fonts, imported from a rewritten `frontend/src/index.css` (currently just three `@tailwind` directives — this becomes the real entry point). Theming is class-based from day one: `<html class="dark">` by default, `.light` on toggle — no attribute-based legacy to migrate away from here, unlike WatchTower.

### 2. Semantic status extension

Foundry's color usage is lighter than WatchTower's was: no 12-tone badge system, no artifact-kind taxonomy — just `slate-*` chrome, `orange-*` as the brand/nav accent, and a handful of status reds/greens/ambers (primarily in `GateCard.tsx`, gate approve/reject states). Phase 1 adds only the semantic tokens actually needed once real usage is confirmed during planning — no speculative token set, following the same discipline that corrected WatchTower's over-scoped original semantic-color plan.

### 3. Component primitives (net-new, not a restyle)

Since nothing exists to preserve, Phase 1 builds `frontend/src/components/ui/` fresh, structured like the DS's own grouping (`forms/`, `display/`, `feedback/`, `overlay/`), populated only with primitives the page-migration phase will actually consume — determined by grepping the 8 pages + 14 components for real patterns (`<table`, `<select`, modal/portal usage, etc.) during plan-writing, the same verification discipline used for WatchTower rather than porting all 17 DS components speculatively.

### 4. Shell

`App.tsx`'s current 47-line `Layout`-equivalent (inline in `App`, not yet split into a separate component) becomes a fixed left sidebar + slim top bar, replacing the 8-link top nav. The DS's own dashboard UI kit (`ui_kits/dashboard/Shell.jsx`) is the structural reference, adapted to Foundry's real routes and orange-as-accent brand identity (not indigo, which is WatchTower's accent — Foundry keeps its own brand color as the semantic "active/accent" hue rather than adopting WatchTower's).

### 5. Testing — Playwright, additive to existing vitest

`@playwright/test` installed fresh (Foundry has no existing e2e setup), `frontend/e2e/` directory, `playwright.config.ts` with a `webServer` starting Foundry's backend (`uv run foundry serve --db <tmp-path> --port 8000`, per `README.md` — a Typer CLI command, not raw uvicorn, matching this project's stack) and `npm run dev` (Vite on `:5173`, proxying `/api` to `:8000` per `frontend/vite.config.ts`). Existing `vitest run` / `*.test.tsx` files are untouched and continue to run via `npm run test`.

## Risks / open items for the plan to account for

- **`useStyle()` duplication**: WatchTower's final review flagged that the DS's dependency-free `useStyle()` hook was copy-pasted into all 11 ported components. Foundry's plan should extract this into one shared `ui/useStyle.ts` from the start, rather than repeating WatchTower's Task-11-discovered tech debt.
- **oklch color assertions in Playwright**: WatchTower's implementation hit a real environment issue (this machine's Chromium serializes oklch-authored computed colors as `oklch(...)` text, and even a `<canvas>` `fillStyle`-getter round-trip doesn't normalize it — only paint+`getImageData()` reliably does). Foundry's plan should use the `getImageData()` pattern from the start rather than rediscovering it.
- **Two dashboards sharing one design language**: this overhaul intentionally gives Foundry and WatchTower the same DS foundation. They are NOT meant to become visually identical (Foundry keeps orange, WatchTower keeps indigo, as brand-differentiating accents) — only the underlying grayscale chrome, type, spacing, and component shapes are shared.
- Foundry has no `Makefile` (unlike what its own `CLAUDE.md` reference-docs table might suggest by analogy to other projects) — dev commands come from `README.md`'s "Run the app" section (`uv run foundry serve --db <path> --port 8000` + `npm run dev`), already confirmed above rather than assumed from WatchTower's `scripts/dev.sh` pattern.
