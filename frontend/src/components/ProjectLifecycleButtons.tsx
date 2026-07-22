import { useMutation, useQueryClient } from "@tanstack/react-query";
import { activateProject, archiveProject, pauseProject } from "../api/projects";

const buttonClassName =
  "rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-orange-400 hover:text-orange-400";

export default function ProjectLifecycleButtons({
  projectId,
  status,
  invalidateQueryKey,
}: {
  projectId: string;
  status: string;
  invalidateQueryKey: readonly unknown[];
}) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: invalidateQueryKey });

  const pauseMutation = useMutation({
    mutationFn: () => pauseProject(projectId),
    onSuccess: invalidate,
  });
  const archiveMutation = useMutation({
    mutationFn: () => archiveProject(projectId),
    onSuccess: invalidate,
  });
  const activateMutation = useMutation({
    mutationFn: () => activateProject(projectId),
    onSuccess: invalidate,
  });

  return (
    <div className="flex gap-2">
      {status !== "paused" && (
        <button
          type="button"
          onClick={() => pauseMutation.mutate()}
          disabled={pauseMutation.isPending}
          className={buttonClassName}
        >
          Pause
        </button>
      )}
      {status !== "archived" && (
        <button
          type="button"
          onClick={() => archiveMutation.mutate()}
          disabled={archiveMutation.isPending}
          className={buttonClassName}
        >
          Archive
        </button>
      )}
      {status !== "active" && (
        <button
          type="button"
          onClick={() => activateMutation.mutate()}
          disabled={activateMutation.isPending}
          className={buttonClassName}
        >
          Activate
        </button>
      )}
    </div>
  );
}
