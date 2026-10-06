#!/usr/bin/env python3
"""Refuse packaging when tests belong to a different binary or test version."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for suite, fixture, binaries in [
    ('native', 'gtk-fixture.py', ['niri']),
    ('backend', 'gtk-slider-fixture.py', ['niri', 'codex-computer-use-linux']),
]:
    directory = root / '.local/checks' / suite
    result = json.loads((directory / 'result.json').read_text())
    assert result['status'] == 'passed', f'{suite} checks did not pass'
    for name in binaries:
        actual = hashlib.sha256((root / '.local/outputs' / name).read_bytes()).hexdigest()
        assert result['binary_sha256'][name] == actual, f'{name} changed since {suite} checks'
    script = 'nested-control.py' if suite == 'native' else 'backend-mcp-check.py'
    for name in [script, fixture]:
        actual = hashlib.sha256((root / 'tests' / name).read_bytes()).hexdigest()
        assert result['test_sha256'][name] == actual, f'{name} changed since {suite} checks'
    assert (directory / 'agent-cursor-screen.png').is_file(), f'{suite} cursor evidence missing'
print('Both native checks passed for the exact packaged binaries and test sources.')
