# Foundry Dashboard UI Overhaul — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Foundry's dashboard (`frontend/`) onto the user's "DS for akshayguleria.com" design system — tokens, a from-scratch `components/ui/` primitives layer, a real light/dark toggle (Foundry has none today), and a sidebar shell replacing the current top nav.

**Architecture:** DS token files (oklch colors, typography, spacing, radius, shadows, Geist fonts) become `frontend/src/index.css`'s real entry point (currently three bare `@tailwind` directives). Six DS primitives — the exact set confirmed needed by grepping all 8 pages + 14 components for real usage (`<table`, `<select`, `<textarea`, no dialogs/tabs/tooltips/progress-bars/alert-banners found anywhere) — are ported verbatim from the DS's dependency-free `.jsx` sources into a fresh `components/ui/` tree, sharing one `useStyle()` helper (WatchTower's equivalent overhaul duplicated this 11 times; this plan extracts it once from the start). `App.tsx`'s inline layout becomes a sidebar (`Shell.tsx`) + top bar (`TopBar.tsx`, carrying the new theme toggle and the existing `DemoModeToggle`).

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3 (arbitrary-value `[var(--x)]` syntax — supported identically to v4 for this purpose), `@playwright/test` (newly added, additive to the existing vitest + Testing Library suite — that suite is untouched by this plan).

## Global Constraints

- Foundry has **no existing `components/ui/` layer** — unlike WatchTower's equivalent Phase 1a, there is nothing to preserve for backward compatibility. This is a net-new build, not a restyle-in-place.
- Foundry has **no light mode today** (dark-only, no toggle exists anywhere in the code). This plan builds a real toggle from scratch: `<html class="dark">` by default, `.light` on toggle, `localStorage` key `"foundry-theme"`.
- **Orange stays Foundry's brand accent** (currently `hover:text-orange-400` on nav links) — this overhaul shares the DS's grayscale chrome/type/spacing/component shapes with WatchTower, not the accent hue. Do not adopt WatchTower's indigo.
- **Zero new runtime npm dependencies** for the ported primitives (DS components use a `useStyle()` hook injecting scoped `<style>` tags — no Radix, no `class-variance-authority`). Only `@playwright/test` is added, as a devDependency.
- Foundry's frontend has no corporate-registry lockfile issue (confirmed: `frontend/package-lock.json` has zero references to any non-public registry, `npm config get registry` already resolves to `https://registry.npmjs.org/`, and a plain `npm install` was verified working during planning) — **use plain `npm install` throughout this plan, no `--package-lock=false` workaround needed** (that was a WatchTower-specific environment issue, not applicable here).
- Confirmed by grepping all 8 pages (`PortfolioHomePage`, `QueuePage`, `ProjectsPage`, `ProjectDetailPage`, `RunsHomePage`, `RunDetailPage`, `KnowledgePage`, `FleetPage`, `MetricsPage`, `PacksPage`) and 14 components for real usage before deciding what to port: `<table` → `MetricsPage.tsx`; `<select` → `ProjectDetailPage.tsx`, `NewRunForm.tsx`; `<textarea` → `GateCard.tsx`. **No** `createPortal`, `role="dialog"`, tabs, tooltips, `<img>`/avatar usage, hand-rolled progress bars, or styled error/alert banners exist anywhere (the two `isError` usages found in `MetricsPage.tsx`/`ProjectDetailPage.tsx` render plain unstyled text, not banners). Hence this plan ports **only** `Button`, `Input`, `Textarea`, `Label`, `Select`, `Table` — no Dialog, DropdownMenu, Tabs, Tooltip, Avatar, Progress, or Alert (YAGNI; a later page-migration phase can add any of these if it turns out to need one, the same discipline that caught WatchTower's original 17-component over-scope down to 11).
- `getComputedStyle()`-based color assertions in Playwright must use the paint-into-canvas + `getImageData()` normalization pattern from the start — WatchTower's equivalent overhaul discovered (the hard way, across two fix rounds) that this machine's Chromium serializes oklch-authored colors as `oklch(...)` text, and even a `<canvas>` `fillStyle`-getter round-trip doesn't reliably normalize it; only reading back the canvas's actual rasterized pixel buffer does.
- Every task ends with `npx tsc -b` (zero errors), `npm run lint` if configured (check `package.json` — if no lint script exists, skip; do not add one, out of scope), `npx vitest run` (must stay fully green — this plan never touches existing `*.test.tsx` files, so this is a pure regression check), and its own new/extended Playwright spec passing via `npx playwright test e2e/<file>.spec.ts`.
- Dev commands (confirmed from `README.md`, not assumed): backend `uv run foundry serve --db <path> --port 8000`, health check `GET /api/_health` (confirmed at `src/foundry/api/app.py:64`), frontend `npm run dev` (Vite default port `5173`, proxies `/api` to `:8000` per `frontend/vite.config.ts`).

---

## File Structure

```
frontend/
  playwright.config.ts            -- new
  package.json                    -- modified (devDependency + test:e2e script)
  e2e/
    foundation.spec.ts            -- new, grows across all 7 tasks
    utils/
      color.ts                    -- new: shared computed-color normalization helper
  public/fonts/
    Geist-Variable.woff2          -- new
    GeistMono-Variable.woff2      -- new
  src/
    index.css                     -- rewritten (currently 3 lines of bare @tailwind directives)
    App.tsx                       -- rewritten (Shell + TopBar composition; route table unchanged)
    tokens/
      status.css                  -- new (the few real status-state tokens actually needed)
    pages/
      dev/
        UiKit.tsx                 -- new: living style-guide page + Playwright render target
    components/
      Shell.tsx                   -- new: sidebar
      TopBar.tsx                  -- new: top bar (relocated theme toggle + existing DemoModeToggle)
      ui/
        useStyle.ts                -- new: shared style-injection hook (used by all 6 ported primitives)
        display/
          Table.tsx                -- new (ported from DS)
        forms/
          Button.tsx                -- new (ported from DS)
          Input.tsx                 -- new (ported from DS)
          Textarea.tsx               -- new (ported from DS)
          Label.tsx                  -- new (ported from DS)
          Select.tsx                 -- new (ported from DS)
        index.ts                   -- new: barrel re-exporting everything
```

No file outside this list is touched. `App.tsx`'s route table (all 10 `<Route>` entries) is unchanged — only the surrounding layout markup changes. `DemoModeToggle.tsx` itself is **not** restyled by this plan (it's an existing component, out of scope) — it's only relocated into `TopBar.tsx` unchanged, same as WatchTower's `HealthDot`/`GheBadge` were relocated-not-restyled-in-logic in its Task 11.

---

### Task 1: Playwright setup

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `npx playwright test e2e/foundation.spec.ts` as the verification command every later task appends to. `webServer` config later tasks rely on (backend on `127.0.0.1:8000`, frontend on `127.0.0.1:5173`).

- [ ] **Step 1: Install `@playwright/test` and the browser binary**

```bash
cd frontend
npm install -D @playwright/test
npx playwright install chromium
```

- [ ] **Step 2: Add the config**

Create `frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5173",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "cd .. && uv run foundry serve --db /tmp/foundry-e2e.db --port 8000",
      url: "http://127.0.0.1:8000/api/_health",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
```

(`--host 127.0.0.1` on the frontend command: WatchTower's equivalent overhaul found Vite defaults to IPv6 `localhost` binding on some systems while Playwright's `webServer` health check expects IPv4 — pinning it here avoids rediscovering that.)

- [ ] **Step 3: Add the `test:e2e` script**

In `frontend/package.json`, add to `"scripts"`:

```json
    "test:e2e": "playwright test"
```

- [ ] **Step 4: Write the baseline smoke spec**

Create `frontend/e2e/foundation.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test.describe("Foundation — app boots", () => {
  test("home page loads and renders the Foundry brand", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Foundry/);
  });
});
```

- [ ] **Step 5: Run it, verify pass**

Run: `cd frontend && npx playwright test e2e/foundation.spec.ts`
Expected: `1 passed`. This also proves `webServer` correctly boots both the backend (a fresh temp SQLite db at `/tmp/foundry-e2e.db`) and frontend — every later task's spec depends on this working.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add package.json package-lock.json playwright.config.ts e2e/foundation.spec.ts
git commit -m "test: install @playwright/test, add foundation smoke spec"
```

---

### Task 2: Token layer + real theme toggle (net-new)

**Files:**
- Create: `frontend/public/fonts/Geist-Variable.woff2`, `frontend/public/fonts/GeistMono-Variable.woff2`
- Create: `frontend/src/tokens/status.css`
- Create: `frontend/e2e/utils/color.ts`
- Modify: `frontend/src/index.css` (full rewrite, currently 3 lines)
- Modify: `frontend/index.html` (add theme-bootstrap inline script — WatchTower's overhaul discovered a first-paint flash-of-wrong-theme without this, folding the fix in from the start here)
- Modify: `frontend/e2e/foundation.spec.ts`
- Modify: `frontend/vitest.config.ts` (exclude `e2e/**` — see Step 6b below)

**Interfaces:**
- Consumes: nothing new.
- Produces: CSS custom properties every later task's ported primitive reads: `--background`, `--foreground`, `--card`, `--card-foreground`, `--popover`, `--popover-foreground`, `--primary`, `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--muted`, `--muted-foreground`, `--accent`, `--accent-foreground`, `--destructive`, `--destructive-foreground`, `--border`, `--input`, `--ring`, `--radius-sm/md/lg/xl/2xl/3xl/full`, `--shadow-2xs/xs/sm/md/lg/xl/2xl`, `--text-xs/sm/base/lg/xl` (+ `-lh` pairs), `--font-sans`, `--font-mono`, `--status-success`, `--status-warning`, `--status-danger`. `<html class="dark">` present by default. `normalizeColor(page, colorStr)` / `luminance(rgb)` from `frontend/e2e/utils/color.ts` — every later task that asserts on a computed CSS color uses these.

- [ ] **Step 1: Fetch the DS's font files and place them**

Use the DesignSync tool (already configured in this environment) to pull them from the design-system project directly onto disk:

```
DesignSync.get_file(projectId: "d67e7e16-2592-454b-bd45-945efaf7829e", path: "assets/fonts/Geist-Variable.woff2")
DesignSync.get_file(projectId: "d67e7e16-2592-454b-bd45-945efaf7829e", path: "assets/fonts/GeistMono-Variable.woff2")
```

Both return `isBase64: true` content — decode and write to `frontend/public/fonts/Geist-Variable.woff2` and `frontend/public/fonts/GeistMono-Variable.woff2`.

- [ ] **Step 2: Rewrite `frontend/src/index.css`**

Replace the entire file (currently just the three `@tailwind` lines). **`@import` must be the very first statement(s) in a CSS file, before any other rule (including `@tailwind`)** — a trailing `@import` is spec-invalid and Vite silently drops it rather than erroring, which would leave `--status-success`/`--status-warning`/`--status-danger` never actually reaching the browser despite the file looking correct at a glance:

```css
@import "./tokens/status.css";

@tailwind base;
@tailwind components;
@tailwind utilities;

/* ---------------------------------------------------------------- */
/* Fonts — Geist (sans/headings) + Geist Mono (code), self-hosted.   */
/* ---------------------------------------------------------------- */
@font-face {
  font-family: "Geist";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("/fonts/Geist-Variable.woff2") format("woff2");
}
@font-face {
  font-family: "Geist Mono";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("/fonts/GeistMono-Variable.woff2") format("woff2");
}

:root {
  --font-sans: "Geist", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo,
    Consolas, "Liberation Mono", monospace;

  /* Type scale */
  --text-xs: 0.75rem;   --text-xs-lh: 1rem;
  --text-sm: 0.875rem;  --text-sm-lh: 1.25rem;
  --text-base: 1rem;    --text-base-lh: 1.5rem;
  --text-lg: 1.125rem;  --text-lg-lh: 1.75rem;
  --text-xl: 1.25rem;   --text-xl-lh: 1.75rem;

  /* Radius */
  --radius: 0.625rem;
  --radius-sm: calc(var(--radius) * 0.6);
  --radius-md: calc(var(--radius) * 0.8);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) * 1.4);
  --radius-2xl: calc(var(--radius) * 1.8);
  --radius-3xl: calc(var(--radius) * 2.2);
  --radius-full: 9999px;

  /* Shadows */
  --shadow-2xs: 0 1px rgb(0 0 0 / 0.05);
  --shadow-xs: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-sm: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
  --shadow-xl: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
  --shadow-2xl: 0 25px 50px -12px rgb(0 0 0 / 0.25);

  /* Colors — light (source: DS tokens/colors.css, shadcn "new-york"/Neutral) */
  --background: oklch(1 0 0);
  --foreground: oklch(0% 0 0);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0% 0 0);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0% 0 0);
  --primary: oklch(0% 0 0);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.97 0 0);
  --secondary-foreground: oklch(0.205 0 0);
  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);
  --accent: oklch(0.97 0 0);
  --accent-foreground: oklch(0.205 0 0);
  --destructive: oklch(0.577 0.245 27.325);
  --destructive-foreground: oklch(0.97 0.01 17);
  --border: oklch(0.922 0 0);
  --input: oklch(0.922 0 0);
  --ring: oklch(0.708 0 0);
  --sidebar: oklch(0.985 0 0);
  --sidebar-foreground: oklch(0% 0 0);
  --sidebar-accent: oklch(0.97 0 0);
  --sidebar-accent-foreground: oklch(0.205 0 0);
  --sidebar-border: oklch(0.922 0 0);
}

