// @ts-nocheck — @playwright/test is not installed; this file is always skipped in CI.
/**
 * E2E: top-nav shell at 390×844 (iPhone 14 viewport).
 * Skipped by default; run with PLAYWRIGHT=1 in CI when a browser is available.
 *
 * To run manually:
 *   cd ui && npx playwright test tests/e2e/responsive-shell.spec.ts
 */
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { test, expect } = require("@playwright/test");

const skip = !process.env.PLAYWRIGHT;

test.describe("Responsive shell — mobile viewport", () => {
  test.skip(skip, "Set PLAYWRIGHT=1 to run browser-based responsive checks");

  test("no horizontal body overflow at 390px width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");

    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test("top bar is sticky and the primary tab row scrolls horizontally", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");

    const header = page.locator("header").first();
    await expect(header).toBeVisible();
    const position = await header.evaluate((el) => getComputedStyle(el).position);
    expect(position).toBe("sticky");

    const nav = page.locator('nav[aria-label="Primary"]');
    await expect(nav).toBeVisible();
    // All six tabs live in one horizontally scrollable row
    await expect(nav.locator("a")).toHaveCount(6);
    const { scrollWidth, clientWidth, overflowX } = await nav.evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      overflowX: getComputedStyle(el).overflowX,
    }));
    expect(overflowX).toBe("auto");
    expect(scrollWidth).toBeGreaterThanOrEqual(clientWidth);
  });

  test("scope counts are collapsed at 390px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/brain");

    const counts = page.getByText(/in scope · .* total/);
    if ((await counts.count()) > 0) {
      await expect(counts.first()).toBeHidden();
    }
  });
});
