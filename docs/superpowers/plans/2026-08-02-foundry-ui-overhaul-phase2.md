# Foundry Dashboard UI Overhaul — Phase 2 (Page Migration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all 10 pages + 13 components in `frontend/src/{pages,components}` off hardcoded `slate-*`/`gray-*` Tailwind classes onto the DS token system and Phase 1's primitives, port 3 newly-identified primitives (`Card`, `Badge`, `Sheet`), and mount the theme toggle in the live app shell.

**Architecture:** Bottom-up: new primitives first (Task 1-2), then leaf/display components (Task 3), then the run-detail cluster including the highest-risk `UnitDrawer`/`Sheet` restructuring (Task 4-7), then the remaining page clusters grouped by shared components (Task 8-11), then the theme-toggle mount + final smoke pass (Task 12). Every task is a restyle — same props, same data flow, same DOM roles/testids — verified by the *existing* vitest file for that component/page, not new tests.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3 (arbitrary-value `var()` syntax for tokens, per Phase 1), Vitest + Testing Library, Playwright.

## Global Constraints

- **No behavior change.** Same props, same data flow, same component boundaries, same conditional rendering. Every `data-testid`, `aria-label`, `role`, and visible text string an existing test file queries must be preserved exactly — grep the file's own `*.test.tsx` before editing it, and run that file's suite after.
- **Token pattern (established by Phase 1):** replace `bg-slate-950`/`border-slate-800`/`text-slate-400`/`text-slate-500` etc. with `bg-[var(--card)]`/`border-[var(--border)]`/`text-[var(--muted-foreground)]` etc. Never introduce a new `bg-[var(--x)]/NN` opacity-modifier class (Tailwind v3 silently drops it) — use `color-mix(in oklab, var(--x) NN%, transparent)` via inline `style` instead, exactly as `TopBar.tsx`'s header already does.
- **Brand orange stays raw Tailwind.** `orange-*` classes (`bg-orange-600`, `text-orange-400`, etc.) are NOT tokenized in this plan — they already render correctly in both themes (fixed hue, not derived from a light/dark-assuming shade), and Phase 1 already shipped `DemoModeToggle.tsx` with `bg-orange-600` reviewed clean. Only classes that assume a dark background (`slate-*`, `gray-*`) get tokenized.
- **Semantic status tokens already exist** (`frontend/src/tokens/status.css`, from Phase 1): `--status-success` (emerald, gate approved/run done), `--status-warning` (amber, needs attention), and `--status-danger` = `var(--destructive)`. Use these for closed/blocked/failed semantics — do not invent new hex or a fourth status color.
- **New primitives follow the exact established shape**: a module-scoped `CSS` string, `useStyle(id, css)` from `frontend/src/components/ui/useStyle.ts`, a `data-slot` attribute on the root element, `data-variant`/`data-size`/etc. attributes for CSS-selector-driven variants (never conditional Tailwind class strings for variant logic). Register every new export in `frontend/src/components/ui/index.ts`.
- **No new dependencies.** No Radix, no class-variance-authority, no new npm packages.
- Run from `frontend/`: `npx tsc -b`, `npm run test -- <file>` (vitest), `npx playwright test <file>` (after `npm run build` if testing production assets isn't needed — dev server is fine for these).

## File Structure

New files:
- `frontend/src/components/ui/display/Card.tsx` — outer panel shell only (no Card­Header/Title/Content/Footer — none of the 23 files use a multi-section card layout; adding them would be speculative).
- `frontend/src/components/ui/display/Badge.tsx` — pill label, DS's 4 base `variant`s plus a Foundry-specific `tone` prop (`"success" | "warning"`) for the two semantic status tones the DS itself doesn't define.
- `frontend/src/components/ui/overlay/Sheet.tsx` — compound slide-over (`Sheet`, `SheetTrigger`, `SheetContent`, `SheetHeader`, `SheetTitle`, `SheetDescription`, `SheetFooter`, `SheetClose`), ported from the DS verbatim (structure/behavior unchanged, only the inline `useStyle` helper duplicate removed in favor of the shared one).

Modified: all 10 files in `frontend/src/pages/` except none are skipped; all 13 non-`ui` files in `frontend/src/components/` except `Shell.tsx`/`TopBar.tsx` (already migrated in Phase 1) — `TopBar.tsx` is touched once more in Task 12 only, to mount `<ThemeToggle />`. `frontend/src/components/ui/index.ts`, `frontend/src/components/ui/forms/Button.tsx` (new `success` variant), `frontend/src/pages/dev/UiKit.tsx`, `frontend/e2e/foundation.spec.ts`.

---

### Task 1: Card + Badge primitives

**Files:**
- Create: `frontend/src/components/ui/display/Card.tsx`
- Create: `frontend/src/components/ui/display/Badge.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/src/pages/dev/UiKit.tsx`
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Produces: `Card({ className, ...divProps })` — renders `<div data-slot="card">`, CSS supplies `background`/`color`/`border`/`border-radius` only (no padding, no shadow — consumers supply their own layout/padding via `className`, exactly as today's `rounded border border-slate-800 …` divs do).
- Produces: `Badge({ variant = "default", tone, className, ...spanProps })` — `variant: "default" | "secondary" | "destructive" | "outline"` (DS parity), `tone?: "success" | "warning"` (Foundry extension; when set, overrides the background/color the `variant` would otherwise apply).

- [ ] **Step 1: Create the Card primitive**

```tsx
// frontend/src/components/ui/display/Card.tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-card{
  background:var(--card);color:var(--card-foreground);
  border:1px solid var(--border);border-radius:var(--radius-md);
}
`;

export type CardProps = React.HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  useStyle("ds-card", CSS);
  return <div data-slot="card" className={`ds-card ${className}`} {...props} />;
}
```

- [ ] **Step 2: Create the Badge primitive**

```tsx
// frontend/src/components/ui/display/Badge.tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-badge{
  display:inline-flex;align-items:center;justify-content:center;gap:.25rem;
  width:fit-content;white-space:nowrap;
  padding:.125rem .5rem;
  font-family:var(--font-sans);font-size:var(--text-xs);font-weight:500;line-height:1.25;
  border:1px solid transparent;border-radius:var(--radius-full);
}
.ds-badge[data-variant="default"]{background:var(--primary);color:var(--primary-foreground)}
.ds-badge[data-variant="secondary"]{background:var(--secondary);color:var(--secondary-foreground)}
.ds-badge[data-variant="destructive"]{background:var(--destructive);color:#fff}
.ds-badge[data-variant="outline"]{border-color:var(--border);color:var(--foreground)}
.ds-badge[data-tone="success"]{background:color-mix(in oklab, var(--status-success) 20%, transparent);color:var(--status-success)}
.ds-badge[data-tone="warning"]{background:color-mix(in oklab, var(--status-warning) 20%, transparent);color:var(--status-warning)}
`;

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "outline";
  tone?: "success" | "warning";
}

export function Badge({ variant = "default", tone, className = "", ...props }: BadgeProps) {
  useStyle("ds-badge", CSS);
  return <span data-slot="badge" data-variant={variant} data-tone={tone} className={`ds-badge ${className}`} {...props} />;
}
```

`data-tone`'s CSS rules are declared after `data-variant`'s in the same stylesheet, so for equal specificity (`[data-variant]` vs `[data-tone]`, both single attribute selectors) the tone rule wins when both attributes are present — `variant` still sets the base shape, `tone` overrides only the color pair.

- [ ] **Step 3: Register both in the barrel export**

```ts
// frontend/src/components/ui/index.ts — add these two lines
export { Card, type CardProps } from "./display/Card";
export { Badge, type BadgeProps } from "./display/Badge";
```

- [ ] **Step 4: Add gallery sections to `/dev/ui-kit`**

Insert after the existing `uikit-table` `<section>` in `frontend/src/pages/dev/UiKit.tsx` (before the `uikit-theme-toggle` section), and add the two imports at the top:

```tsx
import { Card } from "../../components/ui/display/Card";
import { Badge } from "../../components/ui/display/Badge";
```

```tsx
      <section data-testid="uikit-card" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Card
        </h2>
        <Card className="flex max-w-sm flex-col gap-2 p-3">
          <span className="font-medium">Card title</span>
          <span className="text-sm text-[var(--muted-foreground)]">Card body content.</span>
        </Card>
      </section>

      <section data-testid="uikit-badge" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Badge
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>Default</Badge>
          <Badge variant="secondary">Secondary</Badge>
          <Badge variant="destructive">Destructive</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge tone="success">Success</Badge>
          <Badge tone="warning">Warning</Badge>
        </div>
      </section>
```

- [ ] **Step 5: Add Playwright coverage**

Append to `frontend/e2e/foundation.spec.ts`:

```ts
test.describe("Foundation — Card", () => {
  test("renders with token-driven border and background", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const card = page.getByTestId("uikit-card").locator(".ds-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Card title");
  });
});

test.describe("Foundation — Badge", () => {
  test("renders all variants and tones with distinct colors", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-badge");
    const [defaultBg, destructiveBg, successBg, warningBg] = await Promise.all([
      section.getByText("Default").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Destructive").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Success").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Warning").evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(new Set([defaultBg, destructiveBg, successBg, warningBg]).size).toBe(4);
  });
});
```

- [ ] **Step 6: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run dev &` then in another shell `npx playwright test foundation.spec.ts -g "Card|Badge"`.
Expected: 0 tsc errors, both new Playwright tests pass.

```bash
git add frontend/src/components/ui/display/Card.tsx frontend/src/components/ui/display/Badge.tsx frontend/src/components/ui/index.ts frontend/src/pages/dev/UiKit.tsx frontend/e2e/foundation.spec.ts
git commit -m "feat(ui): port DS Card and Badge primitives"
```

---

### Task 2: Sheet primitive

**Files:**
- Create: `frontend/src/components/ui/overlay/Sheet.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Modify: `frontend/src/pages/dev/UiKit.tsx`
- Modify: `frontend/e2e/foundation.spec.ts`

**Interfaces:**
- Consumes: `useStyle` from `../useStyle` (same shared helper as Task 1).
- Produces: `Sheet({ open?, defaultOpen?, onOpenChange?, children })` (context provider), `SheetTrigger`, `SheetContent({ side?: "right"|"left"|"top"|"bottom", showClose?, className?, children })`, `SheetHeader`, `SheetTitle`, `SheetDescription`, `SheetFooter`, `SheetClose`. Controlled via `open`/`onOpenChange` (Task 6 uses this form). Built-in `Escape`-to-close and overlay-click-to-close, both routed through the same `setOpen`/`onOpenChange` path as the close button.

- [ ] **Step 1: Create the Sheet primitive**

```tsx
// frontend/src/components/ui/overlay/Sheet.tsx
import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
@keyframes ds-sheet-overlay-in{from{opacity:0}to{opacity:1}}
@keyframes ds-sheet-right{from{transform:translateX(100%)}to{transform:translateX(0)}}
@keyframes ds-sheet-left{from{transform:translateX(-100%)}to{transform:translateX(0)}}
@keyframes ds-sheet-top{from{transform:translateY(-100%)}to{transform:translateY(0)}}
@keyframes ds-sheet-bottom{from{transform:translateY(100%)}to{transform:translateY(0)}}
.ds-sheet-overlay{position:fixed;inset:0;z-index:50;background:rgb(0 0 0 / .5);animation:ds-sheet-overlay-in .2s ease}
.ds-sheet{
  position:fixed;z-index:51;display:flex;flex-direction:column;gap:1rem;
  padding:1.5rem;background:var(--background);color:var(--foreground);
  box-shadow:var(--shadow-lg);overflow-y:auto;
}
.ds-sheet[data-side="right"]{top:0;right:0;bottom:0;width:min(28rem,calc(100vw - 3rem));border-left:1px solid var(--border);animation:ds-sheet-right .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="left"]{top:0;left:0;bottom:0;width:min(28rem,calc(100vw - 3rem));border-right:1px solid var(--border);animation:ds-sheet-left .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="top"]{top:0;left:0;right:0;border-bottom:1px solid var(--border);animation:ds-sheet-top .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="bottom"]{bottom:0;left:0;right:0;border-top:1px solid var(--border);animation:ds-sheet-bottom .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet-header{display:flex;flex-direction:column;gap:.375rem;text-align:left}
.ds-sheet-title{font-size:var(--text-lg);font-weight:600;line-height:1.2;letter-spacing:-0.01em}
.ds-sheet-description{font-size:var(--text-sm);line-height:var(--text-sm-lh);color:var(--muted-foreground)}
.ds-sheet-footer{display:flex;flex-direction:column;gap:.5rem;margin-top:auto}
.ds-sheet-close{
  position:absolute;top:1rem;right:1rem;display:inline-flex;align-items:center;justify-content:center;
  width:1.5rem;height:1.5rem;cursor:pointer;color:var(--muted-foreground);
  background:transparent;border:none;border-radius:var(--radius-sm);opacity:.7;transition:opacity .15s,background-color .15s;
}
.ds-sheet-close:hover{opacity:1;background:var(--accent)}
.ds-sheet-close svg{width:1rem;height:1rem}
`;

interface SheetCtxValue {
  isOpen: boolean;
  setOpen: (v: boolean) => void;
}
const SheetCtx = React.createContext<SheetCtxValue | null>(null);

function useSheetCtx(): SheetCtxValue {
  const ctx = React.useContext(SheetCtx);
  if (!ctx) throw new Error("Sheet.* components must be rendered inside <Sheet>");
  return ctx;
}

export interface SheetProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children?: React.ReactNode;
}

