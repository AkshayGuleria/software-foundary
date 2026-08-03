import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getProject, updateProjectSettings } from "../api/projects";
import { deleteProjectPlaybook, listProjectPlaybooks } from "../api/projectPlaybooks";
import { getProjectMetrics } from "../api/metrics";
import { getProjectKgGraph, listMemory } from "../api/knowledge";
import { listRuns } from "../api/runs";
import { metricsStats } from "../components/MetricsSummary";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";
import { Card } from "../components/ui/display/Card";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";
import { Label } from "../components/ui/forms/Label";
import { Select } from "../components/ui/forms/Select";

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
  const { data: playbooks } = useQuery({
    queryKey: ["project-playbooks", projectId],
    queryFn: () => listProjectPlaybooks(projectId),
    enabled: !!project,
  });

  const queryClient = useQueryClient();
  const [driver, setDriver] = useState("fake");
  const [tokenBudget, setTokenBudget] = useState(0);
  const [playbookPath, setPlaybookPath] = useState("");

  const settingsMutation = useMutation({
    mutationFn: () =>
      updateProjectSettings(projectId, {
        driver,
        token_budget: tokenBudget,
        playbook_path: playbookPath,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
  });

  const deletePlaybookMutation = useMutation({
    mutationFn: (slug: string) => deleteProjectPlaybook(projectId, slug),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-playbooks", projectId] }),
  });

  useEffect(() => {
    if (project) {
      setDriver(project.default_driver);
      setTokenBudget(project.default_token_budget ?? 0);
      setPlaybookPath(project.default_playbook_path ?? "");
    }
  }, [project]);

  if (isError) {
    return <p className="text-[var(--muted-foreground)]">Project not found.</p>;
  }

  if (!project) {
    return <p className="text-[var(--muted-foreground)]">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">{project.name}</h2>
          <span className="text-xs uppercase text-[var(--muted-foreground)]">{project.status}</span>
        </div>
        <span className="text-sm text-[var(--muted-foreground)]">{project.path}</span>
        <ProjectLifecycleButtons
          projectId={project.id}
          status={project.status}
          invalidateQueryKey={["project", projectId]}
        />
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Settings</h3>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            settingsMutation.mutate();
          }}
        >
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-driver">Driver</Label>
            <Select id="project-driver" value={driver} onChange={(e) => setDriver(e.target.value)}>
              <option value="fake">fake</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </Select>
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-token-budget">Token budget</Label>
            <Input
              id="project-token-budget"
              type="number"
              value={tokenBudget}
              onChange={(e) => setTokenBudget(Number(e.target.value))}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
            <Input
              id="project-playbook-path"
              value={playbookPath}
              onChange={(e) => setPlaybookPath(e.target.value)}
              placeholder="packs/default/playbooks/sdlc_story.toml"
            />
          </div>
          <Button variant="brand" type="submit" disabled={settingsMutation.isPending}>
            Save settings
          </Button>
        </form>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Playbooks</h3>
          <Link to={`/projects/${projectId}/playbooks/new`} className="text-sm text-orange-400 hover:underline">
            New playbook →
          </Link>
        </div>
        {playbooks && playbooks.length === 0 && (
          <p className="text-sm text-[var(--muted-foreground)]">No project-specific playbooks yet.</p>
        )}
        <ul className="flex flex-col gap-2">
          {playbooks?.map((pb) => (
            <li key={pb.slug}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div>
                  <Link
                    to={`/projects/${projectId}/playbooks/${pb.slug}`}
                    className="font-medium text-orange-400 hover:underline"
                  >
                    {pb.playbook_id}
                  </Link>
                  <span className="ml-2 text-sm text-[var(--muted-foreground)]">{pb.description}</span>
                </div>
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => {
                    if (window.confirm(`Delete playbook "${pb.slug}"?`)) {
                      deletePlaybookMutation.mutate(pb.slug);
                    }
                  }}
                >
                  Delete
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Runs</h3>
          <Link to={`/runs?project_id=${projectId}`} className="text-sm text-orange-400 hover:underline">
            View all runs →
          </Link>
        </div>
        <ul className="flex flex-col gap-2">
          {[...(runs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5).map((r) => (
            <li key={r.id}>
              <Card className="flex items-center justify-between px-3 py-2">
                <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                  {r.title}
                </Link>
                <span className="text-sm text-[var(--muted-foreground)]">{r.status}</span>
              </Card>
            </li>
          ))}
        </ul>
      </div>

      {metrics && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Metrics</h3>
          <Card className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 md:grid-cols-6">
            {metricsStats(metrics).map((s) => (
              <div key={s.label} className="flex flex-col gap-1">
                <span className="text-lg font-semibold tabular-nums">{s.value}</span>
                <span className="text-xs text-[var(--muted-foreground)]">{s.label}</span>
              </div>
            ))}
          </Card>
        </div>
      )}

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Knowledge graph</h3>
        <div className="overflow-x-auto">
          {graph?.nodes && <KgGraphView nodes={graph.nodes} edges={graph.edges ?? []} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
