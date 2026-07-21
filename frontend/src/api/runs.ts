import { apiFetch } from "./client";
import type { Artifact, Run, RunDetail, RunGraph } from "./types";

export async function listRuns(params?: { project_id?: string; status?: string }): Promise<Run[]> {
  const query = new URLSearchParams();
  if (params?.project_id) query.set("project_id", params.project_id);
  if (params?.status) query.set("status", params.status);
  const qs = query.toString();
  const res = await apiFetch<Run[]>(`/api/runs${qs ? `?${qs}` : ""}`);
  return res.data;
}

export async function createRun(input: { project_id: string; playbook_path: string; title?: string }): Promise<Run> {
  const res = await apiFetch<Run>("/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const res = await apiFetch<RunDetail>(`/api/runs/${runId}`);
  return res.data;
}

export async function getRunArtifacts(runId: string, latest?: boolean): Promise<Artifact[]> {
  const res = await apiFetch<Artifact[]>(`/api/runs/${runId}/artifacts${latest ? "?latest=1" : ""}`);
  return res.data;
}

export async function getRunGraph(runId: string): Promise<RunGraph> {
  const res = await apiFetch<RunGraph>(`/api/runs/${runId}/graph`);
  return res.data;
}

export async function cancelRun(runId: string): Promise<void> {
  await apiFetch<null>(`/api/runs/${runId}/cancel`, { method: "POST" });
}
