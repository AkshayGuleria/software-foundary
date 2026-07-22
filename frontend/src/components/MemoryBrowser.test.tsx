import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import MemoryBrowser from "./MemoryBrowser";
import type { MemoryItem } from "../api/types";

const item = (overrides: Partial<MemoryItem>): MemoryItem => ({
  id: "01JM1",
  scope: "project",
  kind: "lesson",
  title: "A lesson",
  body_md: "body text",
  project_id: "01JP1",
  pack_id: null,
  source_run_id: null,
  created_at: "2026-07-22T00:00:00Z",
  ...overrides,
});

function renderWithRouter(items: MemoryItem[]) {
  return render(
    <MemoryRouter>
      <MemoryBrowser items={items} />
    </MemoryRouter>
  );
}

describe("MemoryBrowser", () => {
  it("renders each item's title and kind", () => {
    renderWithRouter([item({ title: "Lesson one" }), item({ id: "01JM2", kind: "pattern", title: "Pattern one" })]);

    expect(screen.getByText("Lesson one")).toBeInTheDocument();
    expect(screen.getByText("Pattern one")).toBeInTheDocument();
  });

  it("links to the source run when one exists", () => {
    renderWithRouter([item({ source_run_id: "01JR1" })]);
    expect(screen.getByRole("link", { name: /01JR1/i })).toHaveAttribute("href", "/runs/01JR1");
  });

  it("shows an empty state when there are no items", () => {
    renderWithRouter([]);
    expect(screen.getByText(/no memory items/i)).toBeInTheDocument();
  });
});
