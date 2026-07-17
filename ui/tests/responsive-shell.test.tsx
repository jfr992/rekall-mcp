/**
 * Responsive-shell: vitest/jsdom class-presence assertions for the top-nav shell.
 * Full browser run (390×844 viewport, overflow check) lives in e2e/responsive-shell.spec.ts.
 */
import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CockpitShell } from "@/components/shell/cockpit-shell";

// Stub children that make network calls
vi.mock("@/components/shell/project-switcher", () => ({
  ProjectSwitcher: () => <div data-testid="project-switcher" />,
}));
vi.mock("@/components/shell/health-badge", () => ({
  HealthBadge: () => <div data-testid="health-badge" />,
}));
vi.mock("@/components/shell/global-search", () => ({
  GlobalSearch: () => <button data-testid="global-search" />,
}));
vi.mock("@/lib/queries/use-insights", () => ({
  useInsights: () => ({ data: { in_scope: 12, total: 87 } }),
}));

describe("CockpitShell (top-nav)", () => {
  test("top bar is sticky with backdrop blur", () => {
    const { container } = render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const header = container.querySelector("header");
    expect(header).not.toBeNull();
    expect(header!.className).toMatch(/\bsticky\b/);
    expect(header!.className).toMatch(/top-0/);
    expect(header!.className).toMatch(/backdrop-blur/);
  });

  test("primary nav keeps aria-label and links all six surfaces", () => {
    render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBeInTheDocument();
    const links: Array<[string, string]> = [
      ["Cockpit", "/brain"],
      ["Knowledge Base", "/kb"],
      ["Stream", "/stream"],
      ["Sessions", "/sessions"],
      ["Hygiene", "/hygiene"],
      ["Continuity", "/continuity"],
    ];
    for (const [label, href] of links) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  test("tab row scrolls horizontally at narrow widths instead of overflowing the body", () => {
    render(
      <CockpitShell>
        <div>page content</div>
      </CockpitShell>,
    );
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // overflow-x-auto + nowrap = tabs scroll inside the bar at 390px
    expect(nav.className).toMatch(/overflow-x-auto/);
    expect(nav.className).toMatch(/whitespace-nowrap/);
    // min-w-0 lets the flex row shrink instead of forcing body overflow
    expect(nav.className).toMatch(/min-w-0/);
  });

  test("scope counts render from insights but collapse on mobile; content renders inside main", () => {
    const { container } = render(
      <CockpitShell>
        <div>Hello World</div>
      </CockpitShell>,
    );
    const counts = screen.getByText(/12 in scope · 87 total/);
    expect(counts.className).toMatch(/\bhidden\b/);
    expect(counts.className).toMatch(/lg:inline|lg:block|lg:flex/);

    const main = container.querySelector("main");
    expect(main).not.toBeNull();
    expect(main!.className).toMatch(/min-w-0/);
    expect(screen.getByText("Hello World").closest("main")).toBe(main);
  });
});
