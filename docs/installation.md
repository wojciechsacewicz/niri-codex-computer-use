# CachyOS installation

This is an early integration for x86_64 CachyOS with systemd. The tested source pins are in `sources.lock.json`. We keep stock niri installed and add a separate session, **Niri (Codex background control)**. Returning to the stock session is the compositor rollback.

## Build and test

Build dependencies include Git, Rust/Cargo, pkg-config, clang, the niri development libraries, and the dependencies listed in the community desktop builder. On Arch, start with `base-devel`, `git`, `rust`, `clang`, `libdisplay-info`, `libinput`, `libpipewire`, `libxkbcommon`, `pango`, `cairo`, `mesa`, and `seatd`. Install missing packages through your normal CachyOS update process.

Native checks also need `xorg-server-xvfb`, `xorg-xauth`, `xdotool`, `wtype`, `wl-clipboard`, `bubblewrap`, `dbus`, `gtk3`, `python-gobject`, and `python-pillow`. Use a Python interpreter that can import `gi` and `PIL`.

```sh
make prepare
make build
make test-native
make package
```

`NCCU_JOBS` sets Cargo parallelism. `NCCU_PYTHON` selects the test interpreter and `NCCU_XVFB` selects an existing Xvfb binary. The tests use a private display, bus, and compositor. They do not drive your desktop.

Packaging refuses a changed binary or test source until the native checks pass again. Source preparation refuses to overwrite an edited build tree. Keep any edits before preparing a fresh tree.

## Prepare the Codex desktop package

```sh
bash scripts/build-desktop.sh
```

This uses OpenAI's signed stable package index, builds an isolated candidate, checks the candidate's actual computer-use SDK, and retains the accepted helper and adapter sources in the packaged update-builder. An optional `.deb` argument must match the current signed index. It does not install or restart Codex.

The desktop package reuses an installed `codex-update-manager` binary. Set `NCCU_UPDATER` to a separately built updater if needed. Its local feature configuration defaults to computer use and Helium support. Additional features need their own compatibility checks.

## Install and activate

```sh
bash scripts/install-companion.sh
```

The companion installs a separate compositor and strict background-only backend. It leaves the running session alone.

For the generated `codex-desktop` package, save the currently installed package for rollback and close Codex and its active clients before running `pkexec pacman -U` with the reviewed package from `dist/`. Do not replace a running application's files during an active task.

To install both reviewed packages together after closing active Codex clients, use:

```sh
NCCU_ROLLBACK_PACKAGE="$SAVED_CODEX_PACKAGE" bash scripts/finish-setup.sh
```

`$SAVED_CODEX_PACKAGE` must name a saved package with the same version as the currently installed Codex. The command refuses active clients. `--wait` waits for them to close without stopping them.

Save your work, log out, and choose **Niri (Codex background control)** at the greeter. If your greeter runs a fixed command, select `niri-codex-session` explicitly in its configuration. Do not change or restart the greeter while work is running.

After logging in, check `systemctl --user status niri-codex.service` and start Codex normally. Enable its native Computer Use feature and verify a harmless click and text entry in a separate disposable app. The first live desktop check remains required even after isolated tests pass.

The optional command `niri-codex-computer-use mcp` exposes the same strict backend over stdio MCP. Desktop CUA uses the native integration. A second manual computer-use MCP registration is not needed for that desktop path.

## Rollback

Choose the stock **Niri** session at login. Restore the saved `codex-desktop` package with `pkexec pacman -U` while Codex is closed. The companion package can remain installed alongside stock niri, or be removed with `pkexec pacman -R niri-codex-computer-use` after returning to stock.
