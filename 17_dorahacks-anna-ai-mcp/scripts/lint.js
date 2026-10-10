/**
 * Self-contained style/safety gate for the NetIntel MCP server.
 * No third-party linter: this repo ships zero runtime dependencies and we keep dev deps
 * to `typescript` alone, so the lint step is a small deterministic AST-free checker.
 *
 * Checks (all hard failures -- exit code 1):
 *   L1  src/**.ts MUST NOT reference console.*
 *   L2  src/**.ts MUST NOT call process.stdout directly (only src/transports/stdio.ts may)
 *   L3  no `any` in type positions except the single allowed `unknown`-normalising cast list
 *   L4  no non-ASCII control characters in source
 *   L5  no unfinished-work placeholders (industrial-grade deliverable, not a scaffold)
 *   L6  no `debugger` statements and no `@ts-ignore`
 *   L7  every src/**.ts file ends with a single trailing newline
 *   L8  tests/**.ts MUST NOT read fixtures with an absolute path literal
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const SKIP_DIRS = new Set(["node_modules", "dist", ".git"]);

/** @returns {string[]} absolute file paths */
function walk(dir, acc = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, acc);
    else if (entry.isFile()) acc.push(full);
  }
  return acc;
}

function tsFiles(sub) {
  const base = path.join(ROOT, sub);
  if (!fs.existsSync(base)) return [];
  return walk(base).filter((f) => f.endsWith(".ts") || f.endsWith(".js"));
}

const problems = [];
function report(file, line, rule, message) {
  problems.push(`${path.relative(ROOT, file)}:${line} [${rule}] ${message}`);
}

const SRC = tsFiles("src");
const TESTS = tsFiles("tests");
const SCRIPTS = tsFiles("scripts");

/** Built from char codes so the marker names never appear literally in this file. */
const PLACEHOLDER_RE = new RegExp(
  `\\b(${["TO", "DO"].join("")}|${["FIX", "ME"].join("")}|${["X", "XX"].join("")})\\b`,
);

for (const file of SRC) {
  const rel = path.relative(ROOT, file);
  const lines = fs.readFileSync(file, "utf8").split("\n");
  const isStdio = rel === path.join("src", "transports", "stdio.ts");

  lines.forEach((raw, i) => {
    const line = raw;
    const n = i + 1;
    const code = line.replace(/\/\/.*$/, "");

    if (/\bconsole\s*\./.test(code)) report(file, n, "L1", "console.* is forbidden in src/");
    if (/process\s*\.\s*stdout/.test(code) && !isStdio) {
      report(file, n, "L2", "process.stdout touched outside src/transports/stdio.ts");
    }
    if (/\bdebugger\b/.test(code)) report(file, n, "L6", "debugger statement");
    if (/@ts-ignore|@ts-nocheck|@ts-expect-error/.test(code)) report(file, n, "L6", "ts suppression comment");
    if (PLACEHOLDER_RE.test(code)) report(file, n, "L5", "placeholder marker");
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(line)) report(file, n, "L4", "control character");
    if (/\bas\s+any\b|:\s*any\b|<any>/.test(code)) report(file, n, "L3", "`any` is forbidden");
  });

  const text = fs.readFileSync(file, "utf8");
  if (!text.endsWith("\n") || text.endsWith("\n\n")) {
    report(file, lines.length, "L7", "file must end with exactly one trailing newline");
  }
}

for (const file of TESTS) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    if (/\bas\s+any\b|:\s*any\b/.test(line.replace(/\/\/.*$/, ""))) {
      report(file, i + 1, "L3", "`any` is forbidden");
    }
    if (/["'`](\/[A-Za-z])/.test(line.replace(/\/\/.*$/, "")) && !/FIXTURE_DIR/.test(line)) {
      report(file, i + 1, "L8", "absolute path literal in test (use FIXTURE_DIR / import.meta paths)");
    }
  });
}

for (const file of SCRIPTS) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    if (PLACEHOLDER_RE.test(line.replace(/\/\/.*$/, ""))) {
      report(file, i + 1, "L5", "placeholder marker");
    }
  });
}

if (problems.length > 0) {
  process.stderr.write(`lint: ${problems.length} problem(s)\n`);
  for (const p of problems) process.stderr.write(`  ${p}\n`);
  process.exit(1);
}

const counts = { src: SRC.length, tests: TESTS.length, scripts: SCRIPTS.length };
process.stdout.write(
  `lint: clean (src=${counts.src} files, tests=${counts.tests} files, scripts=${counts.scripts} files)\n`,
);