export function Sheet({ open, defaultOpen = false, onOpenChange, children }: SheetProps) {
  useStyle("ds-sheet", CSS);
  const isControlled = open !== undefined;
  const [internal, setInternal] = React.useState(defaultOpen);
  const isOpen = isControlled ? open : internal;
  const setOpen = (v: boolean) => {
    if (!isControlled) setInternal(v);
    onOpenChange?.(v);
  };

  React.useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen]);

  return <SheetCtx.Provider value={{ isOpen, setOpen }}>{children}</SheetCtx.Provider>;
}

export function SheetTrigger({ asChild, children, onClick, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = useSheetCtx();
  const handleClick: React.MouseEventHandler = (e) => {
    onClick?.(e as React.MouseEvent<HTMLButtonElement>);
    ctx.setOpen(true);
  };
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<{ onClick?: React.MouseEventHandler }>;
    return React.cloneElement(child, {
      onClick: (e: React.MouseEvent) => {
        child.props.onClick?.(e);
        ctx.setOpen(true);
      },
    });
  }
  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}

export interface SheetContentProps extends React.HTMLAttributes<HTMLDivElement> {
  side?: "right" | "left" | "top" | "bottom";
  showClose?: boolean;
}

export function SheetContent({ side = "right", className = "", showClose = true, children, ...props }: SheetContentProps) {
  const ctx = useSheetCtx();
  if (!ctx.isOpen) return null;
  return (
    <React.Fragment>
      <div className="ds-sheet-overlay" onClick={() => ctx.setOpen(false)} />
      <div role="dialog" aria-modal="true" data-slot="sheet" data-side={side} className={`ds-sheet ${className}`} {...props}>
        {children}
        {showClose && (
          <button type="button" className="ds-sheet-close" aria-label="Close" onClick={() => ctx.setOpen(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </React.Fragment>
  );
}

export function SheetHeader({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`ds-sheet-header ${className}`} {...props} />;
}
export function SheetTitle({ className = "", ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={`ds-sheet-title ${className}`} {...props} />;
}
export function SheetDescription({ className = "", ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={`ds-sheet-description ${className}`} {...props} />;
}
export function SheetFooter({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`ds-sheet-footer ${className}`} {...props} />;
}
export function SheetClose({ asChild, children, onClick, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = useSheetCtx();
  const handleClick: React.MouseEventHandler = (e) => {
    onClick?.(e as React.MouseEvent<HTMLButtonElement>);
    ctx.setOpen(false);
  };
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<{ onClick?: React.MouseEventHandler }>;
    return React.cloneElement(child, {
      onClick: (e: React.MouseEvent) => {
        child.props.onClick?.(e);
        ctx.setOpen(false);
      },
    });
  }
  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Register in the barrel export**

```ts
// frontend/src/components/ui/index.ts — add
export {
  Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter, SheetClose,
} from "./overlay/Sheet";
```

- [ ] **Step 3: Add a gallery section to `/dev/ui-kit`**

Add the import and insert after the new `uikit-badge` section:

```tsx
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/overlay/Sheet";
```

```tsx
      <section data-testid="uikit-sheet" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Sheet
        </h2>
        <Sheet>
          <SheetTrigger className="ds-btn" data-variant="outline" data-size="default">
            Open sheet
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>Sheet title</SheetTitle>
              <SheetDescription>Sheet description text.</SheetDescription>
            </SheetHeader>
          </SheetContent>
        </Sheet>
      </section>
```

(`SheetTrigger` is styled directly with the `Button` primitive's own CSS classes/attributes here — `asChild` wrapping a real `<Button>` works too, but this keeps the gallery section dependency-minimal and is equally valid since `ds-btn`'s CSS is already loaded by the Button section above it on the same page.)

- [ ] **Step 4: Add Playwright coverage**

Append to `frontend/e2e/foundation.spec.ts`:

```ts
test.describe("Foundation — Sheet", () => {
  test("opens on trigger click, closes on Escape", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-sheet");
    await expect(section.getByText("Sheet title")).not.toBeVisible();

    await section.getByRole("button", { name: "Open sheet" }).click();
    await expect(section.getByText("Sheet title")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(section.getByText("Sheet title")).not.toBeVisible();
  });
});
```

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && npx tsc -b` then `npx playwright test foundation.spec.ts -g Sheet`.
Expected: 0 tsc errors, test passes.

```bash
git add frontend/src/components/ui/overlay/Sheet.tsx frontend/src/components/ui/index.ts frontend/src/pages/dev/UiKit.tsx frontend/e2e/foundation.spec.ts
git commit -m "feat(ui): port DS Sheet primitive"
```

---

### Task 3: Button success variant + leaf display components

**Files:**
- Modify: `frontend/src/components/ui/forms/Button.tsx`
- Modify: `frontend/src/components/ArtifactCard.tsx`
- Modify: `frontend/src/components/EventFeed.tsx`
- Modify: `frontend/src/components/MetricsSummary.tsx`
- Modify: `frontend/src/components/MemoryBrowser.tsx`
- Test: `frontend/src/components/MemoryBrowser.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Produces: `Button`'s `variant` union gains `"success"` — `ButtonProps["variant"]` is now `"default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "success"`. Task 4 (GateCard) consumes this.
- Consumes: `Card` and `Badge` from Task 1 (`frontend/src/components/ui/display/{Card,Badge}.tsx`).

- [ ] **Step 1: Add the `success` Button variant**

In `frontend/src/components/ui/forms/Button.tsx`, add to the `CSS` string (after the existing `[data-variant="destructive"]` rules):

```css
.ds-btn[data-variant="success"]{background:var(--status-success);color:#fff}
.ds-btn[data-variant="success"]:hover{background:color-mix(in oklab,var(--status-success) 90%,transparent)}
```

And update the type union:

```tsx
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "success";
  size?: "default" | "sm" | "lg" | "xs" | "icon" | "icon-sm" | "icon-lg";
}
```

- [ ] **Step 2: Restyle `ArtifactCard.tsx`**

```tsx
// frontend/src/components/ArtifactCard.tsx
import type { Artifact } from "../api/types";
import { Card } from "./ui/display/Card";

export default function ArtifactCard({ artifact }: { artifact: Artifact }) {
  return (
    <Card className="p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{artifact.kind}</span>
        <span className="text-[var(--muted-foreground)]">v{artifact.version} · {artifact.produced_by_role}</span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded-[var(--radius-md)] bg-[var(--muted)] p-2 text-xs text-[var(--muted-foreground)]">
        {JSON.stringify(artifact.payload_json, null, 2)}
      </pre>
    </Card>
  );
}
```

- [ ] **Step 3: Restyle `EventFeed.tsx`**

```tsx
// frontend/src/components/EventFeed.tsx
import type { FeedEvent } from "../hooks/useEventStream";

export default function EventFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="flex flex-col gap-1 font-mono text-xs">
      {events.length === 0 && <p className="text-[var(--muted-foreground)]">Waiting for events…</p>}
      {events
        .slice()
        .reverse()
        .map((e) => (
          <div key={e.seq} className="rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-1">
            <span className="text-[var(--muted-foreground)]">[{e.seq}]</span> <span className="text-orange-400">{e.type}</span>{" "}
            <span className="text-[var(--muted-foreground)]">{JSON.stringify(e.payload)}</span>
          </div>
        ))}
    </div>
  );
}
```

- [ ] **Step 4: Restyle `MetricsSummary.tsx`**

```tsx
// frontend/src/components/MetricsSummary.tsx
import { useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import type { ProjectMetrics } from "../api/metrics";

export function metricsStats(metrics: ProjectMetrics): { label: string; value: string }[] {
  return [
    { label: "Rework rate", value: `${Math.round(metrics.rework_rate * 100)}%` },
    { label: "Avg approval latency", value: `${Math.round(metrics.approval_latency_seconds)}s` },
    { label: "Retries", value: String(metrics.retry_count) },
    { label: "Crashes", value: String(metrics.crash_count) },
    { label: "Auto-resolved conflicts", value: String(metrics.auto_resolved_count) },
    { label: "Escalated conflicts", value: String(metrics.escalated_count) },
  ];
}

export default function MetricsSummary({ projectId }: { projectId: string }) {
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
  });

  if (!metrics) return null;

  return (
    <div className="grid grid-cols-2 gap-2 rounded-[var(--radius-md)] border border-[var(--border)] p-3 sm:grid-cols-3 md:grid-cols-6">
      {metricsStats(metrics).map((s) => (
        <div key={s.label} className="flex flex-col gap-1">
          <span className="text-lg font-semibold tabular-nums">{s.value}</span>
          <span className="text-xs text-[var(--muted-foreground)]">{s.label}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Restyle `MemoryBrowser.tsx` using `Card` and `Badge`**

```tsx
// frontend/src/components/MemoryBrowser.tsx
import { Link } from "react-router-dom";
import type { MemoryItem } from "../api/types";
import { Card } from "./ui/display/Card";
import { Badge } from "./ui/display/Badge";

export default function MemoryBrowser({ items }: { items: MemoryItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-[var(--muted-foreground)]">No memory items yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <Card key={item.id} as-child="true" className="p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">{item.title}</span>
            <Badge variant="secondary" className="uppercase">{item.kind}</Badge>
          </div>
          <p className="mt-1 text-[var(--muted-foreground)]">{item.body_md}</p>
          <div className="mt-2 text-xs text-[var(--muted-foreground)]">
            {item.scope}
            {item.source_run_id && (
              <>
                {" · from "}
                <Link to={`/runs/${item.source_run_id}`} className="text-orange-400 hover:underline">
                  {item.source_run_id}
                </Link>
              </>
            )}
          </div>
        </Card>
      ))}
    </ul>
  );
}
```

`Card` renders a `<div>`, and this file previously rendered each row as `<li>` (required for the `<ul>` parent's valid child list). Remove the stray `as-child="true"` attribute above — it does nothing on a plain `<div>` — and keep `<li>` as the actual list item, with `Card` nested one level inside it so the DOM stays a valid `<ul><li>…</li></ul>` list (Testing Library's queries in `MemoryBrowser.test.tsx` use `getByText`/`getByRole("link")`, not the tag name, so this nesting is safe):

```tsx
      {items.map((item) => (
        <li key={item.id}>
          <Card className="p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium">{item.title}</span>
              <Badge variant="secondary" className="uppercase">{item.kind}</Badge>
            </div>
            <p className="mt-1 text-[var(--muted-foreground)]">{item.body_md}</p>
            <div className="mt-2 text-xs text-[var(--muted-foreground)]">
              {item.scope}
              {item.source_run_id && (
                <>
                  {" · from "}
                  <Link to={`/runs/${item.source_run_id}`} className="text-orange-400 hover:underline">
                    {item.source_run_id}
                  </Link>
                </>
              )}
            </div>
          </Card>
        </li>
      ))}
```

- [ ] **Step 6: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/components/MemoryBrowser.test.tsx`.
Expected: 0 tsc errors, 3/3 tests pass.

```bash
git add frontend/src/components/ui/forms/Button.tsx frontend/src/components/ArtifactCard.tsx frontend/src/components/EventFeed.tsx frontend/src/components/MetricsSummary.tsx frontend/src/components/MemoryBrowser.tsx
git commit -m "feat(ui): add Button success variant, restyle leaf display components"
```

---

### Task 4: GateCard

**Files:**
- Modify: `frontend/src/components/GateCard.tsx`
- Test: `frontend/src/components/GateCard.test.tsx` (existing, unchanged — run only; confirmed purely behavioral: role/label queries + `vi.fn()` callback assertions, zero CSS assertions)

**Interfaces:**
- Consumes: `Card` (Task 1), `Button` with `variant="success"` (Task 3), `ArtifactCard` (unchanged import, already restyled in Task 3).
- Produces: no change to `GateCard`'s own props (`gate`, `artifact`, `onDecide`) — consumed unchanged by `UnitDrawer` (Task 6) and `RunDetailPage` (Task 7).

- [ ] **Step 1: Restyle `GateCard.tsx`**

```tsx
// frontend/src/components/GateCard.tsx
import { useState } from "react";
import type { Artifact, Gate } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import { Card } from "./ui/display/Card";
import { Button } from "./ui/forms/Button";
import { Textarea } from "./ui/forms/Textarea";
import { Label } from "./ui/forms/Label";

const REJECTION_CHIPS = ["missing tests", "wrong approach", "incomplete", "needs docs"];

export default function GateCard({
  gate,
  artifact,
  onDecide,
}: {
  gate: Gate;
  artifact: Artifact | undefined;
  onDecide: (decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [selectedChips, setSelectedChips] = useState<string[]>([]);

  function toggleChip(chip: string) {
    setSelectedChips((prev) => (prev.includes(chip) ? prev.filter((c) => c !== chip) : [...prev, chip]));
  }

  return (
    <Card className="p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{gate.gate_type} gate</span>
        <span className="text-[var(--muted-foreground)]">{gate.decision}</span>
      </div>

      {gate.gate_type === "derived" && gate.cost_estimate && (
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          Estimated: {gate.cost_estimate.estimated_writes_steps} write step(s), ~
          {gate.cost_estimate.estimated_tokens.toLocaleString()} tokens
        </p>
      )}

      {artifact && (
        <div className="mt-2">
          <ArtifactCard artifact={artifact} />
        </div>
      )}

      {gate.decision === "pending" && (
        <div className="mt-3 flex flex-col gap-2">
          {!rejecting ? (
            <div className="flex gap-2">
              <Button variant="success" size="sm" onClick={() => onDecide("approved", undefined)}>
                Approve
              </Button>
              <Button variant="destructive" size="sm" onClick={() => setRejecting(true)}>
                Reject
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-1">
                {REJECTION_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => toggleChip(chip)}
                    className={`rounded-[var(--radius-full)] border px-2 py-0.5 text-xs ${
                      selectedChips.includes(chip)
                        ? "border-orange-500 bg-orange-950 text-orange-300"
                        : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--ring)]"
                    }`}
                  >
                    {chip}
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="gate-feedback" className="text-xs">Feedback</Label>
                <Textarea
                  id="gate-feedback"
                  className="text-sm"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
              </div>
              <Button
                variant="destructive"
                size="sm"
                className="self-start"
                onClick={() => {
                  onDecide("rejected", { chips: selectedChips, text: feedbackText });
                  setRejecting(false);
                  setFeedbackText("");
                  setSelectedChips([]);
                }}
              >
                Submit rejection
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
```

The original used a `<label>` wrapping both the "Feedback" text and the `<textarea>` (implicit label association); this swaps to `Label`/`Textarea` with an explicit `htmlFor`/`id` pair, which is the stronger and already-established Phase 1 pattern (see `UiKit.tsx`'s `uikit-form-fields` section) — screen-reader and Testing Library `getByLabelText` behavior is equivalent or better, not a regression.

- [ ] **Step 2: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/components/GateCard.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/components/GateCard.tsx
git commit -m "feat(ui): restyle GateCard onto Card/Button/Textarea primitives"
```

---

### Task 5: Ribbon

**Files:**
- Modify: `frontend/src/components/Ribbon.tsx`
- Test: `frontend/src/components/Ribbon.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Produces: no prop changes (`units`, `gates`, `onSelectUnit` unchanged) — consumed unchanged by `RunDetailPage` (Task 7).

**Risk note:** `Ribbon.test.tsx` asserts `pills[0].className !== pills[1].className` between differently-statused pills (not their computed style) — colors must stay expressed as *distinct class names*, not a shared class plus inline `style`, or that assertion breaks. This task injects a local stylesheet (via the existing `useStyle` helper) with one class per tone, exactly like `Button`/`Badge` do with `data-variant` — but keeps the tone selection in the class NAME itself (`ribbon-tone-success` vs `ribbon-tone-warning`) rather than a shared class plus a `data-*` attribute, because the test reads `className`, not `outerHTML`.

- [ ] **Step 1: Restyle `Ribbon.tsx`**

```tsx
// frontend/src/components/Ribbon.tsx
import type { Gate, WorkUnit } from "../api/types";
import { useStyle } from "./ui/useStyle";

const CSS = `
.ribbon-tone-success{background:color-mix(in oklab, var(--status-success) 20%, transparent);color:var(--status-success)}
.ribbon-tone-warning{background:color-mix(in oklab, var(--status-warning) 20%, transparent);color:var(--status-warning)}
.ribbon-tone-danger{background:color-mix(in oklab, var(--destructive) 20%, transparent);color:var(--destructive)}
.ribbon-tone-danger-strong{background:color-mix(in oklab, var(--destructive) 30%, transparent);color:var(--destructive)}
.ribbon-tone-neutral{background:var(--secondary);color:var(--secondary-foreground)}
`;

// Brand orange (in_progress/ready) intentionally stays raw Tailwind, not a
// ribbon-tone-* class -- see Global Constraints: orange isn't tokenized in
// this plan, it already renders correctly in both themes.
const STATUS_STYLES: Record<string, string> = {
  closed: "ribbon-tone-success",
  blocked: "ribbon-tone-warning",
  failed: "ribbon-tone-danger",
  killed: "ribbon-tone-danger-strong",
  in_progress: "bg-orange-900 text-orange-300",
  ready: "bg-orange-950 text-orange-400",
  open: "ribbon-tone-neutral",
};

const GATE_STYLES: Record<string, string> = {
  pending: "ribbon-tone-neutral",
  approved: "ribbon-tone-success",
  rejected: "ribbon-tone-danger",
};

function styleFor(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.open;
}

function gateStyleFor(decision: string): string {
  return GATE_STYLES[decision] ?? GATE_STYLES.pending;
}

export default function Ribbon({
  units,
  gates,
  onSelectUnit,
}: {
  units: WorkUnit[];
  gates: Gate[];
  onSelectUnit?: (unit: WorkUnit) => void;
}) {
  useStyle("ribbon-tones", CSS);
  const steps = units
    .filter((u) => u.type !== "session")
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const gateByUnit = new Map(gates.map((g) => [g.work_unit_id, g]));

  return (
    <div className="flex flex-wrap gap-2">
      {steps.map((u) => {
        const gate = gateByUnit.get(u.id);
        return (
          <div
            key={u.id}
            data-testid={`ribbon-step-${u.id}`}
            role={onSelectUnit ? "button" : undefined}
            onClick={() => onSelectUnit?.(u)}
            className={`flex overflow-hidden rounded-[var(--radius-full)] border border-[var(--border)] text-sm font-medium ${onSelectUnit ? "cursor-pointer" : ""}`}
          >
            <span data-testid="ribbon-pill-agent" className={`px-3 py-1 ${styleFor(u.status)}`}>
              A · {u.step_id}
            </span>
            {gate && (
              <span
                data-testid="ribbon-pill-human"
                data-gate-type={gate.gate_type}
                className={`border-l border-[var(--border)] px-3 py-1 ${gateStyleFor(gate.decision)} ${gate.gate_type === "derived" ? "italic" : ""}`}
              >
                H
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/components/Ribbon.test.tsx`.
Expected: 0 tsc errors, all 6 tests pass — specifically confirm both className-comparison tests ("colors a closed step's agent pill differently from a blocked one" and "colors an approved human pill differently from a rejected one") still pass, since they're the ones this task's design was built around.

```bash
git add frontend/src/components/Ribbon.tsx
git commit -m "feat(ui): restyle Ribbon status/gate pills onto status tokens"
```

---

### Task 6: UnitDrawer restructured around Sheet

**Files:**
- Modify: `frontend/src/components/UnitDrawer.tsx`
- Test: `frontend/src/components/UnitDrawer.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `Sheet`, `SheetContent`, `SheetHeader`, `SheetTitle` from Task 2; `GateCard` (Task 4), `ArtifactCard` (Task 3), `Card` (Task 1).
- Produces: **`UnitDrawer`'s exported prop signature is unchanged** (`unit`, `events`, `artifacts`, `gates`, `sessions`, `onClose: () => void`, `onDecideGate`). `RunDetailPage` (Task 7) keeps its existing `{selectedUnit && <UnitDrawer ... onClose={() => setSelectedUnit(null)} />}` mount/unmount call site verbatim — no changes needed there for this task.

**Risk note (this is the plan's highest-risk task):** `UnitDrawer` is only ever rendered while `selectedUnit` is truthy — the parent unmounts it entirely on close, it doesn't toggle a `hidden` prop. That means `Sheet`'s `open` is always `true` for the lifetime of a mounted `UnitDrawer` instance; there's no need to thread a real boolean through props. Wire `Sheet`'s `onOpenChange` straight to the existing `onClose` callback: `onOpenChange={(v) => { if (!v) onClose(); }}`. This gets Escape-to-close and overlay-click-to-close for free from `Sheet`, replacing the current hand-rolled `<div onClick={onClose}>` backdrop + `e.stopPropagation()` panel — with **zero change** to the component's public contract.

- [ ] **Step 1: Restructure `UnitDrawer.tsx`**

```tsx
// frontend/src/components/UnitDrawer.tsx
import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import GateCard from "./GateCard";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "./ui/overlay/Sheet";

export default function UnitDrawer({
  unit,
  events,
  artifacts,
  gates,
  sessions,
  onClose,
  onDecideGate,
}: {
  unit: WorkUnit;
  events: FeedEventLike[];
  artifacts: Artifact[];
  gates: Gate[];
  sessions: Session[];
  onClose: () => void;
  onDecideGate: (gateId: string, decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const unitEvents = events.filter((e) => e.unit_id === unit.id);
  const unitArtifacts = artifacts.filter((a) => a.work_unit_id === unit.id).sort((a, b) => b.version - a.version);
  const unitGate = gates.find((g) => g.work_unit_id === unit.id);
  // Sessions attach to a SESSION-type WorkUnit, not the TASK-type unit this
  // drawer is scoped to -- filter by the task's owner_session_id (its
  // current/latest session), not its own id, which would never match any
  // session's work_unit_id. This only surfaces the most recent attempt, not
  // full retry history: once a task retries, owner_session_id is
  // reassigned to the new session unit and the old session unit's id is no
  // longer reachable from the task, and there's no other stored link back
  // to it without a schema change -- a real limitation discovered while
  // implementing this plan (not in the original design spec), accepted
  // here as out of scope rather than blocking on a schema change.
  const unitSessions = sessions.filter((s) => s.work_unit_id === unit.owner_session_id);

  return (
    <Sheet open onOpenChange={(v) => { if (!v) onClose(); }}>
      <SheetContent className="w-full max-w-lg gap-4">
        <SheetHeader>
          <SheetTitle>{unit.step_id}</SheetTitle>
        </SheetHeader>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Gate</h4>
          {unitGate ? (
            <GateCard
              gate={unitGate}
              artifact={unitGate.artifact_id ? unitArtifacts.find((a) => a.id === unitGate.artifact_id) : undefined}
              onDecide={(decision, feedback) => onDecideGate(unitGate.id, decision, feedback)}
            />
          ) : (
            <p className="text-sm text-[var(--muted-foreground)]">No gate for this step.</p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Artifacts</h4>
          {unitArtifacts.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No artifacts yet.</p>}
          {unitArtifacts.map((a) => (
            <div key={a.id} data-testid="drawer-artifact">
              <ArtifactCard artifact={a} />
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Session log</h4>
          {unitSessions.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No sessions yet.</p>}
          {unitSessions.map((s) => (
            <div
              key={s.id}
              data-testid="drawer-session"
              className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)]"
            >
              <span>{s.driver} · {s.model ?? "—"}</span>
              <span>{s.status}</span>
              <span className="tabular-nums">{s.tokens_in} in / {s.tokens_out} out</span>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Events</h4>
          {unitEvents.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No events yet.</p>}
          {unitEvents.map((e) => (
            <div key={e.seq} className="font-mono text-xs text-[var(--muted-foreground)]">
              [{e.seq}] {e.type} {JSON.stringify(e.payload)}
            </div>
          ))}
        </section>
      </SheetContent>
    </Sheet>
  );
}
```

`SheetTitle` renders an `<h2>` — `UnitDrawer.test.tsx`'s `screen.getByRole("heading", { name: "implement" })` matches any `<h1>`-`<h6>`, so this still passes even though the original used `<h3>`. The explicit "Close" `<button>` is dropped in favor of `SheetContent`'s built-in close button (`aria-label="Close"`, `showClose` defaults to `true`), which `UnitDrawer.test.tsx`'s `screen.getByRole("button", { name: /close/i })` still matches.

- [ ] **Step 2: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/components/UnitDrawer.test.tsx`.
Expected: 0 tsc errors, all 4 tests pass.

```bash
git add frontend/src/components/UnitDrawer.tsx
git commit -m "feat(ui): restructure UnitDrawer around the Sheet primitive"
```

---

### Task 7: RunDetailPage, DagView, KgGraphView

**Files:**
- Modify: `frontend/src/pages/RunDetailPage.tsx`
- Modify: `frontend/src/components/DagView.tsx`
- Modify: `frontend/src/components/KgGraphView.tsx`
- Test: `frontend/src/pages/RunDetailPage.test.tsx`, `frontend/src/components/DagView.test.tsx`, `frontend/src/components/KgGraphView.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `Ribbon` (Task 5), `GateCard` (Task 4), `UnitDrawer` (Task 6), `EventFeed` (Task 3), `Button` (Task 3), all unchanged props.

**Note:** `DagView`/`KgGraphView`'s node/edge colors (`STATUS_COLORS`, `fill`/`stroke` SVG attributes) are raw hex today and stay raw hex — SVG presentation attributes don't read CSS custom properties the way Tailwind classes do without extra plumbing, and this hex-keyed-by-status map is an established, working pattern already used consistently by both files. Only the outer `<svg>` wrapper's Tailwind classes (`rounded border border-slate-800 bg-slate-950`) are in scope.

- [ ] **Step 1: Restyle `RunDetailPage.tsx`**

```tsx
// frontend/src/pages/RunDetailPage.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { decideGate } from "../api/gates";
import { cancelRun, getRunArtifacts, getRunDetail, getRunGraph, getRunSessions } from "../api/runs";
import type { WorkUnit } from "../api/types";
import DagView from "../components/DagView";
import EventFeed from "../components/EventFeed";
import GateCard from "../components/GateCard";
import Ribbon from "../components/Ribbon";
import UnitDrawer from "../components/UnitDrawer";
import { Button } from "../components/ui/forms/Button";
import { useEventStream } from "../hooks/useEventStream";

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = id!;
  const queryClient = useQueryClient();
  const events = useEventStream(runId);
  const [selectedUnit, setSelectedUnit] = useState<WorkUnit | null>(null);

  const { data: detail, isLoading } = useQuery({ queryKey: ["run", runId], queryFn: () => getRunDetail(runId) });
  const { data: artifacts } = useQuery({ queryKey: ["run-artifacts", runId], queryFn: () => getRunArtifacts(runId) });
  const { data: graph } = useQuery({ queryKey: ["run-graph", runId], queryFn: () => getRunGraph(runId) });
  const { data: sessions } = useQuery({
    queryKey: ["run-sessions", runId],
    queryFn: () => getRunSessions(runId),
    enabled: selectedUnit !== null, // no need to fetch session history until the drawer is actually open
  });

  useEffect(() => {
    if (events.length === 0) return;
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    queryClient.invalidateQueries({ queryKey: ["run-graph", runId] });
  }, [events.length, runId, queryClient]);

  const decideMutation = useMutation({
    mutationFn: ({ gateId, decision, feedback }: { gateId: string; decision: "approved" | "rejected"; feedback?: { chips: string[]; text: string } }) =>
      decideGate(gateId, decision, feedback),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  if (isLoading || !detail) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  const isTerminal = detail.run.status === "closed" || detail.run.status === "cancelled";
  const artifactById = new Map((artifacts ?? []).map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">{detail.run.title}</h2>
          <p className="text-sm text-[var(--muted-foreground)]">{detail.run.status}</p>
          <p className="text-xs text-[var(--muted-foreground)]">Pack: {detail.run.pack_version_pin}</p>
        </div>
        <Button variant="destructive" disabled={isTerminal} onClick={() => cancelMutation.mutate()}>
          Cancel run
        </Button>
      </div>

      <Ribbon units={detail.units} gates={detail.gates} onSelectUnit={setSelectedUnit} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Gates & artifacts</h3>
          {detail.gates.map((gate) => (
            <GateCard
              key={gate.id}
              gate={gate}
              artifact={gate.artifact_id ? artifactById.get(gate.artifact_id) : undefined}
              onDecide={(decision, feedback) => decideMutation.mutate({ gateId: gate.id, decision, feedback })}
            />
          ))}
          {detail.gates.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No gates yet.</p>}
        </div>

        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Live feed</h3>
          <EventFeed events={events} />
        </div>
      </div>

      {graph && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">DAG</h3>
          <div className="overflow-x-auto">
            <DagView units={graph.units} deps={graph.deps} onNodeClick={setSelectedUnit} />
          </div>
        </div>
      )}

      {selectedUnit && (
        <UnitDrawer
          unit={selectedUnit}
          events={events}
          artifacts={artifacts ?? []}
          gates={detail.gates}
          sessions={sessions ?? []}
          onClose={() => setSelectedUnit(null)}
          onDecideGate={(gateId, decision, feedback) => decideMutation.mutate({ gateId, decision, feedback })}
        />
      )}
    </div>
  );
}
```

`Button`'s default `size` is `"default"` (height `2.25rem`), replacing the original's `rounded bg-red-900 px-3 py-1.5 text-sm`. `disabled:opacity-40` is already baked into `.ds-btn:disabled{opacity:.5}` — a slightly different value than the original's `.40`, an acceptable visual parity difference for reusing the shared primitive rather than a `className` override.

- [ ] **Step 2: Restyle `DagView.tsx`'s outer `<svg>` wrapper**

In `frontend/src/components/DagView.tsx`, change only the `className` on the returned `<svg>`:

```tsx
      className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--card)]"
```

(replacing `className="rounded border border-slate-800 bg-slate-950"`). No other lines in this file change — `STATUS_COLORS`, `colorFor`, and all SVG `fill`/`stroke` attributes stay as-is per the note above.

- [ ] **Step 3: Restyle `KgGraphView.tsx`'s outer `<svg>` wrapper**

In `frontend/src/components/KgGraphView.tsx`, change only the `className` on the returned `<svg>`:

```tsx
      className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--card)]"
```

(replacing `className="rounded border border-slate-800 bg-slate-950"`). No other lines change.

- [ ] **Step 4: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/RunDetailPage.test.tsx src/components/DagView.test.tsx src/components/KgGraphView.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/pages/RunDetailPage.tsx frontend/src/components/DagView.tsx frontend/src/components/KgGraphView.tsx
git commit -m "feat(ui): restyle RunDetailPage, DagView, and KgGraphView wrappers"
```

---

### Task 8: Portfolio + Projects cluster

**Files:**
- Modify: `frontend/src/pages/PortfolioHomePage.tsx`
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/components/ProjectLifecycleButtons.tsx`
- Modify: `frontend/src/components/NewProjectForm.tsx`
- Test: `frontend/src/pages/PortfolioHomePage.test.tsx`, `frontend/src/pages/ProjectsPage.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `Card` (Task 1), `Button`, `Input`, `Label` (Phase 1).
- Produces: no prop changes to any of the four components.

- [ ] **Step 1: Restyle `ProjectLifecycleButtons.tsx`**

```tsx
// frontend/src/components/ProjectLifecycleButtons.tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { activateProject, archiveProject, pauseProject } from "../api/projects";
import { Button } from "./ui/forms/Button";

export default function ProjectLifecycleButtons({
  projectId,
  status,
  invalidateQueryKey,
}: {
  projectId: string;
  status: string;
  invalidateQueryKey: readonly unknown[];
}) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: invalidateQueryKey });

  const pauseMutation = useMutation({
    mutationFn: () => pauseProject(projectId),
    onSuccess: invalidate,
  });
  const archiveMutation = useMutation({
    mutationFn: () => archiveProject(projectId),
    onSuccess: invalidate,
  });
  const activateMutation = useMutation({
    mutationFn: () => activateProject(projectId),
    onSuccess: invalidate,
  });

  return (
    <div className="flex gap-2">
      {status !== "paused" && (
        <Button type="button" variant="outline" size="xs" onClick={() => pauseMutation.mutate()} disabled={pauseMutation.isPending}>
          Pause
        </Button>
      )}
      {status !== "archived" && (
        <Button type="button" variant="outline" size="xs" onClick={() => archiveMutation.mutate()} disabled={archiveMutation.isPending}>
          Archive
        </Button>
      )}
      {status !== "active" && (
        <Button type="button" variant="outline" size="xs" onClick={() => activateMutation.mutate()} disabled={activateMutation.isPending}>
          Activate
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Restyle `NewProjectForm.tsx`**

```tsx
// frontend/src/components/NewProjectForm.tsx
import { useState } from "react";
import { Button } from "./ui/forms/Button";
import { Input } from "./ui/forms/Input";
import { Label } from "./ui/forms/Label";

export default function NewProjectForm({ onSubmit }: { onSubmit: (input: { name: string; path: string }) => void }) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name, path });
        setName("");
        setPath("");
      }}
    >
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-project-name">Name</Label>
        <Input id="new-project-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-project-path">Path</Label>
        <Input id="new-project-path" value={path} onChange={(e) => setPath(e.target.value)} required />
      </div>
      <Button type="submit">Create project</Button>
    </form>
  );
}
```

- [ ] **Step 3: Restyle `PortfolioHomePage.tsx`**

```tsx
// frontend/src/pages/PortfolioHomePage.tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import { Card } from "../components/ui/display/Card";
import { getPortfolio } from "../api/portfolio";
import type { ProjectHealth } from "../api/types";

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function ProjectCard({ project }: { project: ProjectHealth }) {
  return (
    <li>
      <Card data-testid={`portfolio-card-${project.project_id}`} className="flex flex-col gap-2 px-3 py-2">
        <div className="flex items-center justify-between">
          <Link to={`/projects/${project.project_id}`} className="font-medium text-orange-400 hover:underline">
            {project.name}
          </Link>
          <span className="text-xs uppercase text-[var(--muted-foreground)]">{project.status}</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--muted-foreground)]">
          <span>Active runs: {project.active_run_count}</span>
          <span>Pending gates: {project.pending_gate_count}</span>
          <span>Last run: {project.last_run_status ?? "none yet"}</span>
          <span>Rework rate: {formatPercent(project.rework_rate)}</span>
          <span>Budget burn: {formatPercent(project.budget_burn_ratio)}</span>
        </div>
        <ProjectLifecycleButtons
          projectId={project.project_id}
          status={project.status}
          invalidateQueryKey={["portfolio"]}
        />
      </Card>
    </li>
  );
}

