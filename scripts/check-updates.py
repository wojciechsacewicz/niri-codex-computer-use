#!/usr/bin/env python3
"""Report upstream changes without modifying a working installation."""
import json
from pathlib import Path
import urllib.request
root = Path(__file__).resolve().parent.parent
lock = json.loads((root / 'sources.lock.json').read_text())
for name in ['upstream_patches', 'niri', 'codex_desktop_linux']:
    item = lock[name]
    repo = item['repository'].removeprefix('https://github.com/')
    url = 'https://api.github.com/repos/' + repo + '/commits?per_page=1'
    request = urllib.request.Request(url, headers={'User-Agent':'niri-codex-computer-use-update-check','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        latest = json.load(response)[0]
    print(json.dumps(dict(component=name, pinned=item['revision'], latest=latest['sha'],
                         date=latest['commit']['committer']['date'], update_available=latest['sha'] != item['revision'])))
print('Source updates require patch checks and native verification before a new package is installed.')
