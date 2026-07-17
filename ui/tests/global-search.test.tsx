import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GlobalSearch } from "@/components/shell/global-search";
import { CockpitShell } from "@/components/shell/cockpit-shell";
import { useProjectStore } from "@/lib/project-store";
import * as searchApi from "@/lib/api/search";
import * as detailApi from "@/lib/api/detail";
import recallFixture from "./fixtures/recall.json";
import detailV2Fixture from "./fixtures/detail-v2.json";
import type { RecallResponse } from "@/lib/schemas";

vi.mock("@/lib/api/search");
vi.mock("@/lib/api/detail");
// Shell children that make their own network calls — stubbed for the mount pin
vi.mock("@/components/shell/project-switcher", () => ({
  ProjectSwitcher: () => <div data-testid="project-switcher" />,
}));
vi.mock("@/components/shell/health-badge", () => ({
  HealthBadge: () => <div data-testid="health-badge" />,
}));
vi.mock("@/lib/queries/use-insights", () => ({
  useInsights: () => ({ data: undefined }),
}));

function renderSearch() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <GlobalSearch />
    </QueryClientProvider>
  );
}

describe("GlobalSearch palette", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectStore.setState({ project: "" });
    vi.mocked(searchApi.postRecall).mockResolvedValue({
      query: "",
      count: 0,
      memories: [],
    });
  });

  test("Cmd-K opens the palette", () => {
    renderSearch();
    expect(screen.queryByPlaceholderText(/search memories/i)).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect(screen.getByPlaceholderText(/search memories/i)).toBeInTheDocument();
  });

  test("the visible search button opens the palette; Escape closes it", async () => {
    renderSearch();
    fireEvent.click(screen.getByRole("button", { name: /search memories/i }));
    expect(screen.getByPlaceholderText(/search memories/i)).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/search memories/i)).not.toBeInTheDocument();
    });
  });

  test("header shows the RECALL label and mode chips, semantic active by default", () => {
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect(screen.getByText("RECALL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^semantic$/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: /^exact$/i })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });

  // PIN NOTE (T5, deliberate): this pin now covers semantic mode (limit 10);
  // the companion test below covers exact mode (limit 50). Both modes pinned.
  test("typing fires one debounced recall scoped to the selected project", async () => {
    useProjectStore.setState({ project: "byte-edge" });
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    const input = screen.getByPlaceholderText(/search memories/i);
    fireEvent.change(input, { target: { value: "meta" } });
    fireEvent.change(input, { target: { value: "metallb" } });

    await waitFor(() => {
      expect(searchApi.postRecall).toHaveBeenCalledWith("metallb", "byte-edge", 10);
    });
    // Debounce collapsed the intermediate keystroke — only the final query fired.
    expect(searchApi.postRecall).toHaveBeenCalledTimes(1);
  });

  // Companion to the debounce pin above (T5, deliberate): exact mode raises
  // the pool to 50 so a verbatim match ranked #11 semantically is findable.
  test("exact mode raises the recall limit to 50", async () => {
    useProjectStore.setState({ project: "byte-edge" });
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    const input = screen.getByPlaceholderText(/search memories/i);
    fireEvent.change(input, { target: { value: "metallb" } });
    await waitFor(() => {
      expect(searchApi.postRecall).toHaveBeenCalledWith("metallb", "byte-edge", 10);
    });

    fireEvent.click(screen.getByRole("button", { name: /^exact$/i }));
    await waitFor(() => {
      expect(searchApi.postRecall).toHaveBeenCalledWith("metallb", "byte-edge", 50);
    });
  });

  test("results render rows with type badge, content preview, and score", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(
      recallFixture as RecallResponse
    );
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByPlaceholderText(/search memories/i), {
      target: { value: "metallb" },
    });

    expect(
      await screen.findByText(/bare-metal load balancing/i)
    ).toBeInTheDocument();
    expect(screen.getByText("decision")).toBeInTheDocument();
    expect(screen.getByText("learning")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
    expect(screen.getByText("0.84")).toBeInTheDocument();
  });

  test("exact mode client-filters to case-insensitive verbatim substring matches", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(
      recallFixture as RecallResponse
    );
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.click(screen.getByRole("button", { name: /^exact$/i }));
    fireEvent.change(screen.getByPlaceholderText(/search memories/i), {
      // Mixed case on purpose — the filter must be case-insensitive.
      target: { value: "MemberList" },
    });

    expect(await screen.findByText(/memberlist secret/i)).toBeInTheDocument();
    // Semantically related but not a verbatim match — filtered out.
    expect(screen.queryByText(/bare-metal load balancing/i)).not.toBeInTheDocument();
  });

  test('exact mode empty state says "No exact matches in top 50"', async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(
      recallFixture as RecallResponse
    );
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.click(screen.getByRole("button", { name: /^exact$/i }));
    fireEvent.change(screen.getByPlaceholderText(/search memories/i), {
      target: { value: "qdrant" },
    });

    // Honest copy: the filter only saw the top 50 — not "no matches anywhere".
    expect(
      await screen.findByText(/no exact matches in top 50/i)
    ).toBeInTheDocument();
  });

  test("clicking a result opens the memory in the inspector", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(
      recallFixture as RecallResponse
    );
    vi.mocked(detailApi.getMemoryDetail).mockResolvedValue(
      detailV2Fixture as Awaited<ReturnType<typeof detailApi.getMemoryDetail>>
    );
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByPlaceholderText(/search memories/i), {
      target: { value: "metallb" },
    });

    fireEvent.click(await screen.findByText(/bare-metal load balancing/i));

    await waitFor(() => {
      expect(detailApi.getMemoryDetail).toHaveBeenCalledWith(
        "2026-07-10_decision_a1b2c3",
        undefined
      );
    });
    expect(await screen.findByText("Memory details")).toBeInTheDocument();
  });

  test("keyboard hints footer renders", () => {
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect(screen.getByText(/↑↓ navigate · ↵ open · esc close/)).toBeInTheDocument();
  });

  test("arrow keys move the highlight and Enter opens the highlighted memory", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(
      recallFixture as RecallResponse
    );
    vi.mocked(detailApi.getMemoryDetail).mockResolvedValue(
      detailV2Fixture as Awaited<ReturnType<typeof detailApi.getMemoryDetail>>
    );
    renderSearch();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByPlaceholderText(/search memories/i);
    fireEvent.change(input, { target: { value: "metallb" } });
    await screen.findByText(/bare-metal load balancing/i);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(detailApi.getMemoryDetail).toHaveBeenCalledWith(
        "2026-07-02_learning_d4e5f6",
        undefined
      );
    });
  });

  test("CockpitShell top bar renders the global search trigger", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CockpitShell>
          <div>page</div>
        </CockpitShell>
      </QueryClientProvider>
    );
    expect(
      screen.getByRole("button", { name: /search memories/i })
    ).toBeInTheDocument();
  });
});
