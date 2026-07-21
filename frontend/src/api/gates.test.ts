import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decideGate } from "./gates";

describe("gates API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("decideGate POSTs decision with no feedback for approval", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "approved" }, paging: {} }),
    });

    await decideGate("01JG1", "approved");

    expect(fetch).toHaveBeenCalledWith("/api/gates/01JG1/decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "approved", feedback_chips: [], feedback_text: null }),
    });
  });

  it("decideGate POSTs feedback chips/text for rejection", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "rejected" }, paging: {} }),
    });

    await decideGate("01JG1", "rejected", { chips: ["incomplete"], text: "needs more detail" });

    expect(fetch).toHaveBeenCalledWith("/api/gates/01JG1/decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: "rejected", feedback_chips: ["incomplete"], feedback_text: "needs more detail" }),
    });
  });
});
