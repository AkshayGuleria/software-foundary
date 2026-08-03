import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { getProjectKgGraph, getRunBlastRadius, listMemory } from "../api/knowledge";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";

export default function KnowledgePage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const [runIdInput, setRunIdInput] = useState("");
  const [blastRadiusRunId, setBlastRadiusRunId] = useState<string | undefined>(undefined);

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId!),
    enabled: !!projectId,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!projectId,
  });
  const { data: blastRadius } = useQuery({
    queryKey: ["blast-radius", blastRadiusRunId],
    queryFn: () => getRunBlastRadius(blastRadiusRunId!),
    enabled: !!blastRadiusRunId,
  });

  if (!projectId) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">Knowledge</h2>
        <p className="text-sm text-[var(--muted-foreground)]">Select a project to view its knowledge graph and memory.</p>
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id}>
              <Link to={`/knowledge?project_id=${p.id}`} className="text-orange-400 hover:underline">
                {p.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Knowledge</h2>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Import graph</h3>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setBlastRadiusRunId(runIdInput || undefined);
          }}
        >
          <Input
            placeholder="Run ID to overlay blast radius"
            value={runIdInput}
            onChange={(e) => setRunIdInput(e.target.value)}
          />
          <Button type="submit">Highlight</Button>
        </form>
        <div className="overflow-x-auto">
          {graph && <KgGraphView nodes={graph.nodes} edges={graph.edges} highlight={blastRadius?.radius} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
