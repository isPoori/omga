#!/usr/bin/env node
/**
 * After `npm i -g omga`: try to ensure the Python backend (PyPI: omga-cli) is available.
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const pyproject = path.join(repoRoot, "pyproject.toml");

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, {
    encoding: "utf8",
    stdio: opts.quiet ? "pipe" : "inherit",
    ...opts,
  });
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? ["py -3.12", "py -3.11", "py -3.10", "python3", "python"]
      : ["python3", "python"];
  for (const c of candidates) {
    const parts = c.split(" ");
    const bin = parts[0];
    const extra = parts.slice(1);
    const r = run(bin, [...extra, "-c", "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"], {
      quiet: true,
      shell: process.platform === "win32",
    });
    if (r.status === 0) return { bin, extra };
  }
  return null;
}

function pipInstall(args) {
  const py = findPython();
  if (!py) return { ok: false, reason: "no-python" };
  const pipArgs = ["-m", "pip", "install", ...args];
  const r = run(py.bin, [...py.extra, ...pipArgs], {
    quiet: true,
    shell: process.platform === "win32",
  });
  return { ok: r.status === 0, reason: r.stderr || r.stdout };
}

function main() {
  // Developing from git checkout: editable install from repo root
  if (fs.existsSync(pyproject)) {
    const r = pipInstall(["-e", repoRoot]);
    if (r.ok) {
      console.log("omga (npm): installed Python package from local repository.");
      return;
    }
  }

  // Published npm package: install backend from PyPI (setuptools name: omga-cli)
  const r = pipInstall(["--user", "omga-cli"]);
  if (r.ok) {
    console.log("omga (npm): installed Python package via pip (--user).");
    return;
  }

  console.warn(`
omga (npm): could not install the Python backend automatically.

The \`omga\` command needs Python 3.10+ and the omga-cli package. Try one of:

  pip install --user omga-cli
  curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash

Then run: omga doctor
`.trim());
}

main();
