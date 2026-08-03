import { useMutation, useQueryClient } from "@tanstack/react-query";
import { activateProject, archiveProject, pauseProject } from "../api/projects";
import { Button } from "./ui/forms/Button";

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
        <Button type="button" variant="outline" size="xs" onClick={() => pauseMutation.mutate()} disabled={pauseMutation.isPending}>
          Pause
        </Button>
      )}
      {status !== "archived" && (
        <Button type="button" variant="outline" size="xs" onClick={() => archiveMutation.mutate()} disabled={archiveMutation.isPending}>
          Archive
        </Button>
      )}
      {status !== "active" && (
        <Button type="button" variant="outline" size="xs" onClick={() => activateMutation.mutate()} disabled={activateMutation.isPending}>
          Activate
        </Button>
      )}
    </div>
  );
}
