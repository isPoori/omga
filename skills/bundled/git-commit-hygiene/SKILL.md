---
name: git-commit-hygiene
description: "Use when staging or committing: small commits, clear messages, no secrets."
version: 1.0.0
tags: [git]
---

# Git commit hygiene

1. `git status` + `git diff` before staging — never commit secrets or `.env`.
2. Stage only related changes; leave WIP elsewhere.
3. Message: why, not what — one short subject, optional body.
4. Do not amend pushed commits or force-push main unless explicitly asked.
5. Prefer `git` CLI read tools first; mutate only when the user asks.
