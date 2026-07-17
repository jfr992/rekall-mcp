import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TierComposition } from "@/components/cockpit/tier-composition";
import type { InsightsResponse } from "@/lib/schemas";
import insightsFixture from "./fixtures/insights.json";

const insights = insightsFixture as InsightsResponse;

describe("TierComposition", () => {
  test("renders a stacked bar segment and a count for every tier", () => {
    render(<TierComposition insights={insights} />);
    const bar = screen.getByTestId("tier-bar");
    expect(bar.children).toHaveLength(4);
    for (const tier of ["working", "episodic", "semantic", "identity"]) {
      expect(screen.getByText(tier)).toBeInTheDocument();
    }
    // counts from tier_counts fixture
    expect(screen.getByText("12")).toBeInTheDocument(); // working
    expect(screen.getByText("18")).toBeInTheDocument(); // episodic
    expect(screen.getByText("9")).toBeInTheDocument(); // semantic
    expect(screen.getByText("2")).toBeInTheDocument(); // identity
  });

  test("renders the exact promotions vs episodics line", () => {
    render(<TierComposition insights={insights} />);
    expect(
      screen.getByText("2 promotions · 4 episodic memories created (7d)")
    ).toBeInTheDocument();
  });
});
