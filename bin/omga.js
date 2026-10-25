#!/usr/bin/env node
/**
 * npm wrapper: spawn the Python `omga` CLI if available.
 */
const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const args = process.argv.slice(2);

function fileExists(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function resolvePythonOmga() {
  // 1. OMGA_PYTHON / explicit venv from install.sh
  const omgaHome =
    process.env.OMGA_HOME ||
    path.join(
      process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"),
      "omga"
    );
  const candidates = [
    path.join(omgaHome, "venv", "bin", "omga"),
    path.join(omgaHome, "venv", "Scripts", "omga.exe"),
    path.join(process.env.LOCALAPPDATA || "", "omga", "venv", "Scripts", "omga.exe"),
    path.join(process.env.LOCALAPPDATA || "", "omga", "bin", "omga.cmd"),
  ].filter(Boolean);

  for (const c of candidates) {
    if (fileExists(c)) return c;
  }

  // 2. Adjacent repo (monorepo / npm link from git checkout)
  const repoRoot = path.resolve(__dirname, "..");
  const pyproject = path.join(repoRoot, "pyproject.toml");
  if (fileExists(pyproject)) {
    const localVenv = [
      path.join(repoRoot, ".venv", "bin", "omga"),
      path.join(repoRoot, "venv", "bin", "omga"),
      path.join(repoRoot, ".venv", "Scripts", "omga.exe"),
      path.join(repoRoot, "venv", "Scripts", "omga.exe"),
    ];
    for (const c of localVenv) {
      if (fileExists(c)) return c;
    }
  }

  // 3. PATH
  const which = spawnSync("which", ["omga"], { encoding: "utf8" });
  if (which.status === 0 && which.stdout.trim()) {
    return which.stdout.trim();
  }
  if (process.platform === "win32") {
    const where = spawnSync("where", ["omga"], { encoding: "utf8", shell: true });
    if (where.status === 0) {
      const line = where.stdout.split(/\r?\n/).find((l) => l.trim());
      if (line) return line.trim();
    }
  }

  return null;
}

function printInstallHint() {
  console.error(`
omga: Python CLI not found.

Install options:

  curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash
  npm i -g omgacli --prefix "$HOME/.local"   # then: export PATH="$HOME/.local/bin:$PATH"
  pip install --user omga-cli
  git clone https://github.com/isPoori/omga.git && cd omga && pip install -e .

Requires Python 3.10+.
`.trim());
  process.exit(1);
}

const omga = resolvePythonOmga();
if (!omga) {
  printInstallHint();
}

const child = spawn(omga, args, {
  stdio: "inherit",
  env: process.env,
  shell: process.platform === "win32" && omga.endsWith(".cmd"),
});

child.on("error", (err) => {
  console.error(`omga: failed to run ${omga}: ${err.message}`);
  process.exit(1);
});

child.on("close", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
