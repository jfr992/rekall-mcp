import { describe, test, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BrainPage from "@/app/brain/page";

vi.mock("react-force-graph-2d", () => ({
  default: () => <div data-testid="force-graph-2d">mock-force-graph</div>,
}));

vi.mock("@/lib/api/insights", async () => {
  const fixture = (await import("./fixtures/insights.json")).default;
  return { getInsights: vi.fn().mockResolvedValue(fixture) };
});

vi.mock("@/lib/api/stream", async () => {
  const fixture = (await import("./fixtures/stream.json")).default;
  return { getStream: vi.fn().mockResolvedValue(fixture) };
});

vi.mock("@/lib/api/pressure", async () => {
  const fixture = (await import("./fixtures/pressure.json")).default;
  return { getPressure: vi.fn().mockResolvedValue(fixture) };
});

vi.mock("@/lib/api/graph", async () => {
  const fixture = (await import("./fixtures/graph.json")).default;
  return { getGraph: vi.fn().mockResolvedValue(fixture) };
});

vi.mock("@/lib/api/detail", async () => {
  const fixture = (await import("./fixtures/detail-v2.json")).default;
  return { getMemoryDetail: vi.fn().mockResolvedValue(fixture) };
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BrainPage />
    </QueryClientProvider>
  );
}

describe("Cockpit dashboard page", () => {
  test("renders every panel from the fixtures — cards, tiers, feed, graph, hygiene, node list", async () => {
    renderPage();
    // stat cards
    expect(await screen.findByText("132")).toBeInTheDocument();
    expect(screen.getByText("+6 this week")).toBeInTheDocument();
    // tier composition
    expect(screen.getByTestId("tier-bar")).toBeInTheDocument();
    expect(
      screen.getByText("2 promotions · 4 episodic memories created (7d)")
    ).toBeInTheDocument();
    // live recall feed from the stream cache
    expect(screen.getByText("how did we fix the rrf filter")).toBeInTheDocument();
    expect(screen.getByText("3 misses · 7d")).toBeInTheDocument();
    // graph panel + a11y node list carry
    expect(await screen.findByTestId("force-graph-2d")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use Go over Rust/i })).toBeInTheDocument();
    // hygiene queue
    expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute("href", "/hygiene");
  });

  test("miss rows are highlighted and the sparkline path renders from the fixture", async () => {
    renderPage();
    const missQuery = await screen.findByText("nothing matches this");
    expect(missQuery.closest("[data-miss]")).not.toBeNull();
    const sparkline = screen.getByTestId("sparkline");
    const path = sparkline.querySelector("path");
    expect(path?.getAttribute("d")).toMatch(/^M/);
  });

  test("clicking a feed hit row opens the memory inspector", async () => {
    renderPage();
    const row = await screen.findByText("how did we fix the rrf filter");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(row);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  test("live recall feed tile never expands — it caps rows and links out to Stream", async () => {
    renderPage();
    await screen.findByText("how did we fix the rrf filter");
    expect(
      screen.queryByRole("button", { name: /show \d+ more/i })
    ).not.toBeInTheDocument();
  });
});
