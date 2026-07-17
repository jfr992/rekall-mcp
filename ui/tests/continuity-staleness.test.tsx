import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResumeHeader } from "@/components/continuity/resume-header";
import { ageBadge } from "@/components/continuity/staleness";

describe("continuity T4 fixes", () => {
  it("null scope renders no header card instead of a fabricated one", () => {
    const { container } = render(<ResumeHeader scope={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("ageBadge labels memories older than 90 days", () => {
    // Fixed 150-day offset: calendar months are 149-153 days and flake at UTC
    // day rollovers (real failure on 2026-07-17: 5 months back = 149.98 days).
    const old = new Date(Date.now() - 150 * 86_400_000);
    expect(ageBadge(old.toISOString().slice(0, 10))).toBe("5mo");
    const recent = new Date().toISOString().slice(0, 10);
    expect(ageBadge(recent)).toBeNull();
  });
});
