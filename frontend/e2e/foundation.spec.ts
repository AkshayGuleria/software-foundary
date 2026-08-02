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

test.describe("Foundation — Select", () => {
  test("renders and changes value", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const select = page.getByTestId("uikit-select").locator("select");
    await expect(select).toHaveValue("active");
    await select.selectOption("paused");
    await expect(select).toHaveValue("paused");
  });
});

test.describe("Foundation — Table", () => {
  test("renders header and row content", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const table = page.getByTestId("uikit-table");
    await expect(table.getByText("rec-app")).toBeVisible();
    await expect(table.getByText("Status")).toBeVisible();
  });
});

test.describe("Foundation — Shell", () => {
  test("sidebar renders all nav links with correct active state", async ({ page }) => {
    await page.goto("/queue");
    const sidebar = page.locator("aside");
    await expect(sidebar.getByRole("link", { name: "Portfolio" })).toBeVisible();
    await expect(sidebar.getByRole("link", { name: "Knowledge" })).toBeVisible();
    const queueLink = sidebar.getByRole("link", { name: "Queue" });
    const portfolioLink = sidebar.getByRole("link", { name: "Portfolio" });
    const [queueBg, portfolioBg] = await Promise.all([
      queueLink.evaluate((el) => getComputedStyle(el).backgroundColor),
      portfolioLink.evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(queueBg).not.toBe(portfolioBg);
  });

  test("theme toggle switches html class and persists the choice", async ({ page }) => {
    await page.goto("/");
    await page.getByTitle(/Switch to light theme/i).click();
    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("light");
    const stored = await page.evaluate(() => localStorage.getItem("foundry-theme"));
    expect(stored).toBe("light");
  });
});
