import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlaybookPicker from "./PlaybookPicker";

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
      if (url === "/api/projects/proj-1/playbooks") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              {
                slug: "hotfix", project_id: "proj-1", playbook_id: "hotfix", description: "",
                path: "project_playbooks/proj-1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
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

function renderPicker(overrides: { projectId?: string; value?: string } = {}, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlaybookPicker
          id="playbook"
          projectId={overrides.projectId ?? "proj-1"}
          value={overrides.value ?? ""}
          onChange={onChange}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onChange;
}

describe("PlaybookPicker", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("disables the select and hides the New link when no project is selected", () => {
    stubFetch();
    renderPicker({ projectId: "" });

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.queryByRole("link", { name: /new playbook/i })).not.toBeInTheDocument();
  });

  it("lists project playbooks and pack templates as grouped options and reports the resolved path on selection", async () => {
    stubFetch();
    const onChange = renderPicker();

    await waitFor(() => expect(screen.getByRole("option", { name: /hotfix/i })).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /default \/ playbooks\/bugfix\.toml/i })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "packs/default/playbooks/bugfix.toml");
    expect(onChange).toHaveBeenCalledWith("packs/default/playbooks/bugfix.toml");

    expect(screen.getByRole("link", { name: /new playbook/i })).toHaveAttribute(
      "href",
      "/projects/proj-1/playbooks/new",
    );
  });

  it("preserves an already-set value that matches no known option as a leading Custom option", async () => {
    stubFetch();
    renderPicker({ value: "tests/orchestrator/fixtures/linear_demo.toml" });

    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /custom: tests\/orchestrator\/fixtures\/linear_demo\.toml/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox")).toHaveValue("tests/orchestrator/fixtures/linear_demo.toml");
  });

  it("allows clearing the value via the placeholder option when not required", async () => {
    stubFetch();
    const onChange = renderPicker({ value: "project_playbooks/proj-1/hotfix.toml" });

    await waitFor(() => expect(screen.getByRole("option", { name: /hotfix/i })).toBeInTheDocument());
    const placeholder = screen.getByRole("option", { name: /select a playbook/i });
    expect(placeholder).not.toBeDisabled();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "");
    expect(onChange).toHaveBeenCalledWith("");
  });
});
