import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import UnitDrawer from "./UnitDrawer";
import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";

// SessionRow.work_unit_id always points to a SESSION-type WorkUnit, never
// the TASK-type unit clicked in the Ribbon/DAG (see Orchestrator.dispatch()
// in src/foundry/orchestrator/tick.py: a fresh session-type unit is created
// per dispatch attempt, and the task unit's own owner_session_id is updated
// to point at it). So a task unit's sessions can only be found via its
// owner_session_id, not its own id -- these fixtures set that up explicitly.
const unit: WorkUnit = {
  id: "01JU1", step_id: "implement", type: "task", status: "closed", attempt: 0, owner_session_id: "01JS1", convoy_id: null,
};
const otherUnit: WorkUnit = { ...unit, id: "01JU2", step_id: "review", owner_session_id: "01JS2" };

describe("UnitDrawer", () => {
  it("shows only the selected unit's events, artifacts, and sessions -- not other units'", () => {
    const events = [
      { seq: 1, type: "unit.closed", unit_id: "01JU1", payload: { a: 1 } },
      { seq: 2, type: "unit.closed", unit_id: "01JU2", payload: { a: 2 } },
    ];
    const artifacts: Artifact[] = [
      { id: "a1", work_unit_id: "01JU1", kind: "diff", version: 1, produced_by_role: "implementer", payload_json: {} },
      { id: "a2", work_unit_id: "01JU2", kind: "diff", version: 1, produced_by_role: "implementer", payload_json: {} },
    ];
    const gates: Gate[] = [
      { id: "g1", work_unit_id: "01JU1", gate_type: "human", decision: "pending" },
      { id: "g2", work_unit_id: "01JU2", gate_type: "human", decision: "pending" },
    ];
    // Session ids/work_unit_ids match the two units' owner_session_id
    // values above (01JS1/01JS2), NOT 01JU1/01JU2 -- see the comment above
    // unit's declaration for why.
    const sessions: Session[] = [
      { id: "01JS1", work_unit_id: "01JS1", run_id: "r1", step_id: "implement", driver: "fake", status: "closed", model: "m1", tokens_in: 1, tokens_out: 2, started_at: null, ended_at: null },
      { id: "01JS2", work_unit_id: "01JS2", run_id: "r1", step_id: "review", driver: "fake", status: "closed", model: "m1", tokens_in: 1, tokens_out: 2, started_at: null, ended_at: null },
    ];

    render(
      <UnitDrawer
        unit={unit}
        events={events as FeedEventLike[]}
        artifacts={artifacts}
        gates={gates}
        sessions={sessions}
        onClose={vi.fn()}
        onDecideGate={vi.fn()}
      />
    );

    // Scoped to the heading role: a plain getByText(/implement/) also matches
    // the artifact card's "v1 · implementer" (produced_by_role), which is an
    // unrelated element -- ambiguous match, not a real assertion failure.
    expect(screen.getByRole("heading", { name: "implement" })).toBeInTheDocument();
    expect(screen.queryByText(/"a":2/)).not.toBeInTheDocument(); // other unit's event payload
    expect(screen.getAllByTestId("drawer-artifact")).toHaveLength(1);
    expect(screen.getAllByTestId("drawer-session")).toHaveLength(1);
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    render(
      <UnitDrawer unit={unit} events={[]} artifacts={[]} gates={[]} sessions={[]} onClose={onClose} onDecideGate={vi.fn()} />
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("shows the unit's gate via GateCard when one exists", () => {
    const gates: Gate[] = [{ id: "g1", work_unit_id: "01JU1", gate_type: "human", decision: "pending" }];
    render(<UnitDrawer unit={unit} events={[]} artifacts={[]} gates={gates} sessions={[]} onClose={vi.fn()} onDecideGate={vi.fn()} />);

    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
  });

  it("shows no gate tab content for a unit with no gate", () => {
    render(<UnitDrawer unit={otherUnit} events={[]} artifacts={[]} gates={[]} sessions={[]} onClose={vi.fn()} onDecideGate={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no gate/i)).toBeInTheDocument();
  });
});
