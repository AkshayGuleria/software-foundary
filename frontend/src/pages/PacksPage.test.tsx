import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import PacksPage from "./PacksPage";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PacksPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists packs and shows each pack's roles and playbooks", async () => {
    const packs = [
      {
        id: "default",
        version: "0.1.0",
        roles: [
          { id: "developer", model: "fake" },
          { id: "reviewer", model: "fake" },
        ],
        playbooks: ["playbooks/sdlc_story.toml", "playbooks/bugfix.toml"],
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: packs, paging: {} }) }),
    );

    renderWithClient(<PacksPage />);

    await waitFor(() => expect(screen.getByText(/default/)).toBeInTheDocument());
    expect(screen.getByText(/0\.1\.0/)).toBeInTheDocument();
    expect(screen.getByText("developer")).toBeInTheDocument();
    expect(screen.getByText("reviewer")).toBeInTheDocument();
    expect(screen.getByText("playbooks/sdlc_story.toml")).toBeInTheDocument();
    expect(screen.getByText("playbooks/bugfix.toml")).toBeInTheDocument();
  });
});
