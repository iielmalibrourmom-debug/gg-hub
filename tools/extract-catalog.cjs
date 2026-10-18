#!/usr/bin/env node
"use strict";

// Extract factual device declarations only. No original code, artwork, keys or
// user settings are copied. This program does not execute G HUB or contact USB.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const sha256 = (data) => crypto.createHash("sha256").update(data).digest("hex");
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function argumentsFrom(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const option = argv[i];
    if (option === "--help" || option === "-h") {
      console.log(
        "Usage: node tools/extract-catalog.cjs --source <core/data> --output <catalog.json> [--source-version <version>] [--build-id <id>]",
      );
      return null;
    }
    const names = {
      "--source": "source",
      "--output": "output",
      "--source-version": "version",
      "--build-id": "buildId",
    };
    if (!own(names, option) || !argv[i + 1] || argv[i + 1].startsWith("--")) {
      throw new Error(`Unknown option or missing value: ${option}`);
    }
    options[names[option]] = argv[++i];
  }
  if (!options.source || !options.output)
    throw new Error("--source and --output are required.");
  return options;
}

function primitive(value) {
  return (
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value)) ||
    (typeof value === "string" && /^[A-Za-z0-9_.:+# -]{1,100}$/.test(value))
  );
}

function factualValue(value, depth = 0) {
  if (depth > 5) return undefined;
  if (primitive(value)) return value;
  if (Array.isArray(value))
    return value
      .slice(0, 256)
      .map((v) => factualValue(v, depth + 1))
      .filter((v) => v !== undefined);
  if (value && typeof value === "object") {
    const result = {};
    for (const [key, child] of Object.entries(value)) {
      if (
        /^(image|thumbnail|icon|render|displayIcon|slotId|description|label|url|path|serial|key$|script|code)/i.test(
          key,
        )
      )
        continue;
      const clean = factualValue(child, depth + 1);
      if (clean !== undefined) result[key] = clean;
    }
    return result;
  }
  return undefined;
}

function settingsFrom(capabilities) {
  const settings = {};
  const mapping = {
    dpiInfoOverride: "dpiInfo",
    dpiTableOverride: "dpiTable",
    reportRatesOverride: "reportRateInfo",
    onboardProfiles: "onboardProfiles",
    receiverPairing: "receiverPairing",
    scrollControls: "scrollControls",
    mouseButtonControls: "mouseButtonControls",
    mstateSupport: "modeState",
    angleSnapping: "angleSnapping",
    fnInversion: "fnInversion",
    hasBatteryStatus: "batteryStatus",
    unifiedBattery: "unifiedBattery",
    chargepadCompatible: "chargepadCompatible",
    wirelessReportRate: "wirelessReportRate",
    hostRemovalSupport: "hostRemovalSupport",
    hybridEngine: "hybridEngine",
  };
  for (const [source, target] of Object.entries(mapping)) {
    if (own(capabilities, source))
      settings[target] = factualValue(capabilities[source]);
  }
  if (capabilities.dpiInfoOverride?.range)
    settings.dpiRange = factualValue(capabilities.dpiInfoOverride.range);
  if (capabilities.dpiTableOverride?.levels)
    settings.dpiLevels = factualValue(capabilities.dpiTableOverride.levels);
  if (capabilities.reportRatesOverride?.rates)
    settings.reportRates = factualValue(capabilities.reportRatesOverride.rates);
  if (capabilities.onboardProfiles?.supportsOnboardMode !== undefined)
    settings.onboardMode = capabilities.onboardProfiles.supportsOnboardMode;
  if (capabilities.inputSupport) {
    const input = capabilities.inputSupport;
    settings.supportedInputCategories = factualValue(
      input.supportedCategories || [],
    );
    settings.supportedLayers = factualValue(input.supportedLayers || []);
    if (typeof input.supportsLayerConfiguration === "boolean")
      settings.layerConfiguration = input.supportsLayerConfiguration;
  }
  const lighting = capabilities.lightingSupport;
  settings.supportedEffects = [];
  settings.lightingZones = [];
  if (lighting) {
    if (primitive(lighting.deviceCategory))
      settings.lightingCategory = lighting.deviceCategory;
    if (typeof lighting.isPerKey === "boolean")
      settings.perKeyLighting = lighting.isPerKey;
    const effects = new Set();
    for (const zone of lighting.zones || []) {
      const zoneEffects = (zone.supportedEffects || [])
        .map((e) => e.id)
        .filter(primitive);
      for (const effect of zoneEffects) effects.add(effect);
      settings.lightingZones.push({
        type: zone.zoneType || null,
        supportedEffects: zoneEffects,
      });
    }
    settings.supportedEffects = [...effects].sort();
  }
  return settings;
}

