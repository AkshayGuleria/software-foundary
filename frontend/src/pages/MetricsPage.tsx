import { useQueries, useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import { listProjects } from "../api/projects";
import { metricsStats } from "../components/MetricsSummary";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/display/Table";

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
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  const rows = projects
    .map((project, i) => ({ project, query: metricsQueries[i] }))
    .sort((a, b) => (b.query.data?.rework_rate ?? -1) - (a.query.data?.rework_rate ?? -1));

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Metrics</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Project</TableHead>
            {STAT_LABELS.map((label) => (
              <TableHead key={label}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ project, query }) => (
            <TableRow key={project.id}>
              <TableCell className="font-medium">{project.name}</TableCell>
              {query.isError ? (
                <TableCell colSpan={STAT_LABELS.length} className="text-[var(--destructive)]">
                  Failed to load metrics
                </TableCell>
              ) : query.data ? (
                metricsStats(query.data).map((s) => (
                  <TableCell key={s.label} className="tabular-nums">{s.value}</TableCell>
                ))
              ) : (
                <TableCell colSpan={STAT_LABELS.length} className="text-[var(--muted-foreground)]">
                  Loading…
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
