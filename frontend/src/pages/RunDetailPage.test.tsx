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
      if (url === "/api/runs/01JR1/graph") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderPage("01JR1");

    await waitFor(() => expect(screen.getByText(/plan_approval/)).toBeInTheDocument());
    expect(screen.getByText(/30000|30,000/)).toBeInTheDocument();
  });

  it("cancel button calls the cancel endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, _init?: RequestInit) => {
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
      if (url === "/api/runs/01JR1/graph") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
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

  it("shows the run's pack_version_pin", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === "/api/runs/01JR1") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              run: {
                id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml", title: "demo run", status: "active",
                pack_version_pin: "default@0.1.0", created_at: "2026-07-21T00:00:00Z",
              },
              units: [],
              gates: [],
            },
            paging: {},
          }),
        });
      }
      if (url === "/api/runs/01JR1/graph") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderPage("01JR1");

    await waitFor(() => expect(screen.getByText(/default@0\.1\.0/)).toBeInTheDocument());
  });
});
