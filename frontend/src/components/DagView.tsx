import dagre from "dagre";
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

function layout(
  units: WorkUnit[],
  deps: { unit_id: string; needs_unit_id: string }[]
): { positions: Map<string, { x: number; y: number }>; width: number; height: number } {
  const idsInGraph = new Set(units.map((u) => u.id));
  const visibleDeps = deps.filter((d) => idsInGraph.has(d.unit_id) && idsInGraph.has(d.needs_unit_id));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: ROW_GAP, ranksep: COL_GAP });
  g.setDefaultEdgeLabel(() => ({}));

  for (const unit of units) {
    g.setNode(unit.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const dep of visibleDeps) {
    g.setEdge(dep.needs_unit_id, dep.unit_id);
  }

  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  let maxX = 0;
  let maxY = 0;
  for (const unit of units) {
    const node = g.node(unit.id);
    // dagre positions are node CENTERS; convert to top-left for rect x/y.
    const x = node.x - NODE_WIDTH / 2;
    const y = node.y - NODE_HEIGHT / 2;
    positions.set(unit.id, { x, y });
    maxX = Math.max(maxX, x + NODE_WIDTH);
    maxY = Math.max(maxY, y + NODE_HEIGHT);
  }

  return { positions, width: maxX, height: maxY };
}

export default function DagView({
  units,
  deps,
  onNodeClick,
}: {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
  onNodeClick?: (unit: WorkUnit) => void;
}) {
  const nodes = units.filter((u) => u.type !== "session");
  const nodeIds = new Set(nodes.map((u) => u.id));
  const visibleDeps = deps.filter((d) => nodeIds.has(d.unit_id) && nodeIds.has(d.needs_unit_id));

  const { positions, width, height } = layout(nodes, visibleDeps);

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
          <g key={unit.id} data-testid="dag-node" data-convoy={unit.convoy_id}>
            <rect
              data-testid={`dag-node-${unit.id}`}
              onClick={() => onNodeClick?.(unit)}
              style={{ cursor: onNodeClick ? "pointer" : "default" }}
              aria-label={`${unit.step_id} node`}
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