export default function PortfolioHomePage() {
  const { data: projects, isLoading } = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Portfolio</h2>
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((project) => (
            <ProjectCard key={project.project_id} project={project} />
          ))}
        </ul>
      )}
    </div>
  );
}
```

`data-testid` moved from the `<li>` onto `Card`'s rendered `<div>` — both are still queryable by `getByTestId`, and no existing test asserts the tag name, only presence/content, so this is safe.

- [ ] **Step 4: Restyle `ProjectsPage.tsx`**

```tsx
// frontend/src/pages/ProjectsPage.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/projects";
import NewProjectForm from "../components/NewProjectForm";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import { Card } from "../components/ui/display/Card";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const { data: projects, isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Projects</h2>
      <NewProjectForm onSubmit={(input) => createMutation.mutate(input)} />
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id}>
              <Card className="flex flex-col gap-2 px-3 py-2">
                <div className="flex items-center justify-between">
                  <div>
                    <Link to={`/projects/${p.id}`} className="font-medium text-orange-400 hover:underline">
                      {p.name}
                    </Link>
                    <span className="ml-2 text-sm text-[var(--muted-foreground)]">{p.path}</span>
                  </div>
                  <span className="text-xs uppercase text-[var(--muted-foreground)]">{p.status}</span>
                </div>
                <ProjectLifecycleButtons projectId={p.id} status={p.status} invalidateQueryKey={["projects"]} />
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/PortfolioHomePage.test.tsx src/pages/ProjectsPage.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/pages/PortfolioHomePage.tsx frontend/src/pages/ProjectsPage.tsx frontend/src/components/ProjectLifecycleButtons.tsx frontend/src/components/NewProjectForm.tsx
git commit -m "feat(ui): restyle Portfolio/Projects pages onto Card/Button/Input"
```

---

### Task 9: ProjectDetailPage

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Test: `frontend/src/pages/ProjectDetailPage.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `ProjectLifecycleButtons` (Task 8), `KgGraphView` (Task 7), `MemoryBrowser` (Task 3), `metricsStats` from `MetricsSummary` (Task 3), `Card`, `Select`, `Input`, `Label`, `Button` (Task 1/Phase 1).

