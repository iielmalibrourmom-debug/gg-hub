const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
(async () => {
  const root = path.resolve(__dirname, ".."),
    out = path.join(root, "docs/screenshots");
  fs.mkdirSync(out, { recursive: true });
  const server = spawn(
    process.execPath,
    [
      path.join(root, "node_modules/vite/bin/vite.js"),
      "preview",
      "--host",
      "127.0.0.1",
      "--port",
      "4173",
      "--strictPort",
    ],
    { cwd: root, windowsHide: true, stdio: "ignore" },
  );
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 60; i++) {
      try {
        if ((await fetch("http://127.0.0.1:4173")).ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 150));
    }
    if (!ready) throw new Error("Preview server did not start.");
    browser = await chromium.launch();
    const page = await browser.newPage({
      viewport: { width: 1200, height: 850 },
      deviceScaleFactor: 1,
    });
    await page.goto("http://127.0.0.1:4173");
    await page.getByText("DESIGN PREVIEW · no hardware control").waitFor();
    await page.getByRole("heading", { name: "PRO X2 SUPERSTRIKE" }).waitFor();
    await page.screenshot({ path: path.join(out, "devices.png") });
    await page.getByRole("button", { name: /PRO X2 SUPERSTRIKE/ }).click();
    await page.getByRole("heading", { name: "DPI SPEEDS" }).waitFor();
    await page.screenshot({ path: path.join(out, "sensitivity.png") });
    await page.getByRole("button", { name: "Macros", exact: true }).click();
    await page
      .getByRole("button", { name: "Create macro", exact: true })
      .click();
    await page.getByLabel("Name", { exact: true }).fill("Quick shortcut");
    await page.getByLabel("Step 1 key", { exact: true }).fill("KEY_LEFTCTRL");
    await page
      .getByLabel("Step 1 action", { exact: true })
      .selectOption("down");
    await page.getByRole("button", { name: "Add step", exact: true }).click();
    await page.getByLabel("Step 2 key", { exact: true }).fill("KEY_C");
    await page.getByRole("button", { name: "Add step", exact: true }).click();
    await page.getByLabel("Step 3 key", { exact: true }).fill("KEY_LEFTCTRL");
    await page.getByLabel("Step 3 action", { exact: true }).selectOption("up");
    await page.screenshot({ path: path.join(out, "macro-editor.png") });
    console.log(
      "Captured 3 design-preview screenshots (sample data, no hardware control).",
    );
  } finally {
    await browser?.close();
    server.kill();
  }
})().catch((e) => {
  console.error(e.message);
  process.exitCode = 1;
});
