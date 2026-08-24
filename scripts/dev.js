#!/usr/bin/env node
/**
 * Cross-platform launcher: macOS / Linux / Windows.
 *   npm run dev  →  http://localhost:8000
 */
const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const ROOT = path.resolve(__dirname, "..");
const PORT = process.env.PORT || "8000";
const WIN = process.platform === "win32";
const VENV = path.join(ROOT, "venv");
const PY_VENV = WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");

function run(cmd, args, opts) {
  const r = spawnSync(cmd, args, {
    cwd: ROOT,
    stdio: "inherit",
    shell: WIN,
    ...opts,
  });
  if (r.error) throw r.error;
  if (r.status !== 0) process.exit(r.status || 1);
}

function firstPython() {
  const candidates = WIN
    ? ["py", "python", "python3"]
    : ["python3", "python"];
  for (const c of candidates) {
    const r = spawnSync(c, ["-c", "import sys; print(sys.executable)"], {
      encoding: "utf8",
      shell: WIN,
    });
    if (r.status === 0 && r.stdout && r.stdout.trim()) return c;
  }
  console.error(
    "Python 3.9+ not found. Install from https://www.python.org/downloads/ then retry npm run dev."
  );
  process.exit(1);
}

function ensureVenv() {
  if (fs.existsSync(PY_VENV)) return;
  console.log("Creating virtualenv…");
  const sysPy = firstPython();
  if (WIN && sysPy === "py") run("py", ["-3", "-m", "venv", "venv"]);
  else run(sysPy, ["-m", "venv", "venv"]);
}

function ensureDeps() {
  const marker = path.join(VENV, ".deps-ok");
  const req = path.join(ROOT, "requirements.txt");
  const reqTime = fs.statSync(req).mtimeMs;
  if (fs.existsSync(marker) && fs.statSync(marker).mtimeMs >= reqTime) return;
  console.log("Installing Python packages (first run only)…");
  run(PY_VENV, ["-m", "pip", "install", "-q", "-r", "requirements.txt"]);
  fs.writeFileSync(marker, String(Date.now()));
}

ensureVenv();
ensureDeps();

console.log("");
console.log("BIT-Forensics  ·  " + os.platform() + "  ·  http://localhost:" + PORT);
console.log("Press Ctrl+C to stop.");
console.log("");

const child = spawn(
  PY_VENV,
  ["run.py"],
  { cwd: ROOT, stdio: "inherit", env: { ...process.env, PORT } }
);
child.on("exit", (code) => process.exit(code == null ? 0 : code));
process.on("SIGINT", () => child.kill("SIGINT"));
process.on("SIGTERM", () => child.kill("SIGTERM"));
