import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import GateCard from "./GateCard";
import type { Gate } from "../api/types";

const pendingHumanGate: Gate = { id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "pending", artifact_id: "01JA1" };
const pendingDerivedGate: Gate = {
  id: "01JG2", work_unit_id: "01JU2", gate_type: "derived", decision: "pending",
  cost_estimate: { estimated_writes_steps: 1, estimated_tokens: 30000, basis: "heuristic" },
};

describe("GateCard", () => {
  it("shows approve/reject controls for a pending gate and calls onDecide on approve", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /approve/i }));

    expect(onDecide).toHaveBeenCalledWith("approved", undefined);
  });

  it("requires feedback text before submitting a rejection", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /reject/i }));
    await user.type(screen.getByLabelText(/feedback/i), "not good enough");
    await user.click(screen.getByRole("button", { name: /submit rejection/i }));

    expect(onDecide).toHaveBeenCalledWith("rejected", { chips: [], text: "not good enough" });
  });

  it("shows the cost estimate for a pending derived gate", () => {
    render(<GateCard gate={pendingDerivedGate} artifact={undefined} onDecide={vi.fn()} />);
    expect(screen.getByText(/30000|30,000/)).toBeInTheDocument();
  });

  it("shows no controls for an already-decided gate", () => {
    render(<GateCard gate={{ ...pendingHumanGate, decision: "approved" }} artifact={undefined} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});
