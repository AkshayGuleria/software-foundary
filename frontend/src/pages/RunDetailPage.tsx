import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { decideGate } from "../api/gates";
import { cancelRun, getRunArtifacts, getRunDetail } from "../api/runs";
import EventFeed from "../components/EventFeed";
import GateCard from "../components/GateCard";
import Ribbon from "../components/Ribbon";
import { useEventStream } from "../hooks/useEventStream";

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = id!;
  const queryClient = useQueryClient();
  const events = useEventStream(runId);

  const { data: detail, isLoading } = useQuery({ queryKey: ["run", runId], queryFn: () => getRunDetail(runId) });
  const { data: artifacts } = useQuery({ queryKey: ["run-artifacts", runId], queryFn: () => getRunArtifacts(runId) });

  // The scheduler drives run progress in the background (new gates, artifacts,
  // and unit status all change outside of any request this page makes). The
  // live feed is the only signal that something changed server-side, so treat
  // each incoming event as a cue to refetch the run's derived state — without
  // this, the ribbon and gates/artifacts panel go stale the moment progress
  // happens off the back of a decision made on some other page (or by the
  // scheduler ticking on its own), even though the feed keeps scrolling.
  useEffect(() => {
    if (events.length === 0) return;
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
  }, [events.length, runId, queryClient]);

  const decideMutation = useMutation({
    mutationFn: ({ gateId, decision, feedback }: { gateId: string; decision: "approved" | "rejected"; feedback?: { chips: string[]; text: string } }) =>
      decideGate(gateId, decision, feedback),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  if (isLoading || !detail) {
    return <p className="text-slate-400">Loading…</p>;
  }

  const isTerminal = detail.run.status === "closed" || detail.run.status === "cancelled";
  const artifactById = new Map((artifacts ?? []).map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">{detail.run.title}</h2>
          <p className="text-sm text-slate-500">{detail.run.status}</p>
        </div>
        <button
          className="rounded bg-red-900 px-3 py-1.5 text-sm hover:bg-red-800 disabled:opacity-40"
          disabled={isTerminal}
          onClick={() => cancelMutation.mutate()}
        >
          Cancel run
        </button>
      </div>

      <Ribbon units={detail.units} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Gates & artifacts</h3>
          {detail.gates.map((gate) => (
            <GateCard
              key={gate.id}
              gate={gate}
              artifact={gate.artifact_id ? artifactById.get(gate.artifact_id) : undefined}
              onDecide={(decision, feedback) => decideMutation.mutate({ gateId: gate.id, decision, feedback })}
            />
          ))}
          {detail.gates.length === 0 && <p className="text-sm text-slate-500">No gates yet.</p>}
        </div>

        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Live feed</h3>
          <EventFeed events={events} />
        </div>
      </div>
    </div>
  );
}
