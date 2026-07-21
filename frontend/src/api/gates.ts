import { apiFetch } from "./client";
import type { Gate } from "./types";

export async function decideGate(
  gateId: string,
  decision: "approved" | "rejected",
  feedback?: { chips: string[]; text: string }
): Promise<Gate> {
  const res = await apiFetch<Gate>(`/api/gates/${gateId}/decide`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      decision,
      feedback_chips: feedback?.chips ?? [],
      feedback_text: feedback?.text ?? null,
    }),
  });
  return res.data;
}
