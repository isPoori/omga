#!/usr/bin/env node
/**
 * After `npm i -g omgacli`: ensure the Python backend (PyPI: omga-cli) is importable.
 * The npm package is only a Node launcher — never the recursive `omga` on PATH.
 */
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const repoRoot = path.resolve(__dirname, "..");
const pyproject = path.join(repoRoot, "pyproject.toml");
const inNodeModules = repoRoot.split(path.sep).includes("node_modules");

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, {
    encoding: "utf8",
    stdio: opts.quiet ? "pipe" : "inherit",
    timeout: opts.timeout || 180000,
    shell: Boolean(opts.shell),
    env: process.env,
  });
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? ["py -3.14", "py -3.13", "py -3.12", "py -3.11", "py -3.10", "python", "python3"]
      : ["python3", "python"];
  for (const c of candidates) {
    const parts = c.split(" ");
    const bin = parts[0];
    const extra = parts.slice(1);
    const r = run(
      bin,
      [...extra, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"],
      { quiet: true, shell: process.platform === "win32" }
    );
    if (r.status === 0) return { bin, extra };
  }
  return null;
}

function pythonCanImportOmga(py) {
  const r = run(
    py.bin,
    [...py.extra, "-c", "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('cli.main') else 1)"],
    { quiet: true, shell: process.platform === "win32" }
  );
  return r.status === 0;
}

function pipInstall(py, args) {
  const r = run(py.bin, [...py.extra, "-m", "pip", "install", ...args], {
    quiet: true,
    shell: process.platform === "win32",
  });
  return { ok: r.status === 0, detail: (r.stderr || r.stdout || "").slice(0, 500) };
}

function ensureOmgaHomeVenv(py) {
  const home =
    process.env.OMGA_HOME ||
    path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "omga");
  const venvPython =
    process.platform === "win32"
      ? path.join(home, "venv", "Scripts", "python.exe")
      : path.join(home, "venv", "bin", "python");
  const venvOmga =
    process.platform === "win32"
      ? path.join(home, "venv", "Scripts", "omga.exe")
      : path.join(home, "venv", "bin", "omga");

  if (!fs.existsSync(venvPython)) {
    fs.mkdirSync(home, { recursive: true });
    const created = run(py.bin, [...py.extra, "-m", "venv", path.join(home, "venv")], {
      quiet: true,
      shell: process.platform === "win32",
    });
    if (created.status !== 0) {
      return { ok: false, detail: "venv create failed" };
    }
  }

  const r = run(venvPython, ["-m", "pip", "install", "--upgrade", "omga-cli"], { quiet: true });
  if (r.status !== 0) {
    // Editable from this tree when developing / when npm tarball ships sources
    if (fs.existsSync(pyproject)) {
      const ed = run(venvPython, ["-m", "pip", "install", "--upgrade", "-e", repoRoot], {
        quiet: true,
      });
      if (ed.status !== 0) {
        return { ok: false, detail: (ed.stderr || ed.stdout || "").slice(0, 400) };
      }
    } else {
      return { ok: false, detail: (r.stderr || r.stdout || "").slice(0, 400) };
    }
  }
  return { ok: fs.existsSync(venvOmga) || true, home, venvOmga };
}

function main() {
  const py = findPython();
  if (!py) {
    console.warn(
      "omgacli: Python 3.10+ not found. Install Python, then: pip install --user omga-cli"
    );
    return;
  }

  if (pythonCanImportOmga(py)) {
    console.log("omgacli: Python backend already available.");
    return;
  }

  // Git checkout (not inside node_modules): editable install into active env
  if (fs.existsSync(pyproject) && !inNodeModules) {
    const r = pipInstall(py, ["-e", repoRoot]);
    if (r.ok && pythonCanImportOmga(py)) {
      console.log("omgacli: installed Python package from local repository (editable).");
      return;
    }
  }

  // Try user install from PyPI (may fail on PEP 668 / externally-managed)
  let r = pipInstall(py, ["--user", "omga-cli"]);
  if (r.ok && pythonCanImportOmga(py)) {
    console.log("omgacli: installed Python backend via pip --user.");
    return;
  }

  // Arch / PEP 668: dedicated venv under ~/.local/share/omga
  const venv = ensureOmgaHomeVenv(py);
  if (venv.ok) {
    console.log(
      `omgacli: installed Python backend into ${venv.home}/venv (OMGA_HOME).`
    );
    return;
  }

  console.warn(`
omgacli: could not install the Python backend automatically.

Install manually (pick one):

  pip install --user omga-cli
  python -m venv ~/.local/share/omga/venv && ~/.local/share/omga/venv/bin/pip install omga-cli
  curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash

Then run: omga version
`.trim());
}

main();
