import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { batchDecideGates, completeHumanTask, getQueue } from "../api/queue";

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
    return <p className="text-slate-400">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">My Queue</h2>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Gates</h3>
          <button
            type="button"
            disabled={selectedGateIds.length === 0 || batchApproveMutation.isPending}
            onClick={() => batchApproveMutation.mutate()}
            className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
          >
            Approve selected
          </button>
        </div>
        <ul className="flex flex-col gap-2">
          {queue.gates.map((g) => (
            <li key={g.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  aria-label={g.step_id}
                  checked={selectedGateIds.includes(g.id)}
                  onChange={() => toggleGate(g.id)}
                />
                <div>
                  <span className="text-sm text-slate-300">
                    {g.project_name} / <Link to={`/runs/${g.run_id}`} className="text-orange-400 hover:underline">{g.run_title}</Link>
                  </span>
                  <span className="ml-2 text-xs text-slate-500">{g.step_id}</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Human tasks</h3>
        <ul className="flex flex-col gap-2">
          {queue.human_tasks.map((h) => (
            <li key={h.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <div>
                <span className="text-sm text-slate-300">
                  {h.project_name} / <Link to={`/runs/${h.run_id}`} className="text-orange-400 hover:underline">{h.run_title}</Link>
                </span>
                <span className="ml-2 text-xs text-slate-500">{h.reason}</span>
              </div>
              <button
                type="button"
                disabled={completeMutation.isPending}
                onClick={() => completeMutation.mutate(h.id)}
                className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-orange-400 hover:text-orange-400"
              >
                Mark resolved
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
