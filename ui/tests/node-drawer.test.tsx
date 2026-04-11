import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NodeDrawer } from "@/components/brain/node-drawer";
import type { DetailResponse } from "@/lib/schemas";

const fakeDetail: DetailResponse = {
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
  neighbors: [
    {
      relation: "related_to",
      memory: {
        memory_id: "m2",
        content: "Go tooling is more mature",
        type: "note",
        tier: "working",
      },
    },
  ],
  scope: { project: "test", agent: "claude-code", repo_name: null },
};

describe("NodeDrawer", () => {
  test("renders memory content, type/tier badges, and neighbor", () => {
    render(<NodeDrawer open detail={fakeDetail} isLoading={false} onClose={vi.fn()} />);
    // Badges
    expect(screen.getByText("decision")).toBeInTheDocument();
    expect(screen.getByText("semantic")).toBeInTheDocument();
    // Memory ID
    expect(screen.getByText("m1")).toBeInTheDocument();
    // Neighbor content
    expect(screen.getByText("Go tooling is more mature")).toBeInTheDocument();
  });

  test("closes on ESC", async () => {
    const onClose = vi.fn();
    render(<NodeDrawer open detail={fakeDetail} isLoading={false} onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
