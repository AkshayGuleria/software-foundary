import { useEffect, useState } from "react";
import type { Project } from "../api/types";
import { Button } from "./ui/forms/Button";
import { Input } from "./ui/forms/Input";
import { Label } from "./ui/forms/Label";
import { Select } from "./ui/forms/Select";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string; driver?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");

  useEffect(() => {
    const selected = projects.find((p) => p.id === projectId);
    if (selected) {
      setDriver(selected.default_driver);
      setPlaybookPath(selected.default_playbook_path ?? "");
    }
    // Intentionally omit `projects` from deps: a background refetch of the
    // projects query (e.g. react-query's refetchOnWindowFocus) produces a
    // new array reference with equivalent content, which would otherwise
    // re-run this effect and silently reset the user's edits even though
    // they never changed the selected project. The effect body still reads
    // the latest `projects` via closure.
  }, [projectId]);

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined, driver });
        setPlaybookPath("");
        setTitle("");
      }}
    >
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-project">Project</Label>
        <Select id="new-run-project" value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-driver">Driver</Label>
        <Select id="new-run-driver" value={driver} onChange={(e) => setDriver(e.target.value)}>
          <option value="fake">fake</option>
          <option value="codex">codex</option>
          <option value="claude">claude</option>
        </Select>
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
        <Input
          id="new-run-playbook"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-title">Title (optional)</Label>
        <Input id="new-run-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <Button type="submit">Start run</Button>
    </form>
  );
}
