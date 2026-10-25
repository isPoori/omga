# OMGA agent notes

## Layout (repo root)

```
agent/       conversation loop, prompt tiers, compression
tools/       file, edit, shell, git, memory, skills, delegate
providers/   openrouter, openai, anthropic, groq, ollama, …
ui/          keyboard-first Unicode TUI
cli/         entrypoint, slash-command registry, doctor
memory/      SQLite + FTS5 + USER.md / MEMORY.md
skills/      agentskills.io playbooks (bundled + user)
context/     AGENTS.md / .omga rules loader
config/      YAML/JSON config + secrets
core/        models, paths, errors, version, doctor, wizard, …
website/     GitHub Pages docs site
```
Entry point: `cli.main:main` · version: `core.version.__version__`


## Conventions

- Prefer `edit_file` over rewriting whole files.
- Persist durable facts with `remember` / `update_user_profile`.
- Keep diffs small; verify with a focused command when cheap.
- Do not commit secrets; keys live in `secrets.json` only.
- Default theme token set is `ink` (deep teal on charcoal); marketing site uses orange-on-dark.
- Proxy: `/proxy off` forces direct; `/proxy clear` uses env; OpenRouter prefers curl transport.
