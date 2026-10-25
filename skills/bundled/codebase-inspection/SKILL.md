---
name: codebase-inspection
description: "Use before large edits: map structure, entry points, and conventions."
version: 1.0.0
tags: [explore, architecture]
---

# Codebase inspection

1. Read manifests (package.json, pyproject.toml, go.mod, …) and README/AGENTS.md.
2. Locate entry points and the module that owns the feature.
3. Search for symbols / patterns before inventing new ones — match local style.
4. Prefer `edit_file` over rewriting whole files.
5. Summarize findings in a few bullets, then act.
