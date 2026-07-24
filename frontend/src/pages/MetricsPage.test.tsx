import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import MetricsPage from "./MetricsPage";

function renderWithProviders() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MetricsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders one row per project sorted by rework rate descending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [
                { id: "p1", name: "quiet", path: "/tmp/quiet", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
                { id: "p2", name: "busy", path: "/tmp/busy", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
              ],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 10, rework_rate: 0.1, retry_count: 0, crash_count: 0, auto_resolved_count: 0, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p2") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 20, rework_rate: 0.9, retry_count: 1, crash_count: 1, auto_resolved_count: 0, escalated_count: 1 },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("busy")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("quiet")).toBeInTheDocument());

    const rows = screen.getAllByRole("row").filter((r) => r.textContent?.includes("busy") || r.textContent?.includes("quiet"));
    expect(rows[0]).toHaveTextContent("busy");
    expect(rows[1]).toHaveTextContent("quiet");
    expect(screen.getByText("90%")).toBeInTheDocument();
  });

  it("shows a per-row error state without dropping the row or blocking other rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [
                { id: "p1", name: "healthy", path: "/tmp/healthy", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
                { id: "p2", name: "broken", path: "/tmp/broken", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
              ],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 10, rework_rate: 0.1, retry_count: 0, crash_count: 0, auto_resolved_count: 0, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p2") {
          return Promise.resolve({
            ok: false, status: 500,
            json: async () => ({ error: { code: "INTERNAL_ERROR", message: "boom", status_code: 500, details: null } }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("healthy")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("broken")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/failed to load metrics/i)).toBeInTheDocument());
    // The healthy row's real stats still render even though the other row errored.
    expect(screen.getByText("10%")).toBeInTheDocument();
  });
});
