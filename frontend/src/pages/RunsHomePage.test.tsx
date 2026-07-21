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
