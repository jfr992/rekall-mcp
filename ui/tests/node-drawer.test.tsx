// Migrated from NodeDrawer to MemoryInspector (T6 integration).
// NodeDrawer is removed; these scenarios are now covered by MemoryInspector.
import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import type { DetailResponseV2 } from "@/lib/schemas";

const fakeDetail: DetailResponseV2 = {
  memory: {
    memory_id: "m1",
    content: "Use Go over Rust for the backend rewrite",
    type: "decision",
    tier: "semantic",
    durability: 0.85,
    date: "2026-04-01",
    project: "test",
    reinforcement_count: 3,
  },
  neighbors: [],
  scope: { project: "test", agent: "claude-code", repo_name: null },
  relationships: [
    {
      source_id: "m1",
      target_id: "m2",
      neighbor_id: "m2",
      direction: "out",
      relation: "related_to",
      weight: 0.7,
      auto: true,
      created: "2026-04-01",
      memory: {
        memory_id: "m2",
        content: "Go tooling is more mature",
        type: "note",
        tier: "working",
      },
    },
  ],
  warnings: [],
};

describe("MemoryInspector (migrated from NodeDrawer)", () => {
  test("renders memory content, type/tier badges, and neighbor", () => {
    render(
      <MemoryInspector
        open
        detail={fakeDetail}
        isLoading={false}
        currentProject="test"
        onClose={vi.fn()}
        onSelectMemory={vi.fn()}
      />,
    );
    expect(screen.getByText("decision")).toBeInTheDocument();
    expect(screen.getByText("semantic")).toBeInTheDocument();
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("Go tooling is more mature")).toBeInTheDocument();
  });

  test("closes on ESC", async () => {
    const onClose = vi.fn();
    render(
      <MemoryInspector
        open
        detail={fakeDetail}
        isLoading={false}
        currentProject="test"
        onClose={onClose}
        onSelectMemory={vi.fn()}
      />,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
