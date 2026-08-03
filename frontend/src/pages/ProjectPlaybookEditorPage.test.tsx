import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectPlaybookEditorPage from "./ProjectPlaybookEditorPage";

function renderPage(initialPath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/projects/:id/playbooks/new" element={<ProjectPlaybookEditorPage />} />
          <Route path="/projects/:id/playbooks/:slug" element={<ProjectPlaybookEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectPlaybookEditorPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("create mode: shows a template picker and prefills the textarea on selection", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/packs") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "default", version: "0.1.0", roles: [], playbooks: ["playbooks/bugfix.toml"] }],
            paging: {},
          }),
        });
      }
      if (url === "/api/packs/default/playbooks/bugfix.toml") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { content: "[playbook]\nid = \"bugfix\"" }, paging: {} }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("option", { name: /bugfix/i })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/start from/i), "default::playbooks/bugfix.toml");

    await waitFor(() =>
      expect(screen.getByLabelText(/playbook toml/i)).toHaveValue("[playbook]\nid = \"bugfix\""),
    );
  });

  it("create mode: shows the server's validation error on save failure", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/packs") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }
      if (url === "/api/projects/proj-1/playbooks" && init?.method === "POST") {
        return Promise.resolve({
          ok: false, status: 400,
          json: async () => ({
            error: { code: "VALIDATION_ERROR", message: "duplicate step id(s)", status_code: 400, timestamp: "", path: "" },
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "My Flow");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/duplicate step id/i)).toBeInTheDocument());
  });

  it("edit mode: prefills the textarea from the existing playbook", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/projects/proj-1/playbooks/hotfix") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              slug: "hotfix", project_id: "proj-1", playbook_id: "hotfix", description: "",
              path: "project_playbooks/proj-1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
              content: "[playbook]\nid = \"hotfix\"",
            },
            paging: {},
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/hotfix");

    await waitFor(() =>
      expect(screen.getByLabelText(/playbook toml/i)).toHaveValue("[playbook]\nid = \"hotfix\""),
    );
    expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument();
  });
});
