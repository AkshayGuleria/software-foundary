import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun, createRun, getRunArtifacts, getRunDetail, getRunGraph, listRuns } from "./runs";

const sampleRun = {
  id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml",
  title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z",
};

describe("runs API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listRuns builds the query string from filters", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [sampleRun], paging: {} }) });

    const runs = await listRuns({ project_id: "01JP1", status: "active" });

    expect(fetch).toHaveBeenCalledWith("/api/runs?project_id=01JP1&status=active", undefined);
    expect(runs).toHaveLength(1);
  });

  it("listRuns with no filters hits the bare endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await listRuns();
    expect(fetch).toHaveBeenCalledWith("/api/runs", undefined);
  });

  it("createRun POSTs the run creation payload", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 201, json: async () => ({ data: sampleRun, paging: {} }) });
    const run = await createRun({ project_id: "01JP1", playbook_path: "demo.toml", title: "demo run" });
    expect(fetch).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_id: "01JP1", playbook_path: "demo.toml", title: "demo run" }),
    });
    expect(run.id).toBe("01JR1");
  });

  it("getRunDetail GETs /api/runs/{id}", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: { run: sampleRun, units: [], gates: [] }, paging: {} }) });
    const detail = await getRunDetail("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1", undefined);
    expect(detail.run.id).toBe("01JR1");
  });

  it("getRunArtifacts appends ?latest=1 when requested", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await getRunArtifacts("01JR1", true);
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/artifacts?latest=1", undefined);
  });

  it("getRunGraph GETs /api/runs/{id}/graph", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
    await getRunGraph("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/graph", undefined);
  });

  it("cancelRun POSTs to the cancel endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 204, json: async () => ({}) });
    await cancelRun("01JR1");
    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/cancel", { method: "POST" });
  });
});
