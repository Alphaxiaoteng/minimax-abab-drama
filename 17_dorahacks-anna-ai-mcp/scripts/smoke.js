"use strict";
// NetIntel MCP end-to-end smoke test: spawns the built CLI over stdio, drives the full
// JSON-RPC lifecycle with newline-delimited JSON, asserts each step, exits non-zero on failure.
// Zero dependencies, CommonJS. Requires `npm run build` (or NETINTEL_SMOKE_BIN) beforehand.

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const REPO_ROOT = path.resolve(__dirname, "..");
const CLI_BIN = process.env.NETINTEL_SMOKE_BIN || path.join(REPO_ROOT, "dist", "src", "cli.js");
const FIXTURE_DIR = process.env.NETINTEL_FIXTURE_DIR || path.join(REPO_ROOT, "fixtures", "feeds");
const STEP_TIMEOUT_MS = 5000;
const EXIT_TIMEOUT_MS = 5000;
const GLOBAL_WATCHDOG_MS = 60000;
const SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];

const results = [];
let child = null;
let childExited = false;
let shutdownRequested = false;
const stderrTail = [];

function record(name, ok, observed) {
  results.push({ name, ok, observed });
}

function printTable() {
  const width = Math.max(4, ...results.map((r) => r.name.length));
  console.log("");
  console.log("STEP  " + "NAME".padEnd(width) + "  STATUS  OBSERVED");
  results.forEach((r, i) => {
    console.log(
      String(i + 1).padStart(4) + "  " + r.name.padEnd(width) + "  " + (r.ok ? "PASS" : "FAIL").padEnd(6) + "  " + r.observed
    );
  });
}

function dumpStderr() {
  for (const line of stderrTail) console.error(line);
}

function killChild() {
  if (child && !childExited && child.exitCode === null) {
    try {
      child.kill("SIGKILL");
    } catch (err) {
      void err;
    }
  }
}

function fail(reason) {
  record("ABORT", false, reason);
  printTable();
  dumpStderr();
  killChild();
  process.exitCode = 1;
  setTimeout(() => process.exit(1), 50);
}

// ---------------------------------------------------------------------- transport

const listeners = new Map(); // requestId -> {resolve, timer}
let stdoutBuf = "";
let nextId = 1;

function deliverMessage(msg) {
  if (msg && typeof msg === "object" && "id" in msg && msg.id !== undefined) {
    const listener = listeners.get(msg.id);
    if (listener) {
      listeners.delete(msg.id);
      clearTimeout(listener.timer);
      listener.resolve(msg);
      return;
    }
  }
  // Unsolicited notifications (logging/progress/resources-updated) are tolerated.
}

function attachStream(childProc) {
  childProc.stdout.setEncoding("utf8");
  childProc.stdout.on("data", (chunk) => {
    stdoutBuf += chunk;
    let nl = stdoutBuf.indexOf("\n");
    while (nl >= 0) {
      const line = stdoutBuf.slice(0, nl).replace(/\r$/, "").trim();
      stdoutBuf = stdoutBuf.slice(nl + 1);
      if (line.length > 0) {
        let parsed;
        try {
          parsed = JSON.parse(line);
        } catch (err) {
          void err;
          fail("server emitted non-JSON line on stdout: " + line.slice(0, 120));
          return;
        }
        deliverMessage(parsed);
      }
      nl = stdoutBuf.indexOf("\n");
    }
  });
  childProc.stderr.setEncoding("utf8");
  childProc.stderr.on("data", (chunk) => {
    for (const l of String(chunk).split("\n").filter((x) => x.length > 0)) {
      stderrTail.push(l);
      if (stderrTail.length > 40) stderrTail.shift();
    }
  });
  childProc.on("exit", (code, signal) => {
    childExited = true;
    if (!shutdownRequested && signal !== "SIGKILL") {
      fail("child exited unexpectedly (code=" + code + " signal=" + signal + ")");
    }
  });
  childProc.on("error", (err) => fail("failed to spawn CLI: " + err.message));
}