- [ ] **Step 1: Restyle `ProjectDetailPage.tsx`**

```tsx
// frontend/src/pages/ProjectDetailPage.tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getProject, updateProjectSettings } from "../api/projects";
import { getProjectMetrics } from "../api/metrics";
import { getProjectKgGraph, listMemory } from "../api/knowledge";
import { listRuns } from "../api/runs";
import { metricsStats } from "../components/MetricsSummary";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";
import { Card } from "../components/ui/display/Card";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";
import { Label } from "../components/ui/forms/Label";
import { Select } from "../components/ui/forms/Select";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id!;

  const { data: project, isError } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
  });
  const { data: runs } = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => listRuns({ project_id: projectId }),
    enabled: !!project,
  });
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
    enabled: !!project,
  });
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId),
    enabled: !!project,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!project,
  });

  const queryClient = useQueryClient();
  const [driver, setDriver] = useState("fake");
  const [tokenBudget, setTokenBudget] = useState(0);
  const [playbookPath, setPlaybookPath] = useState("");

  const settingsMutation = useMutation({
    mutationFn: () =>
      updateProjectSettings(projectId, {
        driver,
        token_budget: tokenBudget,
        playbook_path: playbookPath,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
  });

  useEffect(() => {
    if (project) {
      setDriver(project.default_driver);
      setTokenBudget(project.default_token_budget ?? 0);
      setPlaybookPath(project.default_playbook_path ?? "");
    }
  }, [project]);

  if (isError) {
    return <p className="text-[var(--muted-foreground)]">Project not found.</p>;
  }

  if (!project) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">{project.name}</h2>
          <span className="text-xs uppercase text-[var(--muted-foreground)]">{project.status}</span>
        </div>
        <span className="text-sm text-[var(--muted-foreground)]">{project.path}</span>
        <ProjectLifecycleButtons
          projectId={project.id}
          status={project.status}
          invalidateQueryKey={["project", projectId]}
        />
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Settings</h3>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            settingsMutation.mutate();
          }}
        >
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-driver">Driver</Label>
            <Select id="project-driver" value={driver} onChange={(e) => setDriver(e.target.value)}>
              <option value="fake">fake</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-token-budget">Token budget</Label>
            <Input
              id="project-token-budget"
              type="number"
              value={tokenBudget}
              onChange={(e) => setTokenBudget(Number(e.target.value))}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
            <Input
              id="project-playbook-path"
              value={playbookPath}
              onChange={(e) => setPlaybookPath(e.target.value)}
              placeholder="packs/default/playbooks/sdlc_story.toml"
            />
          </div>
          <Button type="submit" disabled={settingsMutation.isPending}>
            Save settings
          </Button>
        </form>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Runs</h3>
          <Link to={`/runs?project_id=${projectId}`} className="text-sm text-orange-400 hover:underline">
            View all runs →
          </Link>
        </div>
        <ul className="flex flex-col gap-2">
          {[...(runs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5).map((r) => (
            <li key={r.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                  {r.title}
                </Link>
                <span className="text-sm text-[var(--muted-foreground)]">{r.status}</span>
              </Card>
            </li>
          ))}
        </ul>
      </div>

      {metrics && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Metrics</h3>
          <Card className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 md:grid-cols-6">
            {metricsStats(metrics).map((s) => (
              <div key={s.label} className="flex flex-col gap-1">
                <span className="text-lg font-semibold tabular-nums">{s.value}</span>
                <span className="text-xs text-[var(--muted-foreground)]">{s.label}</span>
              </div>
            ))}
          </Card>
        </div>
      )}

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Knowledge graph</h3>
        <div className="overflow-x-auto">
          {graph?.nodes && <KgGraphView nodes={graph.nodes} edges={graph.edges ?? []} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/ProjectDetailPage.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): restyle ProjectDetailPage onto Card/Select/Input/Button"
```

