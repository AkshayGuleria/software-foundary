import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getProject } from "../api/projects";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id!;

  const { data: project, isError } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
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
    </div>
  );
}
