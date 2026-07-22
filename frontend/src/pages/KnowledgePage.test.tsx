import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgePage from "./KnowledgePage";

function renderWithProviders(initialEntries: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <KnowledgePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("KnowledgePage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders the project's KG graph and memory browser", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/kg-graph")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { nodes: ["a.py", "b.py"], edges: [{ from: "a.py", to: "b.py" }] }, paging: {} }),
        });
      }
      if (url.startsWith("/api/memory")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              {
                id: "01JM1", scope: "project", kind: "lesson", title: "A real lesson", body_md: "x",
                project_id: "01JP1", pack_id: null, source_run_id: null, created_at: "2026-07-22T00:00:00Z",
              },
            ],
            paging: {},
          }),
        });
      }
      if (url.startsWith("/api/projects")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: [{ id: "01JP1", name: "demo", path: "/tmp/demo", kg_status: "none", created_at: "2026-07-22T00:00:00Z" }], paging: {} }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderWithProviders(["/knowledge?project_id=01JP1"]);

    await waitFor(() => expect(screen.getAllByTestId("kg-node")).toHaveLength(2));
    await waitFor(() => expect(screen.getByText("A real lesson")).toBeInTheDocument());
  });

  it("prompts for a project when none is selected", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: [{ id: "01JP1", name: "demo", path: "/tmp/demo", kg_status: "none", created_at: "2026-07-22T00:00:00Z" }], paging: {} }),
    });

    renderWithProviders(["/knowledge"]);

    await waitFor(() => expect(screen.getByText(/select a project/i)).toBeInTheDocument());
  });
});