function sendRaw(line) {
  if (!child || childExited) fail("child is not running");
  child.stdin.write(line.endsWith("\n") ? line : line + "\n");
}

function request(method, params) {
  const id = nextId++;
  const payload = { jsonrpc: "2.0", id, method };
  if (params !== undefined) payload.params = params;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      listeners.delete(id);
      reject(new Error("timeout after " + STEP_TIMEOUT_MS + "ms waiting for response to " + method + " (id " + id + ")"));
    }, STEP_TIMEOUT_MS);
    listeners.set(id, { resolve, timer });
    sendRaw(JSON.stringify(payload));
  });
}

function waitForId(id, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      listeners.delete(id);
      reject(new Error("timeout after " + timeoutMs + "ms waiting for message with id " + id));
    }, timeoutMs);
    listeners.set(id, { resolve, timer });
  });
}

function assert(cond, message, observedValue) {
  if (!cond) throw new Error(message + (observedValue === undefined ? "" : " — observed: " + observedValue));
}

// ---------------------------------------------------------------------- steps

async function stepInitialize() {
  const res = await request("initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "netintel-smoke", version: "0.0.0" },
  });
  assert(!("error" in res), "initialize returned an error", JSON.stringify(res.error));
  const r = res.result;
  assert(r && typeof r === "object", "initialize result missing");
  assert(SUPPORTED_VERSIONS.includes(r.protocolVersion), "negotiated protocolVersion not in supported list", r.protocolVersion);
  const caps = r.capabilities || {};
  for (const cap of ["tools", "resources", "prompts", "logging", "completions"]) {
    assert(Object.prototype.hasOwnProperty.call(caps, cap), "initialize capabilities missing " + cap, Object.keys(caps).join(","));
  }
  record(
    "initialize",
    true,
    "protocolVersion=" + r.protocolVersion +
      " serverInfo=" + (r.serverInfo ? r.serverInfo.name + "/" + r.serverInfo.version : "?") +
      " caps=" + Object.keys(caps).sort().join(",")
  );
}

async function stepInitialized() {
  sendRaw(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }));
  await new Promise((resolve) => setTimeout(resolve, 100));
  record("notifications/initialized", true, "accepted (no response expected)");
}

async function stepToolsList() {
  const res = await request("tools/list", {});
  assert(!("error" in res), "tools/list returned an error", JSON.stringify(res.error));
  const names = (res.result.tools || []).map((t) => t.name).sort();
  const expected = ["net_cache", "net_digest", "net_fetch", "net_search", "net_sources"];
  assert(expected.every((n) => names.includes(n)), "tools/list missing expected tool names", names.join(","));
  assert(names.length === 5, "expected exactly 5 tools", names.length + " tools");
  record("tools/list", true, "names=" + names.join(","));
}

async function stepResourcesList() {
  const res = await request("resources/list", {});
  assert(!("error" in res), "resources/list returned an error", JSON.stringify(res.error));
  const uris = (res.result.resources || []).map((x) => x.uri);
  assert(uris.includes("netintel://catalog"), "catalog resource missing", uris.join(","));
  record("resources/list", true, uris.length + " resources: " + uris.join(","));
}

async function stepTemplatesList() {
  const res = await request("resources/templates/list", {});
  assert(!("error" in res), "resources/templates/list returned an error", JSON.stringify(res.error));
  const tpls = (res.result.resourceTemplates || []).map((x) => x.uriTemplate);
  assert(tpls.includes("netintel://feed/{key}"), "feed template missing", tpls.join(","));
  record("resources/templates/list", true, tpls.length + " templates: " + tpls.join(","));
}

