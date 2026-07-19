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
  disputed: [
    { memory_id: "d1", content: "disputed fact", type: "fact", tier: "semantic", date: "2026-07-10" },
  ],
  stale_candidates: [
    { memory_id: "s1", content: "stale candidate note", type: "note", tier: "working", date: "2026-06-01" },
  ],
};

function manyConflicts(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    memory_id: `cf${i}`,
    content: `conflicted fact ${i}`,
    type: "fact",
    tier: "semantic",
    date: "2026-07-01",
  }));
}

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

  it("shows a Disputed group with its tagline and opens the inspector on row click", () => {
    const onSelect = vi.fn();
    render(<FlaggedPanel flagged={FLAGGED} onSelect={onSelect} />);
    expect(screen.getByText(/disputed fact/)).toBeInTheDocument();
    expect(
      screen.getByText(/marked wrong by feedback — suppressed from recall until reviewed/)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText(/disputed fact/));
    expect(onSelect).toHaveBeenCalledWith("d1");
  });

  it("shows a Stale candidates group with its tagline and opens the inspector on row click", () => {
    const onSelect = vi.fn();
    render(<FlaggedPanel flagged={FLAGGED} onSelect={onSelect} />);
    expect(screen.getByText(/stale candidate note/)).toBeInTheDocument();
    expect(screen.getByText(/marked stale — review for supersedes/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/stale candidate note/));
    expect(onSelect).toHaveBeenCalledWith("s1");
  });

  it("collapses a group with more than 5 members to the top 5 plus a Show all N expander", () => {
    const onSelect = vi.fn();
    render(
      <FlaggedPanel
        flagged={{ ...FLAGGED, conflict: manyConflicts(12) }}
        onSelect={onSelect}
      />
    );
    expect(screen.getByText(/conflicted fact 4/)).toBeInTheDocument();
    expect(screen.queryByText(/conflicted fact 5/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all 12" }));
    expect(screen.getByText(/conflicted fact 11/)).toBeInTheDocument();
  });

  it("each group panel is the scroll container, not the page — bounded max-height with internal overflow", () => {
    render(<FlaggedPanel flagged={FLAGGED} onSelect={vi.fn()} />);
    const panel = screen.getByText(/conflicted fact/).closest("section")!;
    expect(panel.className).toContain("max-h-[50vh]");
    expect(panel.className).toContain("overflow-y-auto");
  });
});
