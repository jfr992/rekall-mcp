import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PressureExplainer } from "@/components/hygiene/pressure-explainer";
import type { PressureResponse } from "@/lib/schemas";

const base = {
  load_score: 0.1,
  flagged: { stale_working_count: 30, low_value_count: 20, prune_candidates_count: 34 },
} as unknown as PressureResponse;

describe("PressureExplainer", () => {
  test("counts prune candidates once when low-value and stale overlap", () => {
    render(<PressureExplainer data={base} />);
    expect(screen.getByText(/34 memories are candidates for prune/)).toBeInTheDocument();
  });

  test("falls back to low + stale for older servers", () => {
    const old = { ...base, flagged: { stale_working_count: 3, low_value_count: 2 } } as unknown as PressureResponse;
    render(<PressureExplainer data={old} />);
    expect(screen.getByText(/5 memories are candidates for prune/)).toBeInTheDocument();
  });
});
