import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { ResumeHeader } from "@/components/continuity/resume-header";
import { SectionGroup } from "@/components/continuity/section-group";
import { ImportantSection } from "@/components/continuity/important-section";
import { MemoryRow } from "@/components/continuity/memory-row";

describe("Continuity — TruncatedWarning", () => {
  test("renders warning text when truncated", () => {
    render(<TruncatedWarning truncated={true} />);
    expect(screen.getByText(/showing/i)).toBeInTheDocument();
  });

  test("renders nothing when not truncated", () => {
    const { container } = render(<TruncatedWarning truncated={false} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("Continuity — ResumeHeader", () => {
  test("renders scope metadata as mono", () => {
    const scope = { project: "test", agent: "claude-code", repo_name: "rekall-mcp", branch: "feat/x" };
    render(<ResumeHeader scope={scope} />);
    expect(screen.getByText(/claude-code/i)).toBeInTheDocument();
    expect(screen.getByText(/rekall-mcp/i)).toBeInTheDocument();
  });
});

describe("Continuity — SectionGroup", () => {
  test("collapsed by default hides children, shows count", () => {
    render(
      <SectionGroup title="Recent" eyebrow="EYEBROW" count={7}>
        <p>hidden body</p>
      </SectionGroup>
    );
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("hidden body").closest("details")).not.toHaveAttribute("open");
  });

  test("defaultOpen renders expanded", () => {
    render(
      <SectionGroup title="Important" eyebrow="EYEBROW" count={2} defaultOpen>
        <p>visible body</p>
      </SectionGroup>
    );
    expect(screen.getByText("visible body").closest("details")).toHaveAttribute("open");
  });
});

describe("Continuity — MemoryRow", () => {
  test("click reports memory id", () => {
    const onSelect = vi.fn();
    render(
      <MemoryRow
        memoryId="2026-07-02_note_abc"
        content="clickable memory"
        type="note"
        date="2026-07-02"
        onSelect={onSelect}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith("2026-07-02_note_abc");
  });

  test("has aria-haspopup='dialog' for screen readers", () => {
    render(<MemoryRow memoryId="m1" content="accessible memory" onSelect={() => {}} />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-haspopup", "dialog");
  });

  test("has focus-visible ring class", () => {
    render(<MemoryRow memoryId="m1" content="focusable memory" onSelect={() => {}} />);
    expect(screen.getByRole("button").className).toMatch(/focus-visible/);
  });
});

describe("Continuity — ImportantSection", () => {
  test("groups items by type in importance order", () => {
    const items = [
      { memory_id: "m1", content: "a learning", type: "learning" },
      { memory_id: "m2", content: "a requirement", type: "requirement" },
      { memory_id: "m3", content: "another learning", type: "learning" },
    ];
    render(<ImportantSection items={items} onSelect={() => {}} />);
    const labels = screen.getAllByText(/·/).map((el) => el.textContent);
    const req = labels.findIndex((t) => t?.includes("requirement"));
    const learn = labels.findIndex((t) => t?.includes("learning"));
    expect(req).toBeGreaterThanOrEqual(0);
    expect(learn).toBeGreaterThan(req);
    expect(screen.getByText(/requirement · 1/)).toBeInTheDocument();
    expect(screen.getByText(/learning · 2/)).toBeInTheDocument();
  });
});
