import { apiFetch } from "./client";
import type { Project } from "./types";

export async function listProjects(): Promise<Project[]> {
  const res = await apiFetch<Project[]>("/api/projects");
  return res.data;
}

export async function createProject(input: { name: string; path: string }): Promise<Project> {
  const res = await apiFetch<Project>("/api/projects", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function pauseProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/pause`, { method: "POST" });
  return res.data;
}

export async function archiveProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/archive`, { method: "POST" });
  return res.data;
}

export async function activateProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/activate`, { method: "POST" });
  return res.data;
}

export async function getProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}`);
  return res.data;
}

export async function updateProjectSettings(
  id: string,
  fields: { driver?: string; token_budget?: number; playbook_path?: string },
): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/settings`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  return res.data;
}
