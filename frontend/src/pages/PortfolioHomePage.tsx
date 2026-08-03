import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";
import { Card } from "../components/ui/display/Card";
import { getPortfolio } from "../api/portfolio";
import type { ProjectHealth } from "../api/types";

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function ProjectCard({ project }: { project: ProjectHealth }) {
  return (
    <li>
      <Card data-testid={`portfolio-card-${project.project_id}`} className="flex flex-col gap-2 px-3 py-2">
        <div className="flex items-center justify-between">
          <Link to={`/projects/${project.project_id}`} className="font-medium text-orange-400 hover:underline">
            {project.name}
          </Link>
          <span className="text-xs uppercase text-[var(--muted-foreground)]">{project.status}</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--muted-foreground)]">
          <span>Active runs: {project.active_run_count}</span>
          <span>Pending gates: {project.pending_gate_count}</span>
          <span>Last run: {project.last_run_status ?? "none yet"}</span>
          <span>Rework rate: {formatPercent(project.rework_rate)}</span>
          <span>Budget burn: {formatPercent(project.budget_burn_ratio)}</span>
        </div>
        <ProjectLifecycleButtons
          projectId={project.project_id}
          status={project.status}
          invalidateQueryKey={["portfolio"]}
        />
      </Card>
    </li>
  );
}

export default function PortfolioHomePage() {
  const { data: projects, isLoading } = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Portfolio</h2>
      {isLoading ? (
        <p className="text-[var(--muted-foreground)]">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects?.map((project) => (
            <ProjectCard key={project.project_id} project={project} />
          ))}
        </ul>
      )}
    </div>
  );
}
