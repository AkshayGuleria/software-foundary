import { useState } from "react";
import type { Project } from "../api/types";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined });
        setPlaybookPath("");
        setTitle("");
      }}
    >
      <label className="flex flex-col text-sm">
        Project
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          required
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        Playbook path
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </label>
      <label className="flex flex-col text-sm">
        Title (optional)
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <button type="submit" className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
        Start run
      </button>
    </form>
  );
}
