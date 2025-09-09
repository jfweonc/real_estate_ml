import { test, expect } from "@playwright/test";

test("opens Matrix landing (smoke)", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Matrix/i);
});
