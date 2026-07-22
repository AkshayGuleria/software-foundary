const NODE_WIDTH = 140;
const NODE_HEIGHT = 32;
const COL_GAP = 60;
const ROW_GAP = 14;

// An edge {from, to} means "to" depends on / imports "from" — i.e. "from" must
// come before "to" in the layout, mirroring DagView's {unit_id, needs_unit_id}
// (unit_id is the dependent, needs_unit_id is the dependency).
function computeLevels(nodes: string[], edges: { from: string; to: string }[]): Map<string, number> {
  const nodeSet = new Set(nodes);
  const dependsOn: Map<string, string[]> = new Map();
  for (const edge of edges) {
    if (!nodeSet.has(edge.from) || !nodeSet.has(edge.to)) continue;
    const list = dependsOn.get(edge.to) ?? [];
    list.push(edge.from);
    dependsOn.set(edge.to, list);
  }

  const levels = new Map<string, number>();
  function levelOf(id: string, seen: Set<string>): number {
    if (levels.has(id)) return levels.get(id)!;
    if (seen.has(id)) return 0; // defensive: cyclical data shouldn't happen, don't infinite-loop
    seen.add(id);
    const deps = dependsOn.get(id) ?? [];
    const level = deps.length === 0 ? 0 : Math.max(...deps.map((d) => levelOf(d, seen))) + 1;
    levels.set(id, level);
    return level;
  }

  for (const node of nodes) levelOf(node, new Set());
  return levels;
}

export default function KgGraphView({
  nodes,
  edges,
  highlight,
}: {
  nodes: string[];
  edges: { from: string; to: string }[];
  highlight?: string[] | Set<string>;
}) {
  const highlightSet = highlight instanceof Set ? highlight : new Set(highlight ?? []);
  const levels = computeLevels(nodes, edges);

  const byLevel = new Map<number, string[]>();
  for (const node of nodes.slice().sort()) {
    const level = levels.get(node) ?? 0;
    const list = byLevel.get(level) ?? [];
    list.push(node);
    byLevel.set(level, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, nodesAtLevel] of byLevel) {
    nodesAtLevel.forEach((node, row) => {
      positions.set(node, { x: level * (NODE_WIDTH + COL_GAP), y: row * (NODE_HEIGHT + ROW_GAP) });
    });
  }

  const maxLevel = Math.max(0, ...Array.from(byLevel.keys()));
  const maxRows = Math.max(1, ...Array.from(byLevel.values()).map((n) => n.length));
  const width = (maxLevel + 1) * (NODE_WIDTH + COL_GAP);
  const height = maxRows * (NODE_HEIGHT + ROW_GAP);

  const nodeSet = new Set(nodes);
  const visibleEdges = edges.filter((e) => nodeSet.has(e.from) && nodeSet.has(e.to));

  return (
    <svg
      role="img"
      aria-label="Knowledge graph"
      width={Math.max(width, 200)}
      height={Math.max(height, 100)}
      className="rounded border border-slate-800 bg-slate-950"
    >
      {visibleEdges.map((edge) => {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        if (!from || !to) return null;
        return (
          <line
            key={`${edge.from}-${edge.to}`}
            data-testid="kg-edge"
            x1={from.x + NODE_WIDTH}
            y1={from.y + NODE_HEIGHT / 2}
            x2={to.x}
            y2={to.y + NODE_HEIGHT / 2}
            stroke="#2a303b"
            strokeWidth={1.5}
          />
        );
      })}
      {nodes.map((node) => {
        const pos = positions.get(node) ?? { x: 0, y: 0 };
        const isHighlighted = highlightSet.has(node);
        return (
          <g key={node} data-testid="kg-node">
            <rect
              data-testid={`kg-node-${node}`}
              data-x={pos.x}
              data-y={pos.y}
              data-highlighted={isHighlighted ? "true" : "false"}
              x={pos.x}
              y={pos.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill={isHighlighted ? "#3a2320" : "#191d24"}
              stroke={isHighlighted ? "#e8752c" : "#2a303b"}
              strokeWidth={isHighlighted ? 2.5 : 1}
            />
            <text x={pos.x + 8} y={pos.y + NODE_HEIGHT / 2 + 4} fontSize={10} fill="#e7eaee">
              {node}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