async function stepPromptsList() {
  const res = await request("prompts/list", {});
  assert(!("error" in res), "prompts/list returned an error", JSON.stringify(res.error));
  const names = (res.result.prompts || []).map((p) => p.name);
  assert(names.includes("brief_topic"), "brief_topic prompt missing", names.join(","));
  record("prompts/list", true, names.length + " prompts: " + names.join(","));
}

async function callNetSearch(label) {
  const res = await request("tools/call", {
    name: "net_search",
    arguments: { query: "mcp server", limit: 5 },
  });
  assert(!("error" in res), "net_search returned a JSON-RPC error", JSON.stringify(res.error));
  const r = res.result;
  assert(r.isError !== true, "net_search result.isError=true", JSON.stringify(r.content && r.content[0]));
  const items = r.structuredContent && r.structuredContent.items;
  assert(Array.isArray(items) && items.length > 0, "net_search returned no items", JSON.stringify(r.structuredContent && r.structuredContent.failedSources));
  assert(items.length <= 5, "net_search exceeded limit 5", items.length);
  for (const item of items) {
    assert(typeof item.source === "string" && item.source.length > 0, "item missing source", JSON.stringify(item));
    assert(typeof item.score === "number", "item missing numeric score", JSON.stringify(item));
  }
  for (let i = 1; i < items.length; i++) {
    assert(items[i - 1].score >= items[i].score, "items not ranked descending by score", items[i - 1].score + " < " + items[i].score);
  }
  record(
    label,
    true,
    "offline=" + (r.structuredContent.offline === true) +
      " items=" + items.length +
      " topSource=" + items[0].source +
      " topScore=" + items[0].score +
      " cache=" + JSON.stringify(r.structuredContent.cache)
  );
}

async function stepCatalogRead() {
  const res = await request("resources/read", { uri: "netintel://catalog" });
  assert(!("error" in res), "resources/read returned an error", JSON.stringify(res.error));
  const first = res.result.contents && res.result.contents[0];
  assert(first && first.uri === "netintel://catalog", "catalog content uri mismatch", JSON.stringify(first && first.uri));
  const parsed = JSON.parse(first.text);
  assert(Array.isArray(parsed.sources) && parsed.sources.length > 0, "catalog has no sources");
  record("resources/read catalog", true, "sources=" + parsed.sources.length + " tools=" + (parsed.tools ? parsed.tools.length : "?"));
}

async function stepPromptGet() {
  const res = await request("prompts/get", { name: "brief_topic", arguments: { topic: "mcp" } });
  assert(!("error" in res), "prompts/get returned an error", JSON.stringify(res.error));
  const msgs = res.result.messages || [];
  assert(msgs.length >= 1 && msgs[0].role === "user", "brief_topic must return at least one user message");
  const text = typeof msgs[0].content.text === "string" ? msgs[0].content.text : "";
  assert(/brief/i.test(text), "prompt text does not look like a brief skeleton", text.slice(0, 60));
  record("prompts/get brief_topic", true, "messages=" + msgs.length + " preview=" + JSON.stringify(text.slice(0, 40)));
}

async function stepCompletion() {
  const res = await request("completion/complete", {
    ref: { type: "ref/prompt", name: "brief_topic" },
    argument: { name: "sources", value: "" },
  });
  assert(!("error" in res), "completion/complete returned an error", JSON.stringify(res.error));
  const values = (res.result.completion && res.result.completion.values) || [];
  assert(values.includes("hackernews") && values.includes("github") && values.includes("arxiv"), "sources completion missing ids", values.join(","));
  record("completion/complete sources", true, "values=" + values.join(","));
}

async function stepPing() {
  const res = await request("ping", {});
  assert(!("error" in res), "ping returned an error", JSON.stringify(res.error));
  record("ping", true, "result=" + JSON.stringify(res.result));
}