html.dark {
  color-scheme: dark;
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.205 0 0);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.205 0 0);
  --popover-foreground: oklch(0.985 0 0);
  --primary: oklch(0.922 0 0);
  --primary-foreground: oklch(0.205 0 0);
  --secondary: oklch(0.269 0 0);
  --secondary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.269 0 0);
  --muted-foreground: oklch(0.708 0 0);
  --accent: oklch(0.371 0 0);
  --accent-foreground: oklch(0.985 0 0);
  --destructive: oklch(0.704 0.191 22.216);
  --destructive-foreground: oklch(0.58 0.22 27);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.556 0 0);
  --sidebar: oklch(0.205 0 0);
  --sidebar-foreground: oklch(0.985 0 0);
  --sidebar-accent: oklch(0.269 0 0);
  --sidebar-accent-foreground: oklch(0.985 0 0);
  --sidebar-border: oklch(1 0 0 / 10%);
}

html {
  font-family: var(--font-sans);
}

body {
  background: var(--background);
  color: var(--foreground);
}
```

(`@import "./tokens/status.css";` is already at the top of the file above — do not add a second copy at the end.)

- [ ] **Step 3: Create `frontend/src/tokens/status.css`**

```css
:root {
  --status-success: oklch(0.696 0.17 162);   /* emerald — gate approved / run done */
  --status-warning: oklch(0.769 0.188 70);   /* amber — needs attention */
  --status-danger: var(--destructive);       /* reuse the DS's existing red */
}

