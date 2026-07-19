import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import type { DetailResponseV2 } from "@/lib/schemas";

const disputedDetail: DetailResponseV2 = {
  memory: {
    memory_id: "2026-07-10_fact_0ddba11",
    content: "wrong fact about MetalLB pool exhaustion",
    type: "fact",
    tier: "semantic",
    date: "2026-07-10",
    project: "net-lab",
    disputed: true,
  },
  neighbors: [],
  scope: { project: "net-lab", agent: "claude-code", repo_name: "net-lab" },
  relationships: [],
  storage: { qdrant: true, yaml: true },
  warnings: [],
};

const defaultProps = {
  open: true,
  detail: disputedDetail,
  isLoading: false,
  currentProject: "net-lab",
  onClose: vi.fn(),
  onSelectMemory: vi.fn(),
};

function renderInspector(props = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryInspector {...defaultProps} {...props} />
      <Toaster />
    </QueryClientProvider>
  );
  return client;
}

describe("un-dispute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("disputed memory shows an Un-dispute button", () => {
    renderInspector();
    expect(screen.getByRole("button", { name: /un-dispute/i })).toBeInTheDocument();
  });

  test("clicking Un-dispute fires POST /dispute with disputed=false and the UI mutation header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ memory_id: "2026-07-10_fact_0ddba11", disputed: false })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /un-dispute/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/memory/2026-07-10_fact_0ddba11/dispute");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ disputed: false });
    expect((init.headers as Record<string, string>)["X-Rekall-UI"]).toBe("1");
  });
});
