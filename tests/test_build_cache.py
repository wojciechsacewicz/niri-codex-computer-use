import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildCacheTests(unittest.TestCase):
    def build(self, **settings):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'scripts/build.sh', root / 'scripts/build.sh')
        tools = root / 'tools'
        tools.mkdir()
        prepare = tools / 'python3'
        prepare.write_text('#!/bin/sh\nexit 0\n')
        prepare.chmod(0o755)
        cargo = tools / 'cargo'
        cargo.write_text('''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
assert '--locked' in args and '--release' in args
target=Path(args[args.index('--target-dir')+1])/'release'
target.mkdir(parents=True,exist_ok=True)
names=['niri'] if args[args.index('--manifest-path')+1].endswith('/niri/Cargo.toml') else ['codex-computer-use-linux','codex-computer-use-cosmic']
for name in names:
    (target/name).write_text('controlled fixture '+name)
with open(os.environ['NCCU_BUILD_LOG'],'a') as log:
    log.write(json.dumps(args)+'\\n')
''')
        cargo.chmod(0o755)
        log = root / 'build.jsonl'
        env = {**os.environ, 'PATH': str(tools) + ':/usr/bin:/bin', 'NCCU_BUILD_LOG': str(log)}
        for variable in ('NCCU_CARGO_CACHE', 'NCCU_JOBS'):
            env.pop(variable, None)
        env.update(settings)
        if env.get('NCCU_CARGO_CACHE') == 'fixture':
            env['NCCU_CARGO_CACHE'] = str(root / 'external cache')
        result = subprocess.run(['bash', str(root / 'scripts/build.sh'), 'all'], env=env,
                                capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return root, result, calls

    def test_default_component_targets_ignore_unrelated_global_target(self):
        root, result, calls = self.build(CARGO_TARGET_DIR='/unrelated/global/cache')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(root / 'build/niri/target'), calls[0])
        self.assertIn(str(root / 'build/codex-desktop-linux/target'), calls[1])
        self.assertEqual((root / '.local/outputs/niri').read_text(), 'controlled fixture niri')

    def test_external_cache_produces_all_packaged_helpers(self):
        root, result, calls = self.build(NCCU_CARGO_CACHE='fixture')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(root / 'external cache/niri/target'), calls[0])
        for name in ('niri', 'codex-computer-use-linux', 'codex-computer-use-cosmic'):
            self.assertTrue((root / '.local/outputs' / name).is_file())

    def test_relative_cache_is_rejected_before_build(self):
        _, result, calls = self.build(NCCU_CARGO_CACHE='relative/cache')
        self.assertEqual(result.returncode, 2)
        self.assertIn('absolute', result.stderr)
        self.assertEqual(calls, [])

    def test_invalid_parallelism_is_rejected_before_build(self):
        _, result, calls = self.build(NCCU_JOBS='0')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
