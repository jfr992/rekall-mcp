import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Module-level mocks must precede import of the component under test
vi.mock("@/lib/project-store", () => ({
  useProjectStore: vi.fn(),
}));

vi.mock("@/lib/queries/use-resume", () => ({
  useResume: vi.fn(() => ({ data: null, isLoading: true, isError: false })),
}));

vi.mock("@/lib/queries/use-memory-detail", () => ({
  useMemoryDetail: vi.fn(() => ({ data: undefined, isLoading: false })),
}));

// Import after mocks are hoisted
import { useProjectStore } from "@/lib/project-store";
import ContinuityPage from "@/app/continuity/page";

describe("ContinuityPage — heading", () => {
  test("shows 'all memories' when project sentinel is empty string", () => {
    vi.mocked(useProjectStore).mockImplementation((sel: any) =>
      sel({ project: "", setProject: vi.fn() }),
    );
    render(<ContinuityPage />);
    const heading = screen.getByRole("heading");
    expect(heading).toHaveTextContent("Continuity · all memories");
    // Must not render a bare trailing space/dot from the sentinel
    expect(heading.textContent).not.toMatch(/Continuity · $/);
  });

  test("shows project name when project is set", () => {
    vi.mocked(useProjectStore).mockImplementation((sel: any) =>
      sel({ project: "rekall-mcp", setProject: vi.fn() }),
    );
    render(<ContinuityPage />);
    expect(screen.getByRole("heading")).toHaveTextContent("Continuity · rekall-mcp");
  });
});
