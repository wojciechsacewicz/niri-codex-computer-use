#!/usr/bin/env bash
set -Eeuo pipefail
NCCU_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for binary in niri codex-computer-use-linux; do
    [[ -x "$NCCU_ROOT/.local/outputs/$binary" ]] || { echo "Build $binary before packaging" >&2; exit 1; }
done
python3 "$NCCU_ROOT/scripts/verify-package-inputs.py"
mkdir -p "$NCCU_ROOT/dist" "$NCCU_ROOT/.local/package"
cp "$NCCU_ROOT/packaging/arch/PKGBUILD" "$NCCU_ROOT/.local/package/PKGBUILD"
cd "$NCCU_ROOT/.local/package"
NCCU_PROJECT_ROOT="$NCCU_ROOT" PKGDEST="$NCCU_ROOT/dist" makepkg --nodeps --force --noconfirm
