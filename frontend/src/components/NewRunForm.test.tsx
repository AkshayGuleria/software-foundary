import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { Project } from "../api/types";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import NewRunForm from "./NewRunForm";

const projects: Project[] = [
  {
    id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
    created_at: "2026-07-21T00:00:00Z", default_driver: "codex", default_token_budget: 10000,
    default_playbook_path: "packs/default/playbooks/bugfix.toml",
  },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url === "/api/packs") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "default", version: "0.1.0", roles: [], playbooks: ["playbooks/bugfix.toml"] }],
            paging: {},
          }),
        });
      }
      if (url === "/api/projects/p1/playbooks") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              {
                slug: "hotfix", project_id: "p1", playbook_id: "hotfix", description: "",
                path: "project_playbooks/p1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
              },
            ],
            paging: {},
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

function renderForm(onSubmit: (input: unknown) => void, projectsArg: Project[] = projects) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewRunForm projects={projectsArg} defaultProjectId="p1" onSubmit={onSubmit} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewRunForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("pre-fills driver and playbook path from the selected project's defaults", () => {
    stubFetch();
    renderForm(vi.fn());

    expect(screen.getByLabelText(/driver/i)).toHaveValue("codex");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("packs/default/playbooks/bugfix.toml");
  });

  it("still allows overriding the pre-filled values before submit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: "p1", driver: "claude" }),
    );
  });

  it("does not reset user edits when the projects array is replaced with an equivalent one (e.g. background refetch)", async () => {
    stubFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewRunForm projects={projects} defaultProjectId="p1" onSubmit={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await waitFor(() => expect(screen.getByRole("option", { name: /hotfix/i })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/playbook path/i), "project_playbooks/p1/hotfix.toml");

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("project_playbooks/p1/hotfix.toml");

    const refetchedProjects: Project[] = projects.map((p) => ({ ...p }));
    rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewRunForm projects={refetchedProjects} defaultProjectId="p1" onSubmit={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("project_playbooks/p1/hotfix.toml");
  });
});
