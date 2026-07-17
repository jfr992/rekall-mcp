import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrainCanvas } from "@/components/brain/brain-canvas";

let captured: Record<string, unknown> = {};
let capturedWidths: number[] = [];

vi.mock("react-force-graph-2d", () => ({
  default: (props: Record<string, unknown>) => {
    captured = props;
    capturedWidths.push(props.width as number);
    return <div data-testid="force-graph-2d">mock-force-graph</div>;
  },
}));

const nodes = [
  { id: "m1", type: "decision", content: "a", tier: "semantic", position: { x: 1, y: 0 } },
  { id: "m2", type: "note", content: "b", tier: "working", position: { x: -1, y: 0 } },
];

describe("BrainCanvas panel mode", () => {
  test("particles={false} disables link directional particles", async () => {
    render(
      <BrainCanvas nodes={nodes} links={[]} onNodeClick={vi.fn()} particles={false} />
    );
    await screen.findByTestId("force-graph-2d");
    expect(captured.linkDirectionalParticles).toBe(0);
  });

  test("particles default on when prop omitted", async () => {
    render(<BrainCanvas nodes={nodes} links={[]} onNodeClick={vi.fn()} />);
    await screen.findByTestId("force-graph-2d");
    expect(captured.linkDirectionalParticles).toBeGreaterThan(0);
  });

  test("padding is proportional — max(24, 10% of dimension), not hardcoded 100", async () => {
    render(<BrainCanvas nodes={nodes} links={[]} onNodeClick={vi.fn()} />);
    await screen.findByTestId("force-graph-2d");
    // jsdom container measures 0x0 → fallback dims 900x650.
    // padX = max(24, 90) = 90, padY = max(24, 65) = 65
    // scale = min(900-180, 650-130) / 2 = 260 (old hardcoded pad=100 gave 225)
    const data = captured.graphData as { nodes: Array<{ fx: number }> };
    const xs = data.nodes.map((n) => Math.abs(n.fx));
    expect(Math.max(...xs)).toBeCloseTo(260, 5);
  });

  test("initial dims come from the container when measurable — never the 900x650 fallback", async () => {
    capturedWidths = [];
    const rect = { width: 300, height: 200, top: 0, left: 0, right: 300, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    const spy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue(rect);
    try {
      render(<BrainCanvas nodes={nodes} links={[]} onNodeClick={vi.fn()} />);
      await screen.findByTestId("force-graph-2d");
    } finally {
      spy.mockRestore();
    }
    expect(captured.width).toBe(300);
    expect(capturedWidths).not.toContain(900);
  });
});
