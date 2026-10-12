import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PruneApplyGate } from "@/components/hygiene/prune-apply-gate";

describe("PruneApplyGate copy", () => {
  test("says paste is allowed", () => {
    render(
      <PruneApplyGate planId="plan-1" candidateCount={2} expired={false} loading={false} onRequestApply={vi.fn()} />
    );
    expect(screen.getByText(/type or paste the full plan id/i)).toBeInTheDocument();
    expect(screen.queryByText(/paranoid/i)).not.toBeInTheDocument();
  });
});
