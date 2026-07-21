import type { FeedEvent } from "../hooks/useEventStream";

export default function EventFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="flex flex-col gap-1 font-mono text-xs">
      {events.length === 0 && <p className="text-slate-500">Waiting for events…</p>}
      {events
        .slice()
        .reverse()
        .map((e) => (
          <div key={e.seq} className="rounded border border-slate-800 px-2 py-1">
            <span className="text-slate-500">[{e.seq}]</span> <span className="text-orange-400">{e.type}</span>{" "}
            <span className="text-slate-400">{JSON.stringify(e.payload)}</span>
          </div>
        ))}
    </div>
  );
}
