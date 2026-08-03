import { useState } from "react";
import { Button } from "./ui/forms/Button";
import { Input } from "./ui/forms/Input";
import { Label } from "./ui/forms/Label";

export default function NewProjectForm({ onSubmit }: { onSubmit: (input: { name: string; path: string }) => void }) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name, path });
        setName("");
        setPath("");
      }}
    >
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-project-name">Name</Label>
        <Input id="new-project-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-project-path">Path</Label>
        <Input id="new-project-path" value={path} onChange={(e) => setPath(e.target.value)} required />
      </div>
      <Button type="submit">Create project</Button>
    </form>
  );
}
