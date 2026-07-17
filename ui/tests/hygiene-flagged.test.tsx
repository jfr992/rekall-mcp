import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FlaggedPanel } from "@/components/hygiene/flagged-panel";

const FLAGGED = {
  stale_working_count: 1,
  low_value_count: 1,
  contradiction_count: 1,
  stale_working: [
    { memory_id: "st1", content: "stale note", type: "note", tier: "working", date: "2026-01-01" },
  ],
  low_value: [
    { memory_id: "lv1", content: "low value", type: "note", tier: "working", date: "2026-06-01" },
  ],
  conflict: [
    { memory_id: "cf1", content: "conflicted fact", type: "fact", tier: "semantic", date: "2026-07-01" },
  ],
};

describe("hygiene flagged panel", () => {
  it("groups flags by reason and opens the inspector on row click", () => {
    const onSelect = vi.fn();
    render(<FlaggedPanel flagged={FLAGGED} onSelect={onSelect} />);
    expect(screen.getByText(/conflicted fact/)).toBeInTheDocument();
    expect(screen.getByText(/stale note/)).toBeInTheDocument();
    expect(screen.getByText(/low value/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/conflicted fact/));
    expect(onSelect).toHaveBeenCalledWith("cf1");
  });
});
