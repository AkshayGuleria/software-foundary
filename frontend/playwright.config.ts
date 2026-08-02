import { defineConfig, devices } from "@playwright/test";

// This project has no @types/node (nothing else here runs in a Node type
// context, and Global Constraints forbid adding new deps for this plan).
// Declare just enough of the Node `process` global for the CI check below
// -- this only surfaced once tsconfig.node.json started type-checking this
// file (Fix 4 / Task 7 Step 4b).
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5173",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "cd .. && uv run foundry serve --db /tmp/foundry-e2e.db --port 8000",
      url: "http://127.0.0.1:8000/api/_health",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
