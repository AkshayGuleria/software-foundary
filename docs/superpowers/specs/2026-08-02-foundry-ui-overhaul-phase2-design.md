# Foundry Dashboard UI Overhaul — Phase 2 (Page Migration) Design

## Summary

Phase 1 (merged, `master` at `b12d625`) built the foundation: DS oklch tokens, a from-scratch light/dark theme mechanism (toggle built but not yet mounted — light mode isn't usable app-wide until this phase), a sidebar shell, and 6 ported primitives (`Button`, `Input`, `Textarea`, `Label`, `Select`, `Table`). Phase 2 migrates the actual page content — 8 pages + 14 components, currently all still using hardcoded `slate-*`/`gray-*`/`orange-*` Tailwind classes — onto those primitives and the token system, and decides when it's safe to expose the theme toggle.

Unlike WatchTower's equivalent overhaul (forced into two page-migration plans by sheer size — its `RunDetail.tsx` alone was 1,200+ lines), Foundry's remaining surface is small: **3,411 lines across 22 files** (8 pages + 14 components, excluding the already-migrated `Shell.tsx`/`TopBar.tsx`), largest file 183 lines. This fits in a single implementation plan.

## Goals

- Migrate all 8 pages and 14 components off hardcoded `slate-*`/`gray-*` Tailwind classes onto the DS token system (`bg-[var(--x)]` arbitrary-value syntax, same pattern Phase 1 established).
- Replace hand-rolled UI patterns with the appropriate primitive: raw `<button>` → `Button`, raw `<select>`/`<textarea>` → `Select`/`Textarea` (both already used natively in a few places and just need restyling + primitive swap), hand-rolled bordered `<div>`/`<li>` panels → a new `Card` primitive, hand-rolled `rounded-full` pill labels → a new `Badge` primitive, `UnitDrawer.tsx`'s hand-rolled slide-over → a new `Sheet` primitive.
- Port the 3 newly-identified primitives (`Card`, `Badge`, `Sheet`) — confirmed necessary by reading actual component source, not surface grep alone (Phase 1's grep-based scoping missed these because it only checked for `<table`/`<select`/`<textarea` tags, not visual-vocabulary patterns like bordered panels or pill labels).
- Decide when to mount `ThemeToggle` in the live `TopBar` (currently built and tested at `/dev/ui-kit` only, per Phase 1's explicit deferral).
- Keep the existing vitest + Testing Library suite (107 tests, all behavioral — role/label queries and callback assertions, zero CSS class assertions, confirmed by reading representative test files) fully green throughout. This is real safety margin: restyling cannot break these tests as long as native element semantics (`<button>`, `<textarea>`, associated `<label>`) are preserved, which the ported primitives already guarantee.

## Non-Goals

- Any backend (`src/foundry/`) change.
- Any new page, route, or feature — this is a pure styling-layer migration, same prop signatures, same data flow, same component boundaries (unless a component's internal structure needs adjusting to use a new primitive, e.g. `UnitDrawer` restructuring around `Sheet`'s compound-component API).
- Introducing DS primitives beyond the 3 identified as necessary (`Card`, `Badge`, `Sheet`) — no speculative porting of `Tabs`, `Tooltip`, `Avatar`, `Progress`, `Alert`, `DropdownMenu`, etc. None of these patterns exist anywhere in the current 22 files (confirmed: no `role="tab"`, no `animate-spin`/`Loader`/`Spinner`, no avatar/image usage, no dropdown-menu pattern).

## Architecture

### 1. Three new primitives

- **`Card`** — the de facto panel pattern already used consistently across most pages/components (`rounded border border-slate-800 [px-3 py-2 | p-3]`), just never centralized. Ported from the DS, restyled onto the same token set Phase 1 established.
- **`Badge`** — pill-shaped status/kind labels (`rounded-full border px-2 py-0.5 text-xs`, with tone-based coloring — e.g. `GateCard.tsx`'s rejection-reason chips already have a selected/unselected tone pair). Follows the same tone-system pattern WatchTower's equivalent overhaul used (a fixed set of named tones mapping to Tailwind hue classes layered on the DS's grayscale base), sized to Foundry's actual usage (`MemoryBrowser`, `Ribbon`, `GateCard` — 3 consumers, likely 3-4 tones needed, confirmed exactly during planning by reading all three files).
- **`Sheet`** — right-side slide-over, ported from the DS's dedicated `Sheet` component (compound API: `Sheet`/`SheetTrigger`/`SheetContent`/`SheetHeader`/`SheetTitle`/`SheetDescription`/`SheetFooter`/`SheetClose`, controlled or uncontrolled, `Escape`-to-close already built in — notably more complete than Phase 1's `Dialog` port, which has neither). `UnitDrawer.tsx` is the only consumer; migrating it means restructuring its hand-rolled `fixed inset-0` overlay + `onClick={onClose}` pattern around `Sheet`'s own open/close state management, which the plan will need to reconcile with `UnitDrawer`'s current `onClose` prop (passed down from whichever page renders it — `RunDetailPage.tsx`, confirmed during planning).

### 2. Migration order

All 8 pages + 14 components, task-grouped by natural pairing (a page with its primary child components) rather than one task per file — e.g. `PortfolioHomePage` + `ProjectLifecycleButtons` (both render on the portfolio list), `RunDetailPage` + `UnitDrawer` + `GateCard` + `ArtifactCard` (the run-detail cluster). Exact grouping and task count determined during plan-writing, after reading every file (this spec establishes the approach, not the literal task list — matching the discipline that caught Phase 1's under-scoped primitive list, exact groupings need the same file-by-file read before being committed to a plan).

### 3. Theme toggle exposure

Mounting `<ThemeToggle />` in `TopBar.tsx` (currently a one-line change, deliberately deferred in Phase 1) happens as the **last task** of this plan, after every page/component has been migrated off hardcoded slate classes — at that point light mode is genuinely usable app-wide, not just on the 6 (now 9) ported primitives.

### 4. Testing

Continue Phase 1's pattern: `@playwright/test` gets a new section per new primitive on `/dev/ui-kit` (mirroring `Card`/`Badge`/`Sheet` the same way Phase 1 did for `Button`/`Input`/etc.). For the page-migration tasks themselves, the existing vitest suite is the primary regression gate (already covers behavior; restyling must not touch it) — Playwright is used for whole-page smoke checks (page renders, no console errors, dark/light both work once the toggle is mounted) rather than re-testing behavior vitest already covers.

## Risks / open items for the plan to account for

- **`UnitDrawer`'s restructuring around `Sheet` is the highest-risk single task** — it's not a pure restyle like every other file, it changes how open/close state is owned (currently an `onClose` callback prop from the parent; `Sheet` wants `open`/`onOpenChange` or uncontrolled `defaultOpen`). The plan should map this out explicitly (likely: keep `UnitDrawer` controlled via props, passing `open={!!unit}` / `onOpenChange={(v) => !v && onClose()}` into `Sheet` — confirm during planning by reading `UnitDrawer`'s actual current prop contract and its call site in `RunDetailPage.tsx`).
- **Badge's exact tone set** needs to be derived from reading `MemoryBrowser.tsx`, `Ribbon.tsx`, and `GateCard.tsx`'s actual current color choices during planning, not guessed here.
- **Semantic action-button colors** (`GateCard.tsx`'s `bg-emerald-700` approve / `bg-red-800` reject) don't map cleanly onto `Button`'s existing variant palette (`default`/`destructive`/`outline`/`secondary`/`ghost`/`link`) — `destructive` covers reject, but approve has no matching variant. The plan should decide: add an approve-flavored `Button` variant, or keep these two as bespoke-styled `Button`s with a `className` override (matching how WatchTower's equivalent overhaul left categorical accent colors as raw Tailwind classes layered on top of ported primitives, rather than forcing everything through the DS's own variant enum).
