import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectsPage from "./ProjectsPage";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectsPage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders the list of projects from the API", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [{ id: "01J1", name: "acme", path: "/tmp/acme", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
    });

    renderWithClient(<ProjectsPage />);

    await waitFor(() => expect(screen.getByText("acme")).toBeInTheDocument());
  });

  it("submits the create-project form and refreshes the list", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) }) // initial list
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ data: { id: "01J2", name: "newproj", path: "/tmp/newproj", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }, paging: {} }),
      }) // create
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: [{ id: "01J2", name: "newproj", path: "/tmp/newproj", kg_status: "none", created_at: "2026-07-21T00:00:00Z" }], paging: {} }),
      }); // refetch after create

    renderWithClient(<ProjectsPage />);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByLabelText(/name/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/name/i), "newproj");
    await user.type(screen.getByLabelText(/path/i), "/tmp/newproj");
    await user.click(screen.getByRole("button", { name: /create project/i }));

    await waitFor(() => expect(screen.getByText("newproj")).toBeInTheDocument());
  });

  it("shows a status pill and pause button for each project", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [{ id: "p1", name: "demo", path: ".", kg_status: "none", status: "active", created_at: "2026-01-01T00:00:00Z" }],
        paging: {},
      }),
    });

    renderWithClient(<ProjectsPage />);

    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument();
  });
});
