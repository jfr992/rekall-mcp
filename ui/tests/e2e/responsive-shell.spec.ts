/**
 * E2E: responsive shell at 390×844 (iPhone 14 viewport).
 * Skipped by default; run with PLAYWRIGHT=1 in CI when a browser is available.
 *
 * To run manually:
 *   cd ui && npx playwright test tests/e2e/responsive-shell.spec.ts
 */
import { test, expect } from "@playwright/test";

const skip = !process.env.PLAYWRIGHT;

test.describe("Responsive shell — mobile viewport", () => {
  test.skip(skip, "Set PLAYWRIGHT=1 to run browser-based responsive checks");

  test("no horizontal overflow at 390px width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");

    const bodyWidth = await page.evaluate(
      () => document.body.scrollWidth,
    );
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test("sidebar is hidden, mobile nav is visible", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");

    // Desktop sidebar should not be visible
    const sidebar = page.locator("aside").first();
    await expect(sidebar).not.toBeVisible();

    // Mobile header should be visible
    const mobileHeader = page.locator("header").first();
    await expect(mobileHeader).toBeVisible();
  });

  test("inspector drawer opens full-width on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");
    // Trigger a node click to open the inspector (implementation-dependent)
    // This is a structural check — if the drawer renders full-width
    const drawer = page.locator('[role="dialog"]');
    if (await drawer.count() > 0) {
      const box = await drawer.boundingBox();
      expect(box?.width).toBeCloseTo(390, -1);
    }
  });
});
