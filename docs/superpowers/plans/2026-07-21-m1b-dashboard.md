# M1b — Dashboard (Runs Home + Run Detail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React dashboard M1's roadmap text actually calls for — "runs home, run detail (ribbon, artifacts/gates panel, SSE feed)" — consuming M1a's `/api` so a human can register a project, start a run, and drive the full plan → approve → implement → reject → rework → approve cycle from the browser, closing M1's exit criterion that M1a alone (API-only) couldn't.

**Architecture:** React + Vite + TypeScript, Tailwind for styling, React Router for the two routes (`/runs`, `/runs/:id`), TanStack Query for server-state (fetch/cache/refetch against `/api`, proxied by Vite's dev server to `foundry serve`'s `:8000`), a typed API client wrapping every endpoint and unwrapping the ADR-001 `{data,paging}`/`{error}` envelope into either a value or a typed `ApiClientError`. The run-detail page's live feed uses the browser's native `EventSource` against `/api/stream/{run_id}` — no client library needed, SSE is a web platform primitive.

**Tech Stack:** React 18, Vite 5, TypeScript 5, Tailwind CSS 3, React Router 6, TanStack Query 5, Vitest + React Testing Library (component/unit tests), npm.

## Global Constraints

- Every screen this plan builds is explicitly named in design doc §15's M1 roadmap text: "runs home, run detail (ribbon, artifacts/gates panel, SSE feed)". Nothing else from §11's full view list (portfolio home, fleet view, DAG view, knowledge view, packs & settings) is in scope — those are M2/M3/M4 per the roadmap's own milestone assignments. Don't build them ahead of the plan that needs them.
- Consumes M1a's `/api` exactly as shipped — every request/response shape in this plan must match the actual Pydantic models in `src/foundry/api/routes/{projects,runs,gates}.py` and the envelope in `src/foundry/api/schemas.py`/`docs/adrs/001-api-response-structure.md`. No backend changes in this plan.
- No auth — `/api` has none in M1a, and this is still a local-first, single-user dashboard (design doc §2.2 v1 scale).
- No production build/static-serving wiring (bundling the dashboard into the FastAPI app) — dev-server-only for this plan. `npm run dev` + `foundry serve` running side by side, Vite proxying `/api` to `:8000`.
- Frontend lives at `frontend/` (new top-level directory, sibling to `src/`), matching the design doc's stated stack (React/Vite/TS/Tailwind) and CLAUDE.md's existing note that `frontend/` isn't scaffolded until M1.

---

### Task 1: Vite/React/TS/Tailwind scaffold + typed API client

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/.gitignore`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`
- Test: `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`

**Interfaces:**
- Produces: TS interfaces `Paging`, `ApiResponse<T>`, `ApiErrorBody`, `ErrorEnvelope`, `Project`, `Run`, `WorkUnit`, `Gate`, `Artifact`, `RunDetail`, `CostEstimate` (all in `api/types.ts`, exact field names matching the Python Pydantic models — see Step 3). `class ApiClientError extends Error` (fields: `code: string`, `statusCode: number`, `details: unknown`). `async function apiFetch<T>(path: string, init?: RequestInit): Promise<T>` — unwraps `{data, paging}` → returns `{data: T, paging: Paging}`, throws `ApiClientError` on any non-2xx response by parsing the `{error}` envelope.

- [ ] **Step 1: Scaffold the project (no test yet — this is config/tooling, not logic)**

```json
// frontend/package.json
{
  "name": "foundry-dashboard",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.27.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.2",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.2",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.13",
    "typescript": "^5.6.3",
    "vite": "^5.4.8",
    "vitest": "^2.1.2"
  }
}
```

```typescript
// frontend/vite.config.ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

```json
// frontend/tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

