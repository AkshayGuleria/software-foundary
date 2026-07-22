import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import KgGraphView from "./KgGraphView";

describe("KgGraphView", () => {
  it("renders one node per file and one edge per import", () => {
    render(<KgGraphView nodes={["a.py", "b.py", "c.py"]} edges={[{ from: "a.py", to: "b.py" }]} />);

    expect(screen.getAllByTestId("kg-node")).toHaveLength(3);
    expect(screen.getAllByTestId("kg-edge")).toHaveLength(1);
  });

  it("positions an importer strictly after what it imports", () => {
    render(
      <KgGraphView
        nodes={["a.py", "b.py", "c.py"]}
        edges={[
          { from: "a.py", to: "b.py" },
          { from: "b.py", to: "c.py" },
        ]}
      />
    );

    // a.py imports b.py imports c.py: a.py is the top-level importer (depends
    // on both b.py and c.py transitively), c.py is the pure leaf dependency
    // nothing imports further. The importer must land after what it imports,
    // same convention DagView already established for WorkUnit dependencies.
    const nodeA = screen.getByTestId("kg-node-a.py");
    const nodeB = screen.getByTestId("kg-node-b.py");
    const nodeC = screen.getByTestId("kg-node-c.py");
    expect(Number(nodeA.getAttribute("data-x"))).toBeGreaterThan(Number(nodeB.getAttribute("data-x")));
    expect(Number(nodeB.getAttribute("data-x"))).toBeGreaterThan(Number(nodeC.getAttribute("data-x")));
  });

  it("draws the edge connector spanning only the gap between the two node columns", () => {
    // Regression for a bug introduced when the layout-direction fix (see
    // "positions an importer strictly after what it imports" above) flipped
    // computeLevels's keying without correspondingly flipping which node's
    // near edge each line endpoint uses. Before this test, the connector's
    // x1/x2 spanned from the far edge of the importer's box back to the far
    // edge of the imported box (overshooting both nodes) instead of just the
    // gap between the imported node's right edge and the importer's left edge.
    render(<KgGraphView nodes={["a.py", "b.py"]} edges={[{ from: "a.py", to: "b.py" }]} />);

    const edge = screen.getByTestId("kg-edge");
    const nodeA = screen.getByTestId("kg-node-a.py"); // importer, higher level (further right)
    const nodeB = screen.getByTestId("kg-node-b.py"); // imported, lower level (further left)
    const bX = Number(nodeB.getAttribute("data-x"));
    const aX = Number(nodeA.getAttribute("data-x"));

    expect(Number(edge.getAttribute("x1"))).toBe(bX + 140); // b.py's right edge (NODE_WIDTH = 140)
    expect(Number(edge.getAttribute("x2"))).toBe(aX); // a.py's left edge
  });

  it("marks nodes in the highlight set distinctly", () => {
    render(<KgGraphView nodes={["a.py", "b.py"]} edges={[]} highlight={["a.py"]} />);

    expect(screen.getByTestId("kg-node-a.py").getAttribute("data-highlighted")).toBe("true");
    expect(screen.getByTestId("kg-node-b.py").getAttribute("data-highlighted")).toBe("false");
  });

  it("handles an empty graph without crashing", () => {
    render(<KgGraphView nodes={[]} edges={[]} />);
    expect(screen.queryAllByTestId("kg-node")).toHaveLength(0);
  });
});
