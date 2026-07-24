import { useQueries, useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import { listProjects } from "../api/projects";
import { metricsStats } from "../components/MetricsSummary";

const STAT_LABELS = [
  "Rework rate",
  "Avg approval latency",
  "Retries",
  "Crashes",
  "Auto-resolved conflicts",
  "Escalated conflicts",
];

export default function MetricsPage() {
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const metricsQueries = useQueries({
    queries: (projects ?? []).map((project) => ({
      queryKey: ["project-metrics", project.id],
      queryFn: () => getProjectMetrics(project.id),
    })),
  });

  if (projectsLoading || !projects) {
    return <p className="text-slate-400">Loading…</p>;
  }

  const rows = projects
    .map((project, i) => ({ project, query: metricsQueries[i] }))
    .sort((a, b) => (b.query.data?.rework_rate ?? -1) - (a.query.data?.rework_rate ?? -1));

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Metrics</h2>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
            <th className="py-2">Project</th>
            {STAT_LABELS.map((label) => (
              <th key={label} className="py-2">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ project, query }) => (
            <tr key={project.id} className="border-b border-slate-900">
              <td className="py-2 font-medium">{project.name}</td>
              {query.isError ? (
                <td colSpan={STAT_LABELS.length} className="py-2 text-red-400">
                  Failed to load metrics
                </td>
              ) : query.data ? (
                metricsStats(query.data).map((s) => (
                  <td key={s.label} className="py-2 tabular-nums">{s.value}</td>
                ))
              ) : (
                <td colSpan={STAT_LABELS.length} className="py-2 text-slate-500">
                  Loading…
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
