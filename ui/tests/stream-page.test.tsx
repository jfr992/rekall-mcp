import { describe, test, expect, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";

// Module-level mocks must precede import of the component under test
vi.mock("@/lib/project-store", () => ({
  useProjectStore: vi.fn((sel: any) => sel({ project: "rekall-mcp", setProject: vi.fn() })),
}));

vi.mock("@/lib/queries/use-stream", () => ({
  useStream: vi.fn(),
}));

vi.mock("@/lib/queries/use-insights", () => ({
  useInsights: vi.fn(),
}));

vi.mock("@/lib/queries/use-pressure", () => ({
  usePressure: vi.fn(),
}));

import { useStream } from "@/lib/queries/use-stream";
import { useInsights } from "@/lib/queries/use-insights";
import { usePressure } from "@/lib/queries/use-pressure";
import StreamPage from "@/app/stream/page";
import streamFixture from "./fixtures/stream.json";
import insightsFixture from "./fixtures/insights.json";
import pressureFixture from "./fixtures/pressure.json";

function loaded(data: unknown) {
  return { data, isLoading: false, isError: false } as any;
}

function mockAll({ stream = streamFixture }: { stream?: unknown } = {}) {
  vi.mocked(useStream).mockReturnValue(loaded(stream));
  vi.mocked(useInsights).mockReturnValue(loaded(insightsFixture));
  vi.mocked(usePressure).mockReturnValue(loaded(pressureFixture));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("StreamPage — ladder markers", () => {
  test("shows the promotions marker and the decay queue note linking to /hygiene", () => {
    mockAll();
    render(<StreamPage />);
    expect(screen.getByText(/2 promoted \(7d\)/)).toBeInTheDocument();
    // decay note from pressure.flagged.stale_working_count
    expect(screen.getByText(/DECAY QUEUE/)).toBeInTheDocument();
    expect(screen.getByText(/8 working memories decaying/)).toBeInTheDocument();
    const review = screen.getByRole("link", { name: /review/i });
    expect(review).toHaveAttribute("href", "/hygiene");
  });
});

describe("StreamPage — timeline rows", () => {
  test("renders a saved row with type + tier badges, content, and strength bar", () => {
    mockAll();
    render(<StreamPage />);
    expect(
      screen.getByText(/compose build needs network egress for next\/font/)
    ).toBeInTheDocument();
    expect(screen.getAllByText("note").length).toBeGreaterThan(0);
    expect(screen.getAllByText("working").length).toBeGreaterThan(0);
    expect(screen.getByText(/strength/)).toBeInTheDocument();
  });

  test("renders recalled rows: query → surfaced count with top match, misses without", () => {
    mockAll();
    render(<StreamPage />);
    expect(screen.getByText(/how did we fix the rrf filter/)).toBeInTheDocument();
    expect(screen.getByText(/1 memory surfaced, top match 0\.87/)).toBeInTheDocument();
    expect(screen.getByText(/nothing matches this/)).toBeInTheDocument();
    expect(screen.getByText(/0 memories surfaced/)).toBeInTheDocument();
  });

  test("renders a promoted row with PROMOTED label and from → to tier", () => {
    mockAll();
    render(<StreamPage />);
    expect(screen.getByText("PROMOTED")).toBeInTheDocument();
    expect(screen.getByText(/working → semantic/)).toBeInTheDocument();
  });

  test("renders a consolidated row with CONSOLIDATED label and summary text", () => {
    mockAll();
    render(<StreamPage />);
    expect(screen.getByText("CONSOLIDATED")).toBeInTheDocument();
    expect(
      screen.getByText(/Summary of 6 stale working notes about the compose migration/)
    ).toBeInTheDocument();
  });
});

describe("StreamPage — loading and error", () => {
  test("shows an error empty-state when the stream query fails", () => {
    vi.mocked(useStream).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as any);
    vi.mocked(useInsights).mockReturnValue(loaded(insightsFixture));
    vi.mocked(usePressure).mockReturnValue(loaded(pressureFixture));
    render(<StreamPage />);
    expect(screen.getByText(/Could not load stream/)).toBeInTheDocument();
  });
});

describe("StreamPage — empty state", () => {
  test("shows the no-activity message when the stream has no rows", () => {
    mockAll({ stream: { rows: [], event_window: { events: 0, oldest_at: null } } });
    render(<StreamPage />);
    expect(screen.getByText(/No activity yet/)).toBeInTheDocument();
    expect(screen.getByText(/memories and recalls appear here as they happen/i)).toBeInTheDocument();
  });
});

describe("StreamPage — decaying rows", () => {
  test("dims working-tier saved rows that have fades_in_hours and shows the fade note", () => {
    mockAll();
    render(<StreamPage />);
    const note = screen.getByText(/fades in 311h/);
    const row = note.closest('[data-decaying="true"]');
    expect(row).not.toBeNull();
    expect(row!.className).toContain("opacity-45");
    // display only — no keep/reinforce button
    expect(screen.queryByRole("button", { name: /keep/i })).not.toBeInTheDocument();
  });
});

describe("StreamPage — day grouping", () => {
  test("groups rows under TODAY · <date>, YESTERDAY, then dated headers, newest first", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-17T12:00:00"));
    mockAll();
    render(<StreamPage />);
    expect(screen.getByText("TODAY · JUL 17")).toBeInTheDocument();
    expect(screen.getByText("YESTERDAY")).toBeInTheDocument();
    expect(screen.getByText("JUL 15")).toBeInTheDocument();
  });
});

describe("StreamPage — consolidation ladder", () => {
  test("renders one card per tier with counts from insights and the design taglines", () => {
    mockAll();
    render(<StreamPage />);
    const ladder = within(screen.getByRole("complementary", { name: /consolidation ladder/i }));
    // counts from insights.tier_counts
    expect(ladder.getByText("identity").parentElement).toHaveTextContent("2");
    expect(ladder.getByText("semantic").parentElement).toHaveTextContent("9");
    expect(ladder.getByText("episodic").parentElement).toHaveTextContent("18");
    expect(ladder.getByText("working").parentElement).toHaveTextContent("12");
    // taglines per the design source
    expect(ladder.getByText("who you are · never decays")).toBeInTheDocument();
    expect(ladder.getByText("distilled knowledge")).toBeInTheDocument();
    expect(ladder.getByText("events & sessions")).toBeInTheDocument();
    expect(ladder.getByText("volatile · decays in days")).toBeInTheDocument();
  });
});
