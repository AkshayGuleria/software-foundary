import type { FeedEvent } from "../hooks/useEventStream";

export default function EventFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="flex flex-col gap-1 font-mono text-xs">
      {events.length === 0 && <p className="text-[var(--muted-foreground)]">Waiting for events…</p>}
      {events
        .slice()
        .reverse()
        .map((e) => (
          <div key={e.seq} className="rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-1">
            <span className="text-[var(--muted-foreground)]">[{e.seq}]</span> <span className="text-orange-400">{e.type}</span>{" "}
            <span className="text-[var(--muted-foreground)]">{JSON.stringify(e.payload)}</span>
          </div>
        ))}
    </div>
  );
}
