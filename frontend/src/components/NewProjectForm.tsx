import { useState } from "react";

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
      <label className="flex flex-col text-sm">
        Name
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label className="flex flex-col text-sm">
        Path
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          required
        />
      </label>
      <button type="submit" className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
        Create project
      </button>
    </form>
  );
}
