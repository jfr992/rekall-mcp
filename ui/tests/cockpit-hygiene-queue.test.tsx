import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HygieneQueue } from "@/components/cockpit/hygiene-queue";
import type { PressureResponse } from "@/lib/schemas";
import pressureFixture from "./fixtures/pressure.json";

const pressure = pressureFixture as PressureResponse;

describe("HygieneQueue", () => {
  test("shows stale/low/conflict flagged counts and links to /hygiene", () => {
    render(<HygieneQueue pressure={pressure} />);
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText(/working memories decaying/)).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText(/low-value/)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText(/contradictions detected/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /review/i });
    expect(link).toHaveAttribute("href", "/hygiene");
  });
});
