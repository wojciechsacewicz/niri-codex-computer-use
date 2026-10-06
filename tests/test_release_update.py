import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_update', ROOT / 'scripts/release-update.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
spec = importlib.util.spec_from_file_location('setup_topgrade', ROOT / 'scripts/setup-topgrade.py')
topgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(topgrade)


class ReleaseUpdateTests(unittest.TestCase):
    def setUp(self):
        healthy = patch.object(updater, 'inspect_libraries', return_value={'missing': [], 'error': None})
        healthy.start()
        self.addCleanup(healthy.stop)

    def test_broken_library_is_not_reported_as_up_to_date(self):
        with patch.object(updater, 'inspect_libraries', return_value={'missing': ['libdisplay-info.so.3'], 'error': None}):
            with self.assertRaisesRegex(ValueError, 'rebuild'):
                updater.assert_installed_libraries()

    def test_missing_desktop_helper_stops_compatibility_check(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, 'DESKTOP', Path(directory)), \
             patch.object(updater, 'run') as run:
            with self.assertRaises(ValueError):
                updater.verify_installed_desktop(Path(directory))
            run.assert_not_called()

    def test_desktop_helper_is_tested_on_private_candidate_compositor(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            helper = base / 'resources/plugins/openai-bundled/plugins/unified-computer-use/bin/codex-computer-use-linux'
            node = base / 'resources/cua_node/bin/node'
            for file in (helper, node):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            source = base / 'source'
            with patch.object(updater, 'DESKTOP', base), patch.object(updater.shutil, 'which', return_value='/usr/bin/Xvfb'), \
                 patch.object(updater, 'run') as run:
                updater.verify_installed_desktop(source)
            calls = run.call_args_list
            self.assertEqual(calls[0].kwargs['env']['INSTALL_DIR'], str(base))
            self.assertIn(str(helper), calls[1].args)
            self.assertIn(str(source / '.local/outputs/niri'), calls[1].args)
            self.assertNotIn('pkexec', calls[0].args + calls[1].args)

    def test_absent_release_is_normal(self):
        error = urllib.error.HTTPError('test', 404, 'Not found', None, None)
        with patch.object(updater, 'github', side_effect=error):
            self.assertIsNone(updater.latest_release())

    def test_network_error_is_not_reported_as_no_update(self):
        with patch.object(updater, 'github', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(urllib.error.URLError):
                updater.latest_release()

    def test_draft_and_prerelease_are_rejected(self):
        for flag in ('draft', 'prerelease'):
            with self.subTest(flag=flag), patch.object(updater, 'github', return_value={flag: True}):
                with self.assertRaises(ValueError):
                    updater.latest_release()

    def test_release_resolves_exact_commit_and_package_release(self):
        manifest = {'encoding': 'base64', 'size': 50,
                    'content': base64.b64encode(json.dumps({'pkgver': '0.1.1', 'pkgrel': 2}).encode()).decode()}
        with patch.object(updater, 'github', side_effect=[{'tag_name': 'v0.1.1'}, {'sha': 'a' * 40}, manifest]) as request:
            result = updater.latest_release()
        self.assertEqual(result['package_version'], '0.1.1-2')
        self.assertEqual(request.call_args_list[1].args, ('/commits/v0.1.1',))
        self.assertIn('ref=' + 'a' * 40, request.call_args_list[2].args[0])

    def test_mismatched_metadata_is_rejected(self):
        manifest = {'encoding': 'base64', 'size': 50,
                    'content': base64.b64encode(b'{"pkgver":"9.9.9","pkgrel":1}').decode()}
        with patch.object(updater, 'github', side_effect=[{'tag_name': 'v0.1.1'}, {'sha': 'a' * 40}, manifest]):
            with self.assertRaises(ValueError):
                updater.latest_release()

    def test_version_comparison_respects_package_release(self):
        with patch.object(updater.subprocess, 'check_output', return_value='1\n') as call:
            self.assertTrue(updater.needs_update('0.1.1-1', {'package_version': '0.1.1-2'}))
            self.assertEqual(call.call_args.args[0], ['vercmp', '0.1.1-2', '0.1.1-1'])
        with patch.object(updater.subprocess, 'check_output', return_value='-1\n'):
            self.assertFalse(updater.needs_update('0.2.0-1', {'package_version': '0.1.1-2'}))

    def test_no_release_does_not_build_or_install(self):
        with patch('sys.argv', ['release-update.py']), patch.object(updater.os, 'geteuid', return_value=1000), \
             patch.object(updater, 'installed_version', return_value='0.1.0-3'), \
             patch.object(updater, 'latest_release', return_value=None), patch.object(updater, 'build_release') as build:
            self.assertEqual(updater.main(), 0)
            build.assert_not_called()

    def test_check_does_not_build(self):
        release = {'tag': 'v0.1.1', 'revision': 'a' * 40, 'package_version': '0.1.1-1'}
        with patch('sys.argv', ['release-update.py', '--check']), patch.object(updater.os, 'geteuid', return_value=1000), \
             patch.object(updater, 'installed_version', return_value='0.1.0-3'), \
             patch.object(updater, 'latest_release', return_value=release), patch.object(updater, 'needs_update', return_value=True), \
             patch.object(updater, 'build_release') as build:
            self.assertEqual(updater.main(), 0)
            build.assert_not_called()

    def test_failed_build_never_reaches_polkit(self):
        release = {'tag': 'v0.1.1', 'revision': 'a' * 40, 'package_version': '0.1.1-1'}
        with tempfile.TemporaryDirectory() as cache, patch.dict(updater.os.environ, {'XDG_CACHE_HOME': cache}), \
             patch('sys.argv', ['release-update.py']), patch.object(updater.os, 'geteuid', return_value=1000), \
             patch.object(updater, 'installed_version', return_value='0.1.0-3'), \
             patch.object(updater, 'latest_release', return_value=release), patch.object(updater, 'needs_update', return_value=True), \
             patch.object(updater, 'build_release', side_effect=subprocess.CalledProcessError(1, ['makepkg'])), \
             patch.object(updater, 'run') as run:
            with self.assertRaises(SystemExit) as failure:
                updater.main()
            self.assertEqual(failure.exception.code, 1)
            run.assert_not_called()


class TopgradeTests(unittest.TestCase):
    def test_dropin_is_idempotent_and_preserves_main_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            main = config / 'topgrade.toml'
            main.write_text('[misc]\nnotify_end = "never"\n')
            first = topgrade.install(config)
            self.assertEqual(first, topgrade.install(config))
            self.assertEqual(main.read_text(), '[misc]\nnotify_end = "never"\n')

    def test_existing_custom_dropin_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / 'topgrade.d').mkdir()
            target = config / 'topgrade.d/niri-codex-computer-use.toml'
            target.write_text('custom data')
            with self.assertRaises(ValueError):
                topgrade.install(config)
            self.assertEqual(target.read_text(), 'custom data')

    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / 'topgrade.d').mkdir()
            original = config / 'original'
            original.write_text('keep')
            (config / 'topgrade.d/niri-codex-computer-use.toml').symlink_to(original)
            with self.assertRaises(ValueError):
                topgrade.install(config)
            self.assertEqual(original.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
