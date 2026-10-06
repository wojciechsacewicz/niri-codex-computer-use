"""Inspect the dynamic dependencies of our installed, trusted binaries."""
import subprocess


def inspect_libraries(binary, query=None):
    if query is None:
        query = lambda command: subprocess.run(command, capture_output=True, text=True, timeout=10)
    try:
        result = query(['/usr/bin/ldd', str(binary)])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'missing': [], 'error': str(exc)}
    missing = [line.split('=>', 1)[0].strip() for line in result.stdout.splitlines()
               if '=> not found' in line]
    error = None if result.returncode == 0 else (result.stderr.strip() or 'Cannot inspect binary library dependencies.')
    return {'missing': missing, 'error': error}
