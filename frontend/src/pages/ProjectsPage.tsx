import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/projects";
import NewProjectForm from "../components/NewProjectForm";

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
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id} className="rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs?project_id=${p.id}`} className="font-medium text-orange-400 hover:underline">
                {p.name}
              </Link>
              <span className="ml-2 text-sm text-slate-500">{p.path}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
