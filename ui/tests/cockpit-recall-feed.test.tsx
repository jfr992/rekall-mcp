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
});
