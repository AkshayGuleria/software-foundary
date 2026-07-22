import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProjectKgGraph, getRunBlastRadius, listMemory } from "./knowledge";

describe("knowledge API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listMemory GETs /api/memory with query params", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: [
          {
            id: "01JM1", scope: "project", kind: "lesson", title: "L", body_md: "x",
            project_id: "01JP1", pack_id: null, source_run_id: "01JR1", created_at: "2026-07-22T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    const items = await listMemory({ project_id: "01JP1" });

    expect(fetch).toHaveBeenCalledWith("/api/memory?project_id=01JP1", undefined);
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("L");
  });

  it("listMemory with no params hits the bare endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await listMemory();
    expect(fetch).toHaveBeenCalledWith("/api/memory", undefined);
  });

  it("getProjectKgGraph GETs /api/projects/{id}/kg-graph", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { nodes: ["a.py", "b.py"], edges: [{ from: "a.py", to: "b.py" }] }, paging: {} }),
    });

    const graph = await getProjectKgGraph("01JP1");

    expect(fetch).toHaveBeenCalledWith("/api/projects/01JP1/kg-graph", undefined);
    expect(graph.nodes).toEqual(["a.py", "b.py"]);
  });

  it("getRunBlastRadius GETs /api/runs/{id}/blast-radius", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { changed_files: ["a.py"], radius: ["a.py", "b.py"] }, paging: {} }),
    });

    const result = await getRunBlastRadius("01JR1");

    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/blast-radius", undefined);
    expect(result.radius).toContain("b.py");
  });
});
