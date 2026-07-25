import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectDetailPage from "./ProjectDetailPage";

function renderWithProviders(projectId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/${projectId}`]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectDetailPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the project header with name, path, and status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByText("acme")).toBeInTheDocument());
    expect(screen.getByText("/tmp/acme")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("shows a not-found message for an unknown project", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false, status: 404,
        json: async () => ({ error: { code: "NOT_FOUND", message: "Project p1 not found", status_code: 404, details: null } }),
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByText(/project not found/i)).toBeInTheDocument());
  });

  it("renders recent runs and metrics for the project", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        if (url === "/api/runs?project_id=p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [{ id: "r1", project_id: "p1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" }],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 30, rework_rate: 0.2, retry_count: 1, crash_count: 0, auto_resolved_count: 2, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByRole("link", { name: /demo run/i })).toHaveAttribute("href", "/runs/r1"));
    expect(screen.getByRole("link", { name: /view all runs/i })).toHaveAttribute("href", "/runs?project_id=p1");
    expect(screen.getByText("20%")).toBeInTheDocument();
  });

  it("orders runs by created_at descending regardless of API response order", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        if (url === "/api/runs?project_id=p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              // Deliberately returned oldest-first to prove the page sorts rather than trusting API order.
              data: [
                { id: "r-old", project_id: "p1", playbook_ref: "demo.toml", title: "old run", status: "active", created_at: "2026-07-01T00:00:00Z" },
                { id: "r-new", project_id: "p1", playbook_ref: "demo.toml", title: "new run", status: "active", created_at: "2026-07-20T00:00:00Z" },
              ],
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByRole("link", { name: /new run/i })).toBeInTheDocument());

    const links = screen.getAllByRole("link").filter((el) => el.getAttribute("href")?.startsWith("/runs/"));
    expect(links.map((el) => el.getAttribute("href"))).toEqual(["/runs/r-new", "/runs/r-old"]);
  });
});
