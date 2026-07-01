import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OkfExport } from "@/components/publish/okf-export";

const CONCEPT = `---
type: runbook
title: KubeVirt namespace recovery
timestamp: 2026-05-28T14:30:00Z
---
Delete stuck webhooks, then strip the finalizer to unblock the namespace.

## Sources
- ghost pods block statefulset slots
`;

vi.mock("@/lib/queries/use-publish", () => ({
  usePublish: () => ({
    data: {
      tree: ["byte-edge/runbooks/kubevirt.md", "byte-edge/runbooks/index.md"],
      files: { "byte-edge/runbooks/kubevirt.md": CONCEPT },
      stats: { concepts: 1, synthesized: "cached" },
    },
    isLoading: false,
  }),
}));

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient();
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("OkfExport", () => {
  it("hides index.md and previews a clicked concept as a parsed brief", () => {
    renderWithClient(<OkfExport project="byte-edge" />);
    expect(screen.queryByText("index")).not.toBeInTheDocument(); // index.md filtered out
    fireEvent.click(screen.getByText("kubevirt"));
    expect(screen.getByText(/KubeVirt namespace recovery/)).toBeInTheDocument(); // title
    expect(screen.getByText(/strip the finalizer/)).toBeInTheDocument(); // brief
    expect(screen.getByText(/ghost pods block/)).toBeInTheDocument(); // source
  });

  it("renders a Synthesize button", () => {
    renderWithClient(<OkfExport project="byte-edge" />);
    expect(screen.getByText(/Synthesize/)).toBeInTheDocument();
  });
});
