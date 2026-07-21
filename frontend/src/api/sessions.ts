import { apiFetch } from "./client";
import type { Session } from "./types";

export async function listActiveSessions(): Promise<Session[]> {
  const res = await apiFetch<Session[]>("/api/sessions");
  return res.data;
}
