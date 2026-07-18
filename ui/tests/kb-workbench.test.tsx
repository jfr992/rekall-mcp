import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import KbPage from "@/app/kb/page";
import { useProjectStore } from "@/lib/project-store";
import * as searchApi from "@/lib/api/search";
import * as detailApi from "@/lib/api/detail";
import * as kbApi from "@/lib/api/kb";
import kbFixture from "./fixtures/kb.json";
import detailV2Fixture from "./fixtures/detail-v2.json";
import type { KbResponse, RecallResponse } from "@/lib/schemas";

vi.mock("@/lib/api/search");
vi.mock("@/lib/api/detail");
vi.mock("@/lib/api/kb");
// OkfExport fires its own publish query — stub it out of the page tests.
vi.mock("@/components/publish/okf-export", () => ({
  OkfExport: () => <div data-testid="okf-export" />,
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <KbPage />
    </QueryClientProvider>
  );
}

function daysAgo(n: number): string {
  const d = new Date(Date.now() - n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

const RESULTS: RecallResponse = {
  query: "error handling",
  count: 4,
  memories: [
    {
      memory_id: "m-dec-1",
      content: "Centralize API error handling in one middleware layer",
      type: "decision",
      tier: "semantic",
      date: daysAgo(2),
      project: "byte-edge",
      score: 0.94,
    },
    {
      memory_id: "m-dec-2",
      content: "Read-only observability only for the plugin v1",
      type: "decision",
      tier: "semantic",
      date: daysAgo(12),
      project: "byte-edge",
      score: 0.87,
    },
    {
      memory_id: "m-learn-1",
      content: "Structured logger pino is the sanctioned channel",
      type: "learning",
      tier: "episodic",
      date: daysAgo(45),
      project: "byte-edge",
      score: 0.81,
    },
    {
      memory_id: "m-pref-1",
      content: "Prefers explicit error types over exceptions",
      type: "preference",
      tier: "semantic",
      date: daysAgo(90),
      project: "byte-edge",
      score: 0.74,
    },
  ],
};

async function typeQuery(value = "error handling") {
  fireEvent.change(screen.getByRole("textbox", { name: /recall query/i }), {
    target: { value },
  });
  await screen.findByText(/centralize api error handling/i);
}

describe("KB recall workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectStore.setState({ project: "byte-edge" });
    vi.mocked(kbApi.getKb).mockResolvedValue(kbFixture as KbResponse);
    vi.mocked(searchApi.postRecall).mockResolvedValue({
      query: "",
      count: 0,
      memories: [],
    } satisfies RecallResponse);
  });

  test("Recall tab is default; switching to Curated shows the existing columns", async () => {
    renderPage();

    expect(screen.getByRole("button", { name: /^recall$/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("textbox", { name: /recall query/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^curated$/i }));

    expect(
      await screen.findByRole("heading", { name: /decisions/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /recall query/i })
    ).not.toBeInTheDocument();
  });

  test("typing fires one debounced recall scoped to the project with limit 30", async () => {
    renderPage();
    const input = screen.getByRole("textbox", { name: /recall query/i });

    fireEvent.change(input, { target: { value: "meta" } });
    fireEvent.change(input, { target: { value: "metallb" } });

    await waitFor(() => {
      expect(searchApi.postRecall).toHaveBeenCalledWith("metallb", "byte-edge", 30);
    });
    // Debounce collapsed the intermediate keystroke — only the final query fired.
    expect(searchApi.postRecall).toHaveBeenCalledTimes(1);
  });

  test("result cards render type badge, content, score, and date", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    const list = within(screen.getByRole("list", { name: /recall results/i }));
    expect(list.getAllByText("decision")).toHaveLength(2);
    expect(list.getByText("learning")).toBeInTheDocument();
    expect(list.getByText("0.94")).toBeInTheDocument();
    expect(list.getByText(daysAgo(2))).toBeInTheDocument();
    expect(
      list.getByText(/prefers explicit error types/i)
    ).toBeInTheDocument();
  });

  test("type facets show per-type counts; clicking toggles the filter and ALL resets", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    const rail = within(screen.getByRole("group", { name: /type facets/i }));
    expect(rail.getByRole("button", { name: /decision 2/i })).toBeInTheDocument();
    expect(rail.getByRole("button", { name: /learning 1/i })).toBeInTheDocument();

    fireEvent.click(rail.getByRole("button", { name: /decision 2/i }));

    const list = within(screen.getByRole("list", { name: /recall results/i }));
    expect(list.getByText(/centralize api error handling/i)).toBeInTheDocument();
    expect(list.queryByText(/pino is the sanctioned channel/i)).not.toBeInTheDocument();

    fireEvent.click(rail.getByRole("button", { name: /^all\b/i }));
    expect(list.getByText(/pino is the sanctioned channel/i)).toBeInTheDocument();
  });

  test("recency options filter results client-side by date", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    const rail = within(screen.getByRole("group", { name: /recency/i }));
    const list = within(screen.getByRole("list", { name: /recall results/i }));

    fireEvent.click(rail.getByRole("button", { name: /^7d$/i }));
    expect(list.getByText(/centralize api error handling/i)).toBeInTheDocument();
    expect(list.queryByText(/read-only observability/i)).not.toBeInTheDocument();

    fireEvent.click(rail.getByRole("button", { name: /^30d$/i }));
    expect(list.getByText(/read-only observability/i)).toBeInTheDocument();
    expect(list.queryByText(/pino is the sanctioned channel/i)).not.toBeInTheDocument();

    fireEvent.click(rail.getByRole("button", { name: /^all$/i }));
    expect(list.getByText(/prefers explicit error types/i)).toBeInTheDocument();
  });

  test("the pressed recency chip carries the accent pill treatment", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    const rail = within(screen.getByRole("group", { name: /recency/i }));
    const chip = rail.getByRole("button", { name: /^7d$/i });

    fireEvent.click(chip);

    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(chip.className).toContain("bg-[rgba(45,212,160,0.14)]");
    expect(chip.className).toContain("text-[var(--accent-primary)]");
    // the unpressed neighbour stays muted
    const all = rail.getByRole("button", { name: /^all$/i });
    expect(all.className).not.toContain("text-[var(--accent-primary)]");
  });

  test("count line reflects facet filters honestly", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    const countLine = () => screen.getByText(/results ·/).closest("p")!;
    expect(countLine()).toHaveTextContent("4 results · 4 shown");

    const rail = within(screen.getByRole("group", { name: /type facets/i }));
    fireEvent.click(rail.getByRole("button", { name: /decision 2/i }));

    expect(countLine()).toHaveTextContent("4 results · 2 shown");
  });

  test("count line's shown segment turns accent whenever a filter is active", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();
    await typeQuery();

    // no filter — neutral
    expect(screen.getByText("4 shown").className).not.toContain(
      "text-[var(--accent-primary)]"
    );

    // recency 30d keeps 2 of 4 — accent tracks the active filter
    const recency = within(screen.getByRole("group", { name: /recency/i }));
    fireEvent.click(recency.getByRole("button", { name: /^30d$/i }));
    expect(screen.getByText("2 shown").className).toContain(
      "text-[var(--accent-primary)]"
    );

    // back to all, then a type filter that excludes nothing: still accent
    fireEvent.click(recency.getByRole("button", { name: /^all$/i }));
    const facets = within(screen.getByRole("group", { name: /type facets/i }));
    fireEvent.click(facets.getByRole("button", { name: /decision 2/i }));
    expect(screen.getByText("2 shown").className).toContain(
      "text-[var(--accent-primary)]"
    );
  });

  test("clicking a card opens the memory in the inspector", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    vi.mocked(detailApi.getMemoryDetail).mockResolvedValue(
      detailV2Fixture as Awaited<ReturnType<typeof detailApi.getMemoryDetail>>
    );
    renderPage();
    await typeQuery();

    fireEvent.click(screen.getByText(/centralize api error handling/i));

    await waitFor(() => {
      expect(detailApi.getMemoryDetail).toHaveBeenCalledWith("m-dec-1", "byte-edge");
    });
    expect(await screen.findByText("Memory details")).toBeInTheDocument();
  });

  test("linked memories render from the detail endpoint only for the selected card", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    vi.mocked(detailApi.getMemoryDetail).mockResolvedValue(
      detailV2Fixture as Awaited<ReturnType<typeof detailApi.getMemoryDetail>>
    );
    renderPage();
    await typeQuery();

    const list = within(screen.getByRole("list", { name: /recall results/i }));
    // No detail fetches for the unselected list — no N+1.
    expect(detailApi.getMemoryDetail).not.toHaveBeenCalled();
    expect(list.queryByText(/superseder decision/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/centralize api error handling/i));

    expect(await list.findByText(/superseder decision/i)).toBeInTheDocument();
    expect(list.getByText(/dependency fact/i)).toBeInTheDocument();
    expect(list.getByText("0.80")).toBeInTheDocument();
    expect(detailApi.getMemoryDetail).toHaveBeenCalledTimes(1);
  });

  test("facet rail stays hidden until a query has loaded results", async () => {
    vi.mocked(searchApi.postRecall).mockResolvedValue(RESULTS);
    renderPage();

    // Empty query — no rail, and the prompt sits in the full content width.
    expect(
      screen.queryByRole("group", { name: /type facets/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: /recency/i })
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/type to recall/i).closest('[class*="grid-cols"]')
    ).toBeNull();

    await typeQuery();

    expect(screen.getByRole("group", { name: /type facets/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /recency/i })).toBeInTheDocument();
  });

  test("empty query shows a prompt and fires no recall", async () => {
    renderPage();

    expect(screen.getByText(/type to recall/i)).toBeInTheDocument();
    // Debounce window has to elapse before "no call" means anything.
    await new Promise((r) => setTimeout(r, 250));
    expect(searchApi.postRecall).not.toHaveBeenCalled();
  });

  test("a query with zero matches shows an honest empty state", async () => {
    renderPage();
    fireEvent.change(screen.getByRole("textbox", { name: /recall query/i }), {
      target: { value: "nonexistent thing" },
    });

    expect(await screen.findByText(/no matches/i)).toBeInTheDocument();
  });

  test("the heading eyebrow tracks the active tab", async () => {
    renderPage();
    expect(screen.getByText("RECALL · SEMANTIC SEARCH")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^curated$/i }));
    expect(screen.getByText("CURATED BY TYPE · LIVE")).toBeInTheDocument();
  });
});
