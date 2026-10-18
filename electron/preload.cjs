"use strict";
const { contextBridge, ipcRenderer } = require("electron");
const methods = [
  "hardware.status",
  "hardware.devices",
  "hardware.configure",
  "profiles.list",
  "profiles.save",
  "profiles.delete",
  "profiles.activate",
  "macros.list",
  "macros.save",
  "macros.delete",
  "macros.run",
  "macros.stop",
  "settings.get",
  "settings.update",
  "automation.status",
  "automation.start",
  "automation.stop",
];
const api = {};
for (const method of methods)
  api[method] = (params = {}) =>
    ipcRenderer.invoke("gg-hub:request", method, params);
contextBridge.exposeInMainWorld(
  "ggHub",
  Object.freeze({
    request: (method, params = {}) => {
      if (!Object.hasOwn(api, method))
        return Promise.reject(new Error("Unsupported operation."));
      return api[method](params);
    },
    info: () => ipcRenderer.invoke("gg-hub:info"),
    window: (action) => ipcRenderer.invoke("gg-hub:window", action),
    exportProfiles: () => ipcRenderer.invoke("gg-hub:export"),
    importProfiles: () => ipcRenderer.invoke("gg-hub:import"),
    openLink: (name) => ipcRenderer.invoke("gg-hub:link", name),
  }),
);
