const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/ui",
  timeout: 30000,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1200, height: 850 },
    headless: true,
  },
  webServer: {
    command: "npm run preview",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
  reporter: "list",
});
