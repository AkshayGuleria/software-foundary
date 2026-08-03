import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { batchDecideGates, completeHumanTask, getQueue } from "../api/queue";
import { Button } from "../components/ui/forms/Button";
import { Card } from "../components/ui/display/Card";

export default function QueuePage() {
  const queryClient = useQueryClient();
  const { data: queue, isLoading } = useQuery({ queryKey: ["queue"], queryFn: getQueue });
  const [selectedGateIds, setSelectedGateIds] = useState<string[]>([]);

  const batchApproveMutation = useMutation({
    mutationFn: () => batchDecideGates(selectedGateIds),
    onSuccess: () => {
      setSelectedGateIds([]);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const completeMutation = useMutation({
    mutationFn: (unitId: string) => completeHumanTask(unitId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });

  const toggleGate = (gateId: string) => {
    setSelectedGateIds((prev) =>
      prev.includes(gateId) ? prev.filter((id) => id !== gateId) : [...prev, gateId],
    );
  };

  if (isLoading || !queue) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">My Queue</h2>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Gates</h3>
          <Button
            variant="brand"
            type="button"
            disabled={selectedGateIds.length === 0 || batchApproveMutation.isPending}
            onClick={() => batchApproveMutation.mutate()}
          >
            Approve selected
          </Button>
        </div>
        <ul className="flex flex-col gap-2">
          {queue.gates.map((g) => (
            <li key={g.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    aria-label={g.step_id}
                    checked={selectedGateIds.includes(g.id)}
                    onChange={() => toggleGate(g.id)}
                  />
                  <div>
                    <span className="text-sm text-[var(--foreground)]">
                      {g.project_name} / <Link to={`/runs/${g.run_id}`} className="text-orange-400 hover:underline">{g.run_title}</Link>
                    </span>
                    <span className="ml-2 text-xs text-[var(--muted-foreground)]">{g.step_id}</span>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Human tasks</h3>
        <ul className="flex flex-col gap-2">
          {queue.human_tasks.map((h) => (
            <li key={h.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div>
                  <span className="text-sm text-[var(--foreground)]">
                    {h.project_name} / <Link to={`/runs/${h.run_id}`} className="text-orange-400 hover:underline">{h.run_title}</Link>
                  </span>
                  <span className="ml-2 text-xs text-[var(--muted-foreground)]">{h.reason}</span>
                </div>
                <Button type="button" variant="outline" size="xs" disabled={completeMutation.isPending} onClick={() => completeMutation.mutate(h.id)}>
                  Mark resolved
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
