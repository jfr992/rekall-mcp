/**
 * Responsive-shell: vitest/jsdom class-presence assertions.
 * Full browser run (390×844 viewport, overflow check) lives in e2e/responsive-shell.spec.ts.
 */
import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CockpitShell } from "@/components/shell/cockpit-shell";

// Stub child components that make network calls
vi.mock("@/components/shell/project-switcher", () => ({
  ProjectSwitcher: () => <div data-testid="project-switcher" />,
}));
vi.mock("@/components/shell/health-badge", () => ({
  HealthBadge: () => <div data-testid="health-badge" />,
}));
vi.mock("@/components/shell/header-bar", () => ({
  HeaderBar: () => <div data-testid="header-bar" />,
}));
vi.mock("@/components/ui/serif-heading", () => ({
  SerifHeading: ({ title }: { title: string }) => <span>{title}</span>,
}));

describe("CockpitShell (responsive)", () => {
  test("desktop sidebar has hidden class for mobile and md:flex for desktop", () => {
    const { container } = render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const sidebar = container.querySelector("aside");
    expect(sidebar).not.toBeNull();
    // hidden: invisible on mobile; md:flex: visible from md breakpoint up
    expect(sidebar!.className).toMatch(/\bhidden\b/);
    expect(sidebar!.className).toMatch(/md:flex/);
  });

  test("mobile top bar is visible on small screens (md:hidden)", () => {
    const { container } = render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const mobileHeader = container.querySelector("header");
    expect(mobileHeader).not.toBeNull();
    expect(mobileHeader!.className).toMatch(/md:hidden/);
  });

  test("main content wrapper has min-w-0 to prevent sidebar squeezing on mobile", () => {
    const { container } = render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const mainWrapper = container.querySelector("main")?.parentElement;
    expect(mainWrapper).not.toBeNull();
    expect(mainWrapper!.className).toMatch(/min-w-0/);
  });

  test("renders page content inside main", () => {
    render(
      <CockpitShell>
        <div>Hello World</div>
      </CockpitShell>,
    );
    expect(screen.getByText("Hello World")).toBeInTheDocument();
  });
});
