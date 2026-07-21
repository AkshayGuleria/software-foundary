import type { Artifact } from "../api/types";

export default function ArtifactCard({ artifact }: { artifact: Artifact }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{artifact.kind}</span>
        <span className="text-slate-500">v{artifact.version} · {artifact.produced_by_role}</span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-400">
        {JSON.stringify(artifact.payload_json, null, 2)}
      </pre>
    </div>
  );
}
