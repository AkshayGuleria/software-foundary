import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listActiveSessions } from "./sessions";

describe("sessions API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listActiveSessions GETs /api/sessions and returns the data array", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [
          {
            id: "01JS1", work_unit_id: "01JU1", run_id: "01JR1", step_id: "implement",
            driver: "FakeDriver", status: "running", model: "fake", tokens_in: 10, tokens_out: 20,
            started_at: "2026-07-21T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    const sessions = await listActiveSessions();

    expect(fetch).toHaveBeenCalledWith("/api/sessions", undefined);
    expect(sessions).toHaveLength(1);
    expect(sessions[0].step_id).toBe("implement");
  });
});
