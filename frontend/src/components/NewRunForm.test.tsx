import { render, screen } from "@testing-library/react";
import type { Project } from "../api/types";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import NewRunForm from "./NewRunForm";

const projects = [
  {
    id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
    created_at: "2026-07-21T00:00:00Z", default_driver: "codex", default_token_budget: 10000,
    default_playbook_path: "packs/default/playbooks/bugfix.toml",
  },
];

describe("NewRunForm", () => {
  it("pre-fills driver and playbook path from the selected project's defaults", async () => {
    render(<NewRunForm projects={projects} defaultProjectId="p1" onSubmit={vi.fn()} />);

    expect(screen.getByLabelText(/driver/i)).toHaveValue("codex");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("packs/default/playbooks/bugfix.toml");
  });

  it("still allows overriding the pre-filled values before submit", async () => {
    const onSubmit = vi.fn();
    render(<NewRunForm projects={projects} defaultProjectId="p1" onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: "p1", driver: "claude" }),
    );
  });

  it("does not reset user edits when the projects array is replaced with an equivalent one (e.g. background refetch)", async () => {
    const { rerender } = render(
      <NewRunForm projects={projects} defaultProjectId="p1" onSubmit={vi.fn()} />,
    );
    const user = userEvent.setup();

    // User edits the pre-filled values away from the project's defaults.
    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    const playbookInput = screen.getByLabelText(/playbook path/i);
    await user.clear(playbookInput);
    await user.type(playbookInput, "custom/path.toml");

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(playbookInput).toHaveValue("custom/path.toml");

    // Simulate a background refetch of the projects query: same data, new
    // array (and object) references, projectId unchanged.
    const refetchedProjects: Project[] = projects.map((p) => ({ ...p }));
    rerender(<NewRunForm projects={refetchedProjects} defaultProjectId="p1" onSubmit={vi.fn()} />);

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("custom/path.toml");
  });
});
