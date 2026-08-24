#!/usr/bin/env node
/**
 * Cross-platform launcher for BitForensics (Windows / macOS / Linux).
 *
 *   npm install
 *   npm run dev   →  http://localhost:8000
 *
 * Creates .venv, installs requirements.txt, then starts run.py.
 * Never requires the developer to activate the virtualenv manually.
 */
"use strict";

const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const ROOT = path.resolve(__dirname, "..");
const PORT = process.env.PORT || "8000";
const WIN = process.platform === "win32";
const SETUP_ONLY = process.argv.includes("--setup-only");

/** Prefer .venv; fall back to legacy venv/ if it already works. */
function venvPaths() {
  const modern = path.join(ROOT, ".venv");
  const legacy = path.join(ROOT, "venv");
  const py = (dir) =>
    WIN
      ? path.join(dir, "Scripts", "python.exe")
      : path.join(dir, "bin", "python");

  if (fs.existsSync(py(modern))) {
    return { dir: modern, python: py(modern) };
  }
  if (fs.existsSync(py(legacy))) {
    return { dir: legacy, python: py(legacy) };
  }
  return { dir: modern, python: py(modern) };
}

/**
 * Run a process without a shell so args (and paths with spaces) stay intact.
 * Using shell:true on Windows breaks `python -c "…; …"` because cmd treats `;` as a separator.
 */
function runSync(command, args, opts = {}) {
  return spawnSync(command, args, {
    cwd: ROOT,
    env: process.env,
    windowsHide: true,
    shell: false,
    ...opts,
  });
}

