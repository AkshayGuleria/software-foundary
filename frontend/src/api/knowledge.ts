import { apiFetch } from "./client";
import type { BlastRadius, KgGraph, MemoryItem } from "./types";

export async function listMemory(params?: {
  project_id?: string;
  scope?: string;
  kind?: string;
}): Promise<MemoryItem[]> {
  const query = new URLSearchParams();
  if (params?.project_id) query.set("project_id", params.project_id);
  if (params?.scope) query.set("scope", params.scope);
  if (params?.kind) query.set("kind", params.kind);
  const qs = query.toString();
  const res = await apiFetch<MemoryItem[]>(`/api/memory${qs ? `?${qs}` : ""}`);
  return res.data;
}

export async function getProjectKgGraph(projectId: string): Promise<KgGraph> {
  const res = await apiFetch<KgGraph>(`/api/projects/${projectId}/kg-graph`);
  return res.data;
}

export async function getRunBlastRadius(runId: string): Promise<BlastRadius> {
  const res = await apiFetch<BlastRadius>(`/api/runs/${runId}/blast-radius`);
  return res.data;
}
