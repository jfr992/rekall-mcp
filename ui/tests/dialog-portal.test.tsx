import { describe, test, expect } from "vitest";
import { render } from "@testing-library/react";
import { Dialog } from "@/components/ui/dialog";

describe("Dialog", () => {
  test("renders as a portal into document.body so transformed ancestors cannot trap fixed positioning", () => {
    const { container } = render(
      <div style={{ transform: "translateZ(0)" }}>
        <Dialog open onClose={() => {}} title="t">
          <p>content</p>
        </Dialog>
      </div>
    );
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
  });
});
