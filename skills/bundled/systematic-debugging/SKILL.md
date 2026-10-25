---
name: systematic-debugging
description: "Use when hunting bugs: reproduce, isolate, fix minimally, verify."
version: 1.0.0
tags: [debug, testing]
---

# Systematic debugging

1. **Reproduce** — get a failing command, test, or log line you can re-run.
2. **Locate** — read the stack / failing assertion; open the exact file:line.
3. **Hypothesize** — one root cause at a time; do not shotgun-edit.
4. **Minimal fix** — smallest change that addresses the cause.
5. **Verify** — re-run the failing case; add/adjust a focused test when cheap.
6. **Report** — cause → fix → evidence. No process diary.
