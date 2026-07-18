import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SessionList } from "@/components/sessions/session-list";
import type { SessionRow } from "@/lib/schemas";

const SESSIONS: SessionRow[] = [
  {
    session_id: "sess-abc123",
    project: "rekall-mcp",
    started_at: "2026-07-14T09:00:00+00:00",
    last_at: "2026-07-14T09:45:00+00:00",
    totals: { recalls: 2, injected: 3, tokens: 1450 },
  },
];

describe("SessionList", () => {
  test("each row packs project into the same meta line as totals — a single meta line, not two", () => {
    render(<SessionList sessions={SESSIONS} selectedId={null} onSelect={vi.fn()} />);
    const row = screen.getByText(/sess-abc123/).closest("button")!;
    const metaLines = row.querySelectorAll("[data-meta-line]");
    expect(metaLines).toHaveLength(1);
    expect(metaLines[0]).toHaveTextContent("rekall-mcp");
    expect(metaLines[0]).toHaveTextContent("2 recalls");
  });
});
