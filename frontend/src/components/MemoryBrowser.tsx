import { Link } from "react-router-dom";
import type { MemoryItem } from "../api/types";
import { Card } from "./ui/display/Card";
import { Badge } from "./ui/display/Badge";

export default function MemoryBrowser({ items }: { items: MemoryItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-[var(--muted-foreground)]">No memory items yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id}>
          <Card className="p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium">{item.title}</span>
              <Badge variant="secondary" className="uppercase">{item.kind}</Badge>
            </div>
            <p className="mt-1 text-[var(--muted-foreground)]">{item.body_md}</p>
            <div className="mt-2 text-xs text-[var(--muted-foreground)]">
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
          </Card>
        </li>
      ))}
    </ul>
  );
}
