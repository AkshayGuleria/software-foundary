export interface Paging {
  offset: number | null;
  limit: number | null;
  total: number | null;
  total_pages: number | null;
  has_next: boolean | null;
  has_prev: boolean | null;
}

export interface ApiResponse<T> {
  data: T;
  paging: Paging;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  status_code: number;
  timestamp: string;
  path: string;
  details: unknown;
}

export interface ErrorEnvelope {
  error: ApiErrorBody;
}

export interface Project {
  id: string;
  name: string;
  path: string;
  kg_status: string;
  created_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  playbook_ref: string;
  title: string;
  status: string;
  created_at: string;
}

export interface WorkUnit {
  id: string;
  step_id: string;
  type: string;
  status: string;
  attempt: number;
  owner_session_id: string | null;
}

export interface CostEstimate {
  estimated_writes_steps: number;
  estimated_tokens: number;
  basis: string;
}

export interface Gate {
  id: string;
  work_unit_id: string;
  gate_type: string;
  decision: string;
  artifact_id?: string | null;
  cost_estimate?: CostEstimate | null;
  decided_by?: string | null;
}

export interface Artifact {
  id: string;
  work_unit_id: string;
  kind: string;
  version: number;
  produced_by_role: string;
  payload_json: Record<string, unknown>;
}

export interface RunDetail {
  run: Run;
  units: WorkUnit[];
  gates: Gate[];
}

export interface RunGraph {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
}
