import { useQuery } from "@tanstack/react-query";
import { listPacks } from "../api/packs";
import type { PackManifest } from "../api/types";

function PackCard({ pack }: { pack: PackManifest }) {
  return (
    <li className="flex flex-col gap-2 rounded border border-slate-800 px-3 py-2">
      <div className="flex items-baseline gap-2">
        <span className="font-medium text-orange-400">{pack.id}</span>
        <span className="text-xs uppercase text-slate-500">{pack.version}</span>
      </div>
      <div>
        <div className="text-xs uppercase text-slate-500">Roles</div>
        <ul className="text-sm text-slate-400">
          {pack.roles.map((role) => (
            <li key={role.id}>
              {role.id} <span className="text-xs text-slate-500">({role.model})</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="text-xs uppercase text-slate-500">Playbooks</div>
        <ul className="text-sm text-slate-400">
          {pack.playbooks.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      </div>
    </li>
  );
}

export default function PacksPage() {
  const { data: packs, isLoading } = useQuery({ queryKey: ["packs"], queryFn: listPacks });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Packs</h2>
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {packs?.map((pack) => (
            <PackCard key={pack.id} pack={pack} />
          ))}
        </ul>
      )}
    </div>
  );
}
