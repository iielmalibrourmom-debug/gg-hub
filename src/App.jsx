import React, { useEffect, useRef, useState } from "react";
import {
  Settings,
  UserRound,
  ChevronDown,
  ChevronLeft,
  ArrowLeft,
  LayoutGrid,
  Rows3,
  Microchip,
  Battery,
  Radio,
  Plus,
  Search,
  RefreshCw,
  MousePointer2,
  Keyboard,
  Sun,
  Target,
  SlidersHorizontal,
  Trash2,
  Play,
  Square,
  Download,
  Upload,
  Check,
  Info,
  ExternalLink,
  X,
  Minus,
  Maximize2,
  Gamepad2,
  Command,
  FileCode2,
  Save,
  AlertCircle,
  FolderOpen,
  Link,
  Copy,
} from "lucide-react";
import DeviceArt from "./DeviceArt.jsx";
import { previewClient } from "./preview.js";
import catalog from "../data/device-catalog.json";

const labels = {
  home: "Devices",
  profiles: "Games & Profiles",
  macros: "Macros",
  compatibility: "Device catalog",
  settings: "Settings",
};
const specialActions = [
  ["DPI cycle up", 1073741831],
  ["DPI cycle down", 1073741832],
  ["DPI up", 1073741833],
  ["DPI down", 1073741834],
  ["DPI shift", 1073741835],
  ["Default DPI", 1073741836],
  ["Profile cycle up", 1073741837],
  ["Profile cycle down", 1073741838],
  ["Battery level", 1073741842],
];
const buttonNames = [
  "Primary click",
  "Secondary click",
  "Middle click",
  "Back",
  "Forward",
];
const numberDpi = (x) => (Array.isArray(x) ? x.join(" × ") : x);
const keyNames = {
  30: "A",
  48: "B",
  46: "C",
  32: "D",
  18: "E",
  33: "F",
  34: "G",
  35: "H",
  23: "I",
  36: "J",
  37: "K",
  38: "L",
  50: "M",
  49: "N",
  24: "O",
  25: "P",
  16: "Q",
  19: "R",
  31: "S",
  20: "T",
  22: "U",
  47: "V",
  17: "W",
  45: "X",
  21: "Y",
  44: "Z",
  57: "SPACE",
  28: "ENTER",
  1: "ESC",
  15: "TAB",
  42: "LEFTSHIFT",
  29: "LEFTCTRL",
  56: "LEFTALT",
};
const titleCase = (x) =>
  String(x)
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (s) => s.toUpperCase());

