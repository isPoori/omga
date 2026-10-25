#!/usr/bin/env node
/**
 * npm shim for `omgacli` → real Python CLI (`omga-cli` / `python -m cli.main`).
 *
 * Critical: never re-exec this same Node entry (PATH/`which omga` often points
 * back here and used to recurse until the terminal hung).
 */
"use strict";

const { spawnSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const args = process.argv.slice(2);
const SELF = (() => {
  try {
    return fs.realpathSync(__filename);
  } catch {
    return path.resolve(__filename);
  }
})();

/** Prevent accidental wrapper→wrapper recursion even if resolution regresses. */
const DEPTH = Number(process.env.OMGA_WRAPPER_DEPTH || "0");
if (DEPTH > 0) {
  console.error(
    "omga: npm wrapper refused to re-enter (would recurse). " +
      "Install the Python CLI: pip install --user omga-cli"
  );
  process.exit(1);
}

function existsFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function real(p) {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}

function isSelf(candidate) {
  return real(candidate) === SELF;
}

function looksLikeNodeShim(candidate) {
  if (isSelf(candidate)) return true;
  try {
    const head = fs.readFileSync(candidate, "utf8").slice(0, 120);
    if (/^#!.*\bnode\b/m.test(head)) return true;
    if (head.includes("npm wrapper") || head.includes("omgacli")) return true;
  } catch {
    /* ignore */
  }
  return false;
}

function runCapture(cmd, cmdArgs, opts = {}) {
  return spawnSync(cmd, cmdArgs, {
    encoding: "utf8",
    timeout: opts.timeout || 8000,
    env: opts.env || process.env,
    shell: Boolean(opts.shell),
  });
}

function findPythons() {
  const out = [];
  const seen = new Set();
  const push = (bin) => {
    if (!bin || seen.has(bin)) return;
    seen.add(bin);
    out.push(bin);
  };

  if (process.env.OMGA_PYTHON) push(process.env.OMGA_PYTHON);

  if (process.platform === "win32") {
    for (const c of ["py -3.14", "py -3.13", "py -3.12", "py -3.11", "py -3.10", "python", "python3"]) {
      const parts = c.split(" ");
      const r = runCapture(parts[0], [...parts.slice(1), "-c", "import sys; print(sys.executable)"], {
        shell: true,
      });
      if (r.status === 0 && r.stdout.trim()) push(r.stdout.trim());
    }
  } else {
    for (const bin of ["python3", "python"]) {
      const r = runCapture(bin, ["-c", "import sys; print(sys.executable)"]);
      if (r.status === 0 && r.stdout.trim()) push(r.stdout.trim());
    }
  }
  return out;
}

function pythonHasOmga(pythonBin) {
  const r = runCapture(pythonBin, [
    "-c",
    "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('cli.main') else 1)",
  ]);
  return r.status === 0;
}

/**
 * @returns {{ kind: "module", python: string } | { kind: "bin", path: string } | null}
 */
function resolveTarget() {
  // 1) Explicit override
  if (process.env.OMGA_BIN && existsFile(process.env.OMGA_BIN) && !looksLikeNodeShim(process.env.OMGA_BIN)) {
    return { kind: "bin", path: process.env.OMGA_BIN };
  }

  // 2) Known install / venv locations (never the npm shim)
  const omgaHome =
    process.env.OMGA_HOME ||
    path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "omga");
  const homeCandidates = [
    path.join(omgaHome, "venv", "bin", "omga"),
    path.join(omgaHome, "venv", "Scripts", "omga.exe"),
    path.join(process.env.LOCALAPPDATA || "", "omga", "venv", "Scripts", "omga.exe"),
    path.join(process.env.LOCALAPPDATA || "", "omga", "bin", "omga.cmd"),
  ];

  // Dev checkout next to this file (not inside node_modules)
  const pkgRoot = path.resolve(__dirname, "..");
  const pkgInNodeModules = pkgRoot.split(path.sep).includes("node_modules");
  if (!pkgInNodeModules && existsFile(path.join(pkgRoot, "pyproject.toml"))) {
    homeCandidates.unshift(
      path.join(pkgRoot, ".venv", "bin", "omga"),
      path.join(pkgRoot, "venv", "bin", "omga"),
      path.join(pkgRoot, ".venv", "Scripts", "omga.exe"),
      path.join(pkgRoot, "venv", "Scripts", "omga.exe")
    );
  }

  // When developing: walk up from cwd for a project .venv with omga
  let walk = process.cwd();
  for (let i = 0; i < 6; i++) {
    const cand = path.join(walk, ".venv", "bin", "omga");
    const candWin = path.join(walk, ".venv", "Scripts", "omga.exe");
    if (existsFile(cand) && !looksLikeNodeShim(cand)) {
      homeCandidates.unshift(cand);
      break;
    }
    if (existsFile(candWin) && !looksLikeNodeShim(candWin)) {
      homeCandidates.unshift(candWin);
      break;
    }
    const parent = path.dirname(walk);
    if (parent === walk) break;
    walk = parent;
  }

  for (const c of homeCandidates) {
    if (c && existsFile(c) && !looksLikeNodeShim(c)) {
      return { kind: "bin", path: c };
    }
  }

  // 3) Prefer `python -m cli.main` when the package is importable (pip / editable)
  for (const py of findPythons()) {
    if (pythonHasOmga(py)) {
      return { kind: "module", python: py };
    }
  }

  // 4) Scan PATH for a *Python* omga entry, skipping this Node shim
  const pathDirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  for (const dir of pathDirs) {
    for (const name of ["omga", "omga.exe", "omga.cmd"]) {
      const candidate = path.join(dir, name);
      if (!existsFile(candidate)) continue;
      if (looksLikeNodeShim(candidate)) continue;
      return { kind: "bin", path: candidate };
    }
  }

  return null;
}

function printInstallHint() {
  console.error(`
omga: Python CLI not found.

The npm package \`omgacli\` is only a launcher. Install the Python backend:

  pip install --user omga-cli
  # or
  curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash
  # or (from a git checkout)
  python -m pip install -e .

Then ensure the Python \`omga\` is on PATH (often ~/.local/bin) — or run:

  python -m cli.main

Note: do not rely on \`which omga\` alone after \`npm i -g omgacli\`; that path is this Node shim.
`.trim());
}

const target = resolveTarget();
if (!target) {
  printInstallHint();
  process.exit(1);
}

const childEnv = {
  ...process.env,
  OMGA_WRAPPER_DEPTH: String(DEPTH + 1),
};

let child;
if (target.kind === "module") {
  child = spawn(target.python, ["-m", "cli.main", ...args], {
    stdio: "inherit",
    env: childEnv,
  });
} else {
  child = spawn(target.path, args, {
    stdio: "inherit",
    env: childEnv,
    shell: process.platform === "win32" && /\.(cmd|bat)$/i.test(target.path),
  });
}

child.on("error", (err) => {
  console.error(`omga: failed to start Python CLI: ${err.message}`);
  printInstallHint();
  process.exit(1);
});

child.on("close", (code, signal) => {
  if (signal) {
    try {
      process.kill(process.pid, signal);
    } catch {
      /* ignore */
    }
    return;
  }
  process.exit(code ?? 0);
});
