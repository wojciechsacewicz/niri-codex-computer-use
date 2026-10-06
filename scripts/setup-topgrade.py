#!/usr/bin/env python3
"""Add the GitHub companion updater to Topgrade without editing its main config."""
import os
from pathlib import Path
import shutil
import sys


CONTENT = '[commands]\n"niri Codex computer use" = "/usr/bin/niri-codex-computer-use update"\n'


def install(config):
    directory = config / 'topgrade.d'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'niri-codex-computer-use.toml'
    if destination.is_symlink():
        raise ValueError('Refusing to replace a symlink in the Topgrade configuration.')
    if destination.exists():
        if destination.read_text() != CONTENT:
            raise ValueError('The project Topgrade drop-in already contains other settings. Review it manually.')
        return destination
    with destination.open('x') as stream:
        stream.write(CONTENT)
    return destination


def main():
    if os.geteuid() == 0:
        raise ValueError('Run as your desktop user, not root.')
    if not shutil.which('topgrade'):
        raise ValueError('Install Topgrade before enabling its integration.')
    if not Path('/usr/bin/niri-codex-computer-use').is_file():
        raise ValueError('Install the companion package before enabling its integration.')
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    destination = install(config)
    print(f'Topgrade integration enabled at {destination}. Remove this drop-in to disable it.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
