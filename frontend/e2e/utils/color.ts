import type { Page } from "@playwright/test";

/**
 * Normalize any CSS color string (rgb(), oklch(), etc.) to sRGB bytes by
 * painting it into a 1x1 canvas and reading back getImageData(). Reliable
 * regardless of input color space or how a given browser serializes
 * getComputedStyle() output as text -- unlike a canvas fillStyle *getter*
 * round-trip, which some Chromium builds don't normalize at all.
 */
export async function normalizeColor(page: Page, colorStr: string): Promise<[number, number, number]> {
  const [r, g, b] = await page.evaluate((c) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = c;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3));
  }, colorStr);
  return [r, g, b];
}

/** Perceived luminance (0-255 scale) from sRGB bytes. */
export function luminance([r, g, b]: [number, number, number]): number {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}
