#!/usr/bin/env python3
"""Build and test a published GitHub release before installing its companion."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = 'wojciechsacewicz/niri-codex-computer-use'
PACKAGE = 'niri-codex-computer-use'
DESKTOP = Path('/opt/codex-desktop')
inspect_libraries = runpy.run_path(str(Path(__file__).with_name('runtime-health.py')))['inspect_libraries']


def run(*command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def github(endpoint):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + endpoint,
                                    headers={'Accept': 'application/vnd.github+json',
                                             'User-Agent': PACKAGE})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def latest_release():
    try:
        release = github('/releases/latest')
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('The latest release is not a stable published release.')
    tag = release['tag_name']
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Release tag must use vMAJOR.MINOR.PATCH naming.')
    commit = github('/commits/' + urllib.parse.quote(tag, safe=''))['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('GitHub did not resolve the release to an exact commit.')
    manifest = github('/contents/packaging/arch/release.json?ref=' + commit)
    if manifest.get('encoding') != 'base64' or manifest.get('size', 0) > 65536:
        raise ValueError('Invalid package release manifest.')
    metadata = json.loads(base64.b64decode(manifest['content']))
    if metadata.get('pkgver') != tag[1:] or type(metadata.get('pkgrel')) is not int or metadata['pkgrel'] < 1:
        raise ValueError('The release tag does not match its package metadata.')
    return {'tag': tag, 'version': tag[1:], 'revision': commit,
            'package_version': f"{metadata['pkgver']}-{metadata['pkgrel']}"}


def installed_version():
    result = subprocess.run(['pacman', '-Q', PACKAGE], text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError('Install the companion package before configuring automatic updates.')
    fields = result.stdout.split()
    if len(fields) != 2 or fields[0] != PACKAGE:
        raise ValueError('Unexpected package manager response.')
    return fields[1]


def needs_update(installed, release):
    # vercmp uses pacman's epoch/version/release ordering, including downgrades.
    comparison = subprocess.check_output(['vercmp', release['package_version'], installed],
                                         text=True, timeout=10).strip()
    return int(comparison) > 0


def assert_installed_libraries():
    for name in ('niri', 'codex-computer-use-linux'):
        state = inspect_libraries(Path('/usr/lib') / PACKAGE / 'bin' / name)
        if state['error'] or state['missing']:
            raise ValueError(f'{name} requires a compatible rebuild after a system library update: '
                             f'{state["error"] or ", ".join(state["missing"])}. '
                             'Use stock Niri until a verified companion build is available.')


def verify_installed_desktop(source):
    helper = DESKTOP / 'resources/plugins/openai-bundled/plugins/unified-computer-use/bin/codex-computer-use-linux'
    node = DESKTOP / 'resources/cua_node/bin/node'
    xvfb = shutil.which('Xvfb')
    if not helper.is_file() or not node.is_file() or not xvfb:
        raise ValueError('The installed native Codex helper, bundled Node, and Xvfb are required for update compatibility checks.')
    environment = {**os.environ, 'INSTALL_DIR': str(DESKTOP)}
    run(str(node), '--test', str(source / 'build/codex-desktop-linux/linux-features/computer-use-linux/validator.test.js'),
        env=environment)
    # Exercise the installed app's helper against the candidate compositor on a private display.
    run('python3', str(source / 'tests/backend-mcp-check.py'), '--niri', str(source / '.local/outputs/niri'),
        '--xvfb', xvfb, '--backend', str(helper), '--output', str(source / '.local/checks/installed-desktop'))


def build_release(release, cache):
    directory = Path(tempfile.mkdtemp(prefix=release['revision'] + '-', dir=cache))
    print(f'Building in {directory}. Previous attempts are preserved.', flush=True)
    run('git', 'init', '-q', str(directory))
    run('git', 'fetch', '--depth=1', 'https://github.com/' + REPOSITORY + '.git', release['revision'], cwd=directory)
    run('git', '-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD', cwd=directory)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=directory, text=True).strip()
    if actual != release['revision']:
        raise ValueError('Fetched source does not match the published release.')
    metadata = json.loads((directory / 'packaging/arch/release.json').read_text())
    if metadata.get('pkgver') != release['version'] or type(metadata.get('pkgrel')) is not int or metadata['pkgrel'] < 1:
        raise ValueError('The release tag does not match its package metadata.')
    recipe_directory = directory / 'dist/arch-source'
    run('python3', str(directory / 'scripts/export-arch-recipe.py'), '--revision', actual,
        '--output', str(recipe_directory), cwd=directory)
    # makepkg runs prepare, build, check and the evidence gate in package().
    run('makepkg', '--noconfirm', '--log', cwd=recipe_directory,
        env={**os.environ, 'NCCU_JOBS': os.environ.get('NCCU_JOBS', '2'),
             'NCCU_CARGO_CACHE': os.environ.get('NCCU_CARGO_CACHE', str(cache / 'cargo-cache'))},
        preexec_fn=lambda: os.nice(10))
    packages = subprocess.check_output(['makepkg', '--packagelist'], cwd=recipe_directory, text=True).splitlines()
    if len(packages) != 1:
        raise ValueError('Expected exactly one companion package.')
    package = Path(packages[0])
    expected = f"{PACKAGE} {metadata['pkgver']}-{metadata['pkgrel']}"
    if subprocess.check_output(['pacman', '-Qp', str(package)], text=True, timeout=10).strip() != expected:
        raise ValueError('Built package identity does not match its release.')
    verify_installed_desktop(recipe_directory / 'src/nccu')
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Report availability without downloading sources or installing')
    parser.add_argument('--build-only', action='store_true', help='Build and test without installing')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.exit(1, 'Run this command as your desktop user, not root. Installation uses polkit.\n')
    try:
        installed = installed_version()
        release = latest_release()
        if release is None:
            assert_installed_libraries()
            print('No stable GitHub release is published. The installed package is unchanged.')
            return 0
        if not needs_update(installed, release):
            assert_installed_libraries()
            print(f'Installed {installed}; GitHub {release["tag"]}. No upgrade or downgrade is needed.')
            return 0
        print(f'Available: {release["tag"]}, exact source {release["revision"]}.', flush=True)
        if args.check:
            return 0
        cache_base = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
        cache = cache_base / PACKAGE / 'updates'
        cache.mkdir(parents=True, exist_ok=True)
        with (cache / 'update.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another companion update is running.')
            package = build_release(release, cache)
            if args.build_only:
                print(f'Built and tested: {package}. Nothing was installed.')
                return 0
            run('pkexec', 'pacman', '-U', '--noconfirm', str(package))
            print('Companion installed. Your compositor was not restarted. The new compositor runs at your next login.')
            print('The Codex desktop app keeps its existing updater and SDK compatibility checks.')
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'Companion update stopped: {exc}\nNo session restart was requested.\n')


if __name__ == '__main__':
    raise SystemExit(main())
