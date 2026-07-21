import { useEffect, useState } from "react";

export interface FeedEvent {
  seq: number;
  type: string;
  payload: unknown;
}

const KNOWN_EVENT_TYPES = [
  "unit.ready",
  "unit.closed",
  "unit.blocked",
  "unit.retried",
  "session.intent",
  "session.spawned",
  "artifact.produced",
  "gate.created",
  "gate.approved",
  "gate.rejected",
  "gate.derived_approved",
  "run.cancelled",
  "run.tick_error",
];

export function useEventStream(runId: string): FeedEvent[] {
  const [events, setEvents] = useState<FeedEvent[]>([]);

  useEffect(() => {
    setEvents([]);
    const source = new EventSource(`/api/stream/${runId}`);

    const handler = (type: string) => (ev: MessageEvent) => {
      setEvents((prev) => [...prev, { seq: Number(ev.lastEventId), type, payload: JSON.parse(ev.data) }]);
    };

    for (const type of KNOWN_EVENT_TYPES) {
      source.addEventListener(type, handler(type));
    }

    return () => source.close();
  }, [runId]);

  return events;
}
