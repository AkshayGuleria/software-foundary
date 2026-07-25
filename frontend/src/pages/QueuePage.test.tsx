import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import QueuePage from "./QueuePage";

function renderWithProviders() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <QueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const queueData = {
  gates: [
    {
      id: "g1", work_unit_id: "u1", gate_type: "human", project_id: "p1", project_name: "acme",
      run_id: "r1", run_title: "acme run", step_id: "implement", created_at: "2026-07-20T00:00:00Z",
    },
  ],
  human_tasks: [
    {
      id: "ht1", project_id: "p1", project_name: "acme", run_id: "r1", run_title: "acme run",
      step_id: "_budget", reason: "Budget exceeded", created_at: "2026-07-21T00:00:00Z",
    },
  ],
};

describe("QueuePage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders gates and human tasks with links back to their runs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: queueData, paging: {} }) }),
    );

    renderWithProviders();

    // The fixture puts both the gate and the human task on the same run
    // ("acme run"), so each section renders its own link back to it --
    // hence getAllBy* rather than getBy* here.
    await waitFor(() => expect(screen.getAllByText("acme run")).toHaveLength(2));
    expect(screen.getByText("Budget exceeded")).toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: /acme run/i })) {
      expect(link).toHaveAttribute("href", "/runs/r1");
    }
  });

  it("batch-approves selected gates", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/queue") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: queueData, paging: {} }) });
      }
      if (url === "/api/gates/batch-decide") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { approved: ["g1"], skipped: [] }, paging: {} }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: {}, paging: {} }) });
    });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("checkbox", { name: /implement/i })).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox", { name: /implement/i }));
    await user.click(screen.getByRole("button", { name: /approve selected/i }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/gates/batch-decide",
        expect.objectContaining({ body: JSON.stringify({ gate_ids: ["g1"] }) }),
      ),
    );
  });

  it("batch-approves only the checked gates, not every gate in the queue", async () => {
    const twoGateQueue = {
      gates: [
        queueData.gates[0],
        {
          id: "g2", work_unit_id: "u2", gate_type: "human", project_id: "p1", project_name: "acme",
          run_id: "r1", run_title: "acme run", step_id: "review", created_at: "2026-07-22T00:00:00Z",
        },
      ],
      human_tasks: [],
    };
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/queue") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: twoGateQueue, paging: {} }) });
      }
      if (url === "/api/gates/batch-decide") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { approved: ["g1"], skipped: [] }, paging: {} }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: {}, paging: {} }) });
    });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders();
    const user = userEvent.setup();

    // Two checkboxes now exist (one per gate) -- check only the first
    // ("implement"), leave "review" unchecked.
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /implement/i })).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox", { name: /implement/i }));
    await user.click(screen.getByRole("button", { name: /approve selected/i }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/gates/batch-decide",
        expect.objectContaining({ body: JSON.stringify({ gate_ids: ["g1"] }) }),
      ),
    );
    // The unchecked gate's id must NOT appear in the request -- this is
    // what actually distinguishes "selective send" from "always send all".
    const call = mockFetch.mock.calls.find(([url]) => url === "/api/gates/batch-decide");
    const sentBody = JSON.parse((call![1] as RequestInit).body as string);
    expect(sentBody.gate_ids).not.toContain("g2");
  });

  it("marks a human task resolved", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/queue") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: queueData, paging: {} }) });
      }
      if (url === "/api/human-tasks/ht1/complete") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { id: "ht1", status: "closed" }, paging: {} }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: {}, paging: {} }) });
    });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("button", { name: /mark resolved/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /mark resolved/i }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith("/api/human-tasks/ht1/complete", { method: "POST" }),
    );
  });
});
