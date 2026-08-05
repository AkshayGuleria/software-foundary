import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listPacks } from "../api/packs";
import { listProjectPlaybooks } from "../api/projectPlaybooks";
import { Select } from "./ui/forms/Select";

export default function PlaybookPicker({
  id,
  projectId,
  value,
  onChange,
  required = false,
}: {
  id: string;
  projectId: string;
  value: string;
  onChange: (path: string) => void;
  required?: boolean;
}) {
  const { data: projectPlaybooks } = useQuery({
    queryKey: ["project-playbooks", projectId],
    queryFn: () => listProjectPlaybooks(projectId),
    enabled: !!projectId,
  });
  const { data: packs } = useQuery({ queryKey: ["packs"], queryFn: listPacks });

  const projectOptions = (projectPlaybooks ?? []).map((pb) => ({
    value: pb.path,
    label: pb.playbook_id || pb.slug,
  }));
  const packOptions = (packs ?? []).flatMap((pack) =>
    pack.playbooks.map((relPath) => ({
      value: `packs/${pack.id}/${relPath}`,
      label: `${pack.id} / ${relPath}`,
    })),
  );
  const isCustom = !!value && ![...projectOptions, ...packOptions].some((o) => o.value === value);

  return (
    <div className="flex items-center gap-2">
      <Select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={!projectId}
        required={required}
        wrapClassName="flex-1"
        className="w-full"
      >
        <option value="" disabled>
          {projectId ? "Select a playbook…" : "Select a project first"}
        </option>
        {isCustom && <option value={value}>Custom: {value}</option>}
        {projectOptions.length > 0 && (
          <optgroup label="Project playbooks">
            {projectOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        )}
        {packOptions.length > 0 && (
          <optgroup label="Pack templates">
            {packOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        )}
      </Select>
      {projectId ? (
        <Link
          to={`/projects/${projectId}/playbooks/new`}
          className="whitespace-nowrap text-sm text-orange-400 hover:underline"
        >
          New playbook →
        </Link>
      ) : (
        <span className="whitespace-nowrap text-sm text-[var(--muted-foreground)]">New playbook →</span>
      )}
    </div>
  );
}