html.dark {
  --status-success: oklch(0.75 0.15 162);
  --status-warning: oklch(0.809 0.164 70);
}
```

- [ ] **Step 4: Create `frontend/e2e/utils/color.ts`**

```ts
import type { Page } from "@playwright/test";

/**
 * Normalize any CSS color string (rgb(), oklch(), etc.) to sRGB bytes by
 * painting it into a 1x1 canvas and reading back getImageData(). Reliable
 * regardless of input color space or how a given browser serializes
 * getComputedStyle() output as text -- unlike a canvas fillStyle *getter*
 * round-trip, which some Chromium builds don't normalize at all.
 */
export async function normalizeColor(page: Page, colorStr: string): Promise<[number, number, number]> {
  const [r, g, b] = await page.evaluate((c) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = c;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3));
  }, colorStr);
  return [r, g, b];
}

/** Perceived luminance (0-255 scale) from sRGB bytes. */
export function luminance([r, g, b]: [number, number, number]): number {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}
```

- [ ] **Step 5: Add a theme-bootstrap script to `frontend/index.html`**

Prevents a flash of the wrong theme on first paint (the class must be set before any CSS renders, not after React hydrates). Insert right after the viewport `<meta>` tag, before `<title>`:

```html
    <script>
      (function () {
        var t = localStorage.getItem("foundry-theme");
        document.documentElement.classList.add(t === "light" ? "light" : "dark");
      })();
    </script>
```

The full file becomes:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <script>
      (function () {
        var t = localStorage.getItem("foundry-theme");
        document.documentElement.classList.add(t === "light" ? "light" : "dark");
      })();
    </script>
    <title>Foundry</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Append the theme Playwright test**

Append to `frontend/e2e/foundation.spec.ts`. Add the import at the top of the file, alongside the existing `@playwright/test` import:

```ts
import { normalizeColor, luminance } from "./utils/color";
```

Then append:

```ts
test.describe("Foundation — token layer", () => {
  test("dark is the default theme, class-based", async ({ page }) => {
    await page.goto("/");
    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("dark");

    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bg);
    expect(luminance(rgb)).toBeLessThan(60);
  });
});
```

(This task only proves dark-by-default and the token plumbing — the toggle button itself doesn't exist until Task 7's `TopBar`, so a toggle-interaction test belongs there, not here.)

- [ ] **Step 6b: Exclude `e2e/` from vitest's test collection**

Latent since Task 1 (which never ran `npx vitest run` as part of its own verification, so this went unnoticed): vitest's default `include` glob picks up any `*.spec.ts`/`*.test.ts` file, which means it was already trying to collect `frontend/e2e/foundation.spec.ts` and crashing on Playwright's `test.describe()` (a different `test`/`describe` than vitest's own globals) — exit code 1 despite every actual vitest test passing. Fix by excluding `e2e/` from vitest's `test.exclude`.

Read `frontend/vitest.config.ts`'s current content first, then add `"e2e/**"` to its `exclude` array (spread `configDefaults.exclude` first so vitest's own default excludes — `node_modules`, `dist`, etc. — are preserved, not replaced):

```ts
import { configDefaults, defineConfig } from "vitest/config";
// ...existing imports (react plugin, etc.) stay as they are

