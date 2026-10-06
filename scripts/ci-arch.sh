#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo 'Run the build as an unprivileged user' >&2; exit 1; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
phase="${1:-all}"
[[ "$phase" == all || "$phase" == build || "$phase" == check ]] || { echo 'Use all, build, or check' >&2; exit 2; }
cd "$root"
if [[ "$phase" != check ]]; then
    if [[ "$phase" == build ]]; then
        bash scripts/check-native-runtime.sh --dependencies-only
    else
        bash scripts/check-native-runtime.sh
    fi
    python3 -m unittest discover -s tests -p 'test_*.py'
    python3 scripts/export-arch-recipe.py
    cd "$root/dist/arch-source"
    cp PKGBUILD PKGBUILD.public
    python3 - "$root" "$phase" <<'PY'
from pathlib import Path
import sys
import urllib.parse
recipe = Path('PKGBUILD')
text = recipe.read_text()
expected = 'source=("nccu::git+$url.git#commit=$_project_revision")'
assert expected in text
local = 'git+file://' + urllib.parse.quote(sys.argv[1], safe='/')
text = text.replace(expected, 'source=("nccu::' + local + '#commit=$_project_revision")')
if sys.argv[2] == 'build':
    text = text.replace('bash scripts/check-native-runtime.sh', 'bash scripts/check-native-runtime.sh --dependencies-only')
recipe.write_text(text)
PY
    if [[ "$phase" == build ]]; then
        makepkg --nobuild --force
        # Call the recipe's build function. Packaging waits for the networkless checks.
        export srcdir="$PWD/src"
        # shellcheck source=/dev/null
        source /etc/makepkg.conf
        # shellcheck source=/dev/null
        source PKGBUILD
        export CFLAGS CXXFLAGS CPPFLAGS RUSTFLAGS
        build
        exit 0
    fi
    makepkg --noconfirm
else
    bash scripts/check-native-runtime.sh
    cd "$root/dist/arch-source/src/nccu"
    python3 -m unittest discover -s tests -p 'test_*.py'
    bash scripts/test-native.sh
    python3 scripts/verify-package-inputs.py
    cd "$root/dist/arch-source"
    makepkg --repackage --force --noconfirm
fi
package="$(makepkg --packagelist)"
[[ -f "$package" ]] || { echo 'The source build produced no package' >&2; exit 1; }
bsdtar -xOf "$package" usr/bin/niri-codex-session | cmp - "$root/packaging/arch/niri-codex-session"
bsdtar -xOf "$package" usr/share/niri-codex-computer-use/sources.lock.json | cmp - "$root/sources.lock.json"
printf '%s\n' 'Source package, launcher, source lock and native evidence verified.'
