"""Mock OS reads so the diagnostic tests never touch the user's session."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('doctor', ROOT / 'scripts/doctor.py')
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.system = Mock(spec=doctor.System)
        self.packages = {
            'niri-codex-computer-use': '0.1.0-3',
            'codex-desktop': '2026.10.06.174734-1',
        }
        self.units = {
            'niri.service': {'LoadState': 'loaded', 'ActiveState': 'inactive',
                             'FragmentPath': '/usr/lib/systemd/user/niri.service', 'MainPID': '0'},
            'niri-codex.service': {'LoadState': 'loaded', 'ActiveState': 'active',
                                   'FragmentPath': doctor.SERVICE, 'MainPID': '42'},
        }
        self.executables = {42: doctor.PATCHED_NIRI, 43: doctor.STOCK_NIRI}
        lock = {'schema': 1}
        for name in ('upstream_patches', 'niri', 'codex_desktop_linux'):
            lock[name] = {'repository': f'https://example.org/{name}', 'revision': 'a' * 40}
        self.texts = {
            doctor.INSTALLED_LOCK: json.dumps(lock),
            str(doctor.CHECKOUT / 'sources.lock.json'): json.dumps(lock, indent=2),
            doctor.SERVICE: '[Unit]\nWants=a\nWants=b\n[Service]\n'
                            f'ExecStart={doctor.PATCHED_NIRI} --session\n',
            doctor.DESKTOP: '[Desktop Entry]\nExec=niri-codex-session\nType=Application\n',
        }
        self.missing = set()
        self.system.is_file.side_effect = lambda path: path not in self.missing
        self.system.executable.return_value = True
        self.system.read_text.side_effect = lambda path: self.texts[path]
        self.system.read_exe.side_effect = lambda pid: self.executables[pid]
        self.system.query.side_effect = self.query

    def query(self, command):
        if command[0] == '/usr/bin/pacman':
            name = command[2]
            if name not in self.packages:
                return subprocess.CompletedProcess(command, 1, '', f'package {name} was not found')
            return subprocess.CompletedProcess(command, 0, f'{name} {self.packages[name]}\n', '')
        if command[0] == '/usr/bin/systemctl':
            unit = self.units[command[3]]
            output = '\n'.join(f'{key}={value}' for key, value in unit.items())
            code = 0 if unit['LoadState'] == 'loaded' else 1
            return subprocess.CompletedProcess(command, code, output, '')
        self.fail(f'Unexpected command: {command}')

    def stock_session(self):
        self.units['niri.service'].update(ActiveState='active', MainPID='43')
        self.units['niri-codex.service'].update(ActiveState='inactive', MainPID='0')

    def assert_error(self, report, message):
        self.assertEqual(report['exit_code'], 1, report)
        self.assertTrue(any(message in error for error in report['errors']), report['errors'])

    def test_patched_active_configuration_is_ready_without_input_claim(self):
        report = doctor.diagnose(self.system)
        self.assertEqual(report['exit_code'], 0, report['errors'])
        self.assertEqual(report['status'], 'active ready configuration')
        self.assertEqual(report['session']['executable'], doctor.PATCHED_NIRI)
        self.assertFalse(report['cua_input_verified'])
        self.assertTrue(report['source_lock']['matches'])
        self.assertEqual(report['packages']['niri-codex-computer-use']['version'], '0.1.0-3')

    def test_stock_active_is_activation_pending_not_installation_error(self):
        self.stock_session()
        report = doctor.diagnose(self.system)
        self.assertEqual(report['exit_code'], 2)
        self.assertEqual(report['status'], 'activation pending')
        self.assertEqual(report['session']['status'], 'stock active')
        self.assertEqual(report['errors'], [])
        self.system.read_exe.assert_called_once_with(43)

    def test_no_active_session_is_pending(self):
        self.units['niri-codex.service'].update(ActiveState='inactive', MainPID='0')
        report = doctor.diagnose(self.system)
        self.assertEqual(report['exit_code'], 2)
        self.assertEqual(report['session']['status'], 'no active session')
        self.system.read_exe.assert_not_called()

    def test_missing_packages_are_errors_even_with_stock_active(self):
        self.stock_session()
        for package in tuple(self.packages):
            with self.subTest(package=package):
                version = self.packages.pop(package)
                report = doctor.diagnose(self.system)
                self.assert_error(report, f'Package {package} is unavailable')
                self.assertFalse(report['packages'][package]['installed'])
                self.packages[package] = version

    def test_missing_or_not_loaded_units_are_errors(self):
        for name in self.units:
            for state in ('not-found', 'masked', ''):
                with self.subTest(unit=name, state=state):
                    original = self.units[name].copy()
                    self.units[name].update(LoadState=state, ActiveState='inactive',
                                            FragmentPath='', MainPID='0')
                    self.assert_error(doctor.diagnose(self.system), f'{name} is not loaded')
                    self.units[name] = original

    def test_correct_service_active_with_wrong_binary_is_error(self):
        for executable in (doctor.STOCK_NIRI, '/tmp/niri', doctor.PATCHED_NIRI + ' (deleted)'):
            with self.subTest(executable=executable):
                self.executables[42] = executable
                report = doctor.diagnose(self.system)
                self.assert_error(report, 'niri-codex.service is active with the wrong binary')
                self.assertEqual(report['units']['niri-codex.service']['executable'], executable)

    def test_failed_service_is_error(self):
        self.stock_session()
        self.units['niri-codex.service']['ActiveState'] = 'failed'
        self.assert_error(doctor.diagnose(self.system), 'niri-codex.service is failed')

    def test_missing_backend_cannot_fall_back_to_another_helper(self):
        path = doctor.FILES['backend'][0]
        self.missing.add(path)
        self.assert_error(doctor.diagnose(self.system), f'Missing installed backend: {path}')
        self.assertFalse(any('cosmic' in str(call) for call in self.system.mock_calls))

    def test_missing_installed_service_or_desktop_file_is_error(self):
        for path in (doctor.SERVICE, doctor.DESKTOP):
            with self.subTest(path=path):
                self.missing.add(path)
                self.assert_error(doctor.diagnose(self.system), path)
                self.missing.remove(path)

    def test_nonexecutable_backend_is_error(self):
        self.system.executable.side_effect = lambda path: path != doctor.FILES['backend'][0]
        self.assert_error(doctor.diagnose(self.system), 'backend is not executable')

    def test_wrong_installed_launch_target_is_error(self):
        for path, text, message in (
            (doctor.SERVICE, '[Service]\nExecStart=/usr/bin/niri --session', 'unexpected ExecStart'),
            (doctor.DESKTOP, '[Desktop Entry]\nExec=niri-session', 'unexpected Exec'),
        ):
            with self.subTest(path=path):
                original = self.texts[path]
                self.texts[path] = text
                self.assert_error(doctor.diagnose(self.system), message)
                self.texts[path] = original

    def test_wrong_loaded_fragment_is_error(self):
        self.units['niri-codex.service']['FragmentPath'] = '/home/user/niri-codex.service'
        self.assert_error(doctor.diagnose(self.system), 'unexpected fragment')

    def test_lock_mismatch_invalid_or_unreadable_is_error(self):
        original = self.texts[doctor.INSTALLED_LOCK]
        mismatch = json.loads(original)
        mismatch['niri']['revision'] = 'b' * 40
        for text, message in ((json.dumps(mismatch), 'differs from the checkout'),
                              ('{}', 'Invalid installed source lock'),
                              ('not json', 'Cannot read installed source lock')):
            with self.subTest(text=text):
                self.texts[doctor.INSTALLED_LOCK] = text
                self.assert_error(doctor.diagnose(self.system), message)
        self.system.read_text.side_effect = FileNotFoundError('missing source lock')
        self.assert_error(doctor.diagnose(self.system), 'Cannot read checkout source lock')

    def test_unreadable_proc_exe_never_reports_ready(self):
        self.system.read_exe.side_effect = PermissionError('denied')
        self.assert_error(doctor.diagnose(self.system), 'Cannot read /proc/42/exe')

    def test_invalid_missing_or_zero_mainpid_never_reports_ready(self):
        for pid in ('bad', '-1', '0', None):
            with self.subTest(pid=pid):
                self.units['niri-codex.service']['MainPID'] = pid
                if pid is None:
                    del self.units['niri-codex.service']['MainPID']
                self.assertEqual(doctor.diagnose(self.system)['exit_code'], 1)

    def test_both_units_active_is_error(self):
        self.units['niri.service'].update(ActiveState='active', MainPID='43')
        self.assert_error(doctor.diagnose(self.system), 'Both niri units')

    def test_query_timeout_or_unavailable_tool_becomes_diagnostic_error(self):
        for failure in (subprocess.TimeoutExpired('/usr/bin/systemctl', 5),
                        FileNotFoundError('/usr/bin/pacman')):
            with self.subTest(failure=failure):
                self.system.query.side_effect = failure
                report = doctor.diagnose(self.system)
                self.assertEqual(report['exit_code'], 1)
                self.assertTrue(any(str(failure) in error for error in report['errors']))

    def test_cli_json_is_one_object_and_preserves_exit_codes(self):
        for expected in (0, 2, 1):
            with self.subTest(exit_code=expected):
                if expected == 2:
                    self.stock_session()
                elif expected == 1:
                    self.packages.pop('codex-desktop')
                output = io.StringIO()
                with redirect_stdout(output):
                    code = doctor.main(['--json'], self.system)
                report = json.loads(output.getvalue())
                self.assertEqual(code, expected)
                self.assertEqual(report['exit_code'], code)
                self.assertFalse(report['cua_input_verified'])
                self.assertIsInstance(report['units'], dict)

    def test_cli_default_is_readable_and_documents_pending(self):
        self.stock_session()
        output = io.StringIO()
        with redirect_stdout(output):
            code = doctor.main([], self.system)
        self.assertEqual(code, 2)
        text = output.getvalue()
        for expected in ('activation pending', '0.1.0-3', 'MainPID=43',
                         'exe=/usr/bin/niri (stock)', 'Source lock: matches checkout',
                         'CUA input has not been tested'):
            self.assertIn(expected, text)
        self.assertNotIn('ERROR:', text)

    def test_only_readonly_public_commands_are_queried(self):
        doctor.diagnose(self.system)
        commands = [call.args[0] for call in self.system.query.call_args_list]
        self.assertEqual(commands, [
            ['/usr/bin/pacman', '-Q', 'niri-codex-computer-use'],
            ['/usr/bin/pacman', '-Q', 'codex-desktop'],
            ['/usr/bin/systemctl', '--user', 'show', 'niri.service',
             '--property=LoadState,ActiveState,FragmentPath,MainPID'],
            ['/usr/bin/systemctl', '--user', 'show', 'niri-codex.service',
             '--property=LoadState,ActiveState,FragmentPath,MainPID'],
        ])

    def test_real_query_uses_timeout_and_no_shell(self):
        with patch.object(doctor.subprocess, 'run') as run:
            doctor.System().query(['/usr/bin/pacman', '-Q', 'codex-desktop'])
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['env']['PATH'], '/usr/bin:/bin')
        self.assertFalse(run.call_args.kwargs.get('shell', False))


if __name__ == '__main__':
    unittest.main()
