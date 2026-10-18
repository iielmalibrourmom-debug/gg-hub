"use strict";
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const METHODS = new Set([
  "hardware.status",
  "hardware.devices",
  "hardware.configure",
  "profiles.list",
  "profiles.save",
  "profiles.delete",
  "profiles.activate",
  "profiles.export",
  "profiles.import",
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
]);
class WorkerBridge {
  constructor({
    python,
    backendPath,
    configDir,
    spawnProcess = spawn,
    timeout = 25000,
  }) {
    this.options = { python, backendPath, configDir, spawnProcess, timeout };
    this.pending = new Map();
    this.sequence = 0;
    this.child = null;
    this.stopping = false;
  }
  start() {
    if (this.child) return;
    const { python, backendPath, configDir, spawnProcess } = this.options;
    const child = spawnProcess(python, ["-u", "-m", "gg_hub.worker"], {
      cwd: backendPath,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        GG_HUB_CONFIG_DIR: configDir,
        PYTHONUNBUFFERED: "1",
      },
    });
    this.child = child;
    // Never forward raw device output, identifiers or host paths into the renderer.
    child.stderr.on("data", () => {});
    const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
    lines.on("line", (line) => {
      if (line.length > 2 * 1024 * 1024) {
        this.fail(
          "BACKEND_PROTOCOL",
          "Backend response exceeded the size limit.",
        );
        return;
      }
      let reply;
      try {
        reply = JSON.parse(line);
      } catch {
        this.fail("BACKEND_PROTOCOL", "Backend returned invalid JSON.");
        return;
      }
      const task = this.pending.get(reply.id);
      if (!task) return;
      clearTimeout(task.timer);
      this.pending.delete(reply.id);
      if (reply.error)
        task.reject(
          Object.assign(
            new Error(reply.error.message || "Device operation failed."),
            { code: reply.error.code || "BACKEND_ERROR" },
          ),
        );
      else if (Object.hasOwn(reply, "result")) task.resolve(reply.result);
      else
        task.reject(
          Object.assign(new Error("Incomplete backend response."), {
            code: "BACKEND_PROTOCOL",
          }),
        );
    });
    child.on("error", () => {
      this.fail(
        "BACKEND_UNAVAILABLE",
        "Python backend could not start. Install the Linux dependencies listed in Settings.",
      );
      if (this.child === child) this.child = null;
    });
    child.on("exit", () => {
      this.fail(
        "BACKEND_EXITED",
        "The device backend stopped. Refresh to reconnect.",
      );
      if (this.child === child) this.child = null;
      lines.close();
    });
  }
  fail(code, message) {
    for (const task of this.pending.values()) {
      clearTimeout(task.timer);
      task.reject(Object.assign(new Error(message), { code }));
    }
    this.pending.clear();
  }
  request(method, params = {}) {
    if (!METHODS.has(method))
      return Promise.reject(
        Object.assign(new Error("Unsupported operation."), {
          code: "INVALID_METHOD",
        }),
      );
    if (
      params === null ||
      typeof params !== "object" ||
      Array.isArray(params) ||
      Buffer.byteLength(JSON.stringify(params)) > 1024 * 1024
    )
      return Promise.reject(
        Object.assign(new Error("Invalid request parameters."), {
          code: "INVALID_PARAMS",
        }),
      );
    if (this.stopping)
      return Promise.reject(new Error("Application is closing."));
    this.start();
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timeout =
        method === "hardware.configure" || method === "profiles.activate"
          ? 65000
          : method === "hardware.devices"
            ? 30000
            : method === "hardware.status"
              ? 15000
              : this.options.timeout;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          Object.assign(
            new Error(
              "Backend timed out. Hardware state is unknown; refresh before retrying.",
            ),
            { code: "BACKEND_TIMEOUT" },
          ),
        );
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(
        JSON.stringify({ id, method, params }) + "\n",
        (err) => {
          if (err) {
            clearTimeout(timer);
            this.pending.delete(id);
            reject(
              Object.assign(new Error("Backend connection closed."), {
                code: "BACKEND_EXITED",
              }),
            );
          }
        },
      );
    });
  }
  stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    this.fail("SHUTDOWN", "Application is closing.");
    const child = this.child;
    if (!child) return Promise.resolve();
    this.stopPromise = new Promise((resolve) => {
      let done = false,
        killTimer,
        deadline;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(killTimer);
        clearTimeout(deadline);
        resolve();
      };
      child.once("exit", finish);
      child.once("error", finish);
      killTimer = setTimeout(() => child.kill(), 1500);
      deadline = setTimeout(finish, 3500);
      child.stdin.end();
    });
    return this.stopPromise;
  }
}
module.exports = { WorkerBridge, METHODS };
