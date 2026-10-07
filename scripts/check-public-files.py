#!/usr/bin/env python3
"""Check staged or tracked files without printing suspected private values."""
import argparse
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--staged', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]


def git(*command):
    return subprocess.check_output(['git', *command], cwd=root)


rules = {
    'personal home path': re.compile(rb'/(?:home|Users)/([^/\s\x00"\'<>]+)'),
    'session history': re.compile(rb'rollout-20\d\d|\.codex[/]sessions/|01a[0-9a-f]{5}-[0-9a-f]{4}-[0-9a-f-]{23}', re.I),
    'private network address': re.compile(rb'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b'),
    'machine diagnostic output': re.compile(rb'^(?:COREDUMP_(?:HOSTNAME|ENVIRON|CMDLINE)|(?:Machine|Boot)\s*ID|Hostname|Serial Number|SSID)\s*[:=]', re.M | re.I),
    'credential': re.compile(rb'github_pat_[a-zA-Z0-9_]{20,}|gh[pousr]_[a-zA-Z0-9]{20,}|sk-(?:proj-)?[a-zA-Z0-9_-]{25,}|-----BEGIN (?:OPENSSH|RSA|EC|DSA)? ?PRIVATE KEY-----'),
}
identifiers = [socket.gethostname()]
for filename in ['/etc/machine-id', '/proc/sys/kernel/random/boot_id']:
    try:
        identifiers.append(Path(filename).read_text().strip())
    except OSError:
        pass
identifiers = [value for value in identifiers if value and value not in {'localhost', 'localhost.localdomain'}]
if identifiers:
    rules['local machine identifier'] = re.compile(
        rb'(?<![\w.-])(?:' + b'|'.join(re.escape(value.encode()) for value in identifiers) + rb')(?![\w.-])')
excluded_roots = {'.local', 'build', 'dist', 'target', '.codex', 'sessions'}
examples = {b'user', b'example', b'builder'}
failures = []
paths = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z') if args.staged else git('ls-files', '-z')
for raw in paths.split(b'\0'):
    if not raw:
        continue
    name = raw.decode('utf-8')
    path = Path(name)
    if path.parts[0] in excluded_roots or 'checkpoint' in path.name.lower():
        failures.append((name, 'private/generated file'))
        continue
    content = git('show', ':' + name) if args.staged else (root / path).read_bytes()
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        offset = 8
        while offset + 12 <= len(content):
            size = struct.unpack_from('>I', content, offset)[0]
            kind = content[offset + 4:offset + 8]
            if offset + size + 12 > len(content):
                failures.append((name, 'malformed PNG'))
                break
            if kind in {b'tEXt', b'zTXt', b'iTXt', b'eXIf'}:
                failures.append((name, 'PNG metadata requires review'))
            offset += size + 12
        continue
    if b'\0' in content:
        failures.append((name, 'binary file requires review'))
        continue
    for label, pattern in rules.items():
        for match in pattern.finditer(content):
            if label == 'personal home path' and match.group(1) in examples:
                continue
            line = content[:match.start()].count(b'\n') + 1
            failures.append((f'{name}:{line}', label))

for location, reason in failures:
    print(f'{location}: {reason}', file=sys.stderr)
if failures:
    sys.exit(1)
print('Public-file checks passed. Review image pixels and Git history separately.')
