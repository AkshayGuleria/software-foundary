// frontend/src/components/Ribbon.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Ribbon from "./Ribbon";
import type { WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0, owner_session_id: null, ...overrides,
});

describe("Ribbon", () => {
  it("renders one pill per non-session unit, in id order", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J3", step_id: "review", status: "open" }),
      unit({ id: "01J1", step_id: "plan", status: "closed" }),
      unit({ id: "01J2Z", step_id: "session-for-plan", type: "session", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "blocked" }),
    ];

    render(<Ribbon units={units} />);

    const pills = screen.getAllByTestId("ribbon-pill");
    expect(pills).toHaveLength(3); // session unit excluded
    expect(pills.map((p) => p.textContent)).toEqual([
      expect.stringContaining("plan"),
      expect.stringContaining("implement"),
      expect.stringContaining("review"),
    ]);
  });

  it("colors a closed step differently from a blocked one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "blocked" })];
    render(<Ribbon units={units} />);
    const pills = screen.getAllByTestId("ribbon-pill");
    expect(pills[0].className).not.toEqual(pills[1].className);
  });
});
