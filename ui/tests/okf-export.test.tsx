import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { OkfExport } from "@/components/publish/okf-export";

vi.mock("@/lib/queries/use-publish", () => ({
  usePublish: () => ({
    data: {
      tree: ["byte-edge/runbooks/x.md"],
      files: { "byte-edge/runbooks/x.md": "# KubeVirt recovery" },
      stats: { concepts: 1, titled_by: "slug" },
    },
    isLoading: false,
  }),
}));

describe("OkfExport", () => {
  it("shows the tree and previews a clicked file", () => {
    render(<OkfExport project="byte-edge" />);
    fireEvent.click(screen.getByText(/x\.md/));
    expect(screen.getByText(/KubeVirt recovery/)).toBeInTheDocument();
  });
});
