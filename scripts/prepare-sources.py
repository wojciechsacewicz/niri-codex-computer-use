#!/usr/bin/env python3
"""Fetch pinned sources and apply the reviewed project patches."""
import argparse
import runpy
import hashlib
import json
from pathlib import Path
import subprocess

source_digest = runpy.run_path(str(Path(__file__).with_name('source-state.py')))['source_digest']
root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'sources.lock.json').read_text())
parser = argparse.ArgumentParser()
parser.add_argument('component', choices=['niri', 'codex', 'all'], default='all', nargs='?')
args = parser.parse_args()


def run(*command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def prepare(name, source, patches):
    for patch in patches:
        if not patch.is_file():
            raise SystemExit(f'Missing reviewed patch: {patch.relative_to(root)}')
    stamp = dict(repository=source['repository'], revision=source['revision'],
                 patches={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in patches})
    directory = root / 'build' / name
    marker = directory / '.nccu-source.json'
    if directory.exists():
        if marker.exists():
            previous = json.loads(marker.read_text())
            tree = previous.pop('source_sha256', None)
        else:
            previous, tree = None, None
        if previous == stamp and tree == source_digest(directory):
            run('git', 'diff', '--check', cwd=directory)
            print(f'{name}: pinned source already prepared')
            return
        raise SystemExit(f'{directory.relative_to(root)} exists without the expected source stamp. Preserve any edits before preparing a fresh checkout.')
    directory.mkdir(parents=True)
    run('git', 'init', '-q', str(directory))
    run('git', 'fetch', '--depth=1', source['repository'], source['revision'], cwd=directory)
    run('git', '-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD', cwd=directory)
    for patch in patches:
        run('git', 'apply', '--check', str(patch), cwd=directory)
        run('git', 'apply', str(patch), cwd=directory)
    stamp['source_sha256'] = source_digest(directory)
    marker.write_text(json.dumps(stamp, indent=2) + '\n')
    print(f'{name}: prepared pinned sources and reviewed patches')


if args.component in ['niri', 'all']:
    prepare('niri', lock['niri'], [root / 'patches/niri-ipc-tiled-window-position.patch', root / 'patches/niri-agent-input.patch', root / 'patches/cachyos/niri-themed-agent-cursor.patch'])
if args.component in ['codex', 'all']:
    prepare('codex-desktop-linux', lock['codex_desktop_linux'], [root / 'patches/cachyos/codex-helium-support.patch', root / 'patches/cachyos/codex-current-sdk.patch', root / 'patches/cachyos/codex-niri-background.patch', root / 'patches/cachyos/codex-plugin-cache.patch', root / 'patches/cachyos/codex-agent-api.patch'])
