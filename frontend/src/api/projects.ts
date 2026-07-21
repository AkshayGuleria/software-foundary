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
