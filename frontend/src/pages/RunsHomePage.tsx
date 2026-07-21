import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { createRun, listRuns } from "../api/runs";
import NewRunForm from "../components/NewRunForm";

export default function RunsHomePage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const queryClient = useQueryClient();

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => listRuns(projectId ? { project_id: projectId } : undefined),
  });

  const createMutation = useMutation({
    mutationFn: createRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Runs{projectId ? " for project" : ""}</h2>
      {projects && projects.length > 0 && (
        <NewRunForm projects={projects} defaultProjectId={projectId} onSubmit={(input) => createMutation.mutate(input)} />
      )}
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {runs?.map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                {r.title}
              </Link>
              <span className="text-sm text-slate-500">{r.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
