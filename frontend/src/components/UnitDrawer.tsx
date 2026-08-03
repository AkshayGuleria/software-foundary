import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import GateCard from "./GateCard";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "./ui/overlay/Sheet";

export default function UnitDrawer({
  unit,
  events,
  artifacts,
  gates,
  sessions,
  onClose,
  onDecideGate,
}: {
  unit: WorkUnit;
  events: FeedEventLike[];
  artifacts: Artifact[];
  gates: Gate[];
  sessions: Session[];
  onClose: () => void;
  onDecideGate: (gateId: string, decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const unitEvents = events.filter((e) => e.unit_id === unit.id);
  const unitArtifacts = artifacts.filter((a) => a.work_unit_id === unit.id).sort((a, b) => b.version - a.version);
  const unitGate = gates.find((g) => g.work_unit_id === unit.id);
  // Sessions attach to a SESSION-type WorkUnit, not the TASK-type unit this
  // drawer is scoped to -- filter by the task's owner_session_id (its
  // current/latest session), not its own id, which would never match any
  // session's work_unit_id. This only surfaces the most recent attempt, not
  // full retry history: once a task retries, owner_session_id is
  // reassigned to the new session unit and the old session unit's id is no
  // longer reachable from the task, and there's no other stored link back
  // to it without a schema change -- a real limitation discovered while
  // implementing this plan (not in the original design spec), accepted
  // here as out of scope rather than blocking on a schema change.
  const unitSessions = sessions.filter((s) => s.work_unit_id === unit.owner_session_id);

  return (
    <Sheet open onOpenChange={(v) => { if (!v) onClose(); }}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{unit.step_id}</SheetTitle>
        </SheetHeader>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Gate</h4>
          {unitGate ? (
            <GateCard
              gate={unitGate}
              artifact={unitGate.artifact_id ? unitArtifacts.find((a) => a.id === unitGate.artifact_id) : undefined}
              onDecide={(decision, feedback) => onDecideGate(unitGate.id, decision, feedback)}
            />
          ) : (
            <p className="text-sm text-[var(--muted-foreground)]">No gate for this step.</p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Artifacts</h4>
          {unitArtifacts.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No artifacts yet.</p>}
          {unitArtifacts.map((a) => (
            <div key={a.id} data-testid="drawer-artifact">
              <ArtifactCard artifact={a} />
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Session log</h4>
          {unitSessions.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No sessions yet.</p>}
          {unitSessions.map((s) => (
            <div
              key={s.id}
              data-testid="drawer-session"
              className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)]"
            >
              <span>{s.driver} · {s.model ?? "—"}</span>
              <span>{s.status}</span>
              <span className="tabular-nums">{s.tokens_in} in / {s.tokens_out} out</span>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Events</h4>
          {unitEvents.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">No events yet.</p>}
          {unitEvents.map((e) => (
            <div key={e.seq} className="font-mono text-xs text-[var(--muted-foreground)]">
              [{e.seq}] {e.type} {JSON.stringify(e.payload)}
            </div>
          ))}
        </section>
      </SheetContent>
    </Sheet>
  );
}
