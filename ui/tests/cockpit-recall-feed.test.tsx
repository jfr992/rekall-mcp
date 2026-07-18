import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RecallFeed } from "@/components/cockpit/recall-feed";
import type { StreamRow } from "@/lib/schemas";
import streamFixture from "./fixtures/stream.json";

const rows = streamFixture.rows as StreamRow[];

describe("RecallFeed", () => {
  test("derives recalled rows from the stream rows — query, hits count, top score, HH:MM time", () => {
    render(<RecallFeed rows={rows} misses7d={3} onSelect={vi.fn()} />);
    expect(screen.getByText("how did we fix the rrf filter")).toBeInTheDocument();
    expect(screen.getByText("nothing matches this")).toBeInTheDocument();
    expect(screen.getByText("09:05")).toBeInTheDocument();
    expect(screen.getByText("0.87")).toBeInTheDocument();
    expect(screen.getByText("1 hit")).toBeInTheDocument();
    // non-recalled kinds are not part of the feed
    expect(screen.queryByText(/compose build needs network egress/)).not.toBeInTheDocument();
  });

  test("miss rows (empty hits) are highlighted", () => {
    render(<RecallFeed rows={rows} misses7d={3} onSelect={vi.fn()} />);
    const missRow = screen.getByText("nothing matches this").closest("[data-miss]");
    expect(missRow).not.toBeNull();
    const hitRow = screen.getByText("how did we fix the rrf filter").closest("[data-miss]");
    expect(hitRow).toBeNull();
  });

  test("rows without a query render a human origin label instead of a dash", () => {
    const originRows: StreamRow[] = [
      {
        kind: "recalled",
        at: "2026-07-17T10:00:00.000001",
        payload: {
          query: null,
          memory_ids: ["2026-07-01_learning_ff00aa11"],
          top_score: 0.7,
          project: "rekall-mcp",
          capture_origin: "capsule",
        },
      },
      {
        kind: "recalled",
        at: "2026-07-17T10:01:00.000001",
        payload: {
          query: null,
          memory_ids: [],
          top_score: null,
          project: "rekall-mcp",
          capture_origin: "session_start",
        },
      },
      {
        kind: "recalled",
        at: "2026-07-17T10:02:00.000001",
        payload: {
          query: null,
          memory_ids: [],
          top_score: null,
          project: "rekall-mcp",
          capture_origin: "some_future_origin",
        },
      },
    ];
    render(<RecallFeed rows={originRows} misses7d={0} onSelect={vi.fn()} />);
    expect(screen.getByText("capsule")).toBeInTheDocument();
    expect(screen.getByText("session start")).toBeInTheDocument();
    expect(screen.getByText("background recall")).toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  test("scoped feed with zero recalls explains how attribution works", () => {
    render(<RecallFeed rows={[]} misses7d={0} onSelect={vi.fn()} scoped />);
    expect(
      screen.getByText(
        "No recalls in this scope yet — recalls attribute to a project when the agent passes its working directory"
      )
    ).toBeInTheDocument();
  });

  test("unscoped feed with zero recalls keeps the generic empty state", () => {
    render(<RecallFeed rows={[]} misses7d={0} onSelect={vi.fn()} />);
    expect(screen.queryByText(/No recalls in this scope yet/)).not.toBeInTheDocument();
  });

  test("footer shows the 7d miss count from insights", () => {
    render(<RecallFeed rows={rows} misses7d={3} onSelect={vi.fn()} />);
    expect(screen.getByText("3 misses · 7d")).toBeInTheDocument();
  });

  test("clicking a hit row opens the inspector for its top memory; miss rows do not", () => {
    const onSelect = vi.fn();
    render(<RecallFeed rows={rows} misses7d={3} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("how did we fix the rrf filter"));
    expect(onSelect).toHaveBeenCalledWith("2026-07-01_learning_ff00aa11");
    onSelect.mockClear();
    fireEvent.click(screen.getByText("nothing matches this"));
    expect(onSelect).not.toHaveBeenCalled();
  });

  test("caps at 8 rows and links to /stream instead of expanding", () => {
    const many: StreamRow[] = Array.from({ length: 12 }, (_, i) => ({
      kind: "recalled",
      at: `2026-07-17T10:${String(i).padStart(2, "0")}:00.000001`,
      payload: {
        query: `query number ${i}`,
        memory_ids: ["m1"],
        top_score: 0.8,
        project: "rekall-mcp",
        capture_origin: "recall",
      },
    }));
    render(<RecallFeed rows={many} misses7d={0} onSelect={vi.fn()} />);

    expect(screen.getByText("query number 7")).toBeInTheDocument();
    expect(screen.queryByText("query number 8")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "View all in Stream →" });
    expect(link).toHaveAttribute("href", "/stream");
    expect(
      screen.queryByRole("button", { name: /show \d+ more/i })
    ).not.toBeInTheDocument();
  });
});
