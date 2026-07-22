import { apiFetch } from "./client";
import type { PackManifest } from "./types";

export async function listPacks(): Promise<PackManifest[]> {
  const res = await apiFetch<PackManifest[]>("/api/packs");
  return res.data;
}

export async function getPack(id: string): Promise<PackManifest> {
  const res = await apiFetch<PackManifest>(`/api/packs/${id}`);
  return res.data;
}
