import { apiFetch } from "./client";
import type { DemoStatus } from "./types";

export async function getDemoStatus(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/status");
  return res.data;
}

export async function activateDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/activate", { method: "POST" });
  return res.data;
}

export async function deactivateDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/deactivate", { method: "POST" });
  return res.data;
}

export async function reseedDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/reseed", { method: "POST" });
  return res.data;
}
