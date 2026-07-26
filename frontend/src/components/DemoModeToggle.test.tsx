import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DemoModeToggle from "./DemoModeToggle";

function LocationMarker() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderWithProviders(initialPath = "/queue") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationMarker />
        <Routes>
          <Route path="*" element={<DemoModeToggle />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DemoModeToggle", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a 'Demo mode' button when inactive, no Reseed button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByRole("button", { name: /demo mode/i })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /reseed/i })).not.toBeInTheDocument();
  });

  it("shows 'Exit demo mode' and a Reseed button when active", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByRole("button", { name: /exit demo mode/i })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /reseed/i })).toBeInTheDocument();
  });

  it("activating clears the cache (triggering a status refetch) and navigates to /", async () => {
    let active = false;
    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/demo/status" && !init) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { active, db_path: active ? ".foundry-demo/demo.db" : "/tmp/foundry.db" }, paging: {} }),
        });
      }
      if (url === "/api/demo/activate") {
        active = true;
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders("/queue");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("button", { name: /^demo mode$/i })).toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent("/queue");

    await user.click(screen.getByRole("button", { name: /^demo mode$/i }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/"));
    // Cache clear -> the toggle's own status query loses its cached data and
    // refetches; the mock tracks that /activate was called, so this refetch
    // of /api/demo/status now reflects the post-activation state.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /exit demo mode/i })).toBeInTheDocument(),
    );
  });
});
