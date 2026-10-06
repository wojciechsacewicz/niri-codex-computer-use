#!/usr/bin/env bash
# Shared payload for local builds and source packages.
nccu_package_files() {
    local root="$1" destination="$2" package_name=niri-codex-computer-use
    install -Dm755 "$root/.local/outputs/niri" "$destination/usr/lib/$package_name/bin/niri"
    install -Dm755 "$root/.local/outputs/codex-computer-use-linux" "$destination/usr/lib/$package_name/bin/codex-computer-use-linux"
    install -Dm755 "$root/packaging/arch/niri-codex-session" "$destination/usr/bin/niri-codex-session"
    install -Dm755 "$root/packaging/arch/niri-codex-computer-use" "$destination/usr/bin/niri-codex-computer-use"
    install -Dm644 "$root/packaging/arch/niri-codex.desktop" "$destination/usr/share/wayland-sessions/niri-codex.desktop"
    install -Dm644 "$root/packaging/arch/niri-codex.service" "$destination/usr/lib/systemd/user/niri-codex.service"
    install -Dm644 "$root/LICENSE" "$destination/usr/share/licenses/$package_name/LICENSE"
    install -Dm644 "$root/LICENSES/GPL-3.0-or-later.txt" "$destination/usr/share/licenses/$package_name/GPL-3.0-or-later.txt"
    install -Dm644 "$root/sources.lock.json" "$destination/usr/share/$package_name/sources.lock.json"
    install -Dm644 "$root/README.md" "$destination/usr/share/doc/$package_name/README.md"
    for script in doctor.py check-updates.py release-update.py setup-topgrade.py; do
        install -Dm644 "$root/scripts/$script" "$destination/usr/share/$package_name/scripts/$script"
    done
}
