#!/usr/bin/env bash
set -Eeuo pipefail
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
if ! bwrap --die-with-parent --unshare-user --unshare-pid --unshare-ipc --unshare-net \
    --ro-bind / / --dev /dev --proc /proc -- /usr/bin/true; then
    echo 'Native tests require working unprivileged bubblewrap namespaces and a private /proc. Check the test container configuration.' >&2
    exit 1
fi
printf '%s\n' 'Native test dependencies and private sandbox are available.'
