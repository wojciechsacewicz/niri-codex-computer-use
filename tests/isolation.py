"""Keep backend network isolation inside an already networkless CI container."""
import os
from pathlib import Path


def network_namespace_args(environment=None, interfaces=Path('/sys/class/net')):
    environment = os.environ if environment is None else environment
    flag = environment.get('NCCU_TEST_NETWORK_NONE')
    if flag is None:
        return ['--unshare-net']
    if flag != '1':
        raise RuntimeError('NCCU_TEST_NETWORK_NONE must be explicitly 1 or unset.')
    names = {path.name for path in interfaces.iterdir()}
    if names != {'lo'} or not int((interfaces / 'lo/flags').read_text().strip(), 16) & 8:
        raise RuntimeError('The test container must use Docker --network none and expose only loopback.')
    return []


if __name__ == '__main__':
    print(' '.join(network_namespace_args()))