async function stepCacheStats() {
  const res = await request("tools/call", { name: "net_cache", arguments: { action: "stats" } });
  assert(!("error" in res), "net_cache returned a JSON-RPC error", JSON.stringify(res.error));
  const r = res.result;
  assert(r.isError !== true, "net_cache isError=true", JSON.stringify(r.content && r.content[0]));
  const stats = r.structuredContent && r.structuredContent.stats;
  assert(stats && typeof stats.hits === "number", "net_cache stats payload missing hits", JSON.stringify(r.structuredContent));
  assert(stats.hits > 0, "expected cache hits > 0 after repeated net_search", "hits=" + stats.hits + " misses=" + stats.misses + " sets=" + stats.sets);
  record("net_cache stats", true, "hits=" + stats.hits + " misses=" + stats.misses + " sets=" + stats.sets + " entries=" + stats.entries);
}

async function stepParseError() {
  const wait = waitForId("__parse_error__", STEP_TIMEOUT_MS);
  sendRaw("not json");
  const msg = await wait;
  assert(msg.error && msg.error.code === -32700, "malformed line did not yield -32700", JSON.stringify(msg));
  record("malformed line", true, "id=" + JSON.stringify(msg.id) + " code=" + msg.error.code);
}

async function stepUnknownTool() {
  const res = await request("tools/call", { name: "net_no_such_tool", arguments: {} });
  assert(res.error && res.error.code === -32602, "unknown tool did not yield -32602", JSON.stringify(res));
  record("unknown tool", true, "code=" + res.error.code + " message=" + JSON.stringify(res.error.message));
}

function stepShutdown() {
  return new Promise((resolve, reject) => {
    if (childExited) {
      reject(new Error("child exited before clean shutdown"));
      return;
    }
    const timer = setTimeout(
      () => reject(new Error("child did not exit within " + EXIT_TIMEOUT_MS + "ms after stdin close")),
      EXIT_TIMEOUT_MS
    );
    shutdownRequested = true;
    child.stdin.end();
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error("child exited with code " + code + " (expected 0)"));
    });
  });
}

// ---------------------------------------------------------------------- main

async function main() {
  if (!fs.existsSync(CLI_BIN)) {
    fail("CLI not built: " + CLI_BIN + " — run `npm run build` first (or set NETINTEL_SMOKE_BIN)");
    return;
  }
  if (!fs.existsSync(FIXTURE_DIR)) {
    fail("fixture dir missing: " + FIXTURE_DIR);
    return;
  }
  record("spawn", true, "node=" + process.execPath + " bin=" + CLI_BIN + " transport=stdio offline=1 fixtures=" + FIXTURE_DIR);
  child = spawn(process.execPath, [CLI_BIN, "--transport", "stdio"], {
    cwd: REPO_ROOT,
    env: { ...process.env, NETINTEL_OFFLINE: "1", NETINTEL_FIXTURE_DIR: FIXTURE_DIR },
    stdio: ["pipe", "pipe", "pipe"],
  });
  attachStream(child);

  const watchdog = setTimeout(() => fail("global watchdog exceeded " + GLOBAL_WATCHDOG_MS + "ms"), GLOBAL_WATCHDOG_MS);
  if (typeof watchdog.unref === "function") watchdog.unref();

  const steps = [
    stepInitialize,
    stepInitialized,
    stepToolsList,
    stepResourcesList,
    stepTemplatesList,
    stepPromptsList,
    () => callNetSearch("net_search #1 (miss+set)"),
    () => callNetSearch("net_search #2 (cache hit)"),
    stepCatalogRead,
    stepPromptGet,
    stepCompletion,
    stepPing,
    stepCacheStats,
    stepParseError,
    stepUnknownTool,
    stepShutdown,
  ];
  try {
    for (const s of steps) await s();
    record("clean shutdown", true, "exit code 0 within " + EXIT_TIMEOUT_MS + "ms of stdin close");
    clearTimeout(watchdog);
    printTable();
    console.log("");
    console.log("SMOKE OK (" + results.length + " steps)");
    process.exitCode = 0;
  } catch (err) {
    clearTimeout(watchdog);
    fail(err.message);
  }
}

main();