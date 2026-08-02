import type { Artifact } from "../api/types";
import { Card } from "./ui/display/Card";

export default function ArtifactCard({ artifact }: { artifact: Artifact }) {
  return (
    <Card className="p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{artifact.kind}</span>
        <span className="text-[var(--muted-foreground)]">v{artifact.version} · {artifact.produced_by_role}</span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded-[var(--radius-md)] bg-[var(--muted)] p-2 text-xs text-[var(--muted-foreground)]">
        {JSON.stringify(artifact.payload_json, null, 2)}
      </pre>
    </Card>
  );
}
