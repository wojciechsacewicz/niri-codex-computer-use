#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-wayland}"
[[ "$mode" == wayland || "$mode" == x11 ]] || { echo 'Use wayland or x11' >&2; exit 2; }
xvfb="${NCCU_XVFB:-$(command -v Xvfb || true)}"
[[ -n "$xvfb" ]] || xvfb="$root/.local/runtime/xvfb/usr/bin/Xvfb"
python="${NCCU_PYTHON:-python3}"
if [[ "$mode" == x11 ]]; then
    "$python" "$root/tests/backend-mcp-check.py" --niri "$root/.local/outputs/niri" --xvfb "$xvfb" --backend "$root/.local/outputs/codex-computer-use-linux" --agent-backend x11 --output "$root/.local/checks/x11"
else
    "$python" "$root/tests/nested-control.py" --niri "$root/.local/outputs/niri" --xvfb "$xvfb" --output "$root/.local/checks/native"
    "$python" "$root/tests/backend-mcp-check.py" --niri "$root/.local/outputs/niri" --xvfb "$xvfb" --backend "$root/.local/outputs/codex-computer-use-linux" --output "$root/.local/checks/backend"
fi
