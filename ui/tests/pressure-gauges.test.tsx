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
});
