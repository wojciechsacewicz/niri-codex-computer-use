#!/usr/bin/env python3
"""Read-only CachyOS integration diagnostic.

Exit codes: 0 = active, ready configuration; 1 = errors; 2 = activation pending.
Readiness does not prove CUA input works. No backend or compositor is launched.
Tests inject System reads; the CLI always examines the real installation.
"""

import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess


PACKAGE = 'niri-codex-computer-use'
CHECKOUT = Path(__file__).resolve().parents[1]
inspect_libraries = runpy.run_path(str(Path(__file__).with_name('runtime-health.py')))['inspect_libraries']
PATCHED_NIRI = f'/usr/lib/{PACKAGE}/bin/niri'
STOCK_NIRI = '/usr/bin/niri'
INSTALLED_LOCK = f'/usr/share/{PACKAGE}/sources.lock.json'
SERVICE = '/usr/lib/systemd/user/niri-codex.service'
DESKTOP = '/usr/share/wayland-sessions/niri-codex.desktop'
PROPERTIES = ('LoadState', 'ActiveState', 'FragmentPath', 'MainPID')
TIMEOUT = 5
FILES = {
    'compositor': (PATCHED_NIRI, True),
    'backend': (f'/usr/lib/{PACKAGE}/bin/codex-computer-use-linux', True),
    'session_launcher': ('/usr/bin/niri-codex-session', True),
    'backend_launcher': ('/usr/bin/niri-codex-computer-use', True),
    'service': (SERVICE, False),
    'desktop_entry': (DESKTOP, False),
}


class System:
    """The diagnostic's read-only OS boundary."""

    def query(self, command):
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=TIMEOUT, check=False,
                              stdin=subprocess.DEVNULL,
                              env={**os.environ, 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def is_file(self, path):
        return Path(path).is_file()

    def executable(self, path):
        return os.access(path, os.X_OK)

    def read_text(self, path):
        return Path(path).read_text(encoding='utf-8')

    def read_exe(self, pid):
        return os.readlink(f'/proc/{pid}/exe')


def section_values(text, section, key):
    current = None
    values = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1]
        elif current == section and '=' in line:
            name, value = line.split('=', 1)
            if name.strip() == key:
                values.append(value.strip())
    return values


def valid_lock(value):
    if not isinstance(value, dict) or value.get('schema') != 1:
        return False
    for name in ('upstream_patches', 'niri', 'codex_desktop_linux'):
        pin = value.get(name)
        if not isinstance(pin, dict):
            return False
        revision = pin.get('revision')
        repository = pin.get('repository')
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
            return False
        if not isinstance(repository, str) or not repository.strip():
            return False
    return True


