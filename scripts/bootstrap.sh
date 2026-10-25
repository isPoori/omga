#!/usr/bin/env bash
# Local bootstrap: venv + editable install + tests (+ optional site preview)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> OMGA bootstrap @ $ROOT"

if [[ ! -d .venv ]]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> pip install -e .[test]"
# Clear stale console script if previous install left a read-only shim
rm -f .venv/bin/omga 2>/dev/null || true
python -m pip install -U pip wheel
python -m pip install -e ".[test]"

echo "==> omga version"
omga version

echo "==> pytest"
python -m pytest tests/ -q

if command -v node >/dev/null 2>&1; then
  echo "==> Node $(node -v) — npm shim available (npm link / npm publish)"
else
  echo "==> Node not found (optional for npm package)"
fi

echo
echo "Ready. Try:"
echo "  source .venv/bin/activate"
echo "  omga"
echo "  omga doctor"
echo "  omga doctor --fix"
echo
echo "Site preview:"
echo "  cd website && python -m http.server 8080"
echo
echo "Full publish guide: DEPLOY.md"