```javascript
// frontend/tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

```javascript
// frontend/postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Foundry</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```
# frontend/.gitignore
node_modules/
dist/
*.local
```

```typescript
// frontend/vitest.config.ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
```

```typescript
// frontend/src/test/setup.ts
import "@testing-library/jest-dom/vitest";
```

```css
/* frontend/src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Run `npm install`**

Run: `cd frontend && npm install`
Expected: installs cleanly, no errors (a `package-lock.json` is created — commit it).

- [ ] **Step 3: Write the failing test for the API client**

```typescript
// frontend/src/api/client.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiClientError } from "./client";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps a successful {data, paging} envelope", async () => {
    const mockResponse = {
      data: { id: "01J1", name: "acme" },
      paging: { offset: null, limit: null, total: null, total_pages: null, has_next: null, has_prev: null },
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const result = await apiFetch<{ id: string; name: string }>("/api/projects/01J1");

    expect(result.data).toEqual({ id: "01J1", name: "acme" });
    expect(fetch).toHaveBeenCalledWith("/api/projects/01J1", undefined);
  });

  it("throws ApiClientError with code/message/details on an {error} envelope", async () => {
    const mockError = {
      error: {
        code: "NOT_FOUND",
        message: "Project xyz not found",
        status_code: 404,
        timestamp: "2026-07-21T00:00:00Z",
        path: "/api/projects/xyz",
        details: null,
      },
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => mockError,
    });

    await expect(apiFetch("/api/projects/xyz")).rejects.toThrow(ApiClientError);
    try {
      await apiFetch("/api/projects/xyz");
      throw new Error("expected apiFetch to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.code).toBe("NOT_FOUND");
      expect(apiErr.statusCode).toBe(404);
      expect(apiErr.message).toBe("Project xyz not found");
    }
  });

  it("passes init options through to fetch (method, body, headers)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: { id: "01J2" }, paging: {} }),
    });

    await apiFetch("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "acme", path: "/tmp/acme" }),
    });

    expect(fetch).toHaveBeenCalledWith("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "acme", path: "/tmp/acme" }),
    });
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './client'` (file doesn't exist yet).

- [ ] **Step 5: Write `frontend/src/api/types.ts`**

```typescript
export interface Paging {
  offset: number | null;
  limit: number | null;
  total: number | null;
  total_pages: number | null;
  has_next: boolean | null;
  has_prev: boolean | null;
}

export interface ApiResponse<T> {
  data: T;
  paging: Paging;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  status_code: number;
  timestamp: string;
  path: string;
  details: unknown;
}

export interface ErrorEnvelope {
  error: ApiErrorBody;
}

export interface Project {
  id: string;
  name: string;
  path: string;
  kg_status: string;
  created_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  playbook_ref: string;
  title: string;
  status: string;
  created_at: string;
}

export interface WorkUnit {
  id: string;
  step_id: string;
  type: string;
  status: string;
  attempt: number;
  owner_session_id: string | null;
}

export interface CostEstimate {
  estimated_writes_steps: number;
  estimated_tokens: number;
  basis: string;
}

export interface Gate {
  id: string;
  work_unit_id: string;
  gate_type: string;
  decision: string;
  artifact_id?: string | null;
  cost_estimate?: CostEstimate | null;
  decided_by?: string | null;
}

export interface Artifact {
  id: string;
  work_unit_id: string;
  kind: string;
  version: number;
  produced_by_role: string;
  payload_json: Record<string, unknown>;
}

export interface RunDetail {
  run: Run;
  units: WorkUnit[];
  gates: Gate[];
}

export interface RunGraph {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
}
```

- [ ] **Step 6: Write `frontend/src/api/client.ts`**

```typescript
import type { ApiResponse, ErrorEnvelope } from "./types";

export class ApiClientError extends Error {
  code: string;
  statusCode: number;
  details: unknown;

  constructor(code: string, message: string, statusCode: number, details: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const response = await fetch(path, init);
  const body = await response.json();

  if (!response.ok) {
    const errBody = (body as ErrorEnvelope).error;
    throw new ApiClientError(errBody.code, errBody.message, errBody.status_code, errBody.details);
  }

  return body as ApiResponse<T>;
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (3 tests)

- [ ] **Step 8: Write the app shell**

```tsx
// frontend/src/App.tsx
export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Foundry</h1>
      </header>
      <main className="p-6">
        <p className="text-slate-400">Dashboard scaffold — routes land in later tasks.</p>
      </main>
    </div>
  );
}
```

```tsx
// frontend/src/main.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
```

- [ ] **Step 9: Run full test suite + typecheck**

Run: `cd frontend && npm test && npx tsc -b`
Expected: PASS, no type errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Vite/React/TS/Tailwind scaffold + typed API client (ADR-001 envelope)"
```

---

### Task 2: Projects — list, create, page

**Files:**
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/pages/ProjectsPage.tsx`
- Create: `frontend/src/components/NewProjectForm.tsx`
- Test: `frontend/src/api/projects.test.ts`
- Test: `frontend/src/pages/ProjectsPage.test.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `ApiClientError` (Task 1); `Project`, `ApiResponse` (Task 1).
- Produces: `listProjects(): Promise<Project[]>`, `createProject(input: {name: string; path: string}): Promise<Project>` (both in `api/projects.ts`). `<ProjectsPage />` — lists projects, has an inline create form, uses TanStack Query (`useQuery`/`useMutation`).

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/api/projects.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createProject, listProjects } from "./projects";

describe("projects API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listProjects GETs /api/projects and returns the data array", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ id: "01J1", name: "acme", path: "/tmp/acme", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
    });

    const projects = await listProjects();

    expect(fetch).toHaveBeenCalledWith("/api/projects", undefined);
    expect(projects).toHaveLength(1);
    expect(projects[0].name).toBe("acme");
  });

  it("createProject POSTs to /api/projects with a JSON body", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: { id: "01J2", name: "beta", path: "/tmp/beta", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }, paging: {} }),
    });

    const project = await createProject({ name: "beta", path: "/tmp/beta" });

    expect(fetch).toHaveBeenCalledWith("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "beta", path: "/tmp/beta" }),
    });
    expect(project.id).toBe("01J2");
  });
});
```

```tsx
// frontend/src/pages/ProjectsPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectsPage from "./ProjectsPage";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ProjectsPage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders the list of projects from the API", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ id: "01J1", name: "acme", path: "/tmp/acme", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
    });

    renderWithClient(<ProjectsPage />);

    await waitFor(() => expect(screen.getByText("acme")).toBeInTheDocument());
  });

  it("submits the create-project form and refreshes the list", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) }) // initial list
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ data: { id: "01J2", name: "newproj", path: "/tmp/newproj", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }, paging: {} }),
      }) // create
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: [{ id: "01J2", name: "newproj", path: "/tmp/newproj", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
      }); // refetch after create

    renderWithClient(<ProjectsPage />);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByLabelText(/name/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/name/i), "newproj");
    await user.type(screen.getByLabelText(/path/i), "/tmp/newproj");
    await user.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() => expect(screen.getByText("newproj")).toBeInTheDocument());
  });
});
```

Add `@testing-library/user-event` to `frontend/package.json`'s `devDependencies` (`"@testing-library/user-event": "^14.5.2"`) and run `npm install` before running these tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `Cannot find module './projects'` / `Cannot find module './ProjectsPage'`.

- [ ] **Step 3: Write `frontend/src/api/projects.ts`**

```typescript
import { apiFetch } from "./client";
import type { Project } from "./types";

export async function listProjects(): Promise<Project[]> {
  const res = await apiFetch<Project[]>("/api/projects");
  return res.data;
}

export async function createProject(input: { name: string; path: string }): Promise<Project> {
  const res = await apiFetch<Project>("/api/projects", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}
```

- [ ] **Step 4: Write `frontend/src/components/NewProjectForm.tsx`**

```tsx
import { useState } from "react";

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
      <label className="flex flex-col text-sm">
        Name
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label className="flex flex-col text-sm">
        Path
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          required
        />
      </label>
      <button type="submit" className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
        Create project
      </button>
    </form>
  );
}
```

- [ ] **Step 5: Write `frontend/src/pages/ProjectsPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/projects";
import NewProjectForm from "../components/NewProjectForm";

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
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id} className="rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs?project_id=${p.id}`} className="font-medium text-orange-400 hover:underline">
                {p.name}
              </Link>
              <span className="ml-2 text-sm text-slate-500">{p.path}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests, including Task 1's)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/projects.ts frontend/src/api/projects.test.ts \
        frontend/src/pages/ProjectsPage.tsx frontend/src/pages/ProjectsPage.test.tsx \
        frontend/src/components/NewProjectForm.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): projects list + create page"
```

---

### Task 3: Runs home — list, filter, create

**Files:**
- Create: `frontend/src/api/runs.ts`
- Create: `frontend/src/pages/RunsHomePage.tsx`
- Create: `frontend/src/components/NewRunForm.tsx`
- Test: `frontend/src/api/runs.test.ts`
- Test: `frontend/src/pages/RunsHomePage.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 1); `Run`, `RunDetail`, `RunGraph`, `Artifact` (Task 1); `listProjects` (Task 2, for the create-run project picker).
- Produces: `listRuns(params?: {project_id?: string; status?: string}): Promise<Run[]>`, `createRun(input: {project_id: string; playbook_path: string; title?: string}): Promise<Run>`, `getRunDetail(runId: string): Promise<RunDetail>`, `getRunArtifacts(runId: string, latest?: boolean): Promise<Artifact[]>`, `getRunGraph(runId: string): Promise<RunGraph>`, `cancelRun(runId: string): Promise<void>` (all in `api/runs.ts` — later tasks reuse `getRunDetail`/`getRunArtifacts`/`cancelRun`, defined now so this task's API module is complete). `<RunsHomePage />` — reads `?project_id=` from the URL (via `useSearchParams`), lists matching runs, has a create-run form, each run links to `/runs/:id`.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/api/runs.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun, createRun, getRunArtifacts, getRunDetail, getRunGraph, listRuns } from "./runs";

const sampleRun = {
  id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml",
  title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z",
};

describe("runs API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listRuns builds the query string from filters", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [sampleRun], paging: {} }) });

    const runs = await listRuns({ project_id: "01JP1", status: "active" });

    expect(fetch).toHaveBeenCalledWith("/api/runs?project_id=01JP1&status=active", undefined);
    expect(runs).toHaveLength(1);
  });

  it("listRuns with no filters hits the bare endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await listRuns();
    expect(fetch).toHaveBeenCalledWith("/api/runs", undefined);
  });

  it("createRun POSTs the run creation payload", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 201, json: async () => ({ data: sampleRun, paging: {} }) });
    const run = await createRun({ project_id: "01JP1", playbook_path: "demo.toml", title: "demo run" });
    expect(fetch).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_id: "01JP1", playbook_path: "demo.toml", title: "demo run" }),
    });
    expect(run.id).toBe("01JR1");
  });

  it("getRunDetail GETs /api/runs/{id}", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: { run: sampleRun, units: [], gates: [] }, paging: {} }) });
    const detail = await getRunDetail("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1", undefined);
    expect(detail.run.id).toBe("01JR1");
  });

  it("getRunArtifacts appends ?latest=1 when requested", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await getRunArtifacts("01JR1", true);
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/artifacts?latest=1", undefined);
  });

  it("getRunGraph GETs /api/runs/{id}/graph", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
    await getRunGraph("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/graph", undefined);
  });

  it("cancelRun POSTs to the cancel endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 204, json: async () => ({}) });
    await cancelRun("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/cancel", { method: "POST" });
  });
});
```

```tsx
// frontend/src/pages/RunsHomePage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RunsHomePage from "./RunsHomePage";

function renderWithProviders(initialEntries: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <RunsHomePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RunsHomePage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("lists runs and links each to its detail page", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.startsWith("/api/runs?")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" }],
            paging: {},
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderWithProviders(["/runs?project_id=01JP1"]);

    await waitFor(() => expect(screen.getByText("demo run")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /demo run/i })).toHaveAttribute("href", "/runs/01JR1");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — modules don't exist yet.

- [ ] **Step 3: Write `frontend/src/api/runs.ts`**

```typescript
import { apiFetch } from "./client";
import type { Artifact, Run, RunDetail, RunGraph } from "./types";

export async function listRuns(params?: { project_id?: string; status?: string }): Promise<Run[]> {
  const query = new URLSearchParams();
  if (params?.project_id) query.set("project_id", params.project_id);
  if (params?.status) query.set("status", params.status);
  const qs = query.toString();
  const res = await apiFetch<Run[]>(`/api/runs${qs ? `?${qs}` : ""}`);
  return res.data;
}

export async function createRun(input: { project_id: string; playbook_path: string; title?: string }): Promise<Run> {
  const res = await apiFetch<Run>("/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const res = await apiFetch<RunDetail>(`/api/runs/${runId}`);
  return res.data;
}

export async function getRunArtifacts(runId: string, latest?: boolean): Promise<Artifact[]> {
  const res = await apiFetch<Artifact[]>(`/api/runs/${runId}/artifacts${latest ? "?latest=1" : ""}`);
  return res.data;
}

export async function getRunGraph(runId: string): Promise<RunGraph> {
  const res = await apiFetch<RunGraph>(`/api/runs/${runId}/graph`);
  return res.data;
}

export async function cancelRun(runId: string): Promise<void> {
  await apiFetch<null>(`/api/runs/${runId}/cancel`, { method: "POST" });
}
```

- [ ] **Step 4: Write `frontend/src/components/NewRunForm.tsx`**

```tsx
import { useState } from "react";
import type { Project } from "../api/types";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined });
        setPlaybookPath("");
        setTitle("");
      }}
    >
      <label className="flex flex-col text-sm">
        Project
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          required
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        Playbook path
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </label>
      <label className="flex flex-col text-sm">
        Title (optional)
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <button type="submit" className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
        Start run
      </button>
    </form>
  );
}
```

- [ ] **Step 5: Write `frontend/src/pages/RunsHomePage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { createRun, listRuns } from "../api/runs";
import NewRunForm from "../components/NewRunForm";

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
      {projects && projects.length > 0 && (
        <NewRunForm projects={projects} defaultProjectId={projectId} onSubmit={(input) => createMutation.mutate(input)} />
      )}
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {runs?.map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                {r.title}
              </Link>
              <span className="text-sm text-slate-500">{r.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/runs.ts frontend/src/api/runs.test.ts \
        frontend/src/pages/RunsHomePage.tsx frontend/src/pages/RunsHomePage.test.tsx \
        frontend/src/components/NewRunForm.tsx
git commit -m "feat(frontend): runs home — list, project filter, create-run form"
```

---

### Task 4: Pipeline ribbon

**Files:**
- Create: `frontend/src/components/Ribbon.tsx`
- Test: `frontend/src/components/Ribbon.test.tsx`

**Interfaces:**
- Consumes: `WorkUnit` (Task 1).
- Produces: `<Ribbon units={WorkUnit[]} />` — renders one pill per pipeline step (units materialize in playbook order, and `WorkUnit.id` is a ULID so sorting by `id` recovers that order; `session`-type units are dynamically created during dispatch and are filtered out — they aren't pipeline steps), colored by status.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/Ribbon.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Ribbon from "./Ribbon";
import type { WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0, owner_session_id: null, ...overrides,
});

describe("Ribbon", () => {
  it("renders one pill per non-session unit, in id order", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J3", step_id: "review", status: "open" }),
      unit({ id: "01J1", step_id: "plan", status: "closed" }),
      unit({ id: "01J2Z", step_id: "session-for-plan", type: "session", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "blocked" }),
    ];

    render(<Ribbon units={units} />);

    const pills = screen.getAllByTestId("ribbon-pill");
    expect(pills).toHaveLength(3); // session unit excluded
    expect(pills.map((p) => p.textContent)).toEqual([
      expect.stringContaining("plan"),
      expect.stringContaining("implement"),
      expect.stringContaining("review"),
    ]);
  });

  it("colors a closed step differently from a blocked one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "blocked" })];
    render(<Ribbon units={units} />);
    const pills = screen.getAllByTestId("ribbon-pill");
    expect(pills[0].className).not.toEqual(pills[1].className);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './Ribbon'`

- [ ] **Step 3: Write `frontend/src/components/Ribbon.tsx`**

```tsx
import type { WorkUnit } from "../api/types";

const STATUS_STYLES: Record<string, string> = {
  closed: "bg-emerald-900 text-emerald-300 border-emerald-700",
  blocked: "bg-amber-900 text-amber-300 border-amber-700",
  failed: "bg-red-900 text-red-300 border-red-700",
  killed: "bg-red-950 text-red-400 border-red-800",
  in_progress: "bg-orange-900 text-orange-300 border-orange-700",
  ready: "bg-orange-950 text-orange-400 border-orange-800",
  open: "bg-slate-800 text-slate-400 border-slate-700",
};

function styleFor(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.open;
}

export default function Ribbon({ units }: { units: WorkUnit[] }) {
  const steps = units
    .filter((u) => u.type !== "session")
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  return (
    <div className="flex flex-wrap gap-2">
      {steps.map((u) => (
        <span
          key={u.id}
          data-testid="ribbon-pill"
          className={`rounded-full border px-3 py-1 text-sm font-medium ${styleFor(u.status)}`}
        >
          {u.step_id} · {u.status}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Ribbon.tsx frontend/src/components/Ribbon.test.tsx
git commit -m "feat(frontend): pipeline ribbon component"
```

---

### Task 5: Gates & artifacts panel

**Files:**
- Create: `frontend/src/api/gates.ts`
- Create: `frontend/src/components/GateCard.tsx`
- Create: `frontend/src/components/ArtifactCard.tsx`
- Test: `frontend/src/api/gates.test.ts`
- Test: `frontend/src/components/GateCard.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 1); `Gate`, `Artifact` (Task 1).
- Produces: `decideGate(gateId: string, decision: "approved" | "rejected", feedback?: {chips: string[]; text: string}): Promise<Gate>` (in `api/gates.ts`). `<GateCard gate={Gate} artifact={Artifact | undefined} onDecide={(decision, feedback) => void} />` — shows the gate's kind/decision/cost-estimate (if `gate_type === "derived"`), the linked artifact's payload preview (if any), and approve/reject controls (reject opens a feedback-text input) when `decision === "pending"`. `<ArtifactCard artifact={Artifact} />` — kind/version/role/payload preview, used standalone for artifacts not tied to a currently-pending gate.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/api/gates.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decideGate } from "./gates";

describe("gates API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("decideGate POSTs decision with no feedback for approval", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "approved" }, paging: {} }),
    });

    await decideGate("01JG1", "approved");

    expect(fetch).toHaveBeenCalledWith("/api/gates/01JG1/decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "approved", feedback_chips: [], feedback_text: null }),
    });
  });

  it("decideGate POSTs feedback chips/text for rejection", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "rejected" }, paging: {} }),
    });

    await decideGate("01JG1", "rejected", { chips: ["incomplete"], text: "needs more detail" });

    expect(fetch).toHaveBeenCalledWith("/api/gates/01JG1/decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "rejected", feedback_chips: ["incomplete"], feedback_text: "needs more detail" }),
    });
  });
});
```

```tsx
// frontend/src/components/GateCard.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import GateCard from "./GateCard";
import type { Gate } from "../api/types";

const pendingHumanGate: Gate = { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "pending", artifact_id: "01JA1" };
const pendingDerivedGate: Gate = {
  id: "01JG2", work_unit_id: "01JU2", gate_type: "derived", decision: "pending",
  cost_estimate: { estimated_writes_steps: 1, estimated_tokens: 30000, basis: "heuristic" },
};

describe("GateCard", () => {
  it("shows approve/reject controls for a pending gate and calls onDecide on approve", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(onDecide).toHaveBeenCalledWith("approved", undefined);
  });

  it("requires feedback text before submitting a rejection", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /reject/i }));
    await user.type(screen.getByLabelText(/feedback/i), "not good enough");
    await user.click(screen.getByRole("button", { name: /submit rejection/i }));

    expect(onDecide).toHaveBeenCalledWith("rejected", { chips: [], text: "not good enough" });
  });

  it("shows the cost estimate for a pending derived gate", () => {
    render(<GateCard gate={pendingDerivedGate} artifact={undefined} onDecide={vi.fn()} />);
    expect(screen.getByText(/30000|30,000/)).toBeInTheDocument();
  });

  it("shows no controls for an already-decided gate", () => {
    render(<GateCard gate={{ ...pendingHumanGate, decision: "approved" }} artifact={undefined} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — modules don't exist yet.

- [ ] **Step 3: Write `frontend/src/api/gates.ts`**

```typescript
import { apiFetch } from "./client";
import type { Gate } from "./types";

export async function decideGate(
  gateId: string,
  decision: "approved" | "rejected",
  feedback?: { chips: string[]; text: string }
): Promise<Gate> {
  const res = await apiFetch<Gate>(`/api/gates/${gateId}/decide`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      decision,
      feedback_chips: feedback?.chips ?? [],
      feedback_text: feedback?.text ?? null,
    }),
  });
  return res.data;
}
```

- [ ] **Step 4: Write `frontend/src/components/ArtifactCard.tsx`**

```tsx
import type { Artifact } from "../api/types";

export default function ArtifactCard({ artifact }: { artifact: Artifact }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{artifact.kind}</span>
        <span className="text-slate-500">v{artifact.version} · {artifact.produced_by_role}</span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-400">
        {JSON.stringify(artifact.payload_json, null, 2)}
      </pre>
    </div>
  );
}
```

- [ ] **Step 5: Write `frontend/src/components/GateCard.tsx`**

```tsx
import { useState } from "react";
import type { Artifact, Gate } from "../api/types";
import ArtifactCard from "./ArtifactCard";

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

  return (
    <div className="rounded border border-slate-800 p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{gate.gate_type} gate</span>
        <span className="text-slate-500">{gate.decision}</span>
      </div>

      {gate.gate_type === "derived" && gate.cost_estimate && (
        <p className="mt-1 text-xs text-slate-400">
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
              <button
                className="rounded bg-emerald-700 px-3 py-1 text-sm hover:bg-emerald-600"
                onClick={() => onDecide("approved")}
              >
                Approve
              </button>
              <button
                className="rounded bg-red-800 px-3 py-1 text-sm hover:bg-red-700"
                onClick={() => setRejecting(true)}
              >
                Reject
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col text-xs">
                Feedback
                <textarea
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
              </label>
              <button
                className="self-start rounded bg-red-800 px-3 py-1 text-sm hover:bg-red-700"
                onClick={() => {
                  onDecide("rejected", { chips: [], text: feedbackText });
                  setRejecting(false);
                  setFeedbackText("");
                }}
              >
                Submit rejection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/gates.ts frontend/src/api/gates.test.ts \
        frontend/src/components/GateCard.tsx frontend/src/components/GateCard.test.tsx \
        frontend/src/components/ArtifactCard.tsx
git commit -m "feat(frontend): gates & artifacts panel — approve/reject with feedback, cost estimate display"
```

---

### Task 6: Live SSE feed

**Files:**
- Create: `frontend/src/hooks/useEventStream.ts`
- Create: `frontend/src/components/EventFeed.tsx`
- Test: `frontend/src/hooks/useEventStream.test.ts`

**Interfaces:**
- Produces: `useEventStream(runId: string): FeedEvent[]` hook (`FeedEvent = {seq: number; type: string; payload: unknown}`) — opens an `EventSource` to `/api/stream/${runId}`, appends each received event, closes the connection on unmount. `<EventFeed runId={string} />` — renders the hook's events newest-first.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/hooks/useEventStream.test.ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEventStream } from "./useEventStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: string, lastEventId: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ data, lastEventId } as MessageEvent);
    }
  }
}

describe("useEventStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens an EventSource to /api/stream/{runId} and appends received events", () => {
    const { result } = renderHook(() => useEventStream("01JR1"));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/stream/01JR1");

    act(() => {
      FakeEventSource.instances[0].emit("unit.closed", JSON.stringify({ unit_id: "01JU1" }), "5");
    });

    expect(result.current).toEqual([{ seq: 5, type: "unit.closed", payload: { unit_id: "01JU1" } }]);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useEventStream("01JR1"));
    unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });
});
```

The generic `message` listener won't fire for named SSE events (`event: unit.closed`), and `sse_starlette` sends each event with its own `event:`/`id:` fields — the hook must listen per-event-type as they arrive, not assume a fixed list. Since the set of event types is open-ended (design doc §7's dot-namespaced taxonomy), listen on the generic catch-all by using `EventSource`'s untyped `message` semantics won't work for named events — instead, register a listener that receives ALL event types. Browsers' `EventSource` requires a named `addEventListener` per `event:` value; there's no wildcard. For this task, listen for the specific event-type names the rest of this plan actually produces and displays (`unit.ready`, `unit.closed`, `unit.blocked`, `unit.retried`, `session.spawned`, `artifact.produced`, `gate.created`, `gate.approved`, `gate.rejected`, `gate.derived_approved`, `run.cancelled`, `run.tick_error`) — this list is exactly the event taxonomy already emitted by `Store.append_event` call sites in `src/foundry/orchestrator/tick.py` and `src/foundry/api/routes/runs.py`'s cancel route. A future task can widen this if new event types are added.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './useEventStream'`

- [ ] **Step 3: Write `frontend/src/hooks/useEventStream.ts`**

```typescript
import { useEffect, useState } from "react";

export interface FeedEvent {
  seq: number;
  type: string;
  payload: unknown;
}

const KNOWN_EVENT_TYPES = [
  "unit.ready",
  "unit.closed",
  "unit.blocked",
  "unit.retried",
  "session.intent",
  "session.spawned",
  "artifact.produced",
  "gate.created",
  "gate.approved",
  "gate.rejected",
  "gate.derived_approved",
  "run.cancelled",
  "run.tick_error",
];

export function useEventStream(runId: string): FeedEvent[] {
  const [events, setEvents] = useState<FeedEvent[]>([]);

  useEffect(() => {
    setEvents([]);
    const source = new EventSource(`/api/stream/${runId}`);

    const handler = (type: string) => (ev: MessageEvent) => {
      setEvents((prev) => [...prev, { seq: Number(ev.lastEventId), type, payload: JSON.parse(ev.data) }]);
    };

    for (const type of KNOWN_EVENT_TYPES) {
      source.addEventListener(type, handler(type));
    }

    return () => source.close();
  }, [runId]);

  return events;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 5: Write `frontend/src/components/EventFeed.tsx`**

```tsx
import { useEventStream } from "../hooks/useEventStream";

export default function EventFeed({ runId }: { runId: string }) {
  const events = useEventStream(runId);

  return (
    <div className="flex flex-col gap-1 font-mono text-xs">
      {events.length === 0 && <p className="text-slate-500">Waiting for events…</p>}
      {events
        .slice()
        .reverse()
        .map((e) => (
          <div key={e.seq} className="rounded border border-slate-800 px-2 py-1">
            <span className="text-slate-500">[{e.seq}]</span> <span className="text-orange-400">{e.type}</span>{" "}
            <span className="text-slate-400">{JSON.stringify(e.payload)}</span>
          </div>
        ))}
    </div>
  );
}
```

- [ ] **Step 6: Run full test suite**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/ frontend/src/components/EventFeed.tsx
git commit -m "feat(frontend): live SSE event feed"
```

---

### Task 7: Run detail page + routing + cancel

**Files:**
- Create: `frontend/src/pages/RunDetailPage.tsx`
- Modify: `frontend/src/App.tsx` (add routing)
- Test: `frontend/src/pages/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `getRunDetail`, `getRunArtifacts`, `cancelRun` (Task 3); `decideGate` (Task 5); `Ribbon` (Task 4); `GateCard` (Task 5); `EventFeed` (Task 6).
- Produces: `<RunDetailPage />` (reads `:id` via `useParams`) — composes ribbon + gates/artifacts panel + live feed + a cancel button (disabled once the run is `closed`/`cancelled`). Routing in `App.tsx`: `/` redirects to `/runs`, `/runs` → `RunsHomePage`, `/runs/:id` → `RunDetailPage`, `/projects` → `ProjectsPage`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/RunDetailPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "./RunDetailPage";

class FakeEventSource {
  constructor(public url: string) {}
  addEventListener() {}
  close() {}
}

function renderPage(runId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/runs/${runId}`]}>
        <Routes>
          <Route path="/runs/:id" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RunDetailPage", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the ribbon, a pending gate, and its cost estimate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === "/api/runs/01JR1") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              run: { id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" },
              units: [{ id: "01JU1", step_id: "plan_approval", type: "gate", status: "blocked", attempt: 0, owner_session_id: null }],
              gates: [{ id: "01JG1", work_unit_id: "01JU1", gate_type: "derived", decision: "pending", cost_estimate: { estimated_writes_steps: 1, estimated_tokens: 30000, basis: "x" } }],
            },
            paging: {},
          }),
        });
      }
      if (url.startsWith("/api/runs/01JR1/artifacts")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderPage("01JR1");

    await waitFor(() => expect(screen.getByText(/plan_approval/)).toBeInTheDocument());
    expect(screen.getByText(/30000|30,000/)).toBeInTheDocument();
  });

  it("cancel button calls the cancel endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/runs/01JR1/cancel") {
        return Promise.resolve({ ok: true, status: 204, json: async () => ({}) });
      }
      if (url === "/api/runs/01JR1") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              run: { id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" },
              units: [],
              gates: [],
            },
            paging: {},
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderPage("01JR1");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("button", { name: /cancel run/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /cancel run/i }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/cancel", { method: "POST" })
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './RunDetailPage'`

- [ ] **Step 3: Write `frontend/src/pages/RunDetailPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { decideGate } from "../api/gates";
import { cancelRun, getRunArtifacts, getRunDetail } from "../api/runs";
import EventFeed from "../components/EventFeed";
import GateCard from "../components/GateCard";
import Ribbon from "../components/Ribbon";

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = id!;
  const queryClient = useQueryClient();

  const { data: detail, isLoading } = useQuery({ queryKey: ["run", runId], queryFn: () => getRunDetail(runId) });
  const { data: artifacts } = useQuery({ queryKey: ["run-artifacts", runId], queryFn: () => getRunArtifacts(runId) });

  const decideMutation = useMutation({
    mutationFn: ({ gateId, decision, feedback }: { gateId: string; decision: "approved" | "rejected"; feedback?: { chips: string[]; text: string } }) =>
      decideGate(gateId, decision, feedback),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  if (isLoading || !detail) {
    return <p className="text-slate-400">Loading…</p>;
  }

  const isTerminal = detail.run.status === "closed" || detail.run.status === "cancelled";
  const artifactById = new Map((artifacts ?? []).map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">{detail.run.title}</h2>
          <p className="text-sm text-slate-500">{detail.run.status}</p>
        </div>
        <button
          className="rounded bg-red-900 px-3 py-1.5 text-sm hover:bg-red-800 disabled:opacity-40"
          disabled={isTerminal}
          onClick={() => cancelMutation.mutate()}
        >
          Cancel run
        </button>
      </div>

      <Ribbon units={detail.units} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Gates & artifacts</h3>
          {detail.gates.map((gate) => (
            <GateCard
              key={gate.id}
              gate={gate}
              artifact={gate.artifact_id ? artifactById.get(gate.artifact_id) : undefined}
              onDecide={(decision, feedback) => decideMutation.mutate({ gateId: gate.id, decision, feedback })}
            />
          ))}
          {detail.gates.length === 0 && <p className="text-sm text-slate-500">No gates yet.</p>}
        </div>

        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Live feed</h3>
          <EventFeed runId={runId} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire routing in `frontend/src/App.tsx`**

```tsx
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import ProjectsPage from "./pages/ProjectsPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsHomePage from "./pages/RunsHomePage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-4 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Foundry</h1>
        <nav className="flex gap-3 text-sm">
          <NavLink to="/projects" className="text-slate-400 hover:text-orange-400">
            Projects
          </NavLink>
          <NavLink to="/runs" className="text-slate-400 hover:text-orange-400">
            Runs
          </NavLink>
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/runs" element={<RunsHomePage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
```

`react-router-dom`'s `<BrowserRouter>` needs to wrap `<App />` for routing to work outside tests (tests use `<MemoryRouter>` directly around the page components, as already written) — add it to `frontend/src/main.tsx`:

```tsx
// frontend/src/main.tsx — replace the existing file
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 6: Run typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/RunDetailPage.tsx frontend/src/pages/RunDetailPage.test.tsx \
        frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat(frontend): run detail page (ribbon + gates/artifacts + live feed + cancel) and routing"
```

---

### Task 8: End-to-end manual verification against the real backend

**Files:** None created — this task drives the real `foundry serve` + `npm run dev` stack through the actual exit-criterion cycle in a browser and fixes anything the mocked component tests couldn't catch (a real fetch/CORS/proxy issue, a real SSE connection, real Tailwind rendering). No new automated test — this is the manual-verification counterpart to M1a's Task 10.

**Interfaces:** None new — this task only drives already-built code against the already-built backend.

- [ ] **Step 1: Start the backend**

```bash
cd /Users/akshay.guleria/work/software-foundary/.claude/worktrees/m1b-dashboard
uv run foundry serve --db /tmp/foundry-m1b-verify.db --port 8000 &
```

- [ ] **Step 2: Start the frontend dev server**

```bash
cd frontend && npm run dev &
```

Expected: Vite prints a local URL (typically `http://localhost:5173`).

- [ ] **Step 3: Drive the full exit-criterion cycle through the browser**

Use the `run` skill (or a headless-browser tool if available in this environment) to:
1. Navigate to `http://localhost:5173/projects`, create a project (name: `demo`, path: `/tmp/demo`).
2. Navigate to `/runs`, start a run against `tests/orchestrator/fixtures/gated_demo.toml` (relative to the backend's cwd — the repo root).
3. Open the run's detail page. Confirm the ribbon renders, a pending gate appears within a few seconds (the backend's real `Scheduler.start()` background loop is ticking at its default interval).
4. Reject the gate with feedback text. Confirm a new artifact version appears after rework, and a new gate appears.
5. Approve the new gate. Confirm the run reaches `closed` and the ribbon shows every step `closed`.
6. Confirm the live feed panel showed events arriving in real time throughout (not just on page load) — this is the one thing unit tests with a faked `EventSource` cannot prove.
7. Start a second run, click "Cancel run", confirm its status updates to `cancelled` and the ribbon/cancel button reflect it (button disables).

If ANY step fails in a way the component tests didn't catch (a real CORS error, a proxy misconfiguration, a field-name mismatch that a fetch mock in a test happened to paper over), fix it now — this is exactly the kind of gap only a real end-to-end pass surfaces, and it's why this task exists.

- [ ] **Step 4: Stop both servers and clean up**

```bash
kill %1 %2 2>/dev/null
rm -f /tmp/foundry-m1b-verify.db*
```

Confirm via `ps`/`lsof` that neither process is still running before finishing.

- [ ] **Step 5: Run the full test suites one more time (backend + frontend)**

Run: `uv run pytest -v && cd frontend && npm test`
Expected: PASS (both, no regressions from any fixes made in Step 3)

- [ ] **Step 6: Commit any fixes from Step 3**

```bash
git add -A
git commit -m "fix(frontend): address issues found in end-to-end manual verification"
```

(Skip this commit entirely if Step 3 needed no fixes.)

---

## Out of scope for this plan (tracked, not forgotten)

- **Portfolio home, fleet view, DAG force-layout view, knowledge view, packs & settings** — explicitly M2/M3/M4 per design doc §15's own milestone assignments, not M1.
- **`human_task` / My-queue view** — M1a shipped `Store.complete_human_task` but no HTTP endpoint for it; this plan doesn't add one or a queue UI. A run containing a `human_task` step is visible (ribbon shows it `ready`/pending) but can't be completed from this dashboard yet.
- **Chat / `notes_addressed`** — no `POST /api/runs/{id}/chat` exists yet (M1a deferred it); no chat UI here either.
- **Production build + static-serving from FastAPI** — dev-server-only (`npm run dev` + Vite proxy). Bundling and serving the built dashboard from `foundry serve` itself is a small follow-up, not required for M1's exit criterion (a dev-server dashboard still satisfies "driven entirely from the browser").
- **Auth** — none in `/api` yet (M1a), none in this dashboard.
- **Real driver / `/internal` API** — still owed from M0; every run this dashboard shows still executes on `FakeDriver`.
