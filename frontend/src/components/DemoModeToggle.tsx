import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "../api/demo";
import { Button } from "./ui/forms/Button";

export default function DemoModeToggle() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: status } = useQuery({ queryKey: ["demo-status"], queryFn: getDemoStatus });

  const afterSwap = () => {
    // The entire database underneath the app just changed -- everything is
    // potentially stale, not just one query key. A deep-linked run/project
    // id from before the swap won't exist against the new db, so send the
    // user back to a page that doesn't depend on one.
    queryClient.clear();
    navigate("/");
  };

  const activateMutation = useMutation({ mutationFn: activateDemo, onSuccess: afterSwap });
  const deactivateMutation = useMutation({ mutationFn: deactivateDemo, onSuccess: afterSwap });
  const reseedMutation = useMutation({ mutationFn: reseedDemo, onSuccess: afterSwap });

  if (!status) {
    return null;
  }

  const pending = activateMutation.isPending || deactivateMutation.isPending || reseedMutation.isPending;

  return (
    <div className="ml-auto flex items-center gap-2">
      <Button type="button" disabled={pending} onClick={() => (status.active ? deactivateMutation.mutate() : activateMutation.mutate())}>
        {status.active ? "Exit demo mode" : "Demo mode"}
      </Button>
      {status.active && (
        <Button type="button" variant="outline" disabled={pending} onClick={() => reseedMutation.mutate()}>
          Reseed
        </Button>
      )}
    </div>
  );
}
