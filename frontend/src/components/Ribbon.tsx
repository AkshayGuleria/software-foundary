import type { WorkUnit } from "../api/types";

const STATUS_STYLES: Record<string, string> = {
  closed: "bg-emerald-900 text-emerald-300 border-emerald-700",
  blocked: "bg-amber-900 text-amber-300 border-amber-700",
  failed: "bg-red-900 text-red-300 border-red-700",
  killed: "bg-red-950 text-red-400 border-red-800",
  in_progress: "bg-orange-900 text-orange-300 border-orange-700",
  ready: "bg-orange-950 text-orange-400 border-orange-800",
  open: "bg-slate-800 text-slate-400 border-slate-700",
};

function styleFor(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.open;
}

export default function Ribbon({ units }: { units: WorkUnit[] }) {
  const steps = units
    .filter((u) => u.type !== "session")
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  return (
    <div className="flex flex-wrap gap-2">
      {steps.map((u) => (
        <span
          key={u.id}
          data-testid="ribbon-pill"
          className={`rounded-full border px-3 py-1 text-sm font-medium ${styleFor(u.status)}`}
        >
          {u.step_id} · {u.status}
        </span>
      ))}
    </div>
  );
}
