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

    const nodeA = screen.getByTestId("kg-node-a.py");
    const nodeB = screen.getByTestId("kg-node-b.py");
    const nodeC = screen.getByTestId("kg-node-c.py");
    expect(Number(nodeB.getAttribute("data-x"))).toBeGreaterThan(Number(nodeA.getAttribute("data-x")));
    expect(Number(nodeC.getAttribute("data-x"))).toBeGreaterThan(Number(nodeB.getAttribute("data-x")));
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
