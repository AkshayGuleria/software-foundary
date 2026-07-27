import type { Gate, WorkUnit } from "../api/types";

const STATUS_STYLES: Record<string, string> = {
  closed: "bg-emerald-900 text-emerald-300",
  blocked: "bg-amber-900 text-amber-300",
  failed: "bg-red-900 text-red-300",
  killed: "bg-red-950 text-red-400",
  in_progress: "bg-orange-900 text-orange-300",
  ready: "bg-orange-950 text-orange-400",
  open: "bg-slate-800 text-slate-400",
};

const GATE_STYLES: Record<string, string> = {
  pending: "bg-slate-800 text-slate-400",
  approved: "bg-emerald-900 text-emerald-300",
  rejected: "bg-red-900 text-red-300",
};

function styleFor(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.open;
}

function gateStyleFor(decision: string): string {
  return GATE_STYLES[decision] ?? GATE_STYLES.pending;
}

export default function Ribbon({
  units,
  gates,
  onSelectUnit,
}: {
  units: WorkUnit[];
  gates: Gate[];
  onSelectUnit?: (unit: WorkUnit) => void;
}) {
  const steps = units
    .filter((u) => u.type !== "session")
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const gateByUnit = new Map(gates.map((g) => [g.work_unit_id, g]));

  return (
    <div className="flex flex-wrap gap-2">
      {steps.map((u) => {
        const gate = gateByUnit.get(u.id);
        return (
          <div
            key={u.id}
            data-testid={`ribbon-step-${u.id}`}
            role={onSelectUnit ? "button" : undefined}
            onClick={() => onSelectUnit?.(u)}
            className={`flex overflow-hidden rounded-full border border-slate-700 text-sm font-medium ${onSelectUnit ? "cursor-pointer" : ""}`}
          >
            <span data-testid="ribbon-pill-agent" className={`px-3 py-1 ${styleFor(u.status)}`}>
              A · {u.step_id}
            </span>
            {gate && (
              <span
                data-testid="ribbon-pill-human"
                data-gate-type={gate.gate_type}
                className={`border-l border-slate-700 px-3 py-1 ${gateStyleFor(gate.decision)} ${gate.gate_type === "derived" ? "italic" : ""}`}
              >
                H
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
