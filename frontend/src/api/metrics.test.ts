import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProjectMetrics } from "./metrics";

describe("metrics API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("getProjectMetrics GETs /api/metrics/{projectId}", async () => {
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

    const metrics = await getProjectMetrics("01JP1");

    expect(fetch).toHaveBeenCalledWith("/api/metrics/01JP1", undefined);
    expect(metrics.rework_rate).toBe(0.25);
  });
});
