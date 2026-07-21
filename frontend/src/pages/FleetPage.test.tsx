import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FleetPage from "./FleetPage";

function renderWithProviders() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FleetPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("FleetPage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("lists active sessions with a link to their run", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: [
          {
            id: "01JS1", work_unit_id: "01JU1", run_id: "01JR1", step_id: "implement",
            driver: "FakeDriver", status: "running", model: "fake", tokens_in: 10, tokens_out: 20,
            started_at: "2026-07-21T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("implement")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /implement/i })).toHaveAttribute("href", "/runs/01JR1");
  });

  it("shows an empty state when no sessions are active", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });

    renderWithProviders();

    await waitFor(() => expect(screen.getByText(/no active sessions/i)).toBeInTheDocument());
  });
});
