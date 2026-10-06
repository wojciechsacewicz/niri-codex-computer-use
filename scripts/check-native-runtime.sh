#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 0 || ( $# == 1 && "$1" == --dependencies-only ) ]] || { echo 'Use no arguments or --dependencies-only' >&2; exit 2; }
for command in Xvfb xauth xdotool wtype wl-copy wl-paste bwrap dbus-daemon; do
    command -v "$command" >/dev/null || { echo "Missing native test dependency: $command" >&2; exit 1; }
done
"${NCCU_PYTHON:-python3}" - <<'PY'
import ctypes
import gi
import PIL
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
ctypes.CDLL('libxkbcommon-x11.so.0')
PY
if [[ "${1:-}" == --dependencies-only ]]; then
    printf '%s\n' 'Native test dependencies are available; sandbox checks run in the networkless test phase.'
    exit 0
fi
network="$("${NCCU_PYTHON:-python3}" "$root/tests/isolation.py")"
network_args=()
if [[ "$network" == --unshare-net ]]; then network_args+=(--unshare-net); fi
if ! bwrap --die-with-parent --unshare-user --unshare-pid --unshare-ipc "${network_args[@]}" \
    --ro-bind / / --dev /dev --proc /proc -- /usr/bin/true; then
    echo 'Native tests require working unprivileged bubblewrap namespaces and a private /proc. Check the test container configuration.' >&2
    exit 1
fi
printf '%s\n' 'Native test dependencies and private sandbox are available.'
