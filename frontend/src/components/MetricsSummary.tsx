import { useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";

export default function MetricsSummary({ projectId }: { projectId: string }) {
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
  });

  if (!metrics) return null;

  const stats: { label: string; value: string }[] = [
    { label: "Rework rate", value: `${Math.round(metrics.rework_rate * 100)}%` },
    { label: "Avg approval latency", value: `${Math.round(metrics.approval_latency_seconds)}s` },
    { label: "Retries", value: String(metrics.retry_count) },
    { label: "Crashes", value: String(metrics.crash_count) },
    { label: "Auto-resolved conflicts", value: String(metrics.auto_resolved_count) },
    { label: "Escalated conflicts", value: String(metrics.escalated_count) },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-3 sm:grid-cols-3 md:grid-cols-6">
      {stats.map((s) => (
        <div key={s.label} className="flex flex-col gap-1">
          <span className="text-lg font-semibold tabular-nums">{s.value}</span>
          <span className="text-xs text-slate-500">{s.label}</span>
        </div>
      ))}
    </div>
  );
}
