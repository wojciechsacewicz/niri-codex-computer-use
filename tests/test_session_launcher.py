"""Exercise login startup with a fake manager, without starting a compositor."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'packaging/arch/niri-codex-session'


class SessionLauncherTests(unittest.TestCase):
    def run_launcher(self, **settings):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            commands = base / 'commands.jsonl'
            mock = base / 'systemctl'
            mock.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['NCCU_COMMAND_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if 'is-active' in args:
    sys.exit(0 if os.environ.get('NCCU_ACTIVE') == '1' else 3)
if 'daemon-reload' in args:
    sys.exit(int(os.environ.get('NCCU_RELOAD_EXIT', '0')))
if 'show' in args:
    print(os.environ.get('NCCU_LOAD_STATE', 'loaded'))
elif 'is-failed' in args:
    sys.exit(0 if os.environ.get('NCCU_FAILED') == '1' else 1)
elif 'reset-failed' in args:
    if os.environ.get('NCCU_FAILED') != '1':
        print('Unit niri-codex.service not loaded.', file=sys.stderr)
        sys.exit(1)
elif 'start' in args:
    if '--wait' in args:
        sys.exit(int(os.environ.get('NCCU_START_EXIT', '0')))
    sys.exit(int(os.environ.get('NCCU_CLEANUP_EXIT', '0')))
''')
            mock.chmod(0o755)
            dbus = base / 'dbus-update-activation-environment'
            dbus.write_text('#!/bin/sh\nexit 0\n')
            dbus.chmod(0o755)
            env = {**os.environ, 'PATH': str(base) + ':/usr/bin:/bin',
                   'NCCU_COMMAND_LOG': str(commands), **settings}
            result = subprocess.run(['/usr/bin/bash', str(LAUNCHER), '-l'],
                                    env=env, text=True, capture_output=True, timeout=10)
            calls = [json.loads(line) for line in commands.read_text().splitlines()]
            return result, calls

    def test_first_login_does_not_reset_an_unloaded_unit(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('reset-failed' in call for call in calls))
        self.assertIn(['--user', '--wait', 'start', 'niri-codex.service'], calls)
        self.assertLess(calls.index(['--user', 'daemon-reload']),
                        calls.index(['--user', '--wait', 'start', 'niri-codex.service']))

    def test_failed_unit_is_reset_before_start(self):
        result, calls = self.run_launcher(NCCU_FAILED='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(calls.index(['--user', 'reset-failed', 'niri-codex.service']),
                        calls.index(['--user', '--wait', 'start', 'niri-codex.service']))

    def test_running_session_is_left_alone(self):
        result, calls = self.run_launcher(NCCU_ACTIVE='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('already running', result.stderr)
        self.assertFalse(any('start' in call or 'daemon-reload' in call for call in calls))

    def test_missing_unit_does_not_start_or_shutdown_anything(self):
        result, calls = self.run_launcher(NCCU_LOAD_STATE='not-found')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Reinstall', result.stderr)
        self.assertFalse(any('start' in call for call in calls))

    def test_reload_failure_stops_before_start(self):
        result, calls = self.run_launcher(NCCU_RELOAD_EXIT='5')
        self.assertEqual(result.returncode, 5)
        self.assertFalse(any('start' in call for call in calls))

    def test_start_failure_is_preserved_after_cleanup(self):
        result, calls = self.run_launcher(NCCU_START_EXIT='7', NCCU_CLEANUP_EXIT='9')
        self.assertEqual(result.returncode, 7)
        self.assertTrue(any('niri-shutdown.target' in call for call in calls))
        self.assertTrue(any('unset-environment' in call for call in calls))

    def test_cleanup_failure_is_reported(self):
        result, _ = self.run_launcher(NCCU_CLEANUP_EXIT='9')
        self.assertEqual(result.returncode, 1)
        self.assertIn('cleanup', result.stderr)


if __name__ == '__main__':
    unittest.main()
