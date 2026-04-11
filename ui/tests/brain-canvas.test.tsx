import { describe, test, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { BrainCanvas } from "@/components/brain/brain-canvas";

vi.mock("react-force-graph-2d", () => ({
  default: (props: any) => (
    <div
      data-testid="force-graph-2d"
      onClick={() => props.onNodeClick?.({ id: "m1" })}
    >
      mock-force-graph
    </div>
  ),
}));

describe("BrainCanvas", () => {
  test("renders without crashing on empty graph", () => {
    const { container } = render(<BrainCanvas nodes={[]} links={[]} onNodeClick={vi.fn()} />);
    expect(container).toBeTruthy();
  });

  test("calls onNodeClick with memory id when a node is clicked", async () => {
    const handler = vi.fn();
    const { getByTestId } = render(
      <BrainCanvas
        nodes={[{ id: "m1", type: "decision", content: "test", tier: "semantic" }]}
        links={[]}
        onNodeClick={handler}
      />
    );
    getByTestId("force-graph-2d").click();
    expect(handler).toHaveBeenCalledWith("m1");
  });
});