function deviceFrom(source, sourceFile) {
  const interfaces = [];
  const variants = new Map();
  for (const mode of source.modes || []) {
    for (const iface of mode.interfaces || []) {
      const item = {};
      for (const key of [
        "type",
        "id",
        "usagePage",
        "usage",
        "interfaceNumber",
        "reportId",
      ]) {
        if (primitive(iface[key])) item[key] = iface[key];
      }
      if (Object.keys(item).length) interfaces.push(item);
      for (const variant of iface.derivatives || []) {
        if (typeof variant.modelId !== "string") continue;
        const entry = {
          modelId: variant.modelId,
          name:
            variant.displayName ||
            variant.extendedDisplayName ||
            variant.modelId,
        };
        for (const key of ["extendedModel", "id"])
          if (primitive(variant[key])) entry[key] = variant[key];
        variants.set(entry.modelId, entry);
      }
    }
  }
  const capabilities = source.capabilities || {};
  return {
    modelId: source.modelId,
    name: source.displayName || source.extendedDisplayName || source.modelId,
    type: source.type,
    catalogKnown: true,
    hardwareSupport: "unverified",
    interfaces: [
      ...new Map(interfaces.map((i) => [JSON.stringify(i), i])).values(),
    ],
    interfaceIds: [
      ...new Set(interfaces.map((i) => i.id).filter(Boolean)),
    ].sort(),
    capabilities: Object.keys(capabilities).sort(),
    settings: settingsFrom(capabilities),
    variants: [...variants.values()].sort((a, b) =>
      a.modelId.localeCompare(b.modelId),
    ),
    source: { file: sourceFile },
  };
}

