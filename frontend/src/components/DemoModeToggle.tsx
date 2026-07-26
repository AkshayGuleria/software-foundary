import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "../api/demo";

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
      <button
        type="button"
        disabled={pending}
        onClick={() => (status.active ? deactivateMutation.mutate() : activateMutation.mutate())}
        className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
      >
        {status.active ? "Exit demo mode" : "Demo mode"}
      </button>
      {status.active && (
        <button
          type="button"
          disabled={pending}
          onClick={() => reseedMutation.mutate()}
          className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-orange-400 disabled:opacity-50"
        >
          Reseed
        </button>
      )}
    </div>
  );
}