function isStoreStub(exePath) {
  const p = String(exePath || "")
    .toLowerCase()
    .replace(/\//g, "\\");
  return (
    p.includes("\\windowsapps\\") ||
    p.includes("microsoft.desktopappinstaller") ||
    p.includes("\\windowsapps\\python")
  );
}

function candidateCommands() {
  const out = [];
  if (process.env.BITFORENSICS_PYTHON) {
    out.push(process.env.BITFORENSICS_PYTHON);
  }
  if (WIN) {
    // py launcher first (official Windows installer), then python.exe names
    out.push("py.exe", "py", "python.exe", "python", "python3.exe", "python3");
  } else {
    out.push("python3", "python");
  }
  return out;
}

/**
 * Probe one command. Returns { executable, version } or null.
 * Prints major/minor/executable on three lines so we never parse fragile banners.
 */
function probePython(cmd) {
  const isPyLauncher = /^py(\.exe)?$/i.test(path.basename(String(cmd)));
  const args = isPyLauncher
    ? [
        "-3",
        "-c",
        "import sys; print(sys.version_info[0]); print(sys.version_info[1]); print(sys.executable)",
      ]
    : [
        "-c",
        "import sys; print(sys.version_info[0]); print(sys.version_info[1]); print(sys.executable)",
      ];

  const r = runSync(cmd, args, { encoding: "utf8" });
  const stdout = String(r.stdout || "").trim();
  const stderr = String(r.stderr || "").trim();

  if (r.error) {
    return {
      ok: false,
      cmd,
      reason: r.error.code || r.error.message,
    };
  }
  if (r.status !== 0) {
    return {
      ok: false,
      cmd,
      reason: `exit ${r.status}${stderr ? ": " + stderr.split(/\r?\n/)[0] : ""}`,
    };
  }

  const lines = stdout
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (lines.length < 3) {
    return {
      ok: false,
      cmd,
      reason: "unexpected output: " + stdout.slice(0, 120),
    };
  }

  const major = parseInt(lines[0], 10);
  const minor = parseInt(lines[1], 10);
  const executable = lines[lines.length - 1];

  if (!Number.isFinite(major) || !Number.isFinite(minor)) {
    return { ok: false, cmd, reason: "could not parse version" };
  }
  if (major < 3 || (major === 3 && minor < 9)) {
    return {
      ok: false,
      cmd,
      reason: `Python ${major}.${minor} is too old (need >= 3.9)`,
      executable,
    };
  }
  if (isStoreStub(executable)) {
    return {
      ok: false,
      cmd,
      reason: "Microsoft Store stub (not a real Python)",
      executable,
    };
  }

  // Prefer the resolved absolute path so later steps never depend on PATH
  return {
    ok: true,
    cmd,
    executable,
    version: `${major}.${minor}`,
  };
}

function findPython() {
  const attempts = [];
  for (const cmd of candidateCommands()) {
    const result = probePython(cmd);
    if (result.ok) {
      console.log(
        `Using Python ${result.version}: ${result.executable} (via ${result.cmd})`
      );
      return result;
    }
    attempts.push(result);
  }

  console.error("");
  console.error("Could not find a usable Python 3.9+ interpreter.");
  console.error("Detection attempts:");
  for (const a of attempts) {
    const extra = a.executable ? ` [${a.executable}]` : "";
    console.error(`  - ${a.cmd}: ${a.reason}${extra}`);
  }
  console.error("");
  console.error("Fix:");
  console.error("  1. Install Python 3.9+ from https://www.python.org/downloads/");
  if (WIN) {
    console.error('  2. Tick "Add python.exe to PATH" during install, then open a NEW terminal.');
    console.error(
      "  3. Turn OFF Microsoft Store aliases: Settings → Apps → Advanced app settings → App execution aliases → python.exe / python3.exe"
    );
  } else {
    console.error("  2. On macOS/Linux, ensure `python3 --version` works in this same terminal.");
  }
  console.error(
    "  4. Or set BITFORENSICS_PYTHON to the full path of python.exe / python3."
  );
  console.error("");
  process.exit(1);
}

function venvWorks(pythonPath) {
  if (!fs.existsSync(pythonPath)) return false;
  const r = runSync(
    pythonPath,
    ["-c", "import sys; print(sys.version_info[0])"],
    { encoding: "utf8" }
  );
  return !r.error && r.status === 0;
}

function ensureVenv(py) {
  let { dir, python: venvPy } = venvPaths();

  if (venvWorks(venvPy)) {
    return venvPy;
  }

  if (fs.existsSync(dir)) {
    console.log(`Existing virtualenv at ${dir} is incomplete — recreating…`);
    fs.rmSync(dir, { recursive: true, force: true });
  }

  // Always create the modern .venv location for new installs
  dir = path.join(ROOT, ".venv");
  venvPy = WIN
    ? path.join(dir, "Scripts", "python.exe")
    : path.join(dir, "bin", "python");

  console.log(`Creating virtualenv at ${dir} …`);
  const r = runSync(py.executable, ["-m", "venv", dir], { stdio: "inherit" });
  if (r.error) {
    console.error(`Failed to create virtualenv: ${r.error.message}`);
    process.exit(1);
  }
  if (r.status !== 0) {
    console.error(`python -m venv failed with exit code ${r.status}`);
    process.exit(r.status || 1);
  }
  if (!venvWorks(venvPy)) {
    console.error(`Virtualenv was created but ${venvPy} is not usable.`);
    process.exit(1);
  }
  return venvPy;
}

function ensureDeps(venvPy, venvDir) {
  const marker = path.join(venvDir, ".deps-ok");
  const req = path.join(ROOT, "requirements.txt");
  if (!fs.existsSync(req)) {
    console.error("requirements.txt not found at", req);
    process.exit(1);
  }
  const reqTime = fs.statSync(req).mtimeMs;
  if (fs.existsSync(marker) && fs.statSync(marker).mtimeMs >= reqTime) {
    return;
  }

  console.log("Installing Python packages into the virtualenv…");
  // Upgrade pip quietly first — helps on fresh Windows installs
  runSync(venvPy, ["-m", "pip", "install", "--upgrade", "pip"], {
    stdio: "inherit",
  });
  const r = runSync(venvPy, ["-m", "pip", "install", "-r", req], {
    stdio: "inherit",
  });
  if (r.error) {
    console.error(`pip failed: ${r.error.message}`);
    process.exit(1);
  }
  if (r.status !== 0) {
    console.error(`pip install failed with exit code ${r.status}`);
    process.exit(r.status || 1);
  }
  fs.writeFileSync(marker, `${Date.now()}\n`);
}

function startServer(venvPy) {
  console.log("");
  console.log(
    `BIT-Forensics  ·  ${os.platform()}  ·  http://localhost:${PORT}`
  );
  console.log("Press Ctrl+C to stop.");
  console.log("");

  const child = spawn(venvPy, ["run.py"], {
    cwd: ROOT,
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
    windowsHide: true,
    shell: false,
  });

  const stop = (signal) => {
    if (!child.killed) child.kill(signal);
  };
  process.on("SIGINT", () => stop("SIGINT"));
  process.on("SIGTERM", () => stop("SIGTERM"));
  child.on("error", (err) => {
    console.error("Failed to start server:", err.message);
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    if (signal) process.exit(0);
    process.exit(code == null ? 0 : code);
  });
}

function main() {
  const py = findPython();
  const venvPy = ensureVenv(py);
  const { dir: venvDir } = (() => {
    const p = venvPaths();
    // After ensureVenv, re-resolve (new .venv may exist)
    if (fs.existsSync(venvPy)) {
      const dir = WIN
        ? path.dirname(path.dirname(venvPy)) // .../.venv/Scripts/python.exe
        : path.dirname(path.dirname(venvPy)); // .../.venv/bin/python
      return { dir };
    }
    return p;
  })();

  ensureDeps(venvPy, venvDir);

  if (SETUP_ONLY) {
    console.log("Setup complete. Run: npm run dev");
    return;
  }

  startServer(venvPy);
}

main();
