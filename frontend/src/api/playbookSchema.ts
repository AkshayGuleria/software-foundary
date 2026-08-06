import { apiFetch } from "./client";
import type { SchemaFieldDoc } from "./types";

export async function getPlaybookSchemaHelp(): Promise<SchemaFieldDoc[]> {
  const res = await apiFetch<SchemaFieldDoc[]>("/api/playbooks/schema-help");
  return res.data;
}
