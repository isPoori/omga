<p align="center">
  <img src="assets/omga-mark.svg" alt="OMGA" width="72" height="72" />
</p>

<h1 align="center">OMGA</h1>

<p align="center">
  <strong>The agent that grows with you</strong><br/>
  A self-improving AI coding agent for the terminal — memory, skills, and tools that compound across sessions.
</p>

<p align="center">
  <a href="https://github.com/isPoori/omga/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/isPoori/omga/ci.yml?branch=main&style=flat-square&label=CI" alt="CI" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0ea5a0?style=flat-square" alt="MIT" /></a>
  <a href="https://ispoori.github.io/omga/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-f97316?style=flat-square" alt="Docs" /></a>
  <a href="https://pepy.tech/projects/omga-cli"><img src="https://static.pepy.tech/personalized-badge/omga-cli?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads" alt="PyPI Downloads"></a>
</p>

---

## Why OMGA

| | |
|---|---|
| **Memory** | SQLite + FTS5 profile that remembers preferences, facts, and past sessions |
| **Skills** | Reusable playbooks (`agentskills.io`) — bundled + yours |
| **Providers** | OpenRouter · OpenAI · Anthropic · Groq · DeepSeek · Ollama · Together · Mistral · Fireworks · Gemini · LM Studio · … |
| **TUI** | Keyboard-first Unicode session with ASCII chrome, slash commands, and themes |

```text
   ___  __  __  ____    _
  / _ \|  \/  |/ ___|  / \
 | | | | |\/| | |  _  / _ \
 | |_| | |  | | |_| |/ ___ \
  \___/|_|  |_|\____/_/   \_\
```

## Install

### One-liner (Linux / macOS / WSL)

```bash
curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/isPoori/omga/main/install.ps1 | iex
```

### npm

Package name on the registry is **`omgacli`** (the CLI binary is still `omga`):

```bash
npm i -g omgacli
```

If you hit `EACCES` / permission denied under `/usr/lib/node_modules`, install into your user prefix instead of using `sudo`:

```bash
mkdir -p "$HOME/.local"
npm i -g omgacli --prefix "$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
```

To make that permanent:

```bash
npm config set prefix "$HOME/.local"
# add to ~/.bashrc or ~/.zshrc:
# export PATH="$HOME/.local/bin:$PATH"
```

### pip / source

```bash
pip install omga-cli
# or
git clone https://github.com/isPoori/omga.git && cd omga && pip install -e .
```

Then:

```bash
omga
omga doctor
omga doctor --fix
```

## Quick start

```text
omga                 Start a session
omga init            Setup wizard
omga config          Show config
omga doctor          Diagnostics
omga version
```

### In-session

```text
/ask /plan /agent /think /debug /review
/key       Set API key
/proxy     7890 · off · test
/model     Pick model
/provider  Switch provider
/memory    Browse long-term memory
/skills    Browse playbooks
/help      Shortcuts
```

**Proxy tips** (OpenRouter / Cloudflare / Clash):

```text
/proxy 7890                          # HTTP proxy on localhost
/proxy socks5://127.0.0.1:1080       # SOCKS5 (DNS via proxy)
/proxy off                           # Force direct — ignore env proxy
/proxy clear                         # Fall back to HTTPS_PROXY env
/proxy test                          # Probe OpenRouter via curl + Python
```

## Layout

```text
agent/      conversation loop, prompt tiers, compression
tools/      file, edit, shell, git, memory, skills, delegate
providers/  openrouter, openai, anthropic, groq, ollama, …
ui/         keyboard-first Unicode TUI
cli/        entrypoint, slash commands, doctor
memory/     SQLite + FTS5 + USER.md / MEMORY.md
skills/     agentskills.io playbooks
context/    AGENTS.md / .omga rules
config/     YAML config + secrets.json
core/       models, paths, errors, version, wizard
website/    GitHub Pages docs
```

Config: `~/.config/omga/config.yaml` · Keys: `secrets.json` · State: `state.sqlite`

See [config.example.yaml](config.example.yaml) · [DEPLOY.md](DEPLOY.md) · [docs site](https://ispoori.github.io/omga/)

---

## Community

- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md) · [Accessibility](ACCESSIBILITY.md)

---

<p align="center">
  <sub>Built by <a href="https://pouriahosseini.ir">Pouria Hosseini</a> · MIT</sub>
</p>
