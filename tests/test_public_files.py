import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='public-file-check-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'scripts/check-public-files.py', self.root / 'scripts/check-public-files.py')
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C',
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        for command in [('init', '-q'), ('config', 'user.name', 'Example'),
                        ('config', 'user.email', '1+example@users.noreply.github.com')]:
            self.git(*command)

    def git(self, *command):
        return subprocess.run(['git', *command], cwd=self.root, env=self.env,
                              check=True, capture_output=True, text=True)

    def check(self, name, content):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        self.git('add', name)
        return subprocess.run(['/usr/bin/python3', 'scripts/check-public-files.py', '--staged'],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_placeholder_paths_and_public_identity_are_allowed(self):
        result = self.check('example.md', b'/home/user/example\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_path_is_rejected_without_printing_it(self):
        result = self.check('example.md', b'/home/' + b'private-owner/secrets\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('personal home path', result.stderr)
        self.assertNotIn('private-owner', result.stderr)

    def test_generated_files_are_rejected(self):
        result = self.check('dist/log.md', b'build result\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('private/generated file', result.stderr)

    def test_public_commit_authorship_is_not_restricted(self):
        self.git('config', 'user.email', 'example@example.invalid')
        result = self.check('example.md', b'public content\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_machine_metadata_is_rejected(self):
        result = self.check('example.md', b'Boot ID: private-machine-id\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('machine diagnostic output', result.stderr)
        self.assertNotIn('private-machine-id', result.stderr)

    def test_actual_host_identifier_is_rejected_without_printing_it(self):
        hostname = socket.gethostname()
        if hostname in {'localhost', 'localhost.localdomain'}:
            self.skipTest('generic hostname')
        result = self.check('example.md', hostname.encode() + b' private process log\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('local machine identifier', result.stderr)
        self.assertNotIn(hostname, result.stderr)


if __name__ == '__main__':
    unittest.main()