---

### Task 10: Runs + Queue cluster

**Files:**
- Modify: `frontend/src/pages/RunsHomePage.tsx`
- Modify: `frontend/src/components/NewRunForm.tsx`
- Modify: `frontend/src/pages/QueuePage.tsx`
- Test: `frontend/src/pages/RunsHomePage.test.tsx`, `frontend/src/components/NewRunForm.test.tsx`, `frontend/src/pages/QueuePage.test.tsx` (existing, unchanged — run only)

- [ ] **Step 1: Restyle `NewRunForm.tsx`**

```tsx
// frontend/src/components/NewRunForm.tsx
import { useEffect, useState } from "react";
import type { Project } from "../api/types";
import { Button } from "./ui/forms/Button";
import { Input } from "./ui/forms/Input";
import { Label } from "./ui/forms/Label";
import { Select } from "./ui/forms/Select";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string; driver?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");

  useEffect(() => {
    const selected = projects.find((p) => p.id === projectId);
    if (selected) {
      setDriver(selected.default_driver);
      setPlaybookPath(selected.default_playbook_path ?? "");
    }
    // Intentionally omit `projects` from deps: a background refetch of the
    // projects query (e.g. react-query's refetchOnWindowFocus) produces a
    // new array reference with equivalent content, which would otherwise
    // re-run this effect and silently reset the user's edits even though
    // they never changed the selected project. The effect body still reads
    // the latest `projects` via closure.
  }, [projectId]);

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined, driver });
        setPlaybookPath("");
        setTitle("");
      }}
    >
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-project">Project</Label>
        <Select id="new-run-project" value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-driver">Driver</Label>
        <Select id="new-run-driver" value={driver} onChange={(e) => setDriver(e.target.value)}>
          <option value="fake">fake</option>
          <option value="codex">codex</option>
          <option value="claude">claude</option>
        </Select>
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
        <Input
          id="new-run-playbook"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-title">Title (optional)</Label>
        <Input id="new-run-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <Button type="submit">Start run</Button>
    </form>
  );
}
```

