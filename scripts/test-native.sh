#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xvfb="${NCCU_XVFB:-$(command -v Xvfb || true)}"
[[ -n "$xvfb" ]] || xvfb="$root/.local/runtime/xvfb/usr/bin/Xvfb"
python="${NCCU_PYTHON:-python3}"
"$python" "$root/tests/nested-control.py" --niri "$root/.local/outputs/niri" --xvfb "$xvfb" --output "$root/.local/checks/native"
"$python" "$root/tests/backend-mcp-check.py" --niri "$root/.local/outputs/niri" --xvfb "$xvfb" --backend "$root/.local/outputs/codex-computer-use-linux" --output "$root/.local/checks/backend"
