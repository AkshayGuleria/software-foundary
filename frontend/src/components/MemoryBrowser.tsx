import { Link } from "react-router-dom";
import type { MemoryItem } from "../api/types";

export default function MemoryBrowser({ items }: { items: MemoryItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No memory items yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id} className="rounded border border-slate-800 p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">{item.title}</span>
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs uppercase text-slate-400">
              {item.kind}
            </span>
          </div>
          <p className="mt-1 text-slate-400">{item.body_md}</p>
          <div className="mt-2 text-xs text-slate-500">
            {item.scope}
            {item.source_run_id && (
              <>
                {" · from "}
                <Link to={`/runs/${item.source_run_id}`} className="text-orange-400 hover:underline">
                  {item.source_run_id}
                </Link>
              </>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
