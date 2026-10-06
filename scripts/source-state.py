"""Fingerprint the prepared source tree, excluding build artifacts."""
import hashlib
from pathlib import Path
import subprocess


def source_digest(directory):
    output = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=directory)
    names = sorted(set(output.decode().split('\0')) - {'', '.nccu-source.json'})
    digest = hashlib.sha256()
    for name in names:
        path = Path(directory) / name
        digest.update(name.encode() + b'\0')
        if path.is_symlink():
            digest.update(b'link\0' + str(path.readlink()).encode())
        else:
            digest.update(path.read_bytes())
    return digest.hexdigest()
