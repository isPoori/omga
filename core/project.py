"""
Project discovery — understand the working directory.

On startup OMGA locates the project root (git root when available),
sniffs the stack, reads key manifests, and builds an allowlist of source
files so the agent reads real code without scanning node_modules, .git,
build dirs, or other generated noise.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Callable, Iterable, Iterator

# Directories always skipped when scanning the project.
_IGNORED_DIRS = (
    ".git", ".hg", ".svn",
    "node_modules", ".venv", "venv", "env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt", ".turbo",
    ".idea", ".vscode",
    "target", (os.path.join(".", "go", "pkg", "mod")),
)

# Files always skipped.
_IGNORED_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                  "poetry.lock", "Pipfile.lock", "uv.lock", "go.sum",
                  "Cargo.lock", "composer.lock")

_MANIFESTS = (
    "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    "Cargo.toml", "composer.json", "Gemfile", "build.gradle",
    "pom.xml", "mix.exs", "*.csproj", "setup.py", "setup.cfg",
)

_LANG_BY_MANIFEST = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "composer.json": "php",
    "Gemfile": "ruby",
    "build.gradle": "java",
    "pom.xml": "java",
    "mix.exs": "elixir",
}


class Project:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git_root: Path | None = None
        self.branch: str = "?"
        self.language: str | None = None
        self.manifests: list[str] = []

    def detect(self) -> "Project":
        self.git_root, self.branch = _git_info(self.root)
        root = self.git_root or self.root
        self.root = root
        self._sniff(root)
        return self

    def _sniff(self, root: Path) -> None:
        for entry in root.iterdir():
            if entry.is_file() and entry.name in _MANIFESTS:
                self.manifests.append(entry.name)
                lang = _LANG_BY_MANIFEST.get(entry.name)
                if lang:
                    self.language = lang

    def walk(self, ignore_dirs: Iterable[str] | None = None) -> Iterator[Path]:
        """Yield source files in the project, honouring gitignore-style skips."""
        skip_dirs = set(_IGNORED_DIRS)
        if ignore_dirs:
            skip_dirs |= {str(d) for d in ignore_dirs}
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune directories in place.
            dirnames[:] = [d for d in dirnames if d not in skip_dirs
                           and not d.startswith(".")]
            for fn in filenames:
                if fn in _IGNORED_FILES:
                    continue
                p = Path(dirpath) / fn
                if _is_binary(p):
                    continue
                yield p

    def files(self, limit: int = 60) -> list[str]:
        """Return a display-oriented list of source files (relative)."""
        out = []
        for p in self.walk():
            try:
                rel = p.relative_to(self.root)
            except ValueError:
                rel = p
            out.append(str(rel))
            if len(out) >= limit:
                break
        return out


def _git_info(cwd: Path) -> tuple[Path | None, str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd), capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            root = Path(out.stdout.strip())
            branch = "main"
            try:
                b = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(root), capture_output=True, text=True, timeout=5,
                )
                if b.stdout.strip():
                    branch = b.stdout.strip()
            except Exception:
                pass
            return root, branch
    except Exception:
        pass
    return None, "?"


def is_ignored(path: Path, base: Path) -> bool:
    """Return True when *path* is inside a skipped directory tree."""
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    for part in rel.parts:
        if part in _IGNORED_DIRS:
            return True
    return False


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            data = fh.read(8000)
    except OSError:
        return True
    return b"\x00" in data


def detect_project(cwd: str | None = None) -> Project:
    base = Path(cwd or os.getcwd()).resolve()
    return Project(base).detect()
