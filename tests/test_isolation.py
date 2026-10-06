import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('test_isolation_helper', Path(__file__).with_name('isolation.py'))
isolation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolation)


class IsolationTests(unittest.TestCase):
    def test_normal_tests_always_create_a_private_network_namespace(self):
        self.assertEqual(isolation.network_namespace_args({}), ['--unshare-net'])

    def test_only_networkless_container_may_keep_its_existing_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lo').mkdir()
            (root / 'lo/flags').write_text('0x9')
            self.assertEqual(isolation.network_namespace_args({'NCCU_TEST_NETWORK_NONE': '1'}, root), [])
            (root / 'eth0').mkdir()
            with self.assertRaises(RuntimeError):
                isolation.network_namespace_args({'NCCU_TEST_NETWORK_NONE': '1'}, root)

    def test_loopback_name_without_loopback_flag_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lo').mkdir()
            (root / 'lo/flags').write_text('0x1')
            with self.assertRaises(RuntimeError):
                isolation.network_namespace_args({'NCCU_TEST_NETWORK_NONE': '1'}, root)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(RuntimeError):
            isolation.network_namespace_args({'NCCU_TEST_NETWORK_NONE': '0'})
