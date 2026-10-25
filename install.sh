#!/usr/bin/env bash
# OMGA installer — Linux, macOS, WSL
# https://github.com/isPoori/omga
set -euo pipefail

REPO_URL="https://github.com/isPoori/omga.git"
REPO_TARBALL="https://github.com/isPoori/omga/archive/refs/heads/main.tar.gz"
MIN_PYTHON="3.10"

# ── Colors & symbols ──────────────────────────────────────────────────────────
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  BOLD="$(tput bold)"; DIM="$(tput dim)"; RESET="$(tput sgr0)"
  RED="$(tput setaf 1)"; GREEN="$(tput setaf 2)"; YELLOW="$(tput setaf 3)"; CYAN="$(tput setaf 6)"
else
  BOLD=""; DIM=""; RESET=""; RED=""; GREEN=""; YELLOW=""; CYAN=""
fi
OK="${GREEN}✓${RESET}"
WARN="${YELLOW}!${RESET}"
ERR="${RED}✗${RESET}"

info()  { echo -e "${CYAN}${1}${RESET}"; }
step()  { echo -e "  ${OK} ${1}"; }
warn()  { echo -e "  ${WARN} ${YELLOW}${1}${RESET}"; }
die()   { echo -e "  ${ERR} ${RED}${1}${RESET}" >&2; exit 1; }

# ── Paths ─────────────────────────────────────────────────────────────────────
OMGA_HOME="${OMGA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/omga}"
OMGA_BIN="${OMGA_BIN:-$HOME/.local/bin}"
OMGA_VENV="${OMGA_HOME}/venv"
OMGA_SRC="${OMGA_HOME}/src"
OMGA_LINK="${OMGA_BIN}/omga"

# ── OS / arch ───────────────────────────────────────────────────────────────────
detect_platform() {
  local os arch
  os="$(uname -s 2>/dev/null || echo unknown)"
  arch="$(uname -m 2>/dev/null || echo unknown)"
  case "$os" in
    Linux*)   OS_NAME="linux" ;;
    Darwin*)  OS_NAME="macos" ;;
    MINGW*|MSYS*|CYGWIN*) OS_NAME="windows" ;;
    *)        OS_NAME="$os" ;;
  esac
  case "$arch" in
    x86_64|amd64) ARCH="x64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) ARCH="$arch" ;;
  esac
  info "${BOLD}OMGA installer${RESET}  (${OS_NAME}/${ARCH})"
}

# ── Python ────────────────────────────────────────────────────────────────────
python_version_ok() {
  local ver
  ver="$("$1" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || return 1
  "$1" -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null
}

find_python() {
  local candidates=(python3 python)
  for cmd in "${candidates[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1 && python_version_ok "$cmd"; then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

python_install_hints() {
  warn "Python ${MIN_PYTHON}+ is required."
  case "$OS_NAME" in
    linux)
      echo "    Debian/Ubuntu:  sudo apt update && sudo apt install python3 python3-venv python3-pip"
      echo "    Fedora/RHEL:      sudo dnf install python3 python3-pip"
      echo "    Arch:             sudo pacman -S python python-pip"
      ;;
    macos)
      echo "    Homebrew:         brew install python@3.12"
      echo "    Or download:      https://www.python.org/downloads/macos/"
      ;;
    *)
      echo "    Install Python ${MIN_PYTHON}+ from https://www.python.org/downloads/"
      ;;
  esac
  echo ""
  echo "    Re-run:  curl -fsSL https://raw.githubusercontent.com/isPoori/omga/main/install.sh | bash"
}

ensure_python() {
  info "Checking Python ${MIN_PYTHON}+…"
  if PYTHON_CMD="$(find_python)"; then
    local ver
    ver="$("$PYTHON_CMD" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    step "Found ${PYTHON_CMD} (${ver})"
    return 0
  fi
  python_install_hints
  die "Python ${MIN_PYTHON}+ not found."
}

