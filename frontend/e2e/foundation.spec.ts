import { test, expect } from "@playwright/test";
import { normalizeColor, luminance } from "./utils/color";

test.describe("Foundation — app boots", () => {
  test("home page loads and renders the Foundry brand", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Foundry/);
  });
});

test.describe("Foundation — token layer", () => {
  test("dark is the default theme, class-based", async ({ page }) => {
    await page.goto("/");
    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("dark");

    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bg);
    expect(luminance(rgb)).toBeLessThan(60);
  });
});

test.describe("Foundation — Button", () => {
  test("renders all variants and sizes on /dev/ui-kit", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-button");
    await expect(section.getByRole("button", { name: "Default" })).toBeVisible();
    await expect(section.getByRole("button", { name: "Disabled" })).toBeDisabled();

    const destructive = section.getByRole("button", { name: "Destructive" });
    const defaultBtn = section.getByRole("button", { name: "Default" });
    const [destructiveBg, defaultBg] = await Promise.all([
      destructive.evaluate((el) => getComputedStyle(el).backgroundColor),
      defaultBtn.evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(destructiveBg).not.toBe(defaultBg);
  });
});

test.describe("Foundation — Input/Textarea/Label", () => {
  test("form fields render and accept input", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-form-fields");
    const input = section.getByLabel("Name");
    await input.fill("Test User");
    await expect(input).toHaveValue("Test User");

    const invalid = section.locator('[aria-invalid="true"]');
    const [invalidBorder, validBorder] = await Promise.all([
      invalid.evaluate((el) => getComputedStyle(el).borderColor),
      input.evaluate((el) => getComputedStyle(el).borderColor),
    ]);
    expect(invalidBorder).not.toBe(validBorder);
  });
});
