import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock


spec = importlib.util.spec_from_file_location('runtime_health', Path(__file__).resolve().parents[1] / 'scripts/runtime-health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class RuntimeHealthTests(unittest.TestCase):
    def test_resolved_libraries(self):
        query = Mock(return_value=subprocess.CompletedProcess([], 0, 'libc.so.6 => /usr/lib/libc.so.6\n', ''))
        self.assertEqual(health.inspect_libraries('/trusted/binary', query), {'missing': [], 'error': None})

    def test_missing_library_is_reported(self):
        query = Mock(return_value=subprocess.CompletedProcess([], 0, 'libdisplay-info.so.3 => not found\n', ''))
        self.assertEqual(health.inspect_libraries('/trusted/binary', query)['missing'], ['libdisplay-info.so.3'])

    def test_timeout_is_an_error(self):
        query = Mock(side_effect=subprocess.TimeoutExpired(['ldd'], 10))
        self.assertTrue(health.inspect_libraries('/trusted/binary', query)['error'])

    def test_failed_inspection_is_not_healthy(self):
        query = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'not a dynamic executable'))
        self.assertTrue(health.inspect_libraries('/trusted/binary', query)['error'])


if __name__ == '__main__':
    unittest.main()
