import { apiFetch } from "./client";
import type { ProjectHealth } from "./types";

export async function getPortfolio(): Promise<ProjectHealth[]> {
  const res = await apiFetch<ProjectHealth[]>("/api/portfolio");
  return res.data;
}
