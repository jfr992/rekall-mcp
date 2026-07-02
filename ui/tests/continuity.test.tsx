import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TruncatedWarning } from "@/components/continuity/truncated-warning";
import { ResumeHeader } from "@/components/continuity/resume-header";

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
