import { useState } from "react";
import type { Artifact, Gate } from "../api/types";
import ArtifactCard from "./ArtifactCard";

export default function GateCard({
  gate,
  artifact,
  onDecide,
}: {
  gate: Gate;
  artifact: Artifact | undefined;
  onDecide: (decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");

  return (
    <div className="rounded border border-slate-800 p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{gate.gate_type} gate</span>
        <span className="text-slate-500">{gate.decision}</span>
      </div>

      {gate.gate_type === "derived" && gate.cost_estimate && (
        <p className="mt-1 text-xs text-slate-400">
          Estimated: {gate.cost_estimate.estimated_writes_steps} write step(s), ~
          {gate.cost_estimate.estimated_tokens.toLocaleString()} tokens
        </p>
      )}

      {artifact && (
        <div className="mt-2">
          <ArtifactCard artifact={artifact} />
        </div>
      )}

      {gate.decision === "pending" && (
        <div className="mt-3 flex flex-col gap-2">
          {!rejecting ? (
            <div className="flex gap-2">
              <button
                className="rounded bg-emerald-700 px-3 py-1 text-sm hover:bg-emerald-600"
                onClick={() => onDecide("approved", undefined)}
              >
                Approve
              </button>
              <button
                className="rounded bg-red-800 px-3 py-1 text-sm hover:bg-red-700"
                onClick={() => setRejecting(true)}
              >
                Reject
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col text-xs">
                Feedback
                <textarea
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
              </label>
              <button
                className="self-start rounded bg-red-800 px-3 py-1 text-sm hover:bg-red-700"
                onClick={() => {
                  onDecide("rejected", { chips: [], text: feedbackText });
                  setRejecting(false);
                  setFeedbackText("");
                }}
              >
                Submit rejection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
