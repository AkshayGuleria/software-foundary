import type { Gate, WorkUnit } from "../api/types";
import { useStyle } from "./ui/useStyle";

const CSS = `
.ribbon-tone-success{background:color-mix(in oklab, var(--status-success) 20%, transparent);color:var(--status-success)}
.ribbon-tone-warning{background:color-mix(in oklab, var(--status-warning) 20%, transparent);color:var(--status-warning)}
.ribbon-tone-danger{background:color-mix(in oklab, var(--destructive) 20%, transparent);color:var(--destructive)}
.ribbon-tone-danger-strong{background:color-mix(in oklab, var(--destructive) 30%, transparent);color:var(--destructive)}
.ribbon-tone-neutral{background:var(--secondary);color:var(--secondary-foreground)}
.ribbon-tone-brand{background:color-mix(in oklab, #ea580c 20%, transparent);color:#ea580c}
`;

// Brand orange (in_progress/ready) uses a literal hex via the color-mix
// tint pattern above -- orange isn't tokenized in this plan, but it still
// needs to stay theme-adaptive like the other ribbon-tone-* classes.
const STATUS_STYLES: Record<string, string> = {
  closed: "ribbon-tone-success",
  blocked: "ribbon-tone-warning",
  failed: "ribbon-tone-danger",
  killed: "ribbon-tone-danger-strong",
  in_progress: "ribbon-tone-brand",
  ready: "ribbon-tone-brand",
  open: "ribbon-tone-neutral",
};

const GATE_STYLES: Record<string, string> = {
  pending: "ribbon-tone-neutral",
  approved: "ribbon-tone-success",
  rejected: "ribbon-tone-danger",
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
  useStyle("ribbon-tones", CSS);
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
            className={`flex overflow-hidden rounded-[var(--radius-full)] border border-[var(--border)] text-sm font-medium ${onSelectUnit ? "cursor-pointer" : ""}`}
          >
            <span data-testid="ribbon-pill-agent" className={`px-3 py-1 ${styleFor(u.status)}`}>
              A · {u.step_id}
            </span>
            {gate && (
              <span
                data-testid="ribbon-pill-human"
                data-gate-type={gate.gate_type}
                className={`border-l border-[var(--border)] px-3 py-1 ${gateStyleFor(gate.decision)} ${gate.gate_type === "derived" ? "italic" : ""}`}
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
