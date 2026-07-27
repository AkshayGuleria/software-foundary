import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import GateCard from "./GateCard";

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
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col gap-4 overflow-y-auto border-l border-slate-800 bg-slate-950 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">{unit.step_id}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-xs hover:border-orange-400"
          >
            Close
          </button>
        </div>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Gate</h4>
          {unitGate ? (
            <GateCard
              gate={unitGate}
              artifact={unitGate.artifact_id ? unitArtifacts.find((a) => a.id === unitGate.artifact_id) : undefined}
              onDecide={(decision, feedback) => onDecideGate(unitGate.id, decision, feedback)}
            />
          ) : (
            <p className="text-sm text-slate-500">No gate for this step.</p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Artifacts</h4>
          {unitArtifacts.length === 0 && <p className="text-sm text-slate-500">No artifacts yet.</p>}
          {unitArtifacts.map((a) => (
            <div key={a.id} data-testid="drawer-artifact">
              <ArtifactCard artifact={a} />
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Session log</h4>
          {unitSessions.length === 0 && <p className="text-sm text-slate-500">No sessions yet.</p>}
          {unitSessions.map((s) => (
            <div
              key={s.id}
              data-testid="drawer-session"
              className="flex items-center justify-between rounded border border-slate-800 px-2 py-1 text-xs text-slate-400"
            >
              <span>{s.driver} · {s.model ?? "—"}</span>
              <span>{s.status}</span>
              <span className="tabular-nums">{s.tokens_in} in / {s.tokens_out} out</span>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Events</h4>
          {unitEvents.length === 0 && <p className="text-sm text-slate-500">No events yet.</p>}
          {unitEvents.map((e) => (
            <div key={e.seq} className="font-mono text-xs text-slate-400">
              [{e.seq}] {e.type} {JSON.stringify(e.payload)}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
