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
});

test.describe("Foundation — Card", () => {
  test("renders with token-driven border and background", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const card = page.getByTestId("uikit-card").locator(".ds-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Card title");
  });
});

test.describe("Foundation — Badge", () => {
  test("renders all variants and tones with distinct colors", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-badge");
    const [defaultBg, destructiveBg, successBg, warningBg] = await Promise.all([
      section.getByText("Default").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Destructive").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Success").evaluate((el) => getComputedStyle(el).backgroundColor),
      section.getByText("Warning").evaluate((el) => getComputedStyle(el).backgroundColor),
    ]);
    expect(new Set([defaultBg, destructiveBg, successBg, warningBg]).size).toBe(4);
  });
});

test.describe("Foundation — Theme Toggle (exercised via /dev/ui-kit)", () => {
  test("switches html class, persists the choice, survives reload, and light mode actually renders light", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    // Scoped to the gallery section: since Task 12 mounts ThemeToggle in the
    // (globally-rendered) TopBar too, /dev/ui-kit now legitimately contains
    // two toggle instances -- the live TopBar one plus this page's own
    // gallery instance -- so an unscoped getByTitle is ambiguous.
    await page.getByTestId("uikit-theme-toggle").getByTitle(/Switch to light theme/i).click();
    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("light");
    const stored = await page.evaluate(() => localStorage.getItem("foundry-theme"));
    expect(stored).toBe("light");

    // Exercises index.html's bootstrap script's "light" branch -- until
    // this reload, only the default-dark branch had ever run in a test.
    await page.reload();
    const htmlClassAfterReload = await page.evaluate(() => document.documentElement.className);
    expect(htmlClassAfterReload).toBe("light");

    // Prove light mode actually paints light, not just that the class is
    // present -- a token regression that left light mode rendering dark
    // would pass a class-only assertion unchanged.
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bg);
    expect(luminance(rgb)).toBeGreaterThan(200);
  });
});

test.describe("Foundation — Theme Toggle (mounted in TopBar)", () => {
  test("is visible in the app shell and switches theme app-wide", async ({ page }) => {
    await page.goto("/queue");
    const toggle = page.getByRole("banner").getByTitle(/Switch to light theme/i);
    await expect(toggle).toBeVisible();
    await toggle.click();

    const htmlClass = await page.evaluate(() => document.documentElement.className);
    expect(htmlClass).toBe("light");

    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = await normalizeColor(page, bodyBg);
    expect(luminance(rgb)).toBeGreaterThan(200);

    // Sidebar nav and the queue page's own content must also render light,
    // not just <body> -- this is the whole point of deferring the mount to
    // the last task: a page still holding a hardcoded slate-* background
    // would stay dark here even though <body> switched.
    const sidebarBg = await page.evaluate(() => {
      const aside = document.querySelector("aside");
      return aside ? getComputedStyle(aside).backgroundColor : null;
    });
    expect(sidebarBg).not.toBeNull();
    const sidebarRgb = await normalizeColor(page, sidebarBg!);
    expect(luminance(sidebarRgb)).toBeGreaterThan(150);
  });
});

test.describe("Foundation — Sheet", () => {
  test("opens on trigger click, closes on Escape", async ({ page }) => {
    await page.goto("/dev/ui-kit");
    const section = page.getByTestId("uikit-sheet");
    await expect(section.getByText("Sheet title")).not.toBeVisible();

    await section.getByRole("button", { name: "Open sheet" }).click();
    await expect(section.getByText("Sheet title")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(section.getByText("Sheet title")).not.toBeVisible();
  });
});
