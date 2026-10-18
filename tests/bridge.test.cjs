const { test } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough, Writable } = require("node:stream");
const { WorkerBridge } = require("../electron/bridge.cjs");
function fixture() {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.sent = [];
  child.stdin = new Writable({
    write(chunk, _encoding, done) {
      child.sent.push(JSON.parse(chunk.toString()));
      done();
    },
  });
  child.kill = () => child.emit("exit", 0);
  const bridge = new WorkerBridge({
    python: "python3",
    backendPath: ".",
    configDir: ".",
    timeout: 40,
    spawnProcess: () => child,
  });
  return { child, bridge };
}
test("out-of-order replies resolve the matching request, not the last request", async () => {
  const { child, bridge } = fixture();
  const a = bridge.request("profiles.list");
  const b = bridge.request("macros.list");
  child.stdout.write(
    JSON.stringify({ id: 2, result: { macros: [] } }) +
      "\n" +
      JSON.stringify({ id: 1, result: { profiles: [] } }) +
      "\n",
  );
  assert.deepEqual(await a, { profiles: [] });
  assert.deepEqual(await b, { macros: [] });
  child.emit("exit", 0);
});
test("unavailable workers reject outstanding requests without leaking stderr", async () => {
  const { child, bridge } = fixture();
  const result = bridge.request("profiles.list");
  child.stderr.write("private host details");
  child.emit("error", new Error("sensitive path"));
  await assert.rejects(
    result,
    (e) => e.code === "BACKEND_UNAVAILABLE" && !e.message.includes("sensitive"),
  );
});
test("device error is preserved and never treated as a saved result", async () => {
  const { child, bridge } = fixture();
  const p = bridge.request("hardware.configure", {
    deviceId: "missing",
    dpi: 800,
  });
  child.stdout.write(
    JSON.stringify({
      id: 1,
      error: { code: "DEVICE_NOT_FOUND", message: "Device disconnected." },
    }) + "\n",
  );
  await assert.rejects(p, (e) => e.code === "DEVICE_NOT_FOUND");
  child.emit("exit", 0);
});
test("timeout cannot be satisfied by a stale late response", async () => {
  const { child, bridge } = fixture();
  const p = bridge.request("profiles.list");
  await assert.rejects(p, (e) => e.code === "BACKEND_TIMEOUT");
  child.stdout.write(
    JSON.stringify({ id: 1, result: { profiles: ["wrong"] } }) + "\n",
  );
  assert.equal(bridge.pending.size, 0);
  child.emit("exit", 0);
});
test("methods and oversized payloads are rejected before spawning a process", async () => {
  let spawned = false;
  const bridge = new WorkerBridge({
    spawnProcess: () => {
      spawned = true;
      throw new Error("should not spawn");
    },
  });
  await assert.rejects(bridge.request("shell.run", { command: "bad" }));
  await assert.rejects(
    bridge.request("profiles.import", { document: "x".repeat(1024 * 1024) }),
  );
  assert.equal(spawned, false);
});
test("shutdown waits for the backend and rejects new requests", async () => {
  const { child, bridge } = fixture();
  const p = bridge.request("macros.list");
  const rejected = assert.rejects(p, (e) => e.code === "SHUTDOWN");
  const stop = bridge.stop();
  assert.equal(bridge.stop(), stop);
  await assert.rejects(bridge.request("profiles.list"));
  child.emit("exit", 0);
  await stop;
  await rejected;
  assert.equal(bridge.pending.size, 0);
});
