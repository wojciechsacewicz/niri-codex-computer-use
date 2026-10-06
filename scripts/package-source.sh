#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$root/scripts/export-arch-recipe.py" "$@"
printf '%s\n' 'The standalone PKGBUILD and .SRCINFO are ready. Run makepkg in the exported directory to build and test from pinned public sources.'
