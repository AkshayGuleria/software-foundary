import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import PortfolioHomePage from "./PortfolioHomePage";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortfolioHomePage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders project cards sorted by attention score with health signals", async () => {
    const rows = [
      {
        project_id: "p2",
        name: "busy",
        status: "active",
        active_run_count: 1,
        pending_gate_count: 2,
        last_run_status: "active",
        last_run_at: "2026-07-22T00:00:00Z",
        rework_rate: 0.5,
        budget_burn_ratio: 0.2,
        attention_score: 30.0,
      },
      {
        project_id: "p1",
        name: "quiet",
        status: "active",
        active_run_count: 0,
        pending_gate_count: 0,
        last_run_status: "closed",
        last_run_at: "2026-07-01T00:00:00Z",
        rework_rate: null,
        budget_burn_ratio: null,
        attention_score: 1.0,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: rows, paging: {} }) }),
    );

    renderWithClient(<PortfolioHomePage />);

    await waitFor(() => expect(screen.getByText("busy")).toBeInTheDocument());
    const cards = screen.getAllByTestId(/^portfolio-card-/);
    expect(cards[0]).toHaveAttribute("data-testid", "portfolio-card-p2");
    expect(cards[1]).toHaveAttribute("data-testid", "portfolio-card-p1");
    // Pending gate count somewhere on "busy"'s card. A loose /2/ regex would also
    // match "Budget burn: 20%" on the same card (budget_burn_ratio: 0.2), so match
    // the specific label text instead.
    expect(screen.getByText(/pending gates: 2/i)).toBeInTheDocument();
  });

  it("pausing a project calls the pause endpoint", async () => {
    const rows = [
      {
        project_id: "p1",
        name: "demo",
        status: "active",
        active_run_count: 0,
        pending_gate_count: 0,
        last_run_status: null,
        last_run_at: null,
        rework_rate: null,
        budget_burn_ratio: null,
        attention_score: 0.0,
      },
    ];
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: rows, paging: {} }) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: { ...rows[0], status: "paused" }, paging: {} }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: [{ ...rows[0], status: "paused" }], paging: {} }),
      });
    vi.stubGlobal("fetch", mockFetch);

    renderWithClient(<PortfolioHomePage />);
    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /pause/i }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith("/api/projects/p1/pause", expect.objectContaining({ method: "POST" })),
    );
  });
});
