import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getPortfolio } from "./portfolio";

describe("getPortfolio", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("fetches /api/portfolio and returns the data array", async () => {
    const row = {
      project_id: "p1",
      name: "demo",
      status: "active",
      active_run_count: 1,
      pending_gate_count: 2,
      last_run_status: "active",
      last_run_at: "2026-01-01T00:00:00Z",
      rework_rate: 0.5,
      budget_burn_ratio: null,
      attention_score: 25.0,
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [row], paging: {} }),
    });

    const result = await getPortfolio();

    expect(fetch).toHaveBeenCalledWith("/api/portfolio", undefined);
    expect(result).toEqual([row]);
  });
});
