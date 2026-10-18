const { _electron: electron } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
(async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gg-hub-smoke-"));
  const env = { ...process.env, GG_HUB_APP_DATA: directory };
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  try {
    application = await electron.launch({
      args: [path.resolve(__dirname, "..")],
      env,
      timeout: 30000,
    });
    const page = await application.firstWindow();
    await page.waitForFunction(() => Boolean(window.ggHub));
    const info = await page.evaluate(() => window.ggHub.info());
    assert.equal(info.preview, false);
    await page
      .getByRole("button", { name: "Games & Profiles", exact: true })
      .click();
    await page
      .getByRole("button", { name: "New profile", exact: true })
      .click();
    await page
      .getByLabel("Profile name", { exact: true })
      .fill("Desktop smoke");
    await page
      .getByRole("button", { name: "Save profile", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Desktop smoke", exact: true })
      .waitFor();
    const result = await page.evaluate(() =>
      window.ggHub.request("profiles.list"),
    );
    assert(result.profiles.some((p) => p.name === "Desktop smoke"));
    if (info.platform !== "linux") {
      const hardware = await page.evaluate(() =>
        window.ggHub.request("hardware.status"),
      );
      assert.equal(hardware.supported, false);
      assert.equal(hardware.error.code, "UNSUPPORTED_PLATFORM");
    }
    const failure = await page.evaluate(async () => {
      try {
        await window.ggHub.request("shell.run", {});
        return false;
      } catch {
        return true;
      }
    });
    assert(failure);
    console.log(
      JSON.stringify({
        desktopIPC: true,
        profilePersisted: true,
        unsupportedHostHonest: info.platform !== "linux",
        shellRejected: true,
      }),
    );
  } finally {
    if (application)
      await application.close(); /* Keep no credentials or personal state in the test directory. */
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