# ── Source ────────────────────────────────────────────────────────────────────
fetch_source() {
  info "Fetching OMGA source…"
  mkdir -p "$OMGA_HOME"
  if [[ -d "${OMGA_SRC}/.git" ]]; then
    step "Updating existing clone…"
    git -C "$OMGA_SRC" fetch --depth 1 origin main 2>/dev/null || git -C "$OMGA_SRC" fetch --depth 1 origin master 2>/dev/null || true
    git -C "$OMGA_SRC" reset --hard FETCH_HEAD 2>/dev/null || git -C "$OMGA_SRC" pull --ff-only 2>/dev/null || true
    step "Repository updated"
  elif command -v git >/dev/null 2>&1; then
    rm -rf "$OMGA_SRC"
    git clone --depth 1 "$REPO_URL" "$OMGA_SRC"
    step "Cloned ${REPO_URL}"
  else
    warn "git not found; downloading tarball…"
    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$REPO_TARBALL" -o "$tmp/omga.tar.gz"
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "$tmp/omga.tar.gz" "$REPO_TARBALL"
    else
      die "Need git, curl, or wget to download OMGA."
    fi
    rm -rf "$OMGA_SRC"
    mkdir -p "$OMGA_SRC"
    tar -xzf "$tmp/omga.tar.gz" -C "$tmp"
    local extracted
    extracted="$(find "$tmp" -maxdepth 1 -type d \( -name 'omga-*' -o -name 'Omgacli-*' \) | head -1)"
    [[ -n "$extracted" ]] || die "Unexpected tarball layout."
    cp -a "$extracted/." "$OMGA_SRC/"
    step "Downloaded source archive"
  fi
}

# ── Venv & install ────────────────────────────────────────────────────────────
setup_venv() {
  info "Setting up virtual environment…"
  if [[ ! -d "$OMGA_VENV" ]]; then
    "$PYTHON_CMD" -m venv "$OMGA_VENV"
    step "Created venv at ${OMGA_VENV}"
  else
    step "Using existing venv"
  fi
  # shellcheck disable=SC1091
  source "${OMGA_VENV}/bin/activate"
  python -m pip install -q --upgrade pip wheel
  python -m pip install -q -e "$OMGA_SRC"
  step "Installed omga-cli (editable) into venv"
}

link_binary() {
  info "Linking omga into PATH…"
  mkdir -p "$OMGA_BIN"
  local venv_omga="${OMGA_VENV}/bin/omga"
  [[ -x "$venv_omga" ]] || die "Expected ${venv_omga} after install."
  ln -sf "$venv_omga" "$OMGA_LINK"
  step "Symlink: ${OMGA_LINK} → ${venv_omga}"
}

path_hint() {
  case ":${PATH}:" in
    *":${OMGA_BIN}:"*) return 0 ;;
  esac
  info "Adding ${OMGA_BIN} to your shell PATH…"
  local line='export PATH="$HOME/.local/bin:$PATH"'
  local updated=0
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$rc" ]] || continue
    if grep -qF '.local/bin' "$rc" 2>/dev/null; then
      step "PATH already mentioned in $(basename "$rc")"
    else
      {
        echo ""
        echo "# OMGA CLI"
        echo "$line"
      } >> "$rc"
      step "Appended PATH hint to $(basename "$rc")"
      updated=1
    fi
  done
  if [[ "$updated" -eq 0 ]]; then
    warn "Ensure ${OMGA_BIN} is on your PATH:"
    echo "    ${line}"
  fi
}

print_success() {
  echo ""
  echo -e "${GREEN}${BOLD}Installation complete.${RESET}"
  echo ""
  echo "  Next steps:"
  echo "    ${CYAN}omga${RESET}           Start a session"
  echo "    ${CYAN}omga doctor${RESET}    Run diagnostics"
  echo ""
  if ! command -v omga >/dev/null 2>&1; then
    warn "Open a new terminal or run:"
    echo "    export PATH=\"${OMGA_BIN}:\$PATH\""
  fi
  echo "  Install location: ${DIM}${OMGA_HOME}${RESET}"
  echo "  To update later:    re-run this installer"
  echo ""
}

main() {
  detect_platform
  ensure_python
  fetch_source
  setup_venv
  link_binary
  path_hint
  print_success
}

main "$@"
