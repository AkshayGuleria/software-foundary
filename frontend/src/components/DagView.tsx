import type { WorkUnit } from "../api/types";

const STATUS_COLORS: Record<string, string> = {
  closed: "#4fae7c",
  blocked: "#d9a441",
  failed: "#dc4a4a",
  killed: "#8a2e2e",
  in_progress: "#e8752c",
  ready: "#c9601f",
  open: "#5b6472",
};

function colorFor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.open;
}

const NODE_WIDTH = 140;
const NODE_HEIGHT = 36;
const COL_GAP = 60;
const ROW_GAP = 16;

function computeLevels(
  units: WorkUnit[],
  deps: { unit_id: string; needs_unit_id: string }[]
): Map<string, number> {
  const idsInGraph = new Set(units.map((u) => u.id));
  const needsMap = new Map<string, string[]>();
  for (const dep of deps) {
    if (!idsInGraph.has(dep.unit_id) || !idsInGraph.has(dep.needs_unit_id)) continue;
    const list = needsMap.get(dep.unit_id) ?? [];
    list.push(dep.needs_unit_id);
    needsMap.set(dep.unit_id, list);
  }

  const levels = new Map<string, number>();
  function levelOf(id: string, seen: Set<string>): number {
    if (levels.has(id)) return levels.get(id)!;
    if (seen.has(id)) return 0; // defensive: cyclical data shouldn't happen, don't infinite-loop
    seen.add(id);
    const needs = needsMap.get(id) ?? [];
    const level = needs.length === 0 ? 0 : Math.max(...needs.map((n) => levelOf(n, seen))) + 1;
    levels.set(id, level);
    return level;
  }

  for (const unit of units) levelOf(unit.id, new Set());
  return levels;
}

export default function DagView({
  units,
  deps,
}: {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
}) {
  const nodes = units.filter((u) => u.type !== "session");
  const levels = computeLevels(nodes, deps);

  const byLevel = new Map<number, WorkUnit[]>();
  for (const unit of nodes.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const level = levels.get(unit.id) ?? 0;
    const list = byLevel.get(level) ?? [];
    list.push(unit);
    byLevel.set(level, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, unitsAtLevel] of byLevel) {
    unitsAtLevel.forEach((unit, row) => {
      positions.set(unit.id, {
        x: level * (NODE_WIDTH + COL_GAP),
        y: row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }

  const maxLevel = Math.max(0, ...Array.from(byLevel.keys()));
  const maxRows = Math.max(1, ...Array.from(byLevel.values()).map((u) => u.length));
  const width = (maxLevel + 1) * (NODE_WIDTH + COL_GAP);
  const height = maxRows * (NODE_HEIGHT + ROW_GAP);

  const nodeIds = new Set(nodes.map((u) => u.id));
  const visibleDeps = deps.filter((d) => nodeIds.has(d.unit_id) && nodeIds.has(d.needs_unit_id));

  return (
    <svg
      role="img"
      aria-label="Run DAG"
      width={Math.max(width, 200)}
      height={Math.max(height, 100)}
      className="rounded border border-slate-800 bg-slate-950"
    >
      {visibleDeps.map((dep) => {
        const from = positions.get(dep.needs_unit_id);
        const to = positions.get(dep.unit_id);
        if (!from || !to) return null;
        return (
          <line
            key={`${dep.unit_id}-${dep.needs_unit_id}`}
            data-testid="dag-edge"
            x1={from.x + NODE_WIDTH}
            y1={from.y + NODE_HEIGHT / 2}
            x2={to.x}
            y2={to.y + NODE_HEIGHT / 2}
            stroke="#2a303b"
            strokeWidth={1.5}
          />
        );
      })}
      {nodes.map((unit) => {
        const pos = positions.get(unit.id) ?? { x: 0, y: 0 };
        return (
          <g
            key={unit.id}
            data-testid="dag-node"
            data-x={pos.x}
            data-y={pos.y}
            data-convoy={unit.convoy_id}
          >
            <rect
              data-testid={`dag-node-${unit.id}`}
              data-x={pos.x}
              data-y={pos.y}
              data-convoy={unit.convoy_id}
              x={pos.x}
              y={pos.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill="#191d24"
              stroke={colorFor(unit.status)}
              strokeWidth={unit.convoy_id ? 3 : 1.5}
              strokeDasharray={unit.convoy_id ? "4 2" : undefined}
            />
            <text x={pos.x + 8} y={pos.y + NODE_HEIGHT / 2 + 4} fontSize={11} fill="#e7eaee">
              {unit.step_id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
