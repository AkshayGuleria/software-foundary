// frontend/src/hooks/useEventStream.test.ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEventStream } from "./useEventStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: string, lastEventId: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ data, lastEventId } as MessageEvent);
    }
  }
}

describe("useEventStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens an EventSource to /api/stream/{runId} and appends received events", () => {
    const { result } = renderHook(() => useEventStream("01JR1"));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/stream/01JR1");

    act(() => {
      FakeEventSource.instances[0].emit("unit.closed", JSON.stringify({ unit_id: "01JU1" }), "5");
    });

    expect(result.current).toEqual([{ seq: 5, type: "unit.closed", payload: { unit_id: "01JU1" } }]);
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useEventStream("01JR1"));
    unmount();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });
});
