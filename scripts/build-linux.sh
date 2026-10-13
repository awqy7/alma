#!/usr/bin/env bash
set -euo pipefail
ALMA_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ALMA_ROOT"
export PATH="$HOME/.cargo/bin:$PATH"
if [[ -d "$ALMA_ROOT/.packaging/linux-sysroot" ]]; then
  ALMA_SYSROOT="$ALMA_ROOT/.packaging/linux-sysroot"
  export PKG_CONFIG_SYSROOT_DIR="$ALMA_SYSROOT"
  export PKG_CONFIG_PATH="$ALMA_SYSROOT/usr/lib/x86_64-linux-gnu/pkgconfig:$ALMA_SYSROOT/usr/share/pkgconfig"
  export LD_LIBRARY_PATH="$ALMA_SYSROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export PATH="$ALMA_SYSROOT/usr/bin:$PATH"
fi
# Worker must already have been built and tested with scripts/build_worker.py.
test -x apps/desktop/src-tauri/bundled-runtime/worker/alma-worker
cd apps/desktop
npm run tauri -- build --config src-tauri/tauri.linux-package.conf.json --bundles deb
