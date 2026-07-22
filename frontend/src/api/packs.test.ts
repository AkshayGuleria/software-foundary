import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getPack, listPacks } from "./packs";

describe("listPacks / getPack", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listPacks fetches /api/packs", async () => {
    const pack = { id: "default", version: "0.1.0", roles: [{ id: "developer", model: "fake" }], playbooks: ["playbooks/sdlc_story.toml"] };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [pack], paging: {} }),
    });

    const result = await listPacks();

    expect(fetch).toHaveBeenCalledWith("/api/packs", undefined);
    expect(result).toEqual([pack]);
  });

  it("getPack fetches /api/packs/{id}", async () => {
    const pack = { id: "default", version: "0.1.0", roles: [], playbooks: [] };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: pack, paging: {} }),
    });

    const result = await getPack("default");

    expect(fetch).toHaveBeenCalledWith("/api/packs/default", undefined);
    expect(result).toEqual(pack);
  });
});
