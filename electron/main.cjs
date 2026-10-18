"use strict";
const {
  app,
  BrowserWindow,
  ipcMain,
  protocol,
  net,
  dialog,
  shell,
  session,
} = require("electron");
const path = require("node:path");
const fs = require("node:fs/promises");
const { pathToFileURL } = require("node:url");
const { WorkerBridge } = require("./bridge.cjs");
protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);
const preview = process.argv.includes("--preview");
let window,
  bridge,
  quitting = false;
if (process.env.GG_HUB_APP_DATA)
  app.setPath("userData", path.resolve(process.env.GG_HUB_APP_DATA));
const links = {
  repository: "https://github.com/iielmalibrourmom-debug/gg-hub",
  ratbag: "https://github.com/libratbag/libratbag",
  solaar: "https://pwr-solaar.github.io/Solaar/",
  guide: "https://github.com/iielmalibrourmom-debug/gg-hub#installation",
};
function isAppFrame(value) {
  try {
    const u = new URL(value);
    return (
      u.protocol === "app:" &&
      u.host === "gg-hub" &&
      u.pathname === "/index.html"
    );
  } catch {
    return false;
  }
}
function trusted(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    !isAppFrame(event.senderFrame.url)
  )
    throw new Error("Untrusted application frame.");
}
if (!app.requestSingleInstanceLock()) app.quit();
else
  app.whenReady().then(async () => {
    const root = path.resolve(__dirname, "../dist");
    protocol.handle("app", (request) => {
      const url = new URL(request.url);
      if (url.host !== "gg-hub")
        return new Response("Forbidden", { status: 403 });
      let decoded;
      try {
        decoded = decodeURIComponent(url.pathname);
      } catch {
        return new Response("Invalid path", { status: 400 });
      }
      const file = path.resolve(root, "." + decoded);
      if (file !== root && !file.startsWith(root + path.sep))
        return new Response("Forbidden", { status: 403 });
      return net.fetch(
        pathToFileURL(
          file === root ? path.join(root, "index.html") : file,
        ).toString(),
      );
    });
    session.defaultSession.setPermissionRequestHandler(
      (_wc, _permission, callback) => callback(false),
    );
    session.defaultSession.setPermissionCheckHandler(() => false);
    bridge = new WorkerBridge({
      python:
        process.env.GG_HUB_PYTHON ||
        (process.platform === "win32" ? "python" : "python3"),
      backendPath: app.isPackaged
        ? path.join(process.resourcesPath, "backend")
        : path.resolve(__dirname, "../backend"),
      configDir: path.join(app.getPath("userData"), "config"),
    });
    ipcMain.handle("gg-hub:request", async (event, method, params) => {
      trusted(event);
      if (preview) throw new Error("Design preview uses its own sample data.");
      return bridge.request(method, params);
    });
    ipcMain.handle("gg-hub:info", (event) => {
      trusted(event);
      return {
        version: app.getVersion(),
        platform: process.platform,
        preview,
        packaged: app.isPackaged,
      };
    });
    ipcMain.handle("gg-hub:window", (event, action) => {
      trusted(event);
      if (action === "minimize") window.minimize();
      else if (action === "maximize")
        window.isMaximized() ? window.unmaximize() : window.maximize();
      else if (action === "close") window.close();
      else throw new Error("Invalid window action.");
    });
    ipcMain.handle("gg-hub:link", async (event, name) => {
      trusted(event);
      if (!Object.hasOwn(links, name)) throw new Error("Unknown link.");
      await shell.openExternal(links[name]);
    });
    ipcMain.handle("gg-hub:export", async (event) => {
      trusted(event);
      if (preview) throw new Error("Export requires the normal desktop app.");
      const data = await bridge.request("profiles.export");
      const result = await dialog.showSaveDialog(window, {
        defaultPath: "gg-hub-profiles.json",
        filters: [{ name: "GG HUB profiles", extensions: ["json"] }],
      });
      if (result.canceled) return { canceled: true };
      await fs.writeFile(
        result.filePath,
        JSON.stringify(data.document, null, 2) + "\n",
        { mode: 0o600 },
      );
      return { saved: true };
    });
    ipcMain.handle("gg-hub:import", async (event) => {
      trusted(event);
      const result = await dialog.showOpenDialog(window, {
        properties: ["openFile"],
        filters: [{ name: "GG HUB profiles", extensions: ["json"] }],
      });
      if (result.canceled) return { canceled: true };
      const stat = await fs.stat(result.filePaths[0]);
      if (stat.size > 1024 * 1024)
        throw new Error("Import must be smaller than 1 MiB.");
      return bridge.request("profiles.import", {
        document: await fs.readFile(result.filePaths[0], "utf8"),
      });
    });
    window = new BrowserWindow({
      width: 1200,
      height: 850,
      minWidth: 900,
      minHeight: 680,
      title: "GG HUB",
      frame: false,
      backgroundColor: "#000000",
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event, url) => {
      if (url !== "app://gg-hub/index.html") event.preventDefault();
    });
    window.once("ready-to-show", () => window.show());
    await window.loadURL("app://gg-hub/index.html");
  });
app.on("second-instance", () => {
  window?.show();
  window?.focus();
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (!bridge || quitting) return;
  event.preventDefault();
  quitting = true;
  bridge.stop().finally(() => app.quit());
});