export default function App() {
  const service = useRef(null);
  const [info, setInfo] = useState({
    preview: !window.ggHub,
    platform: "loading",
    version: "0.1.0",
  });
  const [page, setPage] = useState("home"),
    [devices, setDevices] = useState([]),
    [diagnostics, setDiagnostics] = useState(null),
    [profiles, setProfiles] = useState([]),
    [activeId, setActiveId] = useState(null),
    [macros, setMacros] = useState([]),
    [runs, setRuns] = useState([]),
    [status, setStatus] = useState(null),
    [automation, setAutomation] = useState(null),
    [settings, setSettings] = useState({}),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState(null),
    [selected, setSelected] = useState(null),
    [tab, setTab] = useState("sensitivity"),
    [list, setList] = useState(false),
    [menu, setMenu] = useState(false),
    [modal, setModal] = useState(null),
    [query, setQuery] = useState("");
  useEffect(() => {
    if (!modal) return;
    const handler = (e) => {
      if (e.key === "Escape") setModal(null);
      if (e.key === "Tab") {
        const elements = Array.from(
          document.querySelectorAll(
            ".modal button:not(:disabled),.modal input:not(:disabled),.modal select:not(:disabled)",
          ),
        );
        if (!elements.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [modal]);
  const [profileDraft, setProfileDraft] = useState({
      name: "",
      game: "",
      executable: "",
    }),
    [macroDraft, setMacroDraft] = useState({
      name: "",
      mode: "noRepeat",
      steps: [],
    });
  const notify = (message, error = false) => setToast({ message, error });
  const call = (method, params) => {
    if (!service.current) throw new Error("Backend is starting.");
    return service.current(method, params);
  };
  async function refresh() {
    setBusy(true);
    try {
      const results = await Promise.allSettled([
        call("hardware.devices"),
        call("profiles.list"),
        call("macros.list"),
        call("hardware.status"),
        call("settings.get"),
        call("automation.status"),
      ]);
      for (let i = 0; i < results.length; i++) {
        const r = results[i];
        if (r.status === "rejected") {
          if (i === 0) notify(r.reason.message, true);
          continue;
        }
        const v = r.value;
        if (i === 0) {
          setDevices(v.devices || []);
          setDiagnostics(v);
          setSelected((old) =>
            old ? (v.devices || []).find((d) => d.id === old.id) || null : old,
          );
        }
        if (i === 1) {
          setProfiles(v.profiles || []);
          setActiveId(v.activeProfileId);
        }
        if (i === 2) {
          setMacros(v.macros || []);
          setRuns(v.runs || []);
        }
        if (i === 3) setStatus(v);
        if (i === 4) setSettings(v.settings || {});
        if (i === 5) setAutomation(v);
      }
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let alive = true;
    (async () => {
      const nativeInfo = window.ggHub
        ? await window.ggHub.info()
        : { preview: true, platform: "browser", version: "0.1.0" };
      if (!alive) return;
      setInfo(nativeInfo);
      service.current = nativeInfo.preview
        ? previewClient()
        : window.ggHub.request;
      await refresh();
    })().catch((e) => notify(e.message, true));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (!service.current || info.preview) return;
    const timer = setInterval(async () => {
      try {
        const [v, p, a] = await Promise.all([
          call("macros.list"),
          call("profiles.list"),
          call("automation.status"),
        ]);
        setRuns(v.runs || []);
        setProfiles(p.profiles || []);
        setActiveId(p.activeProfileId);
        setAutomation(a);
      } catch {}
    }, 1500);
    return () => clearInterval(timer);
  }, [info.preview]);
  async function perform(fn, success) {
    setBusy(true);
    try {
      const result = await fn();
      if (success) notify(success);
      return result;
    } catch (e) {
      notify(e.message, true);
      return null;
    } finally {
      setBusy(false);
    }
  }
  function go(next) {
    setPage(next);
    setSelected(null);
    setMenu(false);
    setQuery("");
  }
  async function configure(params) {
    const r = await perform(() =>
      call("hardware.configure", { deviceId: selected.id, ...params }),
    );
    if (r?.applied) {
      notify(
        r.readbackVerified
          ? "Applied to device and read back."
          : "Device accepted settings. Refresh to verify.",
      );
      await refresh();
    }
  }
  async function activate(profile) {
    setMenu(false);
    const r = await perform(() =>
      call("profiles.activate", { id: profile.id }),
    );
    if (!r) return;
    setActiveId(r.activeProfileId);
    const h = r.hardware,
      entries = Object.values(h?.result || {}),
      failed = entries.filter((x) => !x.applied);
    if (entries.length && !failed.length)
      notify("Profile activated and device settings applied.");
    else if (failed.length)
      notify(
        "Profile selected, but " +
          failed
            .map((x) => x.error?.message || "device settings failed")
            .join("; "),
        true,
      );
    else
      notify(
        "Profile selected. " +
          (h?.reason || h?.error || "No hardware settings were applied."),
        Boolean(h?.error),
      );
    await refresh();
  }
  function openProfile(p) {
    setProfileDraft(
      p || { name: "", game: "", executable: "", deviceSettings: {} },
    );
    setModal("profile");
  }
  async function saveProfile(e) {
    e.preventDefault();
    const r = await perform(
      () =>
        call(
          "profiles.save",
          Object.fromEntries(
            Object.entries(profileDraft)
              .filter(
                ([k, v]) =>
                  !["game", "executable"].includes(k) || String(v).trim(),
              )
              .map(([k, v]) => [k, typeof v === "string" ? v.trim() : v]),
          ),
        ),
      "Profile saved locally.",
    );
    if (r) {
      setModal(null);
      await refresh();
    }
  }
  async function saveMacro(e) {
    e.preventDefault();
    const r = await perform(
      () => call("macros.save", macroDraft),
      "Macro saved.",
    );
    if (r) {
      setModal(null);
      await refresh();
    }
  }
  async function remove(kind, id) {
    const r = await perform(() => call(kind + ".delete", { id }), "Deleted.");
    if (r) {
      setModal(null);
      await refresh();
    }
  }
  const activeProfile = profiles.find((p) => p.id === activeId);
  const profile =
    selected?.profiles?.find((p) => p.active) || selected?.profiles?.[0];
  const resolutions = profile?.resolutions || [],
    buttons = profile?.buttons || [],
    leds = profile?.leds || [],
    readOnly = info.preview || !selected?.supported;
  const isKeyboard =
    selected &&
    (selected.type === "KEYBOARD" ||
      selected.kind === "keyboard" ||
      /keyboard|g915|g815|g513|g512|g413|g213|g pro.*tkl/i.test(selected.name));
  const [resolutionIndex, setResolutionIndex] = useState(0),
    [buttonIndex, setButtonIndex] = useState(0),
    [ledIndex, setLedIndex] = useState(0);
  const resolution =
    resolutions.find((x) => x.index === resolutionIndex) ||
    resolutions.find((x) => x.active) ||
    resolutions[0];
  const led = leds.find((x) => x.index === ledIndex) || leds[0];
  const [brightness, setBrightness] = useState(255),
    [dpi, setDpi] = useState(800),
    [rate, setRate] = useState(1000),
    [color, setColor] = useState("#00a9e0"),
    [lightMode, setLightMode] = useState(1),
    [assignment, setAssignment] = useState("button:1"),
    [solaarValues, setSolaarValues] = useState({});
  useEffect(() => {
    setDpi(
      Array.isArray(resolution?.dpi)
        ? resolution.dpi[0]
        : resolution?.dpi || 800,
    );
    setRate(profile?.reportRate || 1000);
    setColor(
      Array.isArray(led?.color)
        ? "#" +
            led.color
              .map((x) => Number(x).toString(16).padStart(2, "0"))
              .join("")
        : typeof led?.color === "string"
          ? led.color
          : "#00a9e0",
    );
    setLightMode(led?.mode ?? 1);
    setBrightness(led?.brightness ?? 255);
  }, [
    selected?.id,
    profile?.reportRate,
    resolution?.index,
    JSON.stringify(resolution?.dpi),
    led?.index,
    JSON.stringify(led?.color),
  ]);
  function selectDevice(d) {
    setSelected(d);
    setPage("device");
    setTab(d.backend === "solaar" ? "advanced" : "sensitivity");
    setResolutionIndex(
      d.profiles?.[0]?.resolutions?.find((r) => r.active)?.index || 0,
    );
    setButtonIndex(0);
  }
  function readOnlyNote() {
    return info.preview ? (
      <p className="hint">
        Design preview. Values are examples; hardware controls are disabled.
      </p>
    ) : !selected?.supported ? (
      <p className="hint">
        This device is detected but its configuration interface is unavailable.
      </p>
    ) : null;
  }
  function link(name) {
    if (window.ggHub)
      window.ggHub.openLink(name).catch((e) => notify(e.message, true));
    else
      window.open(
        {
          repository: "https://github.com/iielmalibrourmom-debug/gg-hub",
          guide:
            "https://github.com/iielmalibrourmom-debug/gg-hub#installation",
          solaar: "https://pwr-solaar.github.io/Solaar/",
          ratbag: "https://github.com/libratbag/libratbag",
        }[name],
        "_blank",
        "noopener,noreferrer",
      );
  }
  async function updateSetting(values) {
    const r = await perform(
      () => call("settings.update", values),
      "Preference saved.",
    );
    if (r) setSettings(r.settings);
  }
  async function snapshot() {
    if (!activeProfile) return notify("Create a profile first.", true);
    const settingsByDevice = {};
    for (const d of devices) {
      if (d.backend !== "ratbagd") continue;
      const p = d.profiles?.find((x) => x.active) || d.profiles?.[0];
      const res = p?.resolutions?.find((x) => x.active);
      if (p && res)
        settingsByDevice[d.id] = {
          profile: p.index,
          resolutionIndex: res.index,
          dpi: res.dpi,
          reportRate: p.reportRate,
          activateProfile: true,
          activateResolution: true,
        };
    }
    const r = await perform(
      () =>
        call("profiles.save", {
          ...activeProfile,
          deviceSettings: settingsByDevice,
        }),
      "Current DPI and polling settings saved into profile.",
    );
    if (r) await refresh();
  }
  return (
    <div className="app">
      <div className="window-controls">
        <button
          aria-label="Minimize"
          onClick={() => window.ggHub?.window("minimize")}
        >
          <Minus size={13} />
        </button>
        <button
          aria-label="Maximize"
          onClick={() => window.ggHub?.window("maximize")}
        >
          <Maximize2 size={11} />
        </button>
        <button
          aria-label="Close"
          onClick={() => window.ggHub?.window("close")}
        >
          <X size={13} />
        </button>
      </div>
      <header className="app-header">
        <button
          className="brand"
          aria-label="GG HUB home"
          onClick={() => go("home")}
        >
          <span>
            G<span>G</span>
          </span>
        </button>
        <nav aria-label="Main navigation">
          {["home", "profiles", "macros"].map((p) => (
            <button
              key={p}
              className={
                page === p || (p === "home" && page === "device")
                  ? "active"
                  : ""
              }
              onClick={() => go(p)}
            >
              {labels[p]}
            </button>
          ))}
        </nav>
        <div className="header-right">
          <div className="profile-menu">
            <button className="profile-selector" onClick={() => setMenu(!menu)}>
              <FileCode2 size={23} />
              <span>
                {activeProfile?.game || "Desktop"}:{" "}
                {activeProfile?.name || "Default"}
              </span>
              <ChevronDown size={17} />
            </button>
            {menu && (
              <div className="dropdown">
                {profiles.map((p) => (
                  <button key={p.id} onClick={() => activate(p)}>
                    <span>
                      {p.game || "Desktop"}: {p.name}
                    </span>
                    {activeId === p.id && <Check size={16} />}
                  </button>
                ))}
                <button
                  onClick={() => {
                    setMenu(false);
                    openProfile();
                  }}
                >
                  <Plus size={16} /> New profile
                </button>
              </div>
            )}
          </div>
          <button
            className={"icon " + (page === "settings" ? "selected" : "")}
            aria-label="Settings"
            onClick={() => go("settings")}
          >
            <Settings size={23} />
          </button>
          <button
            className="icon"
            aria-label="About GG HUB"
            onClick={() => setModal("about")}
          >
            <UserRound size={24} />
          </button>
        </div>
      </header>
      {page === "home" && (
        <main className="home">
          <div className="home-toolbar">
            <button
              className="text-button refresh"
              onClick={refresh}
              disabled={busy}
            >
              <RefreshCw size={15} className={busy ? "spin" : ""} /> Refresh
            </button>
            <div className="view-switch">
              <button
                aria-label="Tile view"
                className={!list ? "selected" : ""}
                onClick={() => setList(false)}
              >
                <LayoutGrid size={22} />
              </button>
              <button
                aria-label="List view"
                className={list ? "selected" : ""}
                onClick={() => setList(true)}
              >
                <Rows3 size={22} />
              </button>
            </div>
          </div>
          {devices.length ? (
            <div className={"device-grid " + (list ? "list" : "")}>
              {devices.map((d) => (
                <button
                  className="device-card"
                  key={d.id}
                  onClick={() => selectDevice(d)}
                >
                  <div className="device-label">
                    <h2>{d.name}</h2>
                    <div className="device-status">
                      {info.preview ? (
                        <>
                          <span>{d.battery}%</span>
                          <Battery size={14} />
                          <Radio size={14} />
                        </>
                      ) : (
                        <>
                          <span
                            className={"dot " + (d.connected ? "online" : "")}
                          />
                          <span>{d.supported ? "Connected" : "Detected"}</span>
                          {Number.isInteger(d.battery) && (
                            <>
                              <span> · {d.battery}%</span>
                              <Battery size={14} />
                            </>
                          )}
                          <span className="backend-label">{d.backend}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <DeviceArt
                    keyboard={
                      d.type === "KEYBOARD" ||
                      d.kind === "keyboard" ||
                      /keyboard|g915|g815/i.test(d.name)
                    }
                  />
                  <div className="device-footer">
                    <span>
                      {info.preview
                        ? "Preview device"
                        : d.supported
                          ? "Configure device"
                          : "View details"}
                    </span>
                    <span className="memory">
                      <Microchip size={24} />
                    </span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty devices-empty">
              <MousePointer2 size={64} strokeWidth={1} />
              <h1>Connect your device</h1>
              <p>
                Plug in your Logitech gaming mouse, keyboard or LIGHTSPEED
                receiver.
              </p>
              <p className="muted">
                GG HUB uses ratbagd and Solaar to discover available controls.
              </p>
              <div className="actions">
                <button className="primary" onClick={refresh} disabled={busy}>
                  Check for devices
                </button>
                <button className="secondary" onClick={() => go("settings")}>
                  Set up Linux drivers
                </button>
              </div>
              {diagnostics?.errors?.length > 0 && (
                <p className="hint">
                  Driver connection needs attention. See Settings for details.
                </p>
              )}
            </div>
          )}
          <button className="catalog-link" onClick={() => go("compatibility")}>
            <Keyboard size={15} /> Device catalog <span>↗</span>
          </button>
        </main>
      )}
      {page === "device" && selected && (
        <main className="device-page">
          <div className="device-heading">
            <button
              className="back icon"
              onClick={() => go("home")}
              aria-label="Back to devices"
            >
              <ArrowLeft size={22} />
            </button>
            <h1>{selected.name}</h1>
            <span className="backend-tag">
              {info.preview
                ? "DESIGN PREVIEW"
                : selected.backend?.toUpperCase()}
            </span>
            <button className="text-button" onClick={refresh} disabled={busy}>
              <RefreshCw size={16} /> Refresh
            </button>
          </div>
          <div className="device-layout">
            <aside className="device-tabs">
              {[
                ["sensitivity", Target, "Sensitivity (DPI)"],
                ["assignments", MousePointer2, "Assignments"],
                ["lightsync", Sun, "LIGHTSYNC"],
                ["advanced", SlidersHorizontal, "Device settings"],
                ["onboard", Microchip, "On-board profiles"],
              ].map(([id, Icon, label]) => (
                <button
                  key={id}
                  className={tab === id ? "active" : ""}
                  onClick={() => setTab(id)}
                >
                  <Icon size={25} />
                  <span>{label}</span>
                </button>
              ))}
            </aside>
            <section className="device-content">
              <div className="device-visual">
                <DeviceArt keyboard={isKeyboard} accent={color} />
                <span>
                  {selected.connected && !info.preview
                    ? "CONNECTED"
                    : "PREVIEW"}
                </span>
              </div>
              <div className="controls-panel">
                {tab === "sensitivity" && (
                  <>
                    <p className="eyebrow">SENSITIVITY</p>
                    <h2>DPI SPEEDS</h2>
                    <p className="muted">
                      Choose a sensitivity stage, then adjust its DPI.
                    </p>
                    {resolutions.length > 0 ? (
                      <>
                        <div className="dpi-stages">
                          {resolutions.map((r) => (
                            <button
                              className={
                                resolution?.index === r.index ? "active" : ""
                              }
                              key={r.index}
                              onClick={() => setResolutionIndex(r.index)}
                            >
                              <span>{numberDpi(r.dpi)}</span>
                              <small>
                                {r.active ? "ACTIVE" : "DPI " + (r.index + 1)}
                              </small>
                            </button>
                          ))}
                        </div>
                        <label className="field">
                          <span>DPI</span>
                          <div className="input-with-unit">
                            <input
                              aria-label="DPI"
                              type="number"
                              min="1"
                              max="100000"
                              value={dpi}
                              onChange={(e) => setDpi(Number(e.target.value))}
                            />
                            <span>DPI</span>
                          </div>
                        </label>
                        {resolution?.values?.length > 0 && (
                          <div className="dpi-presets">
                            {resolution.values
                              .filter((v) => typeof v === "number")
                              .filter(
                                (_v, i, a) =>
                                  a.length < 16 ||
                                  i % Math.ceil(a.length / 12) === 0,
                              )
                              .map((v) => (
                                <button
                                  key={v}
                                  onClick={() => setDpi(v)}
                                  className={dpi === v ? "active" : ""}
                                >
                                  {v}
                                </button>
                              ))}
                          </div>
                        )}
                        <button
                          disabled={readOnly || busy}
                          className="primary"
                          onClick={() =>
                            configure({
                              profile: profile.index,
                              resolutionIndex: resolution.index,
                              dpi,
                            })
                          }
                        >
                          Apply DPI
                        </button>
                        <button
                          disabled={readOnly || busy}
                          className="secondary"
                          onClick={() =>
                            configure({
                              profile: profile.index,
                              resolutionIndex: resolution.index,
                              activateResolution: true,
                            })
                          }
                        >
                          Use this stage
                        </button>
                      </>
                    ) : (
                      <p className="hint">
                        DPI control is not exposed by this driver. Check Device
                        settings for available Solaar controls.
                      </p>
                    )}
                    <div className="section-divider" />
                    <h3>REPORT RATE</h3>
                    <p className="muted">
                      How often the mouse reports to your computer.
                    </p>
                    {profile?.reportRates?.length ? (
                      <>
                        <div className="rate-options">
                          {profile.reportRates.map((hz) => (
                            <button
                              className={rate === hz ? "active" : ""}
                              key={hz}
                              onClick={() => setRate(hz)}
                            >
                              {hz}
                              <small>Hz</small>
                            </button>
                          ))}
                        </div>
                        <button
                          className="primary"
                          disabled={readOnly || busy}
                          onClick={() =>
                            configure({
                              profile: profile.index,
                              reportRate: rate,
                            })
                          }
                        >
                          Apply report rate
                        </button>
                      </>
                    ) : (
                      <p className="hint">
                        Polling rate control is unavailable for this device.
                      </p>
                    )}
                    {readOnlyNote()}
                  </>
                )}
                {tab === "assignments" && (
                  <>
                    <p className="eyebrow">ASSIGNMENTS</p>
                    <h2>MAKE IT YOURS</h2>
                    <p className="muted">
                      Map a button to a mouse action, keyboard key or DPI
                      function.
                    </p>
                    {buttons.length ? (
                      <>
                        <div className="button-list">
                          {buttons.map((b) => (
                            <button
                              className={
                                buttonIndex === b.index ? "active" : ""
                              }
                              key={b.index}
                              onClick={() => setButtonIndex(b.index)}
                            >
                              <span>{b.index + 1}</span>
                              {buttonNames[b.index] ||
                                "Button " + (b.index + 1)}
                            </button>
                          ))}
                        </div>
                        <label className="field">
                          <span>Assignment</span>
                          <select
                            value={assignment}
                            onChange={(e) => setAssignment(e.target.value)}
                          >
                            <optgroup label="Mouse buttons">
                              {buttonNames.map((n, i) => (
                                <option key={n} value={"button:" + (i + 1)}>
                                  {n}
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label="DPI & profiles">
                              {specialActions.map(([n, v]) => (
                                <option key={v} value={"special:" + v}>
                                  {n}
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label="Keyboard">
                              {Object.entries(keyNames).map(([v, n]) => (
                                <option key={v} value={"key:" + v}>
                                  {n}
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label="Saved macros (single playback)">
                              {macros
                                .filter((m) =>
                                  ["noRepeat", "sequence"].includes(m.mode),
                                )
                                .map((m) => (
                                  <option key={m.id} value={"macro:" + m.id}>
                                    {m.name}
                                  </option>
                                ))}
                            </optgroup>
                            <option value="none:0">Disable</option>
                          </select>
                        </label>
                        <button
                          className="primary"
                          disabled={readOnly || busy}
                          onClick={() => {
                            const [type, value] = assignment.split(":");
                            const macro =
                              type === "macro"
                                ? macros.find((m) => m.id === value)
                                : null;
                            configure({
                              profile: profile.index,
                              button: buttonIndex,
                              action: macro
                                ? {
                                    type: "macro",
                                    mode: macro.mode,
                                    steps: macro.steps,
                                  }
                                : { type, value: Number(value) },
                            });
                          }}
                        >
                          Apply assignment
                        </button>
                        <p className="hint">
                          Only driver-supported actions are accepted. Assigned
                          macros play once on the device; repeating modes use
                          the Macros page.
                        </p>
                      </>
                    ) : (
                      <p className="hint">
                        Button mappings are not exposed here. For compatible
                        HID++ devices, use Device settings → reprogrammable
                        keys.
                      </p>
                    )}
                    <button
                      className="text-button"
                      onClick={() => go("macros")}
                    >
                      <Command size={16} /> Open macro editor
                    </button>
                    {readOnlyNote()}
                  </>
                )}
                {tab === "lightsync" && (
                  <>
                    <p className="eyebrow">LIGHTSYNC</p>
                    <h2>YOUR COLOR. YOUR STYLE.</h2>
                    {leds.length ? (
                      <>
                        <label className="field">
                          <span>Lighting zone</span>
                          <select
                            value={led?.index}
                            onChange={(e) =>
                              setLedIndex(Number(e.target.value))
                            }
                          >
                            {leds.map((l) => (
                              <option key={l.index} value={l.index}>
                                Zone {l.index + 1}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="color-controls">
                          <input
                            type="color"
                            aria-label="Lighting color"
                            value={
                              /^#[0-9a-f]{6}$/i.test(color) ? color : "#00a9e0"
                            }
                            onChange={(e) => setColor(e.target.value)}
                          />
                          <input
                            aria-label="Color hex"
                            value={color}
                            onChange={(e) => setColor(e.target.value)}
                          />
                        </div>
                        <div className="swatches">
                          {[
                            "#00a9e0",
                            "#9e5dff",
                            "#ff4b65",
                            "#ff8b39",
                            "#f5df43",
                            "#4dea92",
                            "#ffffff",
                          ].map((c) => (
                            <button
                              key={c}
                              style={{ background: c }}
                              aria-label={"Select " + c}
                              onClick={() => setColor(c)}
                            />
                          ))}
                        </div>
                        <label className="field">
                          <span>Effect</span>
                          <select
                            value={lightMode}
                            onChange={(e) =>
                              setLightMode(Number(e.target.value))
                            }
                          >
                            {(led.modes || [0, 1, 2, 3]).map((m) => (
                              <option key={m} value={m}>
                                {["Off", "Fixed", "Color cycle", "Breathing"][
                                  m
                                ] || "Mode " + m}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="field">
                          <span>
                            Brightness · {Math.round((brightness / 255) * 100)}%
                          </span>
                          <input
                            aria-label="Lighting brightness"
                            type="range"
                            min="0"
                            max="255"
                            value={brightness}
                            onChange={(e) =>
                              setBrightness(Number(e.target.value))
                            }
                          />
                        </label>
                        <button
                          className="primary"
                          disabled={
                            readOnly || busy || !/^#[0-9a-f]{6}$/i.test(color)
                          }
                          onClick={() =>
                            configure({
                              profile: profile.index,
                              led: led.index,
                              color,
                              mode: lightMode,
                              ...(led.brightness !== undefined
                                ? { brightness }
                                : {}),
                            })
                          }
                        >
                          Apply lighting
                        </button>
                      </>
                    ) : (
                      <p className="hint">
                        This device has no driver-accessible lighting zones.
                        Solaar lighting controls, when available, appear under
                        Device settings.
                      </p>
                    )}
                    {readOnlyNote()}
                  </>
                )}
                {tab === "advanced" && (
                  <>
                    <p className="eyebrow">DEVICE SETTINGS</p>
                    <h2>AVAILABLE CONTROLS</h2>
                    {selected.backend === "solaar" ? (
                      <>
                        <p className="muted">
                          These controls are discovered from this device through
                          Solaar.
                        </p>
                        {selected.settings?.length ? (
                          selected.settings.map((s) => {
                            const settingId =
                                s.name + (s.key ? ":" + s.key : ""),
                              value = solaarValues[settingId] ?? s.value;
                            return (
                              <div className="solaar-setting" key={settingId}>
                                <label className="field">
                                  <span>
                                    {titleCase(s.name)}
                                    {s.key ? " · " + s.key : ""}
                                  </span>
                                  {s.type === "boolean" ? (
                                    <select
                                      aria-label={settingId}
                                      value={String(value).toLowerCase()}
                                      onChange={(e) =>
                                        setSolaarValues({
                                          ...solaarValues,
                                          [settingId]: e.target.value,
                                        })
                                      }
                                    >
                                      <option value="true">Enabled</option>
                                      <option value="false">Disabled</option>
                                      <option value="on">On</option>
                                      <option value="off">Off</option>
                                    </select>
                                  ) : s.choices?.length ? (
                                    <select
                                      value={String(value ?? "")}
                                      onChange={(e) =>
                                        setSolaarValues({
                                          ...solaarValues,
                                          [settingId]: e.target.value,
                                        })
                                      }
                                    >
                                      {s.choices.map((c) => (
                                        <option
                                          key={String(
                                            typeof c === "object" ? c.value : c,
                                          )}
                                          value={
                                            typeof c === "object" ? c.value : c
                                          }
                                        >
                                          {typeof c === "object"
                                            ? c.label || c.value
                                            : c}
                                        </option>
                                      ))}
                                    </select>
                                  ) : (
                                    <input
                                      aria-label={settingId}
                                      type={
                                        s.type === "integer" ? "number" : "text"
                                      }
                                      value={String(value ?? "")}
                                      onChange={(e) =>
                                        setSolaarValues({
                                          ...solaarValues,
                                          [settingId]: e.target.value,
                                        })
                                      }
                                    />
                                  )}
                                </label>
                                <button
                                  className="secondary"
                                  disabled={readOnly || busy || !s.writable}
                                  onClick={() =>
                                    configure({
                                      setting: s.name,
                                      ...(s.key ? { key: s.key } : {}),
                                      value:
                                        s.type === "boolean"
                                          ? ["true", "on", "yes", "1"].includes(
                                              String(value).toLowerCase(),
                                            )
                                          : s.type === "integer"
                                            ? Number(value)
                                            : value,
                                    })
                                  }
                                >
                                  Apply
                                </button>
                              </div>
                            );
                          })
                        ) : (
                          <p className="hint">
                            No writable settings were exposed. Upgrade Solaar if
                            this is a newer device.
                          </p>
                        )}
                      </>
                    ) : (
                      <>
                        <div className="stat-row">
                          <span>Backend</span>
                          <strong>{selected.backend}</strong>
                        </div>
                        <div className="stat-row">
                          <span>Hardware profiles</span>
                          <strong>{selected.profiles?.length || 0}</strong>
                        </div>
                        <div className="stat-row">
                          <span>Button mappings</span>
                          <strong>{buttons.length}</strong>
                        </div>
                        <div className="stat-row">
                          <span>Lighting zones</span>
                          <strong>{leds.length}</strong>
                        </div>
                        <p className="hint">
                          Available controls depend on the firmware and Linux
                          driver. Refresh to read current device values.
                        </p>
                      </>
                    )}
                    {readOnlyNote()}
                  </>
                )}
                {tab === "onboard" && (
                  <>
                    <p className="eyebrow">ON-BOARD MEMORY</p>
                    <h2>DEVICE PROFILES</h2>
                    <p className="muted">
                      These are the hardware profiles reported by ratbagd.
                    </p>
                    {selected.profiles?.length ? (
                      selected.profiles.map((p) => (
                        <div className="hardware-profile" key={p.index}>
                          <div>
                            <h3>{p.name || "Profile " + (p.index + 1)}</h3>
                            <span className="muted">
                              {p.reportRate ? `${p.reportRate} Hz · ` : ""}
                              {p.resolutions?.length || 0} DPI stages
                            </span>
                          </div>
                          <button
                            className={p.active ? "secondary" : "primary"}
                            disabled={readOnly || busy || p.active}
                            onClick={() =>
                              configure({
                                profile: p.index,
                                activateProfile: true,
                              })
                            }
                          >
                            {p.active ? "Active" : "Activate"}
                          </button>
                        </div>
                      ))
                    ) : (
                      <p className="hint">
                        The driver does not expose on-board profiles for this
                        device.
                      </p>
                    )}
                    {readOnlyNote()}
                  </>
                )}
              </div>
            </section>
          </div>
        </main>
      )}
      {page === "profiles" && (
        <main className="standard-page">
          <PageTitle
            eyebrow="GAMES & APPLICATIONS"
            title="PROFILES"
            actions={
              <>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    perform(async () => {
                      const r = await window.ggHub?.exportProfiles();
                      if (!r)
                        throw new Error(
                          "Export is available in the desktop app.",
                        );
                      return r;
                    }, "Export finished.")
                  }
                >
                  <Download size={16} /> Export
                </button>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => setModal("import")}
                >
                  <Upload size={16} /> Import
                </button>
                <button className="primary" onClick={() => openProfile()}>
                  <Plus size={16} /> New profile
                </button>
              </>
            }
          />
          <p className="muted">
            Keep settings for each game. Automatic switching is available on
            X11.
          </p>
          <div className="profile-grid">
            {profiles.map((p) => (
              <article
                className={
                  "profile-card " + (activeId === p.id ? "active" : "")
                }
                key={p.id}
              >
                <div className="profile-card-top">
                  <Gamepad2 size={32} />
                  {activeId === p.id && <span className="pill">ACTIVE</span>}
                </div>
                <p className="eyebrow">{p.game || "DESKTOP"}</p>
                <h2>{p.name}</h2>
                <p className="muted">
                  {p.executable || "Default desktop profile"}
                </p>
                <p className="hint">
                  {Object.keys(p.deviceSettings || {}).length} saved device
                  configuration(s)
                </p>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={busy || activeId === p.id}
                    onClick={() => activate(p)}
                  >
                    Activate
                  </button>
                  <button className="secondary" onClick={() => openProfile(p)}>
                    Edit
                  </button>
                  <button
                    className="icon"
                    aria-label={"Delete " + p.name}
                    onClick={() =>
                      setModal({
                        kind: "delete",
                        type: "profiles",
                        id: p.id,
                        name: p.name,
                      })
                    }
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              </article>
            ))}
          </div>
          {!profiles.length && (
            <Empty
              title="Create your first profile"
              text="Save a desktop profile or match one to a game executable."
            />
          )}
          <div className="settings-section inline-section">
            <div>
              <h3>Save current device settings</h3>
              <p className="muted">
                Capture connected ratbagd devices' active DPI and report rate
                into the selected profile.
              </p>
            </div>
            <button
              className="secondary"
              onClick={snapshot}
              disabled={busy || info.preview || !activeProfile}
            >
              <Save size={16} /> Capture settings
            </button>
          </div>
        </main>
      )}
      {page === "macros" && (
        <main className="standard-page">
          <PageTitle
            eyebrow="ASSIGNMENTS"
            title="MACROS"
            actions={
              <button
                className="primary"
                onClick={() => {
                  setMacroDraft({
                    name: "",
                    mode: "noRepeat",
                    steps: [{ type: "key", key: "KEY_A", action: "tap" }],
                  });
                  setModal("macro");
                }}
              >
                <Plus size={16} /> Create macro
              </button>
            }
          />
          <p className="muted">
            Build key sequences with delays. Linux execution uses uinput and
            requires permission.
          </p>
          <div className="macro-list">
            {macros.map((m) => {
              const run = runs.find((r) => r.id === m.id);
              return (
                <article className="macro-card" key={m.id}>
                  <Command size={28} />
                  <div className="grow">
                    <h3>{m.name}</h3>
                    <p className="muted">
                      {m.steps.length} steps · {titleCase(m.mode)}
                      {run ? " · " + run.state : ""}
                    </p>
                    {run?.error && <p className="error-text">{run.error}</p>}
                  </div>
                  <button
                    className="secondary"
                    onClick={() => {
                      setMacroDraft({
                        ...m,
                        steps: m.steps.map((s) => ({ ...s })),
                      });
                      setModal("macro");
                    }}
                  >
                    Edit
                  </button>
                  {run?.state === "running" ? (
                    <button
                      className="danger"
                      onClick={() =>
                        perform(
                          () => call("macros.stop", { id: m.id }),
                          "Macro stopped.",
                        )
                      }
                    >
                      <Square size={15} /> Stop
                    </button>
                  ) : (
                    <button
                      className="primary"
                      disabled={info.preview || busy}
                      onClick={async () => {
                        await perform(
                          () => call("macros.run", { id: m.id }),
                          "Macro started.",
                        );
                        await refresh();
                      }}
                    >
                      <Play size={15} /> Run
                    </button>
                  )}
                  <button
                    className="icon"
                    aria-label={"Delete " + m.name}
                    onClick={() =>
                      setModal({
                        kind: "delete",
                        type: "macros",
                        id: m.id,
                        name: m.name,
                      })
                    }
                  >
                    <Trash2 size={18} />
                  </button>
                </article>
              );
            })}
          </div>
          {!macros.length && (
            <Empty
              title="Create a macro"
              text="Combine key presses, text and timing into a reusable sequence."
            />
          )}
          <p className="hint">
            Text steps use a US ASCII layout. Sequence mode plays the steps
            once. Repeating macros stop at the configured time limit.
          </p>
        </main>
      )}
      {page === "settings" && (
        <main className="standard-page">
          <PageTitle eyebrow="GG HUB" title="SETTINGS" />
          <section className="settings-section">
            <h3>Linux device services</h3>
            <p className="muted">
              Install the Arch packages, reconnect your devices, then refresh.
              Run GG HUB as your normal user.
            </p>
            <pre className="command">
              sudo pacman -S libratbag solaar python-dbus-next python-evdev
              xorg-xprop
            </pre>
            <p className="hint">
              ratbagd is D-Bus activated. Solaar supplies device permission
              rules. Macro execution needs access to /dev/uinput; see the
              installation guide.
            </p>
            <div className="actions">
              <button className="primary" onClick={() => link("guide")}>
                Installation guide <ExternalLink size={14} />
              </button>
              <button className="secondary" onClick={refresh} disabled={busy}>
                <RefreshCw size={15} /> Recheck
              </button>
            </div>
            <details>
              <summary>Driver diagnostics</summary>
              <pre>
                {JSON.stringify({ status, discovery: diagnostics }, null, 2)}
              </pre>
            </details>
          </section>
          <section className="settings-section">
            <div className="inline-section">
              <div>
                <h3>Automatic profile switching</h3>
                <p className="muted">
                  Match the foreground X11 executable to a game profile.
                </p>
              </div>
              <button
                className={automation?.running ? "secondary" : "primary"}
                disabled={info.preview || busy}
                onClick={async () => {
                  await perform(
                    () =>
                      call(
                        automation?.running
                          ? "automation.stop"
                          : "automation.start",
                      ),
                    automation?.running
                      ? "Automatic switching stopped."
                      : "Automatic switching started.",
                  );
                  await refresh();
                }}
              >
                {automation?.running ? "Stop" : "Start"}
              </button>
            </div>
            <p className="hint">
              {automation?.protocol || "Unknown session"} ·{" "}
              {automation?.running ? "Running" : "Stopped"}
              {automation?.lastError ? " · " + automation.lastError : ""}
            </p>
            <p className="hint">
              Wayland foreground detection is not implemented. Manual profiles
              and hardware settings remain available.
            </p>
          </section>
          <section className="settings-section">
            <h3>Macro execution limit</h3>
            <label className="field short">
              <span>Maximum run time (seconds)</span>
              <input
                aria-label="Macro timeout"
                type="number"
                min="1"
                max="300"
                value={settings.macroTimeoutSeconds || 30}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    macroTimeoutSeconds: Number(e.target.value),
                  })
                }
              />
            </label>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                updateSetting({
                  macroTimeoutSeconds: settings.macroTimeoutSeconds,
                })
              }
            >
              Save preference
            </button>
          </section>
          <section className="settings-section inline-section">
            <div>
              <h3>GG HUB {info.version}</h3>
              <p className="muted">
                Independent Linux implementation. Driver support varies by
                device.
              </p>
            </div>
            <button className="secondary" onClick={() => link("repository")}>
              GitHub <ExternalLink size={15} />
            </button>
          </section>
        </main>
      )}
      {page === "compatibility" && (
        <main className="standard-page">
          <PageTitle eyebrow="REFERENCE CATALOG" title="MICE & KEYBOARDS" />
          <p className="muted">
            Observed product metadata from the reference app. A catalog entry
            does not guarantee Linux support.
          </p>
          <div className="search">
            <Search size={18} />
            <input
              aria-label="Search devices"
              placeholder="Search model or USB ID"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <p className="hint">
            {catalog.devices?.length || 0} known products · catalog coverage is{" "}
            {catalog.coverage?.complete ? "complete" : "partial"}. Connected
            controls are discovered live.
          </p>
          <div className="catalog-table">
            <div className="catalog-row table-head">
              <span>DEVICE</span>
              <span>TYPE</span>
              <span>LINUX STATUS</span>
            </div>
            {(catalog.devices || [])
              .filter((d) =>
                (d.name + " " + d.modelId + " " + d.interfaceIds?.join(" "))
                  .toLowerCase()
                  .includes(query.toLowerCase()),
              )
              .map((d) => (
                <div className="catalog-row" key={d.modelId}>
                  <span>
                    <strong>{d.name}</strong>
                    <small>{d.modelId}</small>
                  </span>
                  <span>{d.type === "KEYBOARD" ? "Keyboard" : "Mouse"}</span>
                  <span className="muted">Requires device detection</span>
                </div>
              ))}
          </div>
        </main>
      )}
      <footer className="status-bar">
        <span
          className={
            "dot " +
            (!info.preview && devices.some((d) => d.supported) ? "online" : "")
          }
        />
        <span>
          {info.preview
            ? "DESIGN PREVIEW · no hardware control"
            : info.platform === "linux"
              ? `${devices.filter((d) => d.supported).length} configurable device(s)`
              : "Linux hardware service requires Linux"}
        </span>
        <button onClick={() => go("settings")}>GG HUB {info.version}</button>
      </footer>
      {toast && (
        <div role="status" className={"toast " + (toast.error ? "error" : "")}>
          <AlertCircle size={18} />
          <span>{toast.message}</span>
          <button
            className="icon"
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setModal(null);
          }}
        >
          <section
            className={"modal " + (modal === "macro" ? "wide" : "")}
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "macro"
                ? "Macro editor"
                : modal === "profile"
                  ? "Profile editor"
                  : modal === "about"
                    ? "About GG HUB"
                    : "Confirm action"
            }
          >
            <button
              className="modal-close icon"
              aria-label="Close dialog"
              onClick={() => setModal(null)}
            >
              <X size={20} />
            </button>
            {modal === "profile" && (
              <form onSubmit={saveProfile}>
                <p className="eyebrow">GAMES & APPLICATIONS</p>
                <h2>{profileDraft.id ? "EDIT PROFILE" : "NEW PROFILE"}</h2>
                <label className="field">
                  <span>Profile name</span>
                  <input
                    autoFocus
                    required
                    maxLength={80}
                    value={profileDraft.name}
                    onChange={(e) =>
                      setProfileDraft({ ...profileDraft, name: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Game / application</span>
                  <input
                    maxLength={120}
                    placeholder="Desktop"
                    value={profileDraft.game || ""}
                    onChange={(e) =>
                      setProfileDraft({ ...profileDraft, game: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Executable name for automatic switching</span>
                  <input
                    placeholder="e.g. cs2"
                    value={profileDraft.executable || ""}
                    onChange={(e) =>
                      setProfileDraft({
                        ...profileDraft,
                        executable: e.target.value,
                      })
                    }
                  />
                </label>
                <p className="hint">
                  Use an executable name, not a launch command. Leave blank for
                  a desktop profile.
                </p>
                <button className="primary" type="submit" disabled={busy}>
                  Save profile
                </button>
              </form>
            )}
            {modal === "macro" && (
              <form onSubmit={saveMacro}>
                <p className="eyebrow">MACRO EDITOR</p>
                <h2>{macroDraft.id ? "EDIT MACRO" : "CREATE A MACRO"}</h2>
                <div className="form-row">
                  <label className="field">
                    <span>Name</span>
                    <input
                      autoFocus
                      required
                      maxLength={80}
                      value={macroDraft.name}
                      onChange={(e) =>
                        setMacroDraft({ ...macroDraft, name: e.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Playback mode</span>
                    <select
                      value={macroDraft.mode}
                      onChange={(e) =>
                        setMacroDraft({ ...macroDraft, mode: e.target.value })
                      }
                    >
                      <option value="noRepeat">No repeat</option>
                      <option value="repeat">Repeat until limit</option>
                      <option value="toggle">Toggle</option>
                      <option value="sequence">Sequence (once)</option>
                    </select>
                  </label>
                </div>
                <div className="macro-steps">
                  {macroDraft.steps.map((s, i) => (
                    <div className="macro-step" key={i}>
                      <span className="step-number">{i + 1}</span>
                      <select
                        aria-label={"Step " + (i + 1) + " type"}
                        value={s.type}
                        onChange={(e) =>
                          setMacroDraft({
                            ...macroDraft,
                            steps: macroDraft.steps.map((v, j) =>
                              j !== i
                                ? v
                                : e.target.value === "delay"
                                  ? { type: "delay", ms: 100 }
                                  : e.target.value === "text"
                                    ? { type: "text", text: "" }
                                    : {
                                        type: "key",
                                        key: "KEY_A",
                                        action: "tap",
                                      },
                            ),
                          })
                        }
                      >
                        <option value="key">Key</option>
                        <option value="delay">Delay</option>
                        <option value="text">Text</option>
                      </select>
                      {s.type === "key" ? (
                        <>
                          <input
                            aria-label={"Step " + (i + 1) + " key"}
                            value={s.key}
                            onChange={(e) =>
                              setMacroDraft({
                                ...macroDraft,
                                steps: macroDraft.steps.map((v, j) =>
                                  j === i ? { ...v, key: e.target.value } : v,
                                ),
                              })
                            }
                          />
                          <select
                            value={s.action}
                            aria-label={"Step " + (i + 1) + " action"}
                            onChange={(e) =>
                              setMacroDraft({
                                ...macroDraft,
                                steps: macroDraft.steps.map((v, j) =>
                                  j === i
                                    ? { ...v, action: e.target.value }
                                    : v,
                                ),
                              })
                            }
                          >
                            <option value="tap">Press & release</option>
                            <option value="down">Press</option>
                            <option value="up">Release</option>
                          </select>
                        </>
                      ) : (
                        <input
                          aria-label={"Step " + (i + 1) + " value"}
                          type={s.type === "delay" ? "number" : "text"}
                          min="0"
                          max={s.type === "delay" ? 60000 : undefined}
                          value={s.type === "delay" ? s.ms : s.text}
                          placeholder={
                            s.type === "delay"
                              ? "Milliseconds"
                              : "US ASCII text"
                          }
                          onChange={(e) =>
                            setMacroDraft({
                              ...macroDraft,
                              steps: macroDraft.steps.map((v, j) =>
                                j !== i
                                  ? v
                                  : {
                                      ...v,
                                      [s.type === "delay" ? "ms" : "text"]:
                                        s.type === "delay"
                                          ? Number(e.target.value)
                                          : e.target.value,
                                    },
                              ),
                            })
                          }
                        />
                      )}
                      <button
                        type="button"
                        className="icon"
                        aria-label={"Delete step " + (i + 1)}
                        onClick={() =>
                          setMacroDraft({
                            ...macroDraft,
                            steps: macroDraft.steps.filter((_v, j) => j !== i),
                          })
                        }
                      >
                        <X size={17} />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      setMacroDraft({
                        ...macroDraft,
                        steps: [
                          ...macroDraft.steps,
                          { type: "key", key: "KEY_A", action: "tap" },
                        ],
                      })
                    }
                  >
                    <Plus size={16} /> Add step
                  </button>
                  <button
                    type="submit"
                    className="primary"
                    disabled={busy || !macroDraft.steps.length}
                  >
                    Save macro
                  </button>
                </div>
                <p className="hint">
                  Key names: KEY_A, KEY_LEFTCTRL, KEY_F1, BTN_LEFT. Linux sends
                  real input when Run is pressed.
                </p>
              </form>
            )}
            {modal === "about" && (
              <>
                <span className="about-logo">GG</span>
                <h2>GG HUB</h2>
                <p className="muted">
                  Logitech gaming device configuration for Linux.
                </p>
                <p className="hint">
                  Independent project. Not affiliated with Logitech. Original UI
                  structure was used as a reference; artwork and application
                  code are independently implemented.
                </p>
                <div className="actions">
                  <button
                    className="primary"
                    onClick={() => link("repository")}
                  >
                    View on GitHub <ExternalLink size={16} />
                  </button>
                  <button
                    className="secondary"
                    onClick={() => {
                      setModal(null);
                      go("compatibility");
                    }}
                  >
                    Device catalog
                  </button>
                </div>
              </>
            )}
            {modal === "import" && (
              <>
                <h2>IMPORT PROFILES</h2>
                <p className="muted">
                  Import replaces your saved profiles, macros and preferences.
                  Active macros and automatic switching will stop.
                </p>
                <p className="hint">
                  Choose a GG HUB JSON export. Original G HUB databases are not
                  compatible.
                </p>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={async () => {
                    const r = await perform(async () => {
                      if (!window.ggHub || info.preview)
                        throw new Error("Import requires the desktop app.");
                      return window.ggHub.importProfiles();
                    });
                    if (r && !r.canceled) {
                      setModal(null);
                      notify("Profiles imported.");
                      await refresh();
                    }
                  }}
                >
                  Choose export file
                </button>
              </>
            )}
            {modal?.kind === "delete" && (
              <>
                <h2>
                  DELETE {modal.type === "profiles" ? "PROFILE" : "MACRO"}?
                </h2>
                <p className="muted">Delete “{modal.name}” from GG HUB?</p>
                <div className="actions">
                  <button className="secondary" onClick={() => setModal(null)}>
                    Cancel
                  </button>
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={() => remove(modal.type, modal.id)}
                  >
                    Delete
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
function PageTitle({ eyebrow, title, actions }) {
  return (
    <div className="page-title">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      <div className="actions">{actions}</div>
    </div>
  );
}
function Empty({ title, text }) {
  return (
    <div className="empty">
      <Command size={46} strokeWidth={1} />
      <h2>{title}</h2>
      <p className="muted">{text}</p>
    </div>
  );
}
