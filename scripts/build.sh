#!/usr/bin/env bash
set -Eeuo pipefail
NCCU_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NCCU_JOBS="${NCCU_JOBS:-2}"
case "$NCCU_JOBS" in ''|*[!0-9]*|0) echo 'NCCU_JOBS must be a positive integer' >&2; exit 2;; esac
component="${1:-all}"
mkdir -p "$NCCU_ROOT/.local/outputs"
if [[ "$component" == niri || "$component" == all ]]; then
    python3 "$NCCU_ROOT/scripts/prepare-sources.py" niri
    cargo build --locked --release -j "$NCCU_JOBS" --manifest-path "$NCCU_ROOT/build/niri/Cargo.toml"
    install -m755 "$NCCU_ROOT/build/niri/target/release/niri" "$NCCU_ROOT/.local/outputs/niri"
fi
if [[ "$component" == codex || "$component" == all ]]; then
    python3 "$NCCU_ROOT/scripts/prepare-sources.py" codex
    cargo build --locked --release -j "$NCCU_JOBS" --manifest-path "$NCCU_ROOT/build/codex-desktop-linux/Cargo.toml" -p codex-computer-use-linux --bins
    install -m755 "$NCCU_ROOT/build/codex-desktop-linux/target/release/codex-computer-use-linux" "$NCCU_ROOT/.local/outputs/codex-computer-use-linux"
    install -m755 "$NCCU_ROOT/build/codex-desktop-linux/target/release/codex-computer-use-cosmic" "$NCCU_ROOT/.local/outputs/codex-computer-use-cosmic"
fi
[[ "$component" == niri || "$component" == codex || "$component" == all ]] || { echo 'Use niri, codex, or all' >&2; exit 2; }
