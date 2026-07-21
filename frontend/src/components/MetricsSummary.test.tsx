import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricsSummary from "./MetricsSummary";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("MetricsSummary", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders rework rate as a percentage", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: {
          approval_latency_seconds: 120, rework_rate: 0.25, retry_count: 2,
          crash_count: 1, auto_resolved_count: 3, escalated_count: 1,
        },
        paging: {},
      }),
    });

    renderWithClient(<MetricsSummary projectId="01JP1" />);

    await waitFor(() => expect(screen.getByText(/25%/)).toBeInTheDocument());
  });
});
