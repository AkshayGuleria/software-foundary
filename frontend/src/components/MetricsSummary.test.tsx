import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricsSummary, { metricsStats } from "./MetricsSummary";

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

describe("metricsStats", () => {
  it("formats all six stats from raw metrics", () => {
    const stats = metricsStats({
      approval_latency_seconds: 120,
      rework_rate: 0.25,
      retry_count: 2,
      crash_count: 1,
      auto_resolved_count: 3,
      escalated_count: 1,
    });

    expect(stats).toEqual([
      { label: "Rework rate", value: "25%" },
      { label: "Avg approval latency", value: "120s" },
      { label: "Retries", value: "2" },
      { label: "Crashes", value: "1" },
      { label: "Auto-resolved conflicts", value: "3" },
      { label: "Escalated conflicts", value: "1" },
    ]);
  });
});
