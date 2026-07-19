import { describe, test, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryContent } from "@/components/memory-inspector/memory-content";

const COMMAND_CONTENT =
  "Ran: glab mr view 3598 --repo example-org/cloud 2>&1 | head -60 — ERROR Failed to get merge request";

describe("MemoryContent command rendering", () => {
  test("command-shaped content renders as a mono block", () => {
    render(<MemoryContent content={COMMAND_CONTENT} />);
    const block = screen.getByText(/glab mr view 3598/);
    expect(block).toHaveClass("font-mono");
    expect(block).toHaveClass("rounded-md");
  });

  test("$-prefixed and fenced content also get the mono block", () => {
    const { rerender } = render(<MemoryContent content="$ ls -la /tmp" />);
    expect(screen.getByText(/ls -la/)).toHaveClass("font-mono");

    rerender(
      <MemoryContent content={"Fix applied:\n```\nnpm run build\n```"} />,
    );
    expect(screen.getByText(/npm run build/)).toHaveClass("font-mono");
  });

  test("mono block wraps long tokens cleanly in preview and expanded views", () => {
    const longCommand =
      "Ran: glab mr view 3598 --repo example-org/cloud-platform-engineering 2>&1 — GET https://gitlab.com/api/v4/projects/example-org%2Fcloud%2Fplatform%2Fengineering/merge_requests/3598 " +
      "x".repeat(500);
    render(<MemoryContent content={longCommand} />);

    const preview = screen.getByText(/glab mr view 3598/);
    expect(preview).toHaveClass("whitespace-pre-wrap");
    expect(preview).toHaveStyle({ overflowWrap: "anywhere" });

    fireEvent.click(screen.getByRole("button", { name: /show full/i }));
    const full = screen.getByText(/glab mr view 3598/);
    expect(full).toHaveClass("whitespace-pre-wrap");
    expect(full).toHaveStyle({ overflowWrap: "anywhere" });
  });

  test("prose content keeps the existing rendering without the mono treatment", () => {
    render(
      <MemoryContent content="Use PostgreSQL for the primary store — decided after the outage review." />,
    );
    const prose = screen.getByText(/Use PostgreSQL/);
    expect(prose.tagName).toBe("P");
    expect(prose).not.toHaveClass("font-mono");
    expect(prose).toHaveClass("whitespace-pre-wrap");
    expect(prose).toHaveStyle({ overflowWrap: "anywhere" });
  });
});
