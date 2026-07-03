import { describe, test, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Drawer } from "@/components/ui/drawer";

describe("Drawer (accessible foundation)", () => {
  test("renders dialog with accessible name via ariaLabel", () => {
    render(
      <Drawer open ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    expect(
      screen.getByRole("dialog", { name: /memory details/i }),
    ).toBeInTheDocument();
  });

  test("renders dialog with accessible name via ariaLabelledBy", () => {
    render(
      <div>
        <h2 id="drawer-title">Memory details</h2>
        <Drawer open ariaLabelledBy="drawer-title" onClose={vi.fn()}>
          <p>content</p>
        </Drawer>
      </div>,
    );
    expect(
      screen.getByRole("dialog", { name: /memory details/i }),
    ).toBeInTheDocument();
  });

  test("focus moves to close button when drawer opens", async () => {
    render(
      <Drawer open ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    await waitFor(() => {
      expect(document.activeElement?.getAttribute("aria-label")).toBe(
        "Close drawer",
      );
    });
  });

  test("Escape key closes the drawer", async () => {
    const onClose = vi.fn();
    render(
      <Drawer open ariaLabel="Memory details" onClose={onClose}>
        <p>content</p>
      </Drawer>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  test("focus restores to trigger element on close", async () => {
    const user = userEvent.setup();
    function Wrapper() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          <Drawer
            open={open}
            ariaLabel="Memory details"
            onClose={() => setOpen(false)}
          >
            <p>content</p>
          </Drawer>
        </>
      );
    }
    render(<Wrapper />);
    const trigger = screen.getByText("Open");
    await user.click(trigger);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  test("Tab key is trapped within the drawer", async () => {
    const user = userEvent.setup();
    render(
      <Drawer open ariaLabel="Trap test" onClose={vi.fn()}>
        <button>Button A</button>
        <button>Button B</button>
      </Drawer>,
    );
    await waitFor(() => {
      expect(document.activeElement?.getAttribute("aria-label")).toBe(
        "Close drawer",
      );
    });
    const closeBtn = screen.getByLabelText("Close drawer");
    const btnA = screen.getByText("Button A");
    const btnB = screen.getByText("Button B");

    await user.tab();
    expect(document.activeElement).toBe(btnA);
    await user.tab();
    expect(document.activeElement).toBe(btnB);
    // Tab at last should cycle back to first
    await user.tab();
    expect(document.activeElement).toBe(closeBtn);
  });

  test("Shift+Tab is trapped within the drawer", async () => {
    const user = userEvent.setup();
    render(
      <Drawer open ariaLabel="Trap test" onClose={vi.fn()}>
        <button>Only button</button>
      </Drawer>,
    );
    await waitFor(() => {
      expect(document.activeElement?.getAttribute("aria-label")).toBe(
        "Close drawer",
      );
    });
    // Shift+Tab from first focusable should cycle to last
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByText("Only button"));
  });

  test("background scroll is locked when drawer is open", () => {
    render(
      <Drawer open ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    expect(document.body.style.overflow).toBe("hidden");
  });

  test("scroll lock is released when drawer closes", () => {
    const { rerender } = render(
      <Drawer open ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    rerender(
      <Drawer open={false} ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  test("close button has 44px minimum touch target", () => {
    render(
      <Drawer open ariaLabel="Memory details" onClose={vi.fn()}>
        <p>content</p>
      </Drawer>,
    );
    const closeBtn = screen.getByLabelText("Close drawer");
    expect(closeBtn.className).toMatch(/h-11/);
    expect(closeBtn.className).toMatch(/w-11/);
  });
});