def diagnose(system=None):
    system = system if system is not None else System()
    report = {'packages': {}, 'units': {}, 'files': {}, 'source_lock': {},
              'session': {'status': 'unknown'}, 'errors': [], 'pending': [],
              'cua_input_verified': False}
    errors = report['errors']

    def query(command):
        try:
            return system.query(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f'{" ".join(command)}: {exc}')
            return None

    for package in (PACKAGE, 'codex-desktop'):
        result = query(['/usr/bin/pacman', '-Q', package])
        entry = {'installed': None, 'version': None}
        report['packages'][package] = entry
        if result is None:
            continue
        fields = result.stdout.strip().split()
        entry['installed'] = result.returncode == 0
        if result.returncode != 0:
            errors.append(f'Package {package} is unavailable: {result.stderr.strip()}')
        elif len(fields) != 2 or fields[0] != package:
            errors.append(f'Unexpected pacman response for {package}.')
        else:
            entry['version'] = fields[1]

    for role, (path, executable) in FILES.items():
        entry = {'path': path, 'exists': False}
        report['files'][role] = entry
        try:
            entry['exists'] = system.is_file(path)
            if not entry['exists']:
                errors.append(f'Missing installed {role}: {path}')
            elif executable:
                entry['executable'] = system.executable(path)
                if not entry['executable']:
                    errors.append(f'Installed {role} is not executable: {path}')
        except OSError as exc:
            errors.append(f'Cannot inspect {path}: {exc}')

    for role, section, key, expected in (
        ('service', 'Service', 'ExecStart', f'{PATCHED_NIRI} --session'),
        ('desktop_entry', 'Desktop Entry', 'Exec', 'niri-codex-session'),
    ):
        entry = report['files'][role]
        if entry['exists']:
            try:
                entry[key] = section_values(system.read_text(entry['path']), section, key)
                if entry[key] != [expected]:
                    errors.append(f'Installed {role} has unexpected {key}: {entry[key]}')
            except (OSError, UnicodeError) as exc:
                errors.append(f'Cannot read {entry["path"]}: {exc}')

    for role in ('compositor', 'backend'):
        entry = report['files'].get(role)
        if entry and entry['exists']:
            entry['libraries'] = inspect_libraries(entry['path'], system.query)
            libraries = entry['libraries']
            if libraries['missing']:
                errors.append(f'{role} needs a rebuild after a system library update: {", ".join(libraries["missing"])}')
            if libraries['error']:
                errors.append(f'Cannot inspect {role} libraries: {libraries["error"]}')

    locks = report['source_lock']
    for name, path in (('installed', INSTALLED_LOCK),
                       ('checkout', str(CHECKOUT / 'sources.lock.json'))):
        entry = {'path': path, 'value': None}
        locks[name] = entry
        try:
            entry['value'] = json.loads(system.read_text(path))
            entry['valid'] = valid_lock(entry['value'])
            if not entry['valid']:
                errors.append(f'Invalid {name} source lock: {path}')
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f'Cannot read {name} source lock: {exc}')
    locks['matches'] = (all(entry.get('valid') for entry in
                            (locks['installed'], locks['checkout']))
                        and locks['installed']['value'] == locks['checkout']['value'])
    if all(entry.get('valid') for entry in (locks['installed'], locks['checkout'])):
        if not locks['matches']:
            errors.append('Installed source lock differs from the checkout.')

    active = []
    for unit in ('niri.service', 'niri-codex.service'):
        entry = dict.fromkeys(PROPERTIES)
        entry.update(executable=None, binary='unknown')
        report['units'][unit] = entry
        result = query(['/usr/bin/systemctl', '--user', 'show', unit,
                        '--property=' + ','.join(PROPERTIES)])
        if result is None:
            continue
        if result.returncode != 0:
            errors.append(f'Cannot query {unit}: {result.stderr.strip()}')
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if separator and key in PROPERTIES:
                entry[key] = value
        if any(entry[key] is None for key in PROPERTIES):
            errors.append(f'Incomplete systemctl response for {unit}.')
            continue
        if entry['LoadState'] != 'loaded':
            errors.append(f'{unit} is not loaded: {entry["LoadState"] or "unknown"}.')
        elif not entry['FragmentPath']:
            errors.append(f'{unit} has no loaded fragment path.')
        else:
            try:
                if not system.is_file(entry['FragmentPath']):
                    errors.append(f'{unit} fragment is missing: {entry["FragmentPath"]}')
            except OSError as exc:
                errors.append(f'Cannot inspect {unit} fragment: {exc}')
            if unit == 'niri-codex.service' and entry['FragmentPath'] != SERVICE:
                errors.append(f'{unit} uses an unexpected fragment: {entry["FragmentPath"]}')
        if entry['ActiveState'] == 'failed':
            errors.append(f'{unit} is failed.')
        elif entry['ActiveState'] not in ('active', 'inactive', 'activating', 'deactivating'):
            errors.append(f'{unit} has unexpected ActiveState: {entry["ActiveState"]}')
        try:
            pid = int(entry['MainPID'])
            if pid < 0:
                raise ValueError
            entry['MainPID'] = pid
        except ValueError:
            errors.append(f'{unit} has an invalid MainPID: {entry["MainPID"]}')
            continue
        if pid > 0:
            try:
                entry['executable'] = system.read_exe(pid)
                entry['binary'] = {STOCK_NIRI: 'stock', PATCHED_NIRI: 'patched'}.get(
                    entry['executable'], 'unexpected')
            except OSError as exc:
                errors.append(f'Cannot read /proc/{pid}/exe for {unit}: {exc}')
        if entry['ActiveState'] == 'active':
            active.append(unit)
            expected = 'patched' if unit == 'niri-codex.service' else 'stock'
            if pid == 0 or entry['binary'] != expected:
                errors.append(f'{unit} is active with the wrong binary: '
                              f'{entry["executable"] or "unavailable"}; expected {expected}.')

    if len(active) > 1:
        errors.append('Both niri units report active sessions.')
    if active == ['niri-codex.service']:
        entry = report['units']['niri-codex.service']
        if entry['binary'] == 'patched':
            report['session'] = {'status': 'patched active', 'unit': active[0],
                                 'pid': entry['MainPID'], 'executable': entry['executable']}
    elif active == ['niri.service'] and report['units']['niri.service']['binary'] == 'stock':
        entry = report['units']['niri.service']
        report['session'] = {'status': 'stock active', 'unit': active[0],
                             'pid': entry['MainPID'], 'executable': entry['executable']}
        report['pending'].append('Stock niri is active; companion session activation is pending.')
    elif not active:
        report['session']['status'] = 'no active session'
        report['pending'].append('The companion session is not active; activation is pending.')

    report['exit_code'] = 1 if errors else (0 if report['session']['status'] == 'patched active' else 2)
    report['status'] = {0: 'active ready configuration', 1: 'errors',
                        2: 'activation pending'}[report['exit_code']]
    return report


def readable(report):
    lines = [f'Niri Codex diagnostic: {report["status"]} (exit {report["exit_code"]})']
    for name, entry in report['packages'].items():
        lines.append(f'Package {name}: {entry["version"] or "unavailable"}')
    for name, entry in report['units'].items():
        lines.append(f'{name}: load={entry["LoadState"]}, active={entry["ActiveState"]}, '
                     f'fragment={entry["FragmentPath"]}, MainPID={entry["MainPID"]}, '
                     f'exe={entry["executable"] or "none"} ({entry["binary"]})')
    for role, entry in report['files'].items():
        state = 'present' if entry['exists'] else 'missing'
        lines.append(f'{role}: {state}, {entry["path"]}')
    lines.append('Source lock: ' + ('matches checkout' if report['source_lock']['matches']
                                   else 'unavailable, invalid or different from checkout'))
    lines.extend(f'ERROR: {message}' for message in report['errors'])
    lines.extend(f'PENDING: {message}' for message in report['pending'])
    lines.append('CUA input has not been tested. This diagnostic only reads system state.')
    return '\n'.join(lines)


def main(argv=None, system=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print a JSON diagnostic object.')
    args = parser.parse_args(argv)
    report = diagnose(system)
    print(json.dumps(report, indent=2) if args.json else readable(report))
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
