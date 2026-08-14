#!/usr/bin/env bash
# Idempotent Cloud Agent install for the Legacy Error Code Mapper.
# Prepares a Python venv (backend + CLIs), the React/Vite Enterprise UI, and
# an initial COBOL scan so the dashboards have data on first boot.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# python3 ships without the venv/ensurepip module on the base image; install it.
# apt-get install is idempotent, so this is a fast no-op once the package exists.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip
fi

# Python environment: create the venv once, then keep dependencies in sync.
if [ ! -x "${REPO_ROOT}/.venv/bin/python" ]; then
  python3 -m venv "${REPO_ROOT}/.venv"
fi
"${REPO_ROOT}/.venv/bin/python" -m pip install --upgrade pip
# Editable install with the "documents" extras (PDF/Word/HTML/OpenAI ingest) plus pytest.
"${REPO_ROOT}/.venv/bin/python" -m pip install -e ".[documents]" pytest

# Enterprise React UI. The committed package.json pins vite@8 alongside
# @vitejs/plugin-react@4, whose peer range tops out at vite@7, so a plain
# `npm ci` fails on ERESOLVE; --legacy-peer-deps reproduces the working tree.
cd "${REPO_ROOT}/web"
npm ci --legacy-peer-deps
npm run build

# Seed an initial scan so the API/dashboards render findings immediately.
cd "${REPO_ROOT}"
"${REPO_ROOT}/.venv/bin/cobol-scan" samples -r config/error_rules.json -o out

echo "Install complete."
