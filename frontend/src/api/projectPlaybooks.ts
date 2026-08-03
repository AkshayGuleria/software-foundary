import { apiFetch } from "./client";
import type { ProjectPlaybookDetail, ProjectPlaybookSummary } from "./types";

export async function listProjectPlaybooks(projectId: string): Promise<ProjectPlaybookSummary[]> {
  const res = await apiFetch<ProjectPlaybookSummary[]>(`/api/projects/${projectId}/playbooks`);
  return res.data;
}

export async function getProjectPlaybook(projectId: string, slug: string): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks/${slug}`);
  return res.data;
}

export async function createProjectPlaybook(
  projectId: string,
  input: { name: string; content: string },
): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function updateProjectPlaybook(
  projectId: string,
  slug: string,
  input: { content: string },
): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks/${slug}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function deleteProjectPlaybook(projectId: string, slug: string): Promise<void> {
  await apiFetch<undefined>(`/api/projects/${projectId}/playbooks/${slug}`, { method: "DELETE" });
}

export async function getPackPlaybookContent(packId: string, relPath: string): Promise<string> {
  const res = await apiFetch<{ content: string }>(`/api/packs/${packId}/${relPath}`);
  return res.data.content;
}
