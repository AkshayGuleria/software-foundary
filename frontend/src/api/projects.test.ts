import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createProject, listProjects } from "./projects";

describe("projects API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listProjects GETs /api/projects and returns the data array", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ id: "01J1", name: "acme", path: "/tmp/acme", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
    });

    const projects = await listProjects();

    expect(fetch).toHaveBeenCalledWith("/api/projects", undefined);
    expect(projects).toHaveLength(1);
    expect(projects[0].name).toBe("acme");
  });

  it("createProject POSTs to /api/projects with a JSON body", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: { id: "01J2", name: "beta", path: "/tmp/beta", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }, paging: {} }),
    });

    const project = await createProject({ name: "beta", path: "/tmp/beta" });

    expect(fetch).toHaveBeenCalledWith("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "beta", path: "/tmp/beta" }),
    });
    expect(project.id).toBe("01J2");
  });
});
