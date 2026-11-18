#!/usr/bin/env node
// dsh-wrenai CLI shim — spawns the stdlib-only Python engine with args passed through.
const { spawnSync } = require("child_process");
const path = require("path");

const engine = path.join(__dirname, "..", "scripts", "ask.py");
const args = process.argv.slice(2);
const candidates = process.platform === "win32" ? ["python", "python3"] : ["python3", "python"];

for (const py of candidates) {
  const r = spawnSync(py, [engine, ...args], { stdio: "inherit" });
  if (!r.error) process.exit(r.status ?? 1);
}
console.error("dsh-wrenai: python3 not found on PATH (the engine is stdlib-only Python 3, no pip installs needed)");
process.exit(127);
