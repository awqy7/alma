#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
ALMA_CARGO="${HOME}/.cargo/bin/cargo"
if command -v cargo >/dev/null 2>&1; then ALMA_CARGO="$(command -v cargo)"; fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Prepare o ambiente Python conforme README.md antes de iniciar.' >&2
  exit 1
fi
npm --prefix apps/desktop run build
"$ALMA_CARGO" build --locked
exec target/debug/alma-core preview "$PWD" "${ALMA_PREVIEW_PORT:-4318}"
