import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Timeline } from "@/components/stream/timeline";
import type { StreamRow } from "@/lib/schemas";

function savedRow(at: string, id: string): StreamRow {
  return {
    kind: "saved",
    at,
    payload: {
      memory_id: id,
      type: "note",
      tier: "working",
      project: "rekall-mcp",
      preview: `preview ${id}`,
      durability: 0.5,
      fades_in_hours: null,
    },
  };
}

function manyRowsOneDay(n: number): StreamRow[] {
  return Array.from({ length: n }, (_, i) => {
    const minute = String(n - i).padStart(2, "0");
    return savedRow(`2026-07-17T10:${minute}:00.000001`, `id${i}`);
  });
}

describe("Timeline — per-day collapse", () => {
  test("a day with more than 20 rows shows only the first 20 plus a Show N more from this day button", () => {
    render(<Timeline rows={manyRowsOneDay(25)} />);
    expect(screen.getByText(/preview id19/)).toBeInTheDocument();
    expect(screen.queryByText(/preview id20/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show 5 more from this day" })
    ).toBeInTheDocument();
  });
});