export default defineConfig({
  // ...existing plugins/config stay as they are
  test: {
    // ...existing test config (environment, setupFiles, globals) stay as they are
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
```

Add the `configDefaults` import from `"vitest/config"` alongside the existing `defineConfig` import if not already present.

- [ ] **Step 7: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no type errors, existing vitest suite fully green (unaffected — no source file it tests was touched), `2 passed` for Playwright.

- [ ] **Step 8: Commit**

```bash
git add public/fonts src/index.css src/tokens/status.css index.html e2e/foundation.spec.ts e2e/utils/color.ts vitest.config.ts
git commit -m "feat(ui): add DS oklch token layer, .dark-class theming, FOUC-safe bootstrap"
```

---

### Task 3: Shared `useStyle` helper + port `Button`, create the UI-kit gallery page

**Files:**
- Create: `frontend/src/components/ui/useStyle.ts`
- Create: `frontend/src/components/ui/forms/Button.tsx`
- Create: `frontend/src/pages/dev/UiKit.tsx`
- Create: `frontend/src/components/ui/index.ts`
- Modify: `frontend/src/App.tsx` (add `/dev/ui-kit` route only — no nav link, no layout change yet)
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: `--primary`, `--primary-foreground`, `--destructive`, `--background`, `--border`, `--accent`, `--accent-foreground`, `--secondary`, `--secondary-foreground`, `--ring`, `--radius-md`, `--shadow-xs`, `--font-sans`, `--text-sm` from Task 2.
- Produces: `useStyle(id, css)` — the shared style-injection hook every later ported primitive imports (WatchTower's equivalent overhaul duplicated this 11 times; this plan shares it from the start). `Button` (props: `variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"`, `size?: "default" | "sm" | "lg" | "xs" | "icon" | "icon-sm" | "icon-lg"`, plus native `<button>` attributes). `UiKit.tsx` at route `/dev/ui-kit`, a living reference page every subsequent task appends a section to.

- [ ] **Step 1: `frontend/src/components/ui/useStyle.ts`**

```ts
import * as React from "react";

/** Injects a component's CSS once (by element id), so ported primitives can
 * use real :hover/:focus-visible/:disabled selectors while staying
 * dependency-free. Shared by every primitive in components/ui/ -- do not
 * duplicate this per-component. */
export function useStyle(id: string, css: string) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement("style");
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
```

- [ ] **Step 2: `frontend/src/components/ui/forms/Button.tsx`**

Ported from the DS (`components/forms/Button.jsx` + `Button.d.ts`), converted to TSX and using the shared `useStyle`:

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-btn{
  display:inline-flex;align-items:center;justify-content:center;gap:.5rem;
  flex-shrink:0;white-space:nowrap;cursor:pointer;
  font-family:var(--font-sans);font-size:var(--text-sm);font-weight:500;
  line-height:var(--text-sm-lh);border-radius:var(--radius-md);
  border:1px solid transparent;outline:none;
  transition:background-color .15s ease,color .15s ease,border-color .15s ease,box-shadow .15s ease,opacity .15s ease;
}
.ds-btn svg{width:1rem;height:1rem;flex-shrink:0;pointer-events:none}
.ds-btn:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-btn:disabled{pointer-events:none;opacity:.5}
.ds-btn:active{opacity:.9}

.ds-btn[data-size="default"]{height:2.25rem;padding:.5rem 1rem}
.ds-btn[data-size="sm"]{height:2rem;padding:0 .75rem;gap:.375rem}
.ds-btn[data-size="lg"]{height:2.5rem;padding:0 1.5rem}
.ds-btn[data-size="xs"]{height:1.5rem;padding:0 .5rem;font-size:var(--text-xs);gap:.25rem}
.ds-btn[data-size="icon"]{width:2.25rem;height:2.25rem;padding:0}
.ds-btn[data-size="icon-sm"]{width:2rem;height:2rem;padding:0}
.ds-btn[data-size="icon-lg"]{width:2.5rem;height:2.5rem;padding:0}

.ds-btn[data-variant="default"]{background:var(--primary);color:var(--primary-foreground)}
.ds-btn[data-variant="default"]:hover{background:color-mix(in oklab,var(--primary) 90%,transparent)}
.ds-btn[data-variant="destructive"]{background:var(--destructive);color:#fff}
.ds-btn[data-variant="destructive"]:hover{background:color-mix(in oklab,var(--destructive) 90%,transparent)}
.ds-btn[data-variant="outline"]{background:var(--background);border-color:var(--border);box-shadow:var(--shadow-xs);color:var(--foreground)}
.ds-btn[data-variant="outline"]:hover{background:var(--accent);color:var(--accent-foreground)}
.ds-btn[data-variant="secondary"]{background:var(--secondary);color:var(--secondary-foreground)}
.ds-btn[data-variant="secondary"]:hover{background:color-mix(in oklab,var(--secondary) 80%,transparent)}
.ds-btn[data-variant="ghost"]{background:transparent;color:var(--foreground)}
.ds-btn[data-variant="ghost"]:hover{background:var(--accent);color:var(--accent-foreground)}
.ds-btn[data-variant="link"]{background:transparent;color:var(--primary);text-underline-offset:4px}
.ds-btn[data-variant="link"]:hover{text-decoration:underline}
`;

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "xs" | "icon" | "icon-sm" | "icon-lg";
}

export function Button({
  variant = "default",
  size = "default",
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  useStyle("ds-button", CSS);
  return (
    <button
      type={type}
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={`ds-btn ${className}`}
      {...props}
    />
  );
}
```

- [ ] **Step 3: `frontend/src/pages/dev/UiKit.tsx`** — create the gallery page with its first section

```tsx
import { Button } from "../../components/ui/forms/Button";

/**
 * Living reference for every DS-ported primitive in this app. Not linked
 * from the nav (dev-only route) -- visit /dev/ui-kit directly. Each
 * Foundation task appends its own section here.
 */
export default function UiKit() {
  return (
    <div className="mx-auto max-w-4xl space-y-10 p-8">
      <h1 className="text-2xl font-semibold text-[var(--foreground)]">UI Kit</h1>

      <section data-testid="uikit-button" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Button
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">Link</Button>
          <Button size="sm">Small</Button>
          <Button size="lg">Large</Button>
          <Button disabled>Disabled</Button>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Wire the route in `App.tsx`**

Add the import near the other page imports:

```tsx
import UiKit from "./pages/dev/UiKit";
```

Add the route inside `<Routes>` (any position, e.g. right after the `/packs` route):

```tsx
<Route path="/dev/ui-kit" element={<UiKit />} />
```

- [ ] **Step 5: Create the barrel `frontend/src/components/ui/index.ts`**

```ts
export { Button, type ButtonProps } from "./forms/Button";
```

- [ ] **Step 6: Append the Playwright test**

```ts
test.describe("Foundation — Button", () => {
  test("renders all variants and sizes on /dev/ui-kit", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-button");
    await expect(section.getByRole("button", { name: "Default" })).toBeVisible();
    await expect(section.getByRole("button", { name: "Disabled" })).toBeDisabled();

    const destructive = section.getByRole("button", { name: "Destructive" });
    const defaultBtn = section.getByRole("button", { name: "Default" });
    const [destructiveBg, defaultBg] = await Promise.all([
      destructive.evaluate((el) => getComputedStyle(el).backgroundColor),
      defaultBtn.evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(destructiveBg).not.toBe(defaultBg);
  });
});
```

- [ ] **Step 7: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no errors, vitest still fully green, `3 passed` for Playwright.

- [ ] **Step 8: Commit**

```bash
git add src/components/ui src/pages/dev src/App.tsx e2e/foundation.spec.ts
git commit -m "feat(ui): add shared useStyle helper, port DS Button, add /dev/ui-kit gallery page"
```

---

### Task 4: Port `Input`, `Textarea`, `Label`

**Files:**
- Create: `frontend/src/components/ui/forms/Input.tsx`
- Create: `frontend/src/components/ui/forms/Textarea.tsx`
- Create: `frontend/src/components/ui/forms/Label.tsx`
- Modify: `frontend/src/pages/dev/UiKit.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: `--foreground`, `--muted-foreground`, `--input`, `--ring`, `--destructive`, `--radius-md`, `--shadow-xs`, `useStyle` from Tasks 2-3.
- Produces: `Input`, `Textarea`, `Label` — a later page-migration phase uses these for `NewRunForm.tsx`'s and `GateCard.tsx`'s form fields.

- [ ] **Step 1: `frontend/src/components/ui/forms/Input.tsx`**

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-input{
  display:flex;width:100%;min-width:0;height:2.25rem;
  padding:.25rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-input::placeholder{color:var(--muted-foreground)}
.ds-input:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-input:disabled{cursor:not-allowed;opacity:.5}
.ds-input[aria-invalid="true"]{border-color:var(--destructive);box-shadow:0 0 0 3px color-mix(in oklab,var(--destructive) 20%,transparent)}
.ds-input[data-size="sm"]{height:2rem}
`;

// Omit the native "size" attribute (a number, HTML's visual width in
// characters) -- it would otherwise conflict with our own `size` prop
// below, which takes a different type ("sm").
export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: "sm";
}

export function Input({ className = "", size, ...props }: InputProps) {
  useStyle("ds-input", CSS);
  return <input data-slot="input" data-size={size} className={`ds-input ${className}`} {...props} />;
}
```

- [ ] **Step 2: `frontend/src/components/ui/forms/Textarea.tsx`**

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-textarea{
  display:flex;width:100%;min-width:0;min-height:4rem;
  padding:.5rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;resize:vertical;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-textarea::placeholder{color:var(--muted-foreground)}
.ds-textarea:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-textarea:disabled{cursor:not-allowed;opacity:.5}
.ds-textarea[aria-invalid="true"]{border-color:var(--destructive);box-shadow:0 0 0 3px color-mix(in oklab,var(--destructive) 20%,transparent)}
`;

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className = "", ...props }: TextareaProps) {
  useStyle("ds-textarea", CSS);
  return <textarea data-slot="textarea" className={`ds-textarea ${className}`} {...props} />;
}
```

- [ ] **Step 3: `frontend/src/components/ui/forms/Label.tsx`**

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-label{
  display:inline-flex;align-items:center;gap:.5rem;
  font-family:var(--font-sans);font-size:var(--text-sm);font-weight:500;
  line-height:1;color:var(--foreground);user-select:none;
}
.ds-label[data-disabled="true"]{opacity:.5;cursor:not-allowed}
`;

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  disabled?: boolean;
}

export function Label({ className = "", disabled, ...props }: LabelProps) {
  useStyle("ds-label", CSS);
  return <label data-slot="label" data-disabled={disabled} className={`ds-label ${className}`} {...props} />;
}
```

- [ ] **Step 4: Extend `UiKit.tsx`**

Add the import:

```tsx
import { Input } from "../../components/ui/forms/Input";
import { Textarea } from "../../components/ui/forms/Textarea";
import { Label } from "../../components/ui/forms/Label";
```

Append a new section before the closing `</div>`:

```tsx
<section data-testid="uikit-form-fields" className="space-y-3">
  <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
    Input / Textarea / Label
  </h2>
  <div className="max-w-sm space-y-3">
    <div>
      <Label htmlFor="uikit-input">Name</Label>
      <Input id="uikit-input" placeholder="Jane Doe" className="mt-1.5" />
    </div>
    <div>
      <Label htmlFor="uikit-textarea">Description</Label>
      <Textarea id="uikit-textarea" placeholder="Say something…" className="mt-1.5" />
    </div>
    <Input aria-invalid="true" defaultValue="invalid value" />
  </div>
</section>
```

- [ ] **Step 5: Extend the barrel**

```ts
export { Input, type InputProps } from "./forms/Input";
export { Textarea, type TextareaProps } from "./forms/Textarea";
export { Label, type LabelProps } from "./forms/Label";
```

- [ ] **Step 6: Append the Playwright test**

```ts
test.describe("Foundation — Input/Textarea/Label", () => {
  test("form fields render and accept input", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-form-fields");
    const input = section.getByLabel("Name");
    await input.fill("Test User");
    await expect(input).toHaveValue("Test User");

    const invalid = section.locator('[aria-invalid="true"]');
    const [invalidBorder, validBorder] = await Promise.all([
      invalid.evaluate((el) => getComputedStyle(el).borderColor),
      input.evaluate((el) => getComputedStyle(el).borderColor),
    ]);
    expect(invalidBorder).not.toBe(validBorder);
  });
});
```

- [ ] **Step 7: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no errors, `4 passed` for Playwright.

- [ ] **Step 8: Commit**

```bash
git add src/components/ui src/pages/dev/UiKit.tsx e2e/foundation.spec.ts
git commit -m "feat(ui): port DS Input, Textarea, Label"
```

---

### Task 5: Port `Select`

**Files:**
- Create: `frontend/src/components/ui/forms/Select.tsx`
- Modify: `frontend/src/pages/dev/UiKit.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: `--foreground`, `--muted-foreground`, `--input`, `--ring`, `--radius-md`, `--shadow-xs`, `useStyle` from Tasks 2-3.
- Produces: `Select` (wraps a native `<select>`) — a later page-migration phase replaces `ProjectDetailPage.tsx`'s and `NewRunForm.tsx`'s native `<select>` elements with this.

- [ ] **Step 1: `frontend/src/components/ui/forms/Select.tsx`**

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-select-wrap{position:relative;display:inline-flex;align-items:center;width:fit-content}
.ds-select{
  appearance:none;-webkit-appearance:none;
  display:flex;align-items:center;width:100%;height:2.25rem;
  padding:.5rem 2rem .5rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;cursor:pointer;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-select:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-select:disabled{cursor:not-allowed;opacity:.5}
.ds-select[data-size="sm"]{height:2rem}
.ds-select-icon{
  position:absolute;right:.625rem;width:1rem;height:1rem;pointer-events:none;
  color:var(--muted-foreground);
}
`;

// Same "size" collision as InputProps -- native size is a number, ours is
// a string union. Omit it.
export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size?: "default" | "sm";
  wrapClassName?: string;
}

export function Select({ className = "", size = "default", wrapClassName = "", children, ...props }: SelectProps) {
  useStyle("ds-select", CSS);
  return (
    <span className={`ds-select-wrap ${wrapClassName}`}>
      <select data-slot="select" data-size={size} className={`ds-select ${className}`} {...props}>
        {children}
      </select>
      <svg className="ds-select-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </span>
  );
}
```

- [ ] **Step 2: Extend `UiKit.tsx`**

Add the import:

```tsx
import { Select } from "../../components/ui/forms/Select";
```

Append:

```tsx
<section data-testid="uikit-select" className="space-y-3">
  <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
    Select
  </h2>
  <Select defaultValue="active" wrapClassName="w-56">
    <option value="active">Active</option>
    <option value="paused">Paused</option>
    <option value="archived">Archived</option>
  </Select>
</section>
```

- [ ] **Step 3: Extend the barrel**

```ts
export { Select, type SelectProps } from "./forms/Select";
```

- [ ] **Step 4: Append the Playwright test**

```ts
test.describe("Foundation — Select", () => {
  test("renders and changes value", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const select = page.getByTestId("uikit-select").locator("select");
    await expect(select).toHaveValue("active");
    await select.selectOption("paused");
    await expect(select).toHaveValue("paused");
  });
});
```

- [ ] **Step 5: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no errors, `5 passed` for Playwright.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui src/pages/dev/UiKit.tsx e2e/foundation.spec.ts
git commit -m "feat(ui): port DS Select"
```

---

### Task 6: Port `Table` (+ slots)

**Files:**
- Create: `frontend/src/components/ui/display/Table.tsx`
- Modify: `frontend/src/pages/dev/UiKit.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: `--border`, `--muted-foreground`, `--foreground`, `--muted`, `--text-sm`, `useStyle` from Tasks 2-3.
- Produces: `Table`, `TableHeader`, `TableBody`, `TableFooter`, `TableRow`, `TableHead`, `TableCell`, `TableCaption` — a later page-migration phase replaces `MetricsPage.tsx`'s hand-rolled `<table>` with these.

- [ ] **Step 1: `frontend/src/components/ui/display/Table.tsx`**

```tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-table-wrap{position:relative;width:100%;overflow-x:auto}
.ds-table{width:100%;border-collapse:collapse;caption-side:bottom;font-size:var(--text-sm);color:var(--foreground)}
.ds-table-caption{margin-top:.75rem;font-size:var(--text-sm);color:var(--muted-foreground)}
.ds-thead .ds-tr{border-bottom:1px solid var(--border)}
.ds-th{
  height:2.5rem;padding:0 .625rem;text-align:left;vertical-align:middle;white-space:nowrap;
  font-weight:500;color:var(--muted-foreground);
}
.ds-tbody .ds-tr{border-bottom:1px solid var(--border);transition:background-color .1s}
.ds-tbody .ds-tr:last-child{border-bottom:none}
.ds-tbody .ds-tr:hover{background:color-mix(in oklab,var(--muted) 50%,transparent)}
.ds-tbody .ds-tr[data-state="selected"]{background:var(--muted)}
.ds-td{padding:.625rem;vertical-align:middle}
.ds-tfoot{border-top:1px solid var(--border);background:color-mix(in oklab,var(--muted) 50%,transparent);font-weight:500}
.ds-tfoot .ds-td{padding:.625rem}
`;

export interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  wrapClassName?: string;
}

export function Table({ className = "", wrapClassName = "", ...props }: TableProps) {
  useStyle("ds-table", CSS);
  return (
    <div className={`ds-table-wrap ${wrapClassName}`}>
      <table data-slot="table" className={`ds-table ${className}`} {...props} />
    </div>
  );
}
export function TableHeader({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={`ds-thead ${className}`} {...props} />;
}
export function TableBody({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={`ds-tbody ${className}`} {...props} />;
}
export function TableFooter({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tfoot className={`ds-tfoot ${className}`} {...props} />;
}
export function TableRow({ className = "", ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={`ds-tr ${className}`} {...props} />;
}
export function TableHead({ className = "", ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={`ds-th ${className}`} {...props} />;
}
export function TableCell({ className = "", ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={`ds-td ${className}`} {...props} />;
}
export function TableCaption({ className = "", ...props }: React.HTMLAttributes<HTMLTableCaptionElement>) {
  return <caption className={`ds-table-caption ${className}`} {...props} />;
}
```

- [ ] **Step 2: Extend `UiKit.tsx`**

Add the import:

```tsx
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "../../components/ui/display/Table";
```

Append:

```tsx
<section data-testid="uikit-table" className="space-y-3">
  <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
    Table
  </h2>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Project</TableHead>
        <TableHead>Status</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow>
        <TableCell>rec-app</TableCell>
        <TableCell>Active</TableCell>
      </TableRow>
    </TableBody>
  </Table>
</section>
```

- [ ] **Step 3: Extend the barrel**

```ts
export {
  Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell, TableCaption,
} from "./display/Table";
```

- [ ] **Step 4: Append the Playwright test**

```ts
test.describe("Foundation — Table", () => {
  test("renders header and row content", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const table = page.getByTestId("uikit-table");
    await expect(table.getByText("rec-app")).toBeVisible();
    await expect(table.getByText("Status")).toBeVisible();
  });
});
```

- [ ] **Step 5: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no errors, `6 passed` for Playwright.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui src/pages/dev/UiKit.tsx e2e/foundation.spec.ts
git commit -m "feat(ui): port DS Table"
```

---

### Task 7: Sidebar shell (`Shell.tsx` + `TopBar.tsx` with real theme toggle), wire into `App.tsx`

**Files:**
- Create: `frontend/src/components/Shell.tsx`
- Create: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/App.tsx` (replace the inline layout markup; route table itself unchanged)
- Modify: `frontend/src/pages/dev/UiKit.tsx` (add a `ThemeToggle` demo section — see Step 3b)
- Modify: `frontend/e2e/foundation.spec.ts`
- Modify: `frontend/.gitignore` (add `playwright-report/` and `test-results/` — whole-branch review found these leak untracked into the worktree)
- Modify: `frontend/tsconfig.json`, `frontend/tsconfig.node.json` (include `e2e/` and `playwright.config.ts` in type-checking — whole-branch review found `npx tsc -b`, the gate every prior task ran, never actually typed the e2e directory)

**Interfaces:**
- Consumes: `Button` from Task 3; `--sidebar`, `--sidebar-foreground`, `--sidebar-accent`, `--sidebar-accent-foreground`, `--sidebar-border` from Task 2; `normalizeColor`/`luminance` from Task 2's `e2e/utils/color.ts`.
- Produces: `<Shell>` (sidebar nav) + `<TopBar>` (relocated `DemoModeToggle`; exports `ThemeToggle` but does not mount it — see Step 2's note) — the last piece of Foundation. `App.tsx`'s route table is untouched; only the surrounding chrome changes.

- [ ] **Step 1: `frontend/src/components/Shell.tsx`**

Moves the 8 `NavLink`s out of `App.tsx` into a fixed left sidebar, active-state driven by `react-router-dom`'s own `NavLink` (which already provides `isActive` via its className-callback — simpler than WatchTower's hand-rolled `useLocation` check, since Foundry's original code already used `NavLink` correctly):

```tsx
import { NavLink } from "react-router-dom";

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Portfolio", end: true },
  { to: "/queue", label: "Queue" },
  { to: "/projects", label: "Projects" },
  { to: "/runs", label: "Runs" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/fleet", label: "Fleet" },
  { to: "/metrics", label: "Metrics" },
  { to: "/packs", label: "Packs" },
];

export function Shell() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-shrink-0 flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)]">
      <div className="px-4 py-4 text-[var(--sidebar-foreground)]">
        <span className="text-sm font-semibold tracking-tight">Foundry</span>
      </div>
      <div className="h-px bg-[var(--sidebar-border)]" />
      <nav className="flex flex-col gap-0.5 px-2.5 py-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded-[var(--radius-md)] px-2.5 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)]"
                  : "text-[var(--sidebar-foreground)] opacity-70 hover:opacity-100 hover:bg-[var(--sidebar-accent)]"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 2: `frontend/src/components/TopBar.tsx`**

Builds the theme toggle from scratch (Foundry has none today) and relocates the existing `DemoModeToggle` (unchanged, just moved). `lucide-react` is NOT a dependency of `frontend/package.json` (confirmed during planning) and Global Constraints forbid adding new runtime deps for this — use inline SVG sun/moon icons instead, same pattern as `Select.tsx`'s chevron icon (Task 5):

```tsx
import { useEffect, useState } from "react";
import DemoModeToggle from "./DemoModeToggle";

type Theme = "dark" | "light";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = window.localStorage.getItem("foundry-theme") as Theme | null;
  if (saved === "dark" || saved === "light") return saved;
  return "dark";
}

function SunIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </svg>
  );
}

// Exported (not just used internally) so /dev/ui-kit (Task 3's gallery page)
// can render and exercise it -- see the note below on why TopBar itself
// does not mount it yet.
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
    window.localStorage.setItem("foundry-theme", theme);
  }, [theme]);

  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(next)}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
      className="inline-flex h-7 w-7 items-center justify-center rounded-[var(--radius-full)] border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]"
    >
      {theme === "dark" ? <SunIcon className="h-3.5 w-3.5" /> : <MoonIcon className="h-3.5 w-3.5" />}
    </button>
  );
}

