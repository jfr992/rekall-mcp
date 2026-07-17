import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryInspector } from "@/components/memory-inspector/memory-inspector";
import { EntityBacklinks } from "@/components/memory-inspector/entity-backlinks";
import * as byEntityApi from "@/lib/api/by-entity";
import type { ByEntityResponse, DetailResponseV2 } from "@/lib/schemas";

vi.mock("@/lib/api/by-entity");

const backlinks: ByEntityResponse = {
  entity: "MetalLB",
  project: "net-lab",
  count: 2,
  memories: [
    {
      memory_id: "2026-07-02_learning_d4e5f6",
      content: "MetalLB speaker pods need the memberlist secret",
      type: "learning",
      date: "2026-07-02",
      project: "net-lab",
    },
    {
      memory_id: "2026-06-20_fact_090a0b",
      content: "MetalLB IP pools defined per rack",
      type: "fact",
      date: "2026-06-20",
      project: "net-lab",
    },
  ],
};

const detail: DetailResponseV2 = {
  memory: {
    memory_id: "2026-07-10_decision_a1b2c3",
    content: "Chose MetalLB for bare-metal load balancing",
    type: "decision",
    tier: "semantic",
    date: "2026-07-10",
    project: "net-lab",
    entities: ["MetalLB", "bare-metal"],
  },
  neighbors: [],
  scope: { project: "net-lab", agent: "claude-code", repo_name: "net-lab" },
  relationships: [],
  storage: { qdrant: true, yaml: true },
  warnings: [],
};

const defaultProps = {
  open: true,
  detail,
  isLoading: false,
  currentProject: "net-lab",
  onClose: vi.fn(),
  onSelectMemory: vi.fn(),
};

function renderInspector(props = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryInspector {...defaultProps} {...props} />
    </QueryClientProvider>
  );
}

describe("entity backlinks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("inspector renders a clickable chip per entity", () => {
    renderInspector();
    expect(
      screen.getByRole("button", { name: /backlinks for MetalLB/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /backlinks for bare-metal/i })
    ).toBeInTheDocument();
  });

  test("EntityBacklinks renders the fetched memories directly", async () => {
    vi.mocked(byEntityApi.getByEntity).mockResolvedValue(backlinks);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <EntityBacklinks
          entity="MetalLB"
          project="net-lab"
          onClose={vi.fn()}
          onSelectMemory={vi.fn()}
        />
      </QueryClientProvider>
    );

    expect(
      await screen.findByText(/speaker pods need the memberlist secret/i)
    ).toBeInTheDocument();
  });

  test("clicking a chip opens a slide-over listing backlinked memories", async () => {
    vi.mocked(byEntityApi.getByEntity).mockResolvedValue(backlinks);
    renderInspector();

    fireEvent.click(screen.getByRole("button", { name: /backlinks for MetalLB/i }));

    expect(
      await screen.findByText(/speaker pods need the memberlist secret/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/ip pools defined per rack/i)).toBeInTheDocument();
    expect(byEntityApi.getByEntity).toHaveBeenCalledWith("MetalLB", "net-lab");
  });

  test("clicking a backlink row selects that memory and closes the slide-over", async () => {
    vi.mocked(byEntityApi.getByEntity).mockResolvedValue(backlinks);
    const onSelectMemory = vi.fn();
    renderInspector({ onSelectMemory });

    fireEvent.click(screen.getByRole("button", { name: /backlinks for MetalLB/i }));
    fireEvent.click(
      await screen.findByText(/speaker pods need the memberlist secret/i)
    );

    expect(onSelectMemory).toHaveBeenCalledWith("2026-07-02_learning_d4e5f6");
    await waitFor(() => {
      expect(
        screen.queryByText(/ip pools defined per rack/i)
      ).not.toBeInTheDocument();
    });
  });

  test("slide-over shows the entity name and an empty state when nothing links back", async () => {
    vi.mocked(byEntityApi.getByEntity).mockResolvedValue({
      entity: "bare-metal",
      project: "net-lab",
      count: 0,
      memories: [],
    });
    renderInspector();

    fireEvent.click(
      screen.getByRole("button", { name: /backlinks for bare-metal/i })
    );

    expect(
      await screen.findByText(/no other memories mention bare-metal/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Backlinks")).toBeInTheDocument();
  });
});
