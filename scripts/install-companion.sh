#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$root/scripts/verify-package-inputs.py"
package="$root/dist/niri-codex-computer-use-0.1.0-1-x86_64.pkg.tar.zst"
[[ -f "$package" ]] || { echo 'Run make package first' >&2; exit 1; }
pkexec pacman -U --noconfirm "$package"
printf '%s\n' 'Installed alongside stock niri. Save your work and select Niri (Codex background control) at your next login.'
