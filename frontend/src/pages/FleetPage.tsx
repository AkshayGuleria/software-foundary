import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listActiveSessions } from "../api/sessions";

export default function FleetPage() {
  const { data: sessions, isLoading } = useQuery({
    queryKey: ["active-sessions"],
    queryFn: listActiveSessions,
    refetchInterval: 3000,
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Fleet</h2>
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : sessions && sessions.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li
              key={s.id}
              className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm"
            >
              <Link to={`/runs/${s.run_id}`} className="font-medium text-orange-400 hover:underline">
                {s.step_id}
              </Link>
              <span className="text-slate-500">{s.driver}</span>
              <span className="text-slate-500">{s.model ?? "—"}</span>
              <span className="tabular-nums text-slate-500">
                {s.tokens_in.toLocaleString()} in / {s.tokens_out.toLocaleString()} out
              </span>
              <span className="text-slate-500">{s.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">No active sessions.</p>
      )}
    </div>
  );
}
