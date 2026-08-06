import { useEffect, useState } from "react";
import type { Project } from "../api/types";
import { Button } from "./ui/forms/Button";
import { Input } from "./ui/forms/Input";
import { Label } from "./ui/forms/Label";
import PlaybookPicker from "./PlaybookPicker";
import { Select } from "./ui/forms/Select";
import { Textarea } from "./ui/forms/Textarea";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: {
    project_id: string;
    playbook_path: string;
    title?: string;
    driver?: string;
    requirement_text?: string;
    requirement_path?: string;
  }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");
  const [requirementText, setRequirementText] = useState("");
  const [requirementPath, setRequirementPath] = useState("");

  const handleRequirementTextChange = (value: string) => {
    setRequirementText(value);
    if (value) setRequirementPath("");
  };

  const handleRequirementPathChange = (value: string) => {
    setRequirementPath(value);
    if (value) setRequirementText("");
  };

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
        onSubmit({
          project_id: projectId,
          playbook_path: playbookPath,
          title: title || undefined,
          driver,
          requirement_text: requirementText || undefined,
          requirement_path: requirementPath || undefined,
        });
        setPlaybookPath("");
        setTitle("");
        setRequirementText("");
        setRequirementPath("");
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
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
        <PlaybookPicker
          id="new-run-playbook"
          projectId={projectId}
          value={playbookPath}
          onChange={setPlaybookPath}
          required
        />
      </div>
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[20rem]">
        <Label htmlFor="new-run-requirement-text">Requirement (optional)</Label>
        <Textarea
          id="new-run-requirement-text"
          value={requirementText}
          onChange={(e) => handleRequirementTextChange(e.target.value)}
          disabled={!!requirementPath}
          placeholder="Describe what this run should accomplish..."
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-requirement-path">...or a file path in the repo (optional)</Label>
        <Input
          id="new-run-requirement-path"
          value={requirementPath}
          onChange={(e) => handleRequirementPathChange(e.target.value)}
          disabled={!!requirementText}
          placeholder="docs/REQUIREMENTS.md"
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-title">Title (optional)</Label>
        <Input id="new-run-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <Button variant="brand" type="submit">Start run</Button>
    </form>
  );
}
