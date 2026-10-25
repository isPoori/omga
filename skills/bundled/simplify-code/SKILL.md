---
name: simplify-code
description: "Use after a working change: reduce complexity without changing behaviour."
version: 1.0.0
tags: [refactor, cleanup]
---

# Simplify code

1. Confirm behaviour is covered (test or repro command).
2. Remove dead paths, unused imports, and speculative abstraction.
3. Prefer clear names over comments that restate the code.
4. Keep the diff small — one concern per PR-sized change.
5. Re-run the verification step.
