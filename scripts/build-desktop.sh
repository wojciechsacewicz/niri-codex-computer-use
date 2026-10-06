#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
builder="$root/build/codex-desktop-linux"
python3 "$root/scripts/prepare-sources.py" codex
python3 "$root/scripts/verify-package-inputs.py"
[[ -x "$root/.local/outputs/codex-computer-use-cosmic" ]] || { echo 'Run make build-backend to build the desktop helper' >&2; exit 1; }
mkdir -p "$root/.local/desktop-reports" "$root/dist"
features="$root/.local/desktop-features.json"
[[ -f "$features" ]] || printf '%s\n' '{"enabled":["computer-use-linux","helium-browser-support"]}' > "$features"
if [[ $# -gt 1 ]]; then echo 'Usage: bash scripts/build-desktop.sh [official-chatgpt.deb]' >&2; exit 2; fi
if [[ $# == 1 ]]; then
    node "$builder/scripts/lib/upstream-linux-package.js" --output-dir "$root/.local/official-index" --metadata "$root/.local/official-index/metadata.json" --key-base64 "$builder/assets/openai-codex-linux-repository-key.gpg.base64" --arch amd64 --metadata-only
    python3 - "$root/.local/official-index/metadata.json" "$1" <<'PY'
import hashlib,json,sys
from pathlib import Path
metadata=json.loads(Path(sys.argv[1]).read_text())
with Path(sys.argv[2]).open('rb') as source:
    actual=hashlib.file_digest(source,'sha256').hexdigest()
assert actual==metadata['sha256'], 'Provided package does not match the current signed official release'
PY
fi
export CODEX_INSTALL_DIR="$root/.local/codex-app-candidate"
export REBUILD_REPORT_DIR="$root/.local/desktop-reports"
export CODEX_LINUX_FEATURES_CONFIG="$features"
export CODEX_COMPUTER_USE_BINARY_SOURCE="$root/.local/outputs/codex-computer-use-linux"
export CODEX_COMPUTER_USE_COSMIC_BINARY_SOURCE="$root/.local/outputs/codex-computer-use-cosmic"
bash "$builder/install.sh" "$@"
INSTALL_DIR="$CODEX_INSTALL_DIR" "$CODEX_INSTALL_DIR/resources/cua_node/bin/node" --test "$builder/linux-features/computer-use-linux/validator.test.js"
APP_DIR_OVERRIDE="$CODEX_INSTALL_DIR" DIST_DIR_OVERRIDE="$root/dist" MAX_BUILD_THREADS="${NCCU_JOBS:-2}" UPDATER_BINARY_SOURCE="${NCCU_UPDATER:-/usr/bin/codex-update-manager}" bash "$builder/scripts/build-pacman.sh"
