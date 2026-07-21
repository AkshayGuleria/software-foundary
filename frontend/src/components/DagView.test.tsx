import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DagView from "./DagView";
import type { WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0,
  owner_session_id: null, convoy_id: null, ...overrides,
});

describe("DagView", () => {
  it("renders one node per non-session unit and one line per dep edge", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "architecture", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "ready" }),
      unit({ id: "01J3", step_id: "sess", type: "session", status: "closed" }),
    ];
    const deps = [{ unit_id: "01J2", needs_unit_id: "01J1" }];

    render(<DagView units={units} deps={deps} />);

    const nodes = screen.getAllByTestId("dag-node");
    expect(nodes).toHaveLength(2); // session excluded
    expect(screen.getAllByTestId("dag-edge")).toHaveLength(1);
  });

  it("positions a unit strictly after everything it depends on (topological level)", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "a", status: "closed" }),
      unit({ id: "01J2", step_id: "b", status: "closed" }),
      unit({ id: "01J3", step_id: "c", status: "ready" }),
    ];
    const deps = [
      { unit_id: "01J2", needs_unit_id: "01J1" },
      { unit_id: "01J3", needs_unit_id: "01J2" },
    ];

    render(<DagView units={units} deps={deps} />);

    const nodeA = screen.getByTestId("dag-node-01J1");
    const nodeB = screen.getByTestId("dag-node-01J2");
    const nodeC = screen.getByTestId("dag-node-01J3");
    const xA = Number(nodeA.getAttribute("data-x"));
    const xB = Number(nodeB.getAttribute("data-x"));
    const xC = Number(nodeC.getAttribute("data-x"));
    expect(xB).toBeGreaterThan(xA);
    expect(xC).toBeGreaterThan(xB);
  });

  it("marks units sharing a convoy_id with a distinct outline", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "implement", status: "closed", convoy_id: "01JC1" }),
      unit({ id: "01J2", step_id: "review", status: "ready", convoy_id: "01JC1" }),
      unit({ id: "01J3", step_id: "solo", status: "open", convoy_id: null }),
    ];
    render(<DagView units={units} deps={[]} />);

    const convoyNode = screen.getByTestId("dag-node-01J1");
    const soloNode = screen.getByTestId("dag-node-01J3");
    expect(convoyNode.getAttribute("data-convoy")).toBe("01JC1");
    expect(soloNode.getAttribute("data-convoy")).toBeNull();
  });
});
