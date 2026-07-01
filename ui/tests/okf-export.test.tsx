import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OkfExport } from "@/components/publish/okf-export";

vi.mock("@/lib/queries/use-publish", () => ({
  usePublish: () => ({
    data: {
      tree: ["byte-edge/runbooks/x.md"],
      files: { "byte-edge/runbooks/x.md": "# KubeVirt recovery" },
      stats: { concepts: 1, synthesized: "raw" },
    },
    isLoading: false,
  }),
}));

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient();
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("OkfExport", () => {
  it("shows the tree and previews a clicked file", () => {
    renderWithClient(<OkfExport project="byte-edge" />);
    fireEvent.click(screen.getByText(/x\.md/));
    expect(screen.getByText(/KubeVirt recovery/)).toBeInTheDocument();
  });

  it("renders a Synthesize button", () => {
    renderWithClient(<OkfExport project="byte-edge" />);
    expect(screen.getByText(/Synthesize/)).toBeInTheDocument();
  });
});
