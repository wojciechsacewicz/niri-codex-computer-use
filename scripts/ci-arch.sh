#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo 'Run the build as an unprivileged user' >&2; exit 1; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/export-arch-recipe.py
cd "$root/dist/arch-source"
# Test the checked-out PR or commit, including merge commits absent from public refs.
# The exported public recipe remains separate from this temporary CI recipe.
cp PKGBUILD PKGBUILD.public
python3 - "$root" <<'PY'
from pathlib import Path
import sys
import urllib.parse
recipe = Path('PKGBUILD')
local = 'git+file://' + urllib.parse.quote(sys.argv[1], safe='/')
text = recipe.read_text()
expected = 'source=("nccu::git+$url.git#commit=$_project_revision")'
assert expected in text
recipe.write_text(text.replace(expected, 'source=("nccu::' + local + '#commit=$_project_revision")'))
PY
makepkg --noconfirm
package="$(makepkg --packagelist)"
[[ -f "$package" ]] || { echo 'The source build produced no package' >&2; exit 1; }
bsdtar -xOf "$package" usr/bin/niri-codex-session | cmp - "$root/packaging/arch/niri-codex-session"
bsdtar -xOf "$package" usr/share/niri-codex-computer-use/sources.lock.json | cmp - "$root/sources.lock.json"
printf '%s\n' 'Source package, launcher, source lock and native evidence verified.'