- [ ] **Step 2: Restyle `RunsHomePage.tsx`**

```tsx
// frontend/src/pages/RunsHomePage.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { createRun, listRuns } from "../api/runs";
import NewRunForm from "../components/NewRunForm";
import { Card } from "../components/ui/display/Card";

export default function RunsHomePage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const queryClient = useQueryClient();

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => listRuns(projectId ? { project_id: projectId } : undefined),
  });

  const createMutation = useMutation({
    mutationFn: createRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Runs{projectId ? " for project" : ""}</h2>
      {projectId && (
        <Link to="/metrics" className="text-sm text-orange-400 hover:underline">
          View portfolio metrics →
        </Link>
      )}
      {projects && projects.length > 0 && (
        <NewRunForm projects={projects} defaultProjectId={projectId} onSubmit={(input) => createMutation.mutate(input)} />
      )}
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {runs?.map((r) => (
            <li key={r.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                  {r.title}
                </Link>
                <span className="text-sm text-[var(--muted-foreground)]">{r.status}</span>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Restyle `QueuePage.tsx`**

```tsx
// frontend/src/pages/QueuePage.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { batchDecideGates, completeHumanTask, getQueue } from "../api/queue";
import { Button } from "../components/ui/forms/Button";
import { Card } from "../components/ui/display/Card";

