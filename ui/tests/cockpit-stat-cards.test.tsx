import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatCards } from "@/components/cockpit/stat-cards";
import type { InsightsResponse, PressureResponse } from "@/lib/schemas";
import insightsFixture from "./fixtures/insights.json";
import pressureFixture from "./fixtures/pressure.json";

const insights = insightsFixture as InsightsResponse;
const pressure = pressureFixture as PressureResponse;

describe("StatCards", () => {
  test("total card shows total, weekly delta, and an inline-SVG sparkline from per_week", () => {
    render(<StatCards insights={insights} pressure={pressure} />);
    expect(screen.getByText("132")).toBeInTheDocument();
    expect(screen.getByText("+6 this week")).toBeInTheDocument();
    const sparkline = screen.getByTestId("sparkline");
    expect(sparkline.tagName.toLowerCase()).toBe("svg");
    expect(sparkline.querySelector("path")).not.toBeNull();
  });

  test("recalls card shows recalls_7d and avg top match with the denominator in a tooltip", () => {
    render(<StatCards insights={insights} pressure={pressure} />);
    expect(screen.getByText("23")).toBeInTheDocument();
    const avg = screen.getByText("0.84");
    expect(avg).toBeInTheDocument();
    // honest denominator: mean over recalls that had >= 1 numeric score
    expect(avg.closest("[title]")?.getAttribute("title")).toMatch(
      /19 scored recalls/,
    );
  });

  test("recalls-with-hits card shows the percentage labeled 'recalls with hits' (never 'hit rate')", () => {
    const { container } = render(
      <StatCards insights={insights} pressure={pressure} />,
    );
    // 20 of 23 recalls surfaced at least one memory → 87%
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getAllByText(/recalls with hits/i).length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/hit rate/i);
  });

  test("needs-attention card counts prune candidates once and renders the breakdown", () => {
    render(<StatCards insights={insights} pressure={pressure} />);
    // 12 prune (low and stale overlap) + 1 conflict + 1 disputed + 1 stale_candidate = 15
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText(/needs attention/i)).toBeInTheDocument();
    expect(
      screen.getByText("prune 12 \u00b7 conflict 1 \u00b7 disputed 1"),
    ).toBeInTheDocument();
  });

  test("falls back to low + stale when an older server omits prune_candidates_count, omitting zero parts", () => {
    const legacy = {
      ...pressure,
      flagged: {
        ...pressure.flagged,
        prune_candidates_count: undefined,
        contradiction_count: 0,
        disputed_count: 0,
        stale_candidates_count: 0,
      },
    } as PressureResponse;
    render(<StatCards insights={insights} pressure={legacy} />);
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("prune 18")).toBeInTheDocument();
  });
});
