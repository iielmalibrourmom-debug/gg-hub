// Design preview is explicitly separate from the Linux hardware service.
const device = {
  id: "preview-superstrike",
  name: "PRO X2 SUPERSTRIKE",
  type: "MOUSE",
  backend: "preview",
  connected: false,
  supported: false,
  battery: 55,
  capabilities: ["dpi", "reportRate", "buttons"],
  profiles: [
    {
      index: 0,
      name: "Default",
      active: true,
      reportRate: 1000,
      reportRates: [125, 250, 500, 1000, 2000, 4000, 8000],
      resolutions: [
        {
          index: 0,
          dpi: 400,
          values: [100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600],
          active: false,
        },
        {
          index: 1,
          dpi: 800,
          values: [100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600],
          active: true,
        },
        {
          index: 2,
          dpi: 1600,
          values: [100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600],
          active: false,
        },
      ],
      buttons: [
        { index: 0, actionTypes: [0, 1, 2, 3, 4], mapping: [1, 1] },
        { index: 1, actionTypes: [0, 1, 2, 3, 4], mapping: [1, 2] },
        { index: 2, actionTypes: [0, 1, 2, 3, 4], mapping: [1, 3] },
        { index: 3, actionTypes: [0, 1, 2, 3, 4], mapping: [1, 4] },
        { index: 4, actionTypes: [0, 1, 2, 3, 4], mapping: [1, 5] },
      ],
      leds: [],
    },
  ],
};
export const previewDevice = device;
export function previewClient() {
  let data;
  try {
    data = JSON.parse(localStorage.getItem("gg-hub-preview") || "null");
  } catch {}
  data ||= {
    profiles: [
      { id: "desktop", name: "Default", game: "Desktop", deviceSettings: {} },
    ],
    activeProfileId: "desktop",
    macros: [],
    settings: {
      autoSwitch: false,
      pollIntervalMs: 1000,
      macroTimeoutSeconds: 30,
    },
  };
  const save = () =>
    localStorage.setItem("gg-hub-preview", JSON.stringify(data));
  return async (method, params = {}) => {
    if (method === "hardware.devices")
      return {
        devices: [device],
        errors: [],
        diagnostics: [],
        coverage: "preview",
      };
    if (method === "hardware.status")
      return {
        platform: "preview",
        connected: false,
        message: "Design preview — no hardware is connected or controlled.",
      };
    if (
      method === "hardware.configure" ||
      method === "macros.run" ||
      method === "automation.start"
    )
      throw new Error(
        "Hardware execution is unavailable in design preview. Run GG HUB on Linux.",
      );
    if (method === "profiles.list")
      return { profiles: data.profiles, activeProfileId: data.activeProfileId };
    if (method === "macros.list") return { macros: data.macros, runs: [] };
    if (method === "settings.get") return { settings: data.settings };
    if (method === "automation.status")
      return { running: false, protocol: "Preview", waylandSupported: false };
    if (method === "profiles.save" || method === "macros.save") {
      const key = method.startsWith("profiles") ? "profiles" : "macros";
      const entry = { ...params, id: params.id || crypto.randomUUID() };
      data[key] = [...data[key].filter((x) => x.id !== entry.id), entry];
      save();
      return {
        saved: true,
        [key === "profiles" ? "profile" : "macro"]: entry,
        hardwareApplied: false,
      };
    }
    if (method === "profiles.activate") {
      data.activeProfileId = params.id;
      save();
      return {
        saved: true,
        activeProfileId: params.id,
        hardware: { applied: false, reason: "Design preview" },
      };
    }
    if (method === "profiles.delete" || method === "macros.delete") {
      const key = method.startsWith("profiles") ? "profiles" : "macros";
      data[key] = data[key].filter((x) => x.id !== params.id);
      save();
      return { deleted: true };
    }
    if (method === "settings.update") {
      data.settings = { ...data.settings, ...params };
      save();
      return { saved: true, settings: data.settings };
    }
    if (method === "automation.stop" || method === "macros.stop")
      return { stopped: true };
    throw new Error("This operation requires the Linux desktop app.");
  };
}
