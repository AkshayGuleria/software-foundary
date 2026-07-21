import { apiFetch } from "./client";

export interface ProjectMetrics {
  approval_latency_seconds: number;
  rework_rate: number;
  retry_count: number;
  crash_count: number;
  auto_resolved_count: number;
  escalated_count: number;
}

export async function getProjectMetrics(projectId: string): Promise<ProjectMetrics> {
  const res = await apiFetch<ProjectMetrics>(`/api/metrics/${projectId}`);
  return res.data;
}