export function TopBar() {
  return (
    // Tailwind v3 cannot apply an opacity modifier to an arbitrary var()
    // color (bg-[var(--background)]/95 silently compiles to nothing --
    // same class of failure as the @import bug Task 2 already hit). Use
    // color-mix() via an inline style instead, matching the pattern the
    // ported DS components already use throughout for hover/hover states.
    <header
      className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b border-[var(--border)] px-6 backdrop-blur-sm"
      style={{ backgroundColor: "color-mix(in oklab, var(--background) 95%, transparent)" }}
    >
      <DemoModeToggle />
      {/* ThemeToggle is intentionally NOT rendered here yet. Whole-branch
          review found ~138 unmigrated slate-* / gray-* Tailwind classes still
          hardcoded across all 8 pages + components -- switching to light
          mode today would render most of the app with near-black text on
          near-black backgrounds, since none of that markup reads the new
          oklch tokens yet. The full toggle mechanism (tokens, bootstrap
          script, this component) IS fully built and tested -- exercised via
          /dev/ui-kit (see Task 3's gallery page) -- it's just not exposed
          in the live app shell until a Phase 2 plan migrates enough pages
          that light mode is actually usable. Mount `<ThemeToggle />` here
          once that's true. */}
    </header>
  );
}
```

(Note: `getInitialTheme()`'s default `"dark"` must match `index.html`'s Task 2 bootstrap script exactly — both check `localStorage.getItem("foundry-theme") === "light"` and default to `"dark"` otherwise. They already do; don't drift them apart.)

- [ ] **Step 3: Rewrite `App.tsx`**

Read the current file's imports and JSX carefully before editing — this step removes the inline `<header>`/`<nav>` block and replaces it with `<Shell />` + `<TopBar />`, but the `<Routes>` block itself must be copied through completely unchanged (all 10 `<Route>` entries, same paths, same components) plus the `/dev/ui-kit` route Task 3 already added.

Remove the now-unused `DemoModeToggle` import from the top of `App.tsx` (it moves into `TopBar.tsx`, which imports it directly) and add:

```tsx
import { Shell } from "./components/Shell";
import { TopBar } from "./components/TopBar";
```

Replace the `return (...)` body of `App()`:

```tsx
export default function App() {
  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <Shell />
      <div className="pl-60">
        <TopBar />
        <main className="p-6">
          <Routes>
            <Route path="/" element={<PortfolioHomePage />} />
            <Route path="/queue" element={<QueuePage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
            <Route path="/runs" element={<RunsHomePage />} />
            <Route path="/runs/:id" element={<RunDetailPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/fleet" element={<FleetPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/packs" element={<PacksPage />} />
            <Route path="/dev/ui-kit" element={<UiKit />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
```

(`pl-60` matches `Shell`'s fixed `w-60` — keeps main content clear of the fixed sidebar.)

- [ ] **Step 3b: Add a `ThemeToggle` demo section to `UiKit.tsx`**

`ThemeToggle` isn't mounted in the live app shell (see the comment in Step 2's `TopBar` above), so it needs a render target for Playwright to exercise it against. Add a section to `frontend/src/pages/dev/UiKit.tsx` (created in Task 3, already has sections from Tasks 3-6 — append, don't disturb them). Add the import:

```tsx
import { ThemeToggle } from "../../components/TopBar";
```

Append a new section:

```tsx
<section data-testid="uikit-theme-toggle" className="space-y-3">
  <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
    Theme Toggle (not yet mounted in the app shell -- see TopBar.tsx)
  </h2>
  <ThemeToggle />
</section>
```

- [ ] **Step 4: Append the Playwright test**

The theme-toggle test targets `/dev/ui-kit` (where `ThemeToggle` actually renders per Step 3b above, not the live app shell) and, per whole-branch review, must prove light mode actually *renders* light — not just that the `html` class flips — and must exercise `index.html`'s bootstrap script's `"light"` branch via a real reload (the default-`"dark"` branch is already covered by Task 2's test; nothing exercised the other branch before this):

```ts
test.describe("Foundation — Shell", () => {
  test("sidebar renders all nav links with correct active state", async ({ page }) => {
    await page.goto("/queue");
    const sidebar = page.locator("aside");
    await expect(sidebar.getByRole("link", { name: "Portfolio" })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Knowledge" })).toBeVisible();
    const queueLink = sidebar.getByRole("link", { name: "Queue" });
    const portfolioLink = sidebar.getByRole("link", { name: "Portfolio" });
    const [queueBg, portfolioBg] = await Promise.all([
      queueLink.evaluate((el) => getComputedStyle(el).backgroundColor),
      portfolioLink.evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(queueBg).not.toBe(portfolioBg);
  });
});

test.describe("Foundation — Theme Toggle (exercised via /dev/ui-kit)", () => {
  test("switches html class, persists the choice, survives reload, and light mode actually renders light", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    await page.getByTitle(/Switch to light theme/i).click();
    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("light");
    const stored = await page.evaluate(() => localStorage.getItem("foundry-theme"));
    expect(stored).toBe("light");

    // Exercises index.html's bootstrap script's "light" branch -- until
    // this reload, only the default-dark branch had ever run in a test.
    await page.reload();
    const htmlClassAfterReload = await page.evaluate(() => document.documentElement.className);
    expect(htmlClassAfterReload).toBe("light");

    // Prove light mode actually paints light, not just that the class is
    // present -- a token regression that left light mode rendering dark
    // would pass a class-only assertion unchanged.
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bg);
    expect(luminance(rgb)).toBeGreaterThan(200);
  });
});
```

- [ ] **Step 4b: Close two verification gaps whole-branch review found**

Neither of these was ever exercised by any prior task's `npx tsc -b` or `npm run test:e2e` run:

1. `frontend/tsconfig.json`'s `include` is `["src"]` — `e2e/` was never type-checked (Playwright transpiles via esbuild, no type errors surfaced even if the code were wrong). Add `"e2e"` to the array.
2. `frontend/tsconfig.node.json`'s `include` is `["vite.config.ts", "vitest.config.ts"]` — add `"playwright.config.ts"`.
3. `frontend/.gitignore` doesn't cover Playwright's own output directories. Add two lines:

```
playwright-report/
test-results/
```

- [ ] **Step 5: Run all checks**

```bash
cd frontend
npx tsc -b
npx vitest run
npx playwright test e2e/foundation.spec.ts
```
Expected: no errors (this run now actually type-checks `e2e/` for the first time), existing vitest suite fully green, `9 passed` for Playwright (8 from before this task's additions + the reworked theme-toggle test, which replaced 1 test with 1 more thorough test, net +1 from Task 6's baseline of 6 plus this task's 2 new specs = 8, then the theme-toggle test itself doesn't add a second test — recount from the actual file if this number drifts; the important thing is zero failures, not matching this exact count).

Also manually verify: `npm run dev`, visit every route (dark mode only — the toggle isn't mounted in the app shell), confirm no console errors and the sidebar/top-bar render correctly, including the top bar's now-translucent background over scrolled content. Separately visit `/dev/ui-kit` and confirm the Theme Toggle section switches to light and back correctly. `DemoModeToggle`'s own existing behavior (whatever it does) must be unaffected — it's relocated, not modified.

- [ ] **Step 6: Commit**

```bash
git add src/components/Shell.tsx src/components/TopBar.tsx src/App.tsx src/pages/dev/UiKit.tsx e2e/foundation.spec.ts .gitignore tsconfig.json tsconfig.node.json
git commit -m "feat(ui): replace top nav with DS sidebar shell + top bar, add real theme toggle"
```

---

## End of Phase 1

At this point: tokens/theme/shell are fully on the DS, 6 DS primitives are ported (scoped to confirmed real usage) and proven via Playwright + the `/dev/ui-kit` gallery, and the existing vitest/Testing Library suite stays green throughout since no page/component file was touched. A later Phase 2 plan migrates the 8 existing pages + 14 components onto these primitives.

**The light/dark theme toggle is fully built (tokens, FOUC-safe bootstrap script, `ThemeToggle` component) but deliberately NOT mounted in the live app shell** — whole-branch review found ~138 unmigrated `slate-*`/`gray-*` Tailwind classes still hardcoded across all 8 pages, which would render as near-unreadable (near-black text on near-black backgrounds) if a user actually switched to light mode today. The toggle is exercised and tested via `/dev/ui-kit` only. Mounting `<ThemeToggle />` in `TopBar.tsx` is a one-line change Phase 2 should make once enough pages are migrated that light mode is genuinely usable — track this explicitly in Phase 2's plan rather than leaving it as an easy-to-forget loose end.
