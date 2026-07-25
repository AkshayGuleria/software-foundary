import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { batchDecideGates, completeHumanTask, getQueue } from "./queue";

describe("queue API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("getQueue GETs /api/queue", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { gates: [], human_tasks: [] }, paging: {} }),
    });

    const queue = await getQueue();

    expect(fetch).toHaveBeenCalledWith("/api/queue", undefined);
    expect(queue.gates).toEqual([]);
  });

  it("batchDecideGates POSTs the gate ids", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { approved: ["g1"], skipped: [] }, paging: {} }),
    });

    const result = await batchDecideGates(["g1"]);

    expect(fetch).toHaveBeenCalledWith("/api/gates/batch-decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ gate_ids: ["g1"] }),
    });
    expect(result.approved).toEqual(["g1"]);
  });

  it("completeHumanTask POSTs to the complete endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { id: "u1", status: "closed" }, paging: {} }),
    });

    const result = await completeHumanTask("u1");

    expect(fetch).toHaveBeenCalledWith("/api/human-tasks/u1/complete", { method: "POST" });
    expect(result.status).toBe("closed");
  });
});
