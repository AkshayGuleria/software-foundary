import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createProjectPlaybook,
  deleteProjectPlaybook,
  getPackPlaybookContent,
  getProjectPlaybook,
  listProjectPlaybooks,
  updateProjectPlaybook,
} from "./projectPlaybooks";

function mockFetchOnce(data: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status < 400,
      status,
      json: async () => ({ data, paging: {} }),
    }),
  );
}

describe("projectPlaybooks API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("listProjectPlaybooks calls the right URL", async () => {
    mockFetchOnce([]);
    await listProjectPlaybooks("proj-1");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks", undefined);
  });

  it("getProjectPlaybook calls the right URL", async () => {
    mockFetchOnce({ slug: "hotfix", content: "..." });
    await getProjectPlaybook("proj-1", "hotfix");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", undefined);
  });

  it("createProjectPlaybook POSTs name and content", async () => {
    mockFetchOnce({ slug: "hotfix" }, 201);
    await createProjectPlaybook("proj-1", { name: "Hotfix", content: "toml..." });
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Hotfix", content: "toml..." }),
    });
  });

  it("updateProjectPlaybook PUTs content", async () => {
    mockFetchOnce({ slug: "hotfix" });
    await updateProjectPlaybook("proj-1", "hotfix", { content: "toml..." });
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content: "toml..." }),
    });
  });

  it("deleteProjectPlaybook DELETEs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 204 }),
    );
    await deleteProjectPlaybook("proj-1", "hotfix");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", { method: "DELETE" });
  });

  it("getPackPlaybookContent calls the right URL and returns the content string", async () => {
    mockFetchOnce({ content: "[playbook]\nid = \"bugfix\"" });
    const content = await getPackPlaybookContent("default", "playbooks/bugfix.toml");
    expect(fetch).toHaveBeenCalledWith("/api/packs/default/playbooks/bugfix.toml", undefined);
    expect(content).toBe("[playbook]\nid = \"bugfix\"");
  });
});
