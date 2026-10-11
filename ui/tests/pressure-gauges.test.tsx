import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PressureGauges } from "@/components/hygiene/pressure-gauges";
import pressureFixture from "./fixtures/pressure.json";
import { PressureResponseSchema } from "@/lib/schemas";

describe("PressureGauges", () => {
  test("renders load, capacity, flagged from fixture", () => {
    const data = PressureResponseSchema.parse(pressureFixture);
    render(<PressureGauges data={data} />);
    expect(screen.getByText(/147/)).toBeInTheDocument();
    expect(screen.getByText(/0\.12/)).toBeInTheDocument();
  });

  test("flagged matches the Cockpit needs-attention number", () => {
    const data = PressureResponseSchema.parse(pressureFixture);
    render(<PressureGauges data={data} />);
    const card = screen.getByText(/flagged/i).parentElement!;
    expect(card.textContent).toContain("15");
    expect(card.textContent).not.toContain("19");
  });

  test("empty scope shows capacity 0", () => {
    const data = { ...PressureResponseSchema.parse(pressureFixture), capacity: 0 };
    render(<PressureGauges data={data} />);
    expect(screen.getByText("empty")).toBeInTheDocument();
  });
});
