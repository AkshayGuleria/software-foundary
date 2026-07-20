import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiClientError } from "./client";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps a successful {data, paging} envelope", async () => {
    const mockResponse = {
      data: { id: "01J1", name: "acme" },
      paging: { offset: null, limit: null, total: null, total_pages: null, has_next: null, has_prev: null },
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const result = await apiFetch<{ id: string; name: string }>("/api/projects/01J1");

    expect(result.data).toEqual({ id: "01J1", name: "acme" });
    expect(fetch).toHaveBeenCalledWith("/api/projects/01J1", undefined);
  });

  it("throws ApiClientError with code/message/details on an {error} envelope", async () => {
    const mockError = {
      error: {
        code: "NOT_FOUND",
        message: "Project xyz not found",
        status_code: 404,
        timestamp: "2026-07-21T00:00:00Z",
        path: "/api/projects/xyz",
        details: null,
      },
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => mockError,
    });

    await expect(apiFetch("/api/projects/xyz")).rejects.toThrow(ApiClientError);
    try {
      await apiFetch("/api/projects/xyz");
      throw new Error("expected apiFetch to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      const apiErr = err as ApiClientError;
      expect(apiErr.code).toBe("NOT_FOUND");
      expect(apiErr.statusCode).toBe(404);
      expect(apiErr.message).toBe("Project xyz not found");
    }
  });

  it("passes init options through to fetch (method, body, headers)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ data: { id: "01J2" }, paging: {} }),
    });

    await apiFetch("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "acme", path: "/tmp/acme" }),
    });

    expect(fetch).toHaveBeenCalledWith("/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "acme", path: "/tmp/acme" }),
    });
  });
});
