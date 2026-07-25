import { apiFetch } from "./client";
import type { Queue } from "./types";

export async function getQueue(): Promise<Queue> {
  const res = await apiFetch<Queue>("/api/queue");
  return res.data;
}

export async function batchDecideGates(gateIds: string[]): Promise<{ approved: string[]; skipped: string[] }> {
  const res = await apiFetch<{ approved: string[]; skipped: string[] }>("/api/gates/batch-decide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ gate_ids: gateIds }),
  });
  return res.data;
}

export async function completeHumanTask(unitId: string): Promise<{ id: string; status: string }> {
  const res = await apiFetch<{ id: string; status: string }>(`/api/human-tasks/${unitId}/complete`, {
    method: "POST",
  });
  return res.data;
}
