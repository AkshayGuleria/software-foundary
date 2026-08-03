import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ApiClientError } from "../api/client";
import { listPacks } from "../api/packs";
import {
  createProjectPlaybook,
  getPackPlaybookContent,
  getProjectPlaybook,
  updateProjectPlaybook,
} from "../api/projectPlaybooks";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";
import { Label } from "../components/ui/forms/Label";
import { Select } from "../components/ui/forms/Select";
import { Textarea } from "../components/ui/forms/Textarea";

export default function ProjectPlaybookEditorPage() {
  const { id, slug } = useParams<{ id: string; slug?: string }>();
  const projectId = id!;
  const isEdit = !!slug;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: existing, isError: isExistingError } = useQuery({
    queryKey: ["project-playbook", projectId, slug],
    queryFn: () => getProjectPlaybook(projectId, slug!),
    enabled: isEdit,
  });

  useEffect(() => {
    if (existing) setContent(existing.content);
  }, [existing]);

  useEffect(() => {
    if (isExistingError) setError("Failed to load this playbook.");
  }, [isExistingError]);

  const { data: packs } = useQuery({ queryKey: ["packs"], queryFn: listPacks, enabled: !isEdit });
  const templateOptions = (packs ?? []).flatMap((p) =>
    p.playbooks.map((pb) => ({ value: `${p.id}::${pb}`, label: `${p.id} / ${pb}` })),
  );

  const applyTemplateMutation = useMutation({
    mutationFn: (value: string) => {
      const [packId, relPath] = value.split("::");
      return getPackPlaybookContent(packId, relPath);
    },
    onSuccess: (fetchedContent) => setContent(fetchedContent),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      isEdit
        ? updateProjectPlaybook(projectId, slug!, { content })
        : createProjectPlaybook(projectId, { name, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-playbooks", projectId] });
      navigate(`/projects/${projectId}`);
    },
    onError: (err) => {
      setError(err instanceof ApiClientError ? err.message : "Failed to save playbook.");
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{isEdit ? `Edit playbook: ${slug}` : "New playbook"}</h2>

      {error && (
        <div
          className="rounded-[var(--radius-md)] border border-[var(--destructive)] p-3 text-sm text-[var(--destructive)]"
          style={{ backgroundColor: "color-mix(in oklab, var(--destructive) 10%, transparent)" }}
        >
          {error}
        </div>
      )}

      {!isEdit && (
        <>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="playbook-name">Name</Label>
            <Input id="playbook-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="playbook-template">Start from</Label>
            <Select
              id="playbook-template"
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) applyTemplateMutation.mutate(e.target.value);
                else setContent("");
              }}
            >
              <option value="">Blank</option>
              {templateOptions.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </div>
        </>
      )}

      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="playbook-content">Playbook TOML</Label>
        <Textarea
          id="playbook-content"
          className="min-h-[70vh] font-mono text-xs"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </div>

      <div className="flex gap-2">
        <Button
          variant="brand"
          disabled={saveMutation.isPending || (!isEdit && !name)}
          onClick={() => {
            setError(null);
            saveMutation.mutate();
          }}
        >
          Save
        </Button>
        <Button variant="outline" onClick={() => navigate(`/projects/${projectId}`)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
