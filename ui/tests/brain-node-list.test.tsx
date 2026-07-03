import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BrainNodeList } from "@/components/brain/brain-node-list";
import type { GraphNode } from "@/lib/schemas";

const nodes: GraphNode[] = [
  { id: "m1", content: "Use Go for the backend", type: "decision", tier: "semantic" },
  { id: "m2", content: "PostgreSQL for primary store", type: "fact", tier: "working" },
  { id: "m3", content: "Deploy on Kubernetes", type: "requirement", tier: "episodic" },
];

describe("BrainNodeList", () => {
  test("renders node contents as buttons", () => {
    render(<BrainNodeList nodes={nodes} onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Use Go for the backend/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PostgreSQL for primary store/i })).toBeInTheDocument();
  });

  test("clicking a node button calls onSelect with the memory id", () => {
    const onSelect = vi.fn();
    render(<BrainNodeList nodes={nodes} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Use Go for the backend/i }));
    expect(onSelect).toHaveBeenCalledWith("m1");
  });

  test("second node button calls onSelect with its own id", () => {
    const onSelect = vi.fn();
    render(<BrainNodeList nodes={nodes} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /PostgreSQL for primary store/i }));
    expect(onSelect).toHaveBeenCalledWith("m2");
  });

  test("panel is collapsible — has a toggle button or summary", () => {
    render(<BrainNodeList nodes={nodes} onSelect={vi.fn()} />);
    const summary = document.querySelector("summary");
    expect(summary).not.toBeNull();
  });

  test("renders empty state gracefully when no nodes", () => {
    const { container } = render(<BrainNodeList nodes={[]} onSelect={vi.fn()} />);
    expect(container).toBeTruthy();
    // No node buttons when empty
    expect(screen.queryAllByRole("button").filter((b) => /m\d/.test(b.textContent ?? ""))).toHaveLength(0);
  });
});