function extract(options) {
  const root = fs.realpathSync(path.resolve(options.source));
  const inputs = [];
  function read(relative) {
    const absolute = path.resolve(root, relative);
    if (!absolute.startsWith(root + path.sep))
      throw new Error(`Input escapes source directory: ${relative}`);
    if (!fs.existsSync(absolute)) return null;
    const actual = fs.realpathSync(absolute);
    if (!actual.startsWith(root + path.sep))
      throw new Error(`Input symlink escapes source directory: ${relative}`);
    const stat = fs.statSync(actual);
    if (!stat.isFile() || stat.size > 16 * 1024 * 1024)
      throw new Error(`Input is not a bounded file: ${relative}`);
    return fs.readFileSync(actual);
  }
  const indexBytes = read("devices.json");
  if (!indexBytes) throw new Error("Source devices.json does not exist.");
  const index = JSON.parse(indexBytes.toString("utf8"));
  if (!Array.isArray(index.files))
    throw new Error("Source index must contain a files array.");
  inputs.push({
    file: "devices.json",
    size: indexBytes.length,
    sha256: sha256(indexBytes),
    status: "index",
  });
  const devices = new Map();
  const observedTypes = {};
  const coverage = {
    indexedFiles: index.files.length,
    parsedFiles: 0,
    opaqueFiles: [],
    missingFiles: [],
    invalidFiles: [],
    parsedDeviceDeclarations: 0,
    observedTypes,
    selectedTypes: ["MOUSE", "KEYBOARD"],
    catalogKnownCount: 0,
    complete: false,
  };
  for (const reference of index.files) {
    if (
      typeof reference !== "string" ||
      !reference.startsWith("pipeline://core/data/")
    )
      throw new Error("Unexpected source reference scheme.");
    const relative = reference
      .slice("pipeline://core/data/".length)
      .replace(/\\/g, "/");
    const bytes = read(relative);
    if (!bytes) {
      coverage.missingFiles.push(relative);
      inputs.push({ file: relative, status: "missing" });
      continue;
    }
    const entry = {
      file: relative,
      size: bytes.length,
      sha256: sha256(bytes),
      status: "parsed",
    };
    inputs.push(entry);
    let parsed;
    try {
      parsed = JSON.parse(bytes.toString("utf8").replace(/^\uFEFF/, ""));
    } catch {
      entry.status = "opaque";
      const info = {
        file: relative,
        reason: "Non-JSON envelope; decoding not implemented.",
      };
      if (
        bytes.length >= 8 &&
        bytes.subarray(0, 4).toString("hex") === "21052120"
      ) {
        info.envelopeMagic = "21052120";
        const headerLength = bytes.readUInt32LE(4);
        if (headerLength <= bytes.length - 8 && headerLength < 65536) {
          try {
            const header = JSON.parse(
              bytes.subarray(8, 8 + headerLength).toString("utf8"),
            );
            info.headerFields = Object.keys(header).sort();
            // Intentionally omit local asset key identifiers and all key values.
          } catch {
            info.headerParseFailed = true;
          }
        }
      }
      coverage.opaqueFiles.push(info);
      continue;
    }
    if (!Array.isArray(parsed.devices)) {
      entry.status = "invalid";
      coverage.invalidFiles.push(relative);
      continue;
    }
    coverage.parsedFiles++;
    for (const device of parsed.devices) {
      coverage.parsedDeviceDeclarations++;
      observedTypes[device.type || "UNKNOWN"] =
        (observedTypes[device.type || "UNKNOWN"] || 0) + 1;
      if (
        !coverage.selectedTypes.includes(device.type) ||
        typeof device.modelId !== "string"
      )
        continue;
      if (devices.has(device.modelId))
        throw new Error(`Duplicate modelId: ${device.modelId}`);
      devices.set(device.modelId, deviceFrom(device, relative));
    }
  }
  const selected = [...devices.values()].sort(
    (a, b) => a.type.localeCompare(b.type) || a.name.localeCompare(b.name),
  );
  coverage.catalogKnownCount = selected.length;
  coverage.complete =
    coverage.opaqueFiles.length === 0 &&
    coverage.missingFiles.length === 0 &&
    coverage.invalidFiles.length === 0;
  const sourceDigest = sha256(
    inputs
      .map((i) => `${i.file}\0${i.sha256 || "MISSING"}\n`)
      .sort()
      .join(""),
  );
  const catalog = {
    schemaVersion: 1,
    metadata: {
      generatedAt: new Date().toISOString(),
      sourceProduct: "Logitech G HUB",
      sourceVersion: options.version || null,
      sourceBuildId: options.buildId || null,
      extractorVersion: "1.0.0",
      sourceDigestAlgorithm:
        "sha256(relative-path + NUL + file-sha256 + LF; sorted)",
      sourceDigest,
      sourceIndexSha256: sha256(indexBytes),
      classification:
        "Static catalog facts; catalogKnown is not Linux hardware support.",
      hardwareValidatedCount: 0,
      inputs,
    },
    coverage,
    devices: selected,
  };
  fs.mkdirSync(path.dirname(path.resolve(options.output)), { recursive: true });
  fs.writeFileSync(options.output, JSON.stringify(catalog, null, 2) + "\n");
  return catalog;
}

if (require.main === module) {
  try {
    const options = argumentsFrom(process.argv.slice(2));
    if (options) {
      const catalog = extract(options);
      console.log(
        JSON.stringify({
          catalogKnown: catalog.devices.length,
          types: catalog.coverage.observedTypes,
          complete: catalog.coverage.complete,
          parsedFiles: catalog.coverage.parsedFiles,
          opaqueFiles: catalog.coverage.opaqueFiles.length,
          missingFiles: catalog.coverage.missingFiles.length,
          sourceDigest: catalog.metadata.sourceDigest,
        }),
      );
    }
  } catch (error) {
    console.error(`Catalog extraction failed: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = { extract, deviceFrom, settingsFrom };
