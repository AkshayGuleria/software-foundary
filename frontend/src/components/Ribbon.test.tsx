import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Ribbon from "./Ribbon";
import type { Gate, WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0, owner_session_id: null, convoy_id: null, ...overrides,
});
const gate = (overrides: Partial<Gate>): Gate => ({
  id: "01JG0", work_unit_id: "01J0", gate_type: "human", decision: "pending", ...overrides,
});

describe("Ribbon", () => {
  it("renders one agent pill per non-session unit, in id order", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J3", step_id: "review", status: "open" }),
      unit({ id: "01J1", step_id: "plan", status: "closed" }),
      unit({ id: "01J2Z", step_id: "session-for-plan", type: "session", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "blocked" }),
    ];

    render(<Ribbon units={units} gates={[]} />);

    const pills = screen.getAllByTestId("ribbon-pill-agent");
    expect(pills).toHaveLength(3); // session unit excluded
    expect(pills.map((p) => p.textContent)).toEqual([
      expect.stringContaining("plan"),
      expect.stringContaining("implement"),
      expect.stringContaining("review"),
    ]);
  });

  it("colors a closed step's agent pill differently from a blocked one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "blocked" })];
    render(<Ribbon units={units} gates={[]} />);
    const pills = screen.getAllByTestId("ribbon-pill-agent");
    expect(pills[0].className).not.toEqual(pills[1].className);
  });

  it("renders a human pill only for a step that has a gate", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "gated", status: "blocked" }), unit({ id: "01J2", step_id: "ungated", status: "open" })];
    const gates: Gate[] = [gate({ id: "01JG1", work_unit_id: "01J1", decision: "pending" })];

    render(<Ribbon units={units} gates={gates} />);

    expect(screen.getAllByTestId("ribbon-pill-human")).toHaveLength(1);
  });

  it("colors an approved human pill differently from a rejected one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "closed" })];
    const gates: Gate[] = [
      gate({ id: "01JG1", work_unit_id: "01J1", decision: "approved" }),
      gate({ id: "01JG2", work_unit_id: "01J2", decision: "rejected" }),
    ];

    render(<Ribbon units={units} gates={gates} />);

    const humanPills = screen.getAllByTestId("ribbon-pill-human");
    expect(humanPills[0].className).not.toEqual(humanPills[1].className);
  });

  it("marks a derived gate's human pill distinctly from a human-type gate's", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "closed" })];
    const gates: Gate[] = [
      gate({ id: "01JG1", work_unit_id: "01J1", gate_type: "human", decision: "pending" }),
      gate({ id: "01JG2", work_unit_id: "01J2", gate_type: "derived", decision: "pending" }),
    ];

    render(<Ribbon units={units} gates={gates} />);

    const humanPills = screen.getAllByTestId("ribbon-pill-human");
    expect(humanPills[0].getAttribute("data-gate-type")).toBe("human");
    expect(humanPills[1].getAttribute("data-gate-type")).toBe("derived");
  });

  it("calls onSelectUnit with the clicked step's unit", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const onSelectUnit = vi.fn();
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "implement", status: "closed" })];

    render(<Ribbon units={units} gates={[]} onSelectUnit={onSelectUnit} />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("ribbon-step-01J1"));

    expect(onSelectUnit).toHaveBeenCalledWith(units[0]);
  });
});
