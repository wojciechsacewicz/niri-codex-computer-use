# Backend MCP check

Run with the Python interpreter that has PyGObject, GTK 3, and Pillow installed:

```sh
python3 tests/backend-mcp-check.py \
  --niri "$NIRI_BINARY" \
  --xvfb "$XVFB_BINARY" \
  --backend "$BACKEND_BINARY" \
  --output "$CHECK_OUTPUT"
```

The three binary arguments select existing builds. The check does not build or
install anything. Other dependencies are `bwrap`, `dbus-daemon`, `xauth`,
`xdotool`, `wtype`, `wl-copy`, and `wl-paste`. Bubblewrap must support user
namespaces; the check fails if backend device isolation cannot start.

The harness creates a private authenticated Xvfb display, D-Bus session, runtime
directory, and niri instance. Backend children use a private `/dev` and writable
paths limited to that runtime and the output directory. It tests MCP screenshot,
click, text including Unicode, keys, scroll, and a held-button slider drag starting
at 20. The verified build lands at 83; the assertion allows slider/theme rounding
and requires a value above 60 plus motion while the button is held.

It also checks input on another workspace, refusal of the human-focused client,
eight strict refusal cases with unavailable agent IPC, and four refusals with live
IPC. Human focus, pointer, clipboard, and input stream must remain unchanged.
`result.json`, client state, logs, a window screenshot, and a cursor screenshot are
saved under `--output`. Previous success output is removed before a rerun.

Cleanup asks only the owned niri instance to quit, accepts EOF during shutdown,
and then reaps all owned process groups, including the private bus and Xvfb.
A successful result records `owned_processes_reaped: true`. The main desktop and
its environment are never used as control targets.
