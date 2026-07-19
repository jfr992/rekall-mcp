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
    expect(avg.closest("[title]")?.getAttribute("title")).toMatch(/19 scored recalls/);
  });

  test("recalls-with-hits card shows the percentage labeled 'recalls with hits' (never 'hit rate')", () => {
    const { container } = render(<StatCards insights={insights} pressure={pressure} />);
    // 20 of 23 recalls surfaced at least one memory → 87%
    expect(screen.getByText("87%")).toBeInTheDocument();
    expect(screen.getAllByText(/recalls with hits/i).length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/hit rate/i);
  });

  test("needs-attention card sums pressure flagged counts with a breakdown, including disputed and stale_candidates (T5)", () => {
    render(<StatCards insights={insights} pressure={pressure} />);
    // 8 stale + 10 low + 1 conflict + 1 disputed + 1 stale_candidate = 21
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(screen.getByText(/needs attention/i)).toBeInTheDocument();
    expect(screen.getByText(/stale 8/)).toBeInTheDocument();
    expect(screen.getByText(/low 10/)).toBeInTheDocument();
    expect(screen.getByText(/conflict 1/)).toBeInTheDocument();
  });
});
