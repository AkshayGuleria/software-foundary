import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/projects";
import NewProjectForm from "../components/NewProjectForm";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import { Card } from "../components/ui/display/Card";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const { data: projects, isLoading } = useQuery({ queryKey: ["projects"], queryFn: listProjects });

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Projects</h2>
      <NewProjectForm onSubmit={(input) => createMutation.mutate(input)} />
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id}>
              <Card className="flex flex-col gap-2 px-3 py-2">
                <div className="flex items-center justify-between">
                  <div>
                    <Link to={`/projects/${p.id}`} className="font-medium text-orange-400 hover:underline">
                      {p.name}
                    </Link>
                    <span className="ml-2 text-sm text-[var(--muted-foreground)]">{p.path}</span>
                  </div>
                  <span className="text-xs uppercase text-[var(--muted-foreground)]">{p.status}</span>
                </div>
                <ProjectLifecycleButtons projectId={p.id} status={p.status} invalidateQueryKey={["projects"]} />
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