export default function QueuePage() {
  const queryClient = useQueryClient();
  const { data: queue, isLoading } = useQuery({ queryKey: ["queue"], queryFn: getQueue });
  const [selectedGateIds, setSelectedGateIds] = useState<string[]>([]);

  const batchApproveMutation = useMutation({
    mutationFn: () => batchDecideGates(selectedGateIds),
    onSuccess: () => {
      setSelectedGateIds([]);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const completeMutation = useMutation({
    mutationFn: (unitId: string) => completeHumanTask(unitId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });

  const toggleGate = (gateId: string) => {
    setSelectedGateIds((prev) =>
      prev.includes(gateId) ? prev.filter((id) => id !== gateId) : [...prev, gateId],
    );
  };

  if (isLoading || !queue) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">My Queue</h2>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Gates</h3>
          <Button
            type="button"
            disabled={selectedGateIds.length === 0 || batchApproveMutation.isPending}
            onClick={() => batchApproveMutation.mutate()}
          >
            Approve selected
          </Button>
        </div>
        <ul className="flex flex-col gap-2">
          {queue.gates.map((g) => (
            <li key={g.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    aria-label={g.step_id}
                    checked={selectedGateIds.includes(g.id)}
                    onChange={() => toggleGate(g.id)}
                  />
                  <div>
                    <span className="text-sm text-[var(--foreground)]">
                      {g.project_name} / <Link to={`/runs/${g.run_id}`} className="text-orange-400 hover:underline">{g.run_title}</Link>
                    </span>
                    <span className="ml-2 text-xs text-[var(--muted-foreground)]">{g.step_id}</span>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Human tasks</h3>
        <ul className="flex flex-col gap-2">
          {queue.human_tasks.map((h) => (
            <li key={h.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div>
                  <span className="text-sm text-[var(--foreground)]">
                    {h.project_name} / <Link to={`/runs/${h.run_id}`} className="text-orange-400 hover:underline">{h.run_title}</Link>
                  </span>
                  <span className="ml-2 text-xs text-[var(--muted-foreground)]">{h.reason}</span>
                </div>
                <Button type="button" variant="outline" size="xs" disabled={completeMutation.isPending} onClick={() => completeMutation.mutate(h.id)}>
                  Mark resolved
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/RunsHomePage.test.tsx src/components/NewRunForm.test.tsx src/pages/QueuePage.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/pages/RunsHomePage.tsx frontend/src/components/NewRunForm.tsx frontend/src/pages/QueuePage.tsx
git commit -m "feat(ui): restyle Runs/Queue pages onto Card/Button/Select/Input"
```

---

### Task 11: Knowledge, Fleet, Metrics, Packs pages

**Files:**
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/pages/FleetPage.tsx`
- Modify: `frontend/src/pages/MetricsPage.tsx`
- Modify: `frontend/src/pages/PacksPage.tsx`
- Test: `frontend/src/pages/KnowledgePage.test.tsx`, `frontend/src/pages/FleetPage.test.tsx`, `frontend/src/pages/MetricsPage.test.tsx`, `frontend/src/pages/PacksPage.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `KgGraphView` (Task 7), `MemoryBrowser` (Task 3), `Card`, `Input`, `Button`, `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableHead`/`TableCell` (Phase 1).

- [ ] **Step 1: Restyle `KnowledgePage.tsx`**

```tsx
// frontend/src/pages/KnowledgePage.tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { getProjectKgGraph, getRunBlastRadius, listMemory } from "../api/knowledge";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";

export default function KnowledgePage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const [runIdInput, setRunIdInput] = useState("");
  const [blastRadiusRunId, setBlastRadiusRunId] = useState<string | undefined>(undefined);

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId!),
    enabled: !!projectId,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!projectId,
  });
  const { data: blastRadius } = useQuery({
    queryKey: ["blast-radius", blastRadiusRunId],
    queryFn: () => getRunBlastRadius(blastRadiusRunId!),
    enabled: !!blastRadiusRunId,
  });

  if (!projectId) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">Knowledge</h2>
        <p className="text-sm text-[var(--muted-foreground)]">Select a project to view its knowledge graph and memory.</p>
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id}>
              <Link to={`/knowledge?project_id=${p.id}`} className="text-orange-400 hover:underline">
                {p.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Knowledge</h2>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Import graph</h3>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setBlastRadiusRunId(runIdInput || undefined);
          }}
        >
          <Input
            placeholder="Run ID to overlay blast radius"
            value={runIdInput}
            onChange={(e) => setRunIdInput(e.target.value)}
          />
          <Button type="submit">Highlight</Button>
        </form>
        <div className="overflow-x-auto">
          {graph && <KgGraphView nodes={graph.nodes} edges={graph.edges} highlight={blastRadius?.radius} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Restyle `FleetPage.tsx`**

```tsx
// frontend/src/pages/FleetPage.tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listActiveSessions } from "../api/sessions";
import { Card } from "../components/ui/display/Card";

export default function FleetPage() {
  const { data: sessions, isLoading } = useQuery({
    queryKey: ["active-sessions"],
    queryFn: listActiveSessions,
    refetchInterval: 3000,
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Fleet</h2>
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : sessions && sessions.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li key={s.id}>
              <Card className="flex items-center justify-between px-3 py-2 text-sm">
                <Link to={`/runs/${s.run_id}`} className="font-medium text-orange-400 hover:underline">
                  {s.step_id}
                </Link>
                <span className="text-[var(--muted-foreground)]">{s.driver}</span>
                <span className="text-[var(--muted-foreground)]">{s.model ?? "—"}</span>
                <span className="tabular-nums text-[var(--muted-foreground)]">
                  {s.tokens_in.toLocaleString()} in / {s.tokens_out.toLocaleString()} out
                </span>
                <span className="text-[var(--muted-foreground)]">{s.status}</span>
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">No active sessions.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Restyle `MetricsPage.tsx` using the `Table` primitive**

```tsx
// frontend/src/pages/MetricsPage.tsx
import { useQueries, useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import { listProjects } from "../api/projects";
import { metricsStats } from "../components/MetricsSummary";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/display/Table";

const STAT_LABELS = [
  "Rework rate",
  "Avg approval latency",
  "Retries",
  "Crashes",
  "Auto-resolved conflicts",
  "Escalated conflicts",
];

export default function MetricsPage() {
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const metricsQueries = useQueries({
    queries: (projects ?? []).map((project) => ({
      queryKey: ["project-metrics", project.id],
      queryFn: () => getProjectMetrics(project.id),
    })),
  });

  if (projectsLoading || !projects) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  const rows = projects
    .map((project, i) => ({ project, query: metricsQueries[i] }))
    .sort((a, b) => (b.query.data?.rework_rate ?? -1) - (a.query.data?.rework_rate ?? -1));

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Metrics</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Project</TableHead>
            {STAT_LABELS.map((label) => (
              <TableHead key={label}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ project, query }) => (
            <TableRow key={project.id}>
              <TableCell className="font-medium">{project.name}</TableCell>
              {query.isError ? (
                <TableCell colSpan={STAT_LABELS.length} className="text-[var(--destructive)]">
                  Failed to load metrics
                </TableCell>
              ) : query.data ? (
                metricsStats(query.data).map((s) => (
                  <TableCell key={s.label} className="tabular-nums">{s.value}</TableCell>
                ))
              ) : (
                <TableCell colSpan={STAT_LABELS.length} className="text-[var(--muted-foreground)]">
                  Loading…
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

Before writing this step, the implementer must read `frontend/src/components/ui/display/Table.tsx` to confirm `TableCell`'s prop signature accepts `colSpan` and `className` (it wraps a native `<td>`, so both pass through via `...props`) and that `TableHead`/`TableCell` don't require a fixed number of siblings per row — this file's dynamic per-row cell count (1, or `STAT_LABELS.length` via `colSpan`, or `STAT_LABELS.length` individual cells) must render valid HTML table rows in all three cases, exactly as the original raw `<table>` did.

- [ ] **Step 4: Restyle `PacksPage.tsx`**

```tsx
// frontend/src/pages/PacksPage.tsx
import { useQuery } from "@tanstack/react-query";
import { listPacks } from "../api/packs";
import type { PackManifest } from "../api/types";
import { Card } from "../components/ui/display/Card";

function PackCard({ pack }: { pack: PackManifest }) {
  return (
    <li>
      <Card className="flex flex-col gap-2 px-3 py-2">
        <div className="flex items-baseline gap-2">
          <span className="font-medium text-orange-400">{pack.id}</span>
          <span className="text-xs uppercase text-[var(--muted-foreground)]">{pack.version}</span>
        </div>
        <div>
          <div className="text-xs uppercase text-[var(--muted-foreground)]">Roles</div>
          <ul className="text-sm text-[var(--muted-foreground)]">
            {pack.roles.map((role) => (
              <li key={role.id}>
                {role.id} <span className="text-xs text-[var(--muted-foreground)]">({role.model})</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-xs uppercase text-[var(--muted-foreground)]">Playbooks</div>
          <ul className="text-sm text-[var(--muted-foreground)]">
            {pack.playbooks.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        </div>
      </Card>
    </li>
  );
}

export default function PacksPage() {
  const { data: packs, isLoading } = useQuery({ queryKey: ["packs"], queryFn: listPacks });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Packs</h2>
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {packs?.map((pack) => (
            <PackCard key={pack.id} pack={pack} />
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/KnowledgePage.test.tsx src/pages/FleetPage.test.tsx src/pages/MetricsPage.test.tsx src/pages/PacksPage.test.tsx`.
Expected: 0 tsc errors, all tests pass.

```bash
git add frontend/src/pages/KnowledgePage.tsx frontend/src/pages/FleetPage.tsx frontend/src/pages/MetricsPage.tsx frontend/src/pages/PacksPage.tsx
git commit -m "feat(ui): restyle Knowledge/Fleet/Metrics/Packs pages onto tokens and Table"
```

---

### Task 12: DemoModeToggle, mount ThemeToggle, final smoke pass

**Files:**
- Modify: `frontend/src/components/DemoModeToggle.tsx`
- Modify: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/e2e/foundation.spec.ts`
- Test: `frontend/src/components/DemoModeToggle.test.tsx` (existing, unchanged — run only)

**Interfaces:**
- Consumes: `Button` (Task 3), `ThemeToggle` (already exported from `TopBar.tsx` since Phase 1 — no signature change).

This is the last task: by this point every page and component has been migrated off `slate-*`/`gray-*` classes (Tasks 3-11), so mounting the toggle no longer produces unreadable near-black-on-near-black content in light mode.

- [ ] **Step 1: Restyle `DemoModeToggle.tsx`**

```tsx
// frontend/src/components/DemoModeToggle.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "../api/demo";
import { Button } from "./ui/forms/Button";

export default function DemoModeToggle() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: status } = useQuery({ queryKey: ["demo-status"], queryFn: getDemoStatus });

  const afterSwap = () => {
    // The entire database underneath the app just changed -- everything is
    // potentially stale, not just one query key. A deep-linked run/project
    // id from before the swap won't exist against the new db, so send the
    // user back to a page that doesn't depend on one.
    queryClient.clear();
    navigate("/");
  };

  const activateMutation = useMutation({ mutationFn: activateDemo, onSuccess: afterSwap });
  const deactivateMutation = useMutation({ mutationFn: deactivateDemo, onSuccess: afterSwap });
  const reseedMutation = useMutation({ mutationFn: reseedDemo, onSuccess: afterSwap });

  if (!status) {
    return null;
  }

  const pending = activateMutation.isPending || deactivateMutation.isPending || reseedMutation.isPending;

  return (
    <div className="ml-auto flex items-center gap-2">
      <Button type="button" disabled={pending} onClick={() => (status.active ? deactivateMutation.mutate() : activateMutation.mutate())}>
        {status.active ? "Exit demo mode" : "Demo mode"}
      </Button>
      {status.active && (
        <Button type="button" variant="outline" disabled={pending} onClick={() => reseedMutation.mutate()}>
          Reseed
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Mount `ThemeToggle` in `TopBar.tsx`**

In `frontend/src/components/TopBar.tsx`, replace the `TopBar` function's body — delete the explanatory comment block (its reasoning is now stale, this task is the "once that's true" it referred to) and render `<ThemeToggle />` next to `<DemoModeToggle />`:

```tsx
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
      <ThemeToggle />
    </header>
  );
}
```

(`ThemeToggle`'s own definition, above this function in the same file, is unchanged.)

- [ ] **Step 3: Update `/dev/ui-kit`'s theme-toggle section heading**

In `frontend/src/pages/dev/UiKit.tsx`, the `uikit-theme-toggle` section's `<h2>` currently reads "Theme Toggle (not yet mounted in the app shell -- see TopBar.tsx)" — this is now false. Change it to:

```tsx
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Theme Toggle
        </h2>
```

- [ ] **Step 4: Update the existing theme-toggle Playwright test to exercise the mounted `TopBar`, not just `/dev/ui-kit`**

In `frontend/e2e/foundation.spec.ts`, add a new test alongside the existing `"Foundation — Theme Toggle (exercised via /dev/ui-kit)"` block (keep that one as-is — it still exercises the same underlying component and is still valid regression coverage):

```ts
test.describe("Foundation — Theme Toggle (mounted in TopBar)", () => {
  test("is visible in the app shell and switches theme app-wide", async ({ page }) => {
    await page.goto("/queue");
    const toggle = page.getByRole("banner").getByTitle(/Switch to light theme/i);
    await expect(toggle).toBeVisible();
    await toggle.click();

    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("light");

    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bodyBg);
    expect(luminance(rgb)).toBeGreaterThan(200);

    // Sidebar nav and the queue page's own content must also render light,
    // not just <body> -- this is the whole point of deferring the mount to
    // the last task: a page still holding a hardcoded slate-* background
    // would stay dark here even though <body> switched.
    const sidebarBg = await page.evaluate(() => {
      const aside = document.querySelector("aside");
      return aside ? getComputedStyle(aside).backgroundColor : null;
    });
    expect(sidebarBg).not.toBeNull();
    const sidebarRgb = await normalizeColor(page, sidebarBg!);
    expect(luminance(sidebarRgb)).toBeGreaterThan(150);
  });
});
```

`TopBar` renders inside a `<header>`, which has the implicit ARIA `banner` role — `page.getByRole("banner")` scopes the lookup to it, avoiding ambiguity with the `/dev/ui-kit` gallery's own unmounted `<ThemeToggle />` instance (not present on `/queue`, so there's no actual ambiguity today, but scoping this way keeps the test correct if a future page ever renders a second toggle).

- [ ] **Step 5: Full verification pass**

Run, from `frontend/`:

```bash
npx tsc -b
npm run test
npm run build
npx playwright test
```

Expected: 0 tsc errors, all vitest tests pass (107 pre-existing + this plan's new assertions), production build succeeds, all Playwright tests pass including every new one added across Tasks 1, 2, and this task.

Then, from the repo root, confirm the backend baseline is unaffected (this plan touches only `frontend/`):

```bash
uv run pytest -q
```

Expected: 279 passed (same baseline recorded before this plan started).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DemoModeToggle.tsx frontend/src/components/TopBar.tsx frontend/src/pages/dev/UiKit.tsx frontend/e2e/foundation.spec.ts
git commit -m "feat(ui): restyle DemoModeToggle, mount ThemeToggle in the live app shell"
```

---

## Post-plan note for the final whole-branch review

Before the final review, correct one factual error in the committed Phase 2 design spec (`docs/superpowers/specs/2026-08-02-foundry-ui-overhaul-phase2-design.md`, Architecture §1, the `Sheet` bullet): it claims Sheet is "notably more complete than Phase 1's `Dialog` port, which has neither" (Escape-to-close). **Foundry has no `Dialog` at all** — Phase 1 never ported one (confirmed: no `Dialog`/`dialog` reference anywhere in `frontend/src`). This sentence bled in from the unrelated WatchTower codebase during spec-writing. It doesn't change the architecture decision (Sheet is still the right port, there's just nothing to compare it against) — fix the sentence to remove the false comparison when convenient, e.g. as part of the final review's docs pass.
