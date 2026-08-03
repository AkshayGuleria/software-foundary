import { useId, useState } from "react";
import type { Artifact, Gate } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import { Card } from "./ui/display/Card";
import { Button } from "./ui/forms/Button";
import { Textarea } from "./ui/forms/Textarea";
import { Label } from "./ui/forms/Label";

const REJECTION_CHIPS = ["missing tests", "wrong approach", "incomplete", "needs docs"];

export default function GateCard({
  gate,
  artifact,
  onDecide,
}: {
  gate: Gate;
  artifact: Artifact | undefined;
  onDecide: (decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const feedbackId = useId();
  const [rejecting, setRejecting] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [selectedChips, setSelectedChips] = useState<string[]>([]);

  function toggleChip(chip: string) {
    setSelectedChips((prev) => (prev.includes(chip) ? prev.filter((c) => c !== chip) : [...prev, chip]));
  }

  return (
    <Card className="p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{gate.gate_type} gate</span>
        <span className="text-[var(--muted-foreground)]">{gate.decision}</span>
      </div>

      {gate.gate_type === "derived" && gate.cost_estimate && (
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
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
              <Button variant="success" size="sm" onClick={() => onDecide("approved", undefined)}>
                Approve
              </Button>
              <Button variant="destructive" size="sm" onClick={() => setRejecting(true)}>
                Reject
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-1">
                {REJECTION_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => toggleChip(chip)}
                    className={`rounded-[var(--radius-full)] border px-2 py-0.5 text-xs ${
                      selectedChips.includes(chip)
                        ? "border-orange-500 text-[#ea580c]"
                        : "border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--ring)]"
                    }`}
                    style={
                      selectedChips.includes(chip)
                        ? { backgroundColor: "color-mix(in oklab, #ea580c 25%, transparent)" }
                        : undefined
                    }
                  >
                    {chip}
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor={feedbackId} className="text-xs">Feedback</Label>
                <Textarea
                  id={feedbackId}
                  className="text-sm"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
              </div>
              <Button
                variant="destructive"
                size="sm"
                className="self-start"
                onClick={() => {
                  onDecide("rejected", { chips: selectedChips, text: feedbackText });
                  setRejecting(false);
                  setFeedbackText("");
                  setSelectedChips([]);
                }}
              >
                Submit rejection
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
