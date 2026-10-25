# Contributing to OMGA

Thanks for helping improve OMGA — a terminal coding agent with memory, skills,
and multi-provider support.

## Development setup

```bash
git clone https://github.com/isPoori/omga.git
cd omga
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Run the TUI from the repo:

```bash
omga
# or
python -m cli.main
```

## Project layout

See [AGENTS.md](AGENTS.md) for the package map (`agent/`, `tools/`, `providers/`,
`ui/`, `cli/`, `memory/`, …).

## Guidelines

- Prefer small, focused pull requests.
- Match existing style; run `pytest` before opening a PR.
- Do not commit secrets (`secrets.json`, API keys, `.env`).
- Prefer `edit_file`-sized diffs; avoid drive-by refactors.
- New providers belong under `providers/` and should follow `BaseProvider`.
- TUI changes should keep keyboard-first navigation and UTF-8 / ASCII fallbacks.

## Commit messages

Use short, imperative subjects:

```text
Fix Selector viewport scroll for long model lists
```

## Pull requests

- Fill in the PR template.
- Link related issues when applicable.
- Include a brief test plan (commands you ran).

## Code of conduct

By participating, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Questions

- Docs site: https://ispoori.github.io/omga/
- Author: [Pouria Hosseini](https://pouriahosseini.ir)
