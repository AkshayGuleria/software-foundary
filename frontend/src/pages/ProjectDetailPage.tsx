import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getProject } from "../api/projects";
import { getProjectMetrics } from "../api/metrics";
import { getProjectKgGraph, listMemory } from "../api/knowledge";
import { listRuns } from "../api/runs";
import { metricsStats } from "../components/MetricsSummary";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id!;

  const { data: project, isError } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
  });
  const { data: runs } = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => listRuns({ project_id: projectId }),
    enabled: !!project,
  });
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
    enabled: !!project,
  });
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId),
    enabled: !!project,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!project,
  });

  if (isError) {
    return <p className="text-slate-400">Project not found.</p>;
  }

  if (!project) {
    return <p className="text-slate-400">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">{project.name}</h2>
          <span className="text-xs uppercase text-slate-500">{project.status}</span>
        </div>
        <span className="text-sm text-slate-500">{project.path}</span>
        <ProjectLifecycleButtons
          projectId={project.id}
          status={project.status}
          invalidateQueryKey={["project", projectId]}
        />
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Runs</h3>
          <Link to={`/runs?project_id=${projectId}`} className="text-sm text-orange-400 hover:underline">
            View all runs →
          </Link>
        </div>
        <ul className="flex flex-col gap-2">
          {[...(runs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5).map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                {r.title}
              </Link>
              <span className="text-sm text-slate-500">{r.status}</span>
            </li>
          ))}
        </ul>
      </div>

      {metrics && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Metrics</h3>
          <div className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-3 sm:grid-cols-3 md:grid-cols-6">
            {metricsStats(metrics).map((s) => (
              <div key={s.label} className="flex flex-col gap-1">
                <span className="text-lg font-semibold tabular-nums">{s.value}</span>
                <span className="text-xs text-slate-500">{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Knowledge graph</h3>
        <div className="overflow-x-auto">
          {graph?.nodes && <KgGraphView nodes={graph.nodes} edges={graph.edges ?? []} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
