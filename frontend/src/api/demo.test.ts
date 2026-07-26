import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "./demo";

describe("demo API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("getDemoStatus GETs /api/demo/status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
    });

    const status = await getDemoStatus();

    expect(fetch).toHaveBeenCalledWith("/api/demo/status", undefined);
    expect(status.active).toBe(false);
  });

  it("activateDemo POSTs to /api/demo/activate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
    });

    const status = await activateDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/activate", { method: "POST" });
    expect(status.active).toBe(true);
  });

  it("deactivateDemo POSTs to /api/demo/deactivate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
    });

    const status = await deactivateDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/deactivate", { method: "POST" });
    expect(status.active).toBe(false);
  });

  it("reseedDemo POSTs to /api/demo/reseed", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
    });

    const status = await reseedDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/reseed", { method: "POST" });
    expect(status.active).toBe(true);
  });
});
