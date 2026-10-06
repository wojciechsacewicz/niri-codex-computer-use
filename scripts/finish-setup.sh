#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --wait ) ]] || { echo 'Usage: bash scripts/finish-setup.sh [--wait]' >&2; exit 2; }
python3 - "${1:-}" <<'PY'
from pathlib import Path
import os,sys,time
waiting=False
while True:
    active=[]
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            executable=os.readlink(directory/'exe').removesuffix(' (deleted)')
            if executable.startswith('/opt/codex-desktop/'):
                active.append(int(directory.name))
        except OSError:
            pass
    if not active:
        break
    if sys.argv[1]!='--wait':
        raise SystemExit(f'Close Codex and its active clients before installation. {len(active)} installed-runtime processes are still running.')
    if not waiting:
        print(f'Waiting for Codex and its active clients to close ({len(active)} runtime processes). No processes will be stopped automatically.',flush=True)
        waiting=True
    time.sleep(2)
PY
python3 "$root/scripts/verify-package-inputs.py"
companion="$root/dist/niri-codex-computer-use-latest.pkg.tar.zst"
desktop="$root/dist/codex-desktop-latest.pkg.tar.zst"
for file in "$companion" "$desktop"; do [[ -f "$file" ]] || { echo "Missing built package: $file" >&2; exit 1; }; done
[[ -n "${NCCU_ROLLBACK_PACKAGE:-}" && -f "$NCCU_ROLLBACK_PACKAGE" ]] || { echo 'Set NCCU_ROLLBACK_PACKAGE to the saved installed Codex package before promotion.' >&2; exit 1; }
installed="$(pacman -Q codex-desktop)"
rollback="$(pacman -Qp "$NCCU_ROLLBACK_PACKAGE")"
[[ "$installed" == "$rollback" ]] || { echo 'Rollback package must match the currently installed Codex version.' >&2; exit 1; }
pkexec pacman -U --noconfirm "$companion" "$desktop"
printf '%s\n' 'Installation complete. Save your work, log out, and select Niri (Codex background control). Start Codex in that session and verify a harmless native click and text entry.'
