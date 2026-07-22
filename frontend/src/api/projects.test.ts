import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activateProject, archiveProject, createProject, listProjects, pauseProject } from "./projects";

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
      json: async () => ({ data: { id: "01J2", name: "beta", path: "/tmp/beta", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" }, paging: {} }),
    });

    const project = await createProject({ name: "beta", path: "/tmp/beta" });

    expect(fetch).toHaveBeenCalledWith("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "beta", path: "/tmp/beta" }),
    });
    expect(project.id).toBe("01J2");
  });

  it("pauseProject posts to the pause endpoint and returns the updated project", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: { id: "p1", name: "demo", path: ".", kg_status: "none", status: "paused", created_at: "2026-01-01T00:00:00Z" },
        paging: {},
      }),
    });

    const result = await pauseProject("p1");

    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/pause", expect.objectContaining({ method: "POST" }));
    expect(result.status).toBe("paused");
  });

  it("archiveProject posts to the archive endpoint and returns the updated project", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: { id: "p1", name: "demo", path: ".", kg_status: "none", status: "archived", created_at: "2026-01-01T00:00:00Z" },
        paging: {},
      }),
    });

    const result = await archiveProject("p1");

    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/archive", expect.objectContaining({ method: "POST" }));
    expect(result.status).toBe("archived");
  });

  it("activateProject posts to the activate endpoint and returns the updated project", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: { id: "p1", name: "demo", path: ".", kg_status: "none", status: "active", created_at: "2026-01-01T00:00:00Z" },
        paging: {},
      }),
    });

    const result = await activateProject("p1");

    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/activate", expect.objectContaining({ method: "POST" }));
    expect(result.status).toBe("active");
  });
});
