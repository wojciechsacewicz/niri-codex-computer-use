#!/usr/bin/env python3
"""Export a standalone makepkg recipe for a committed integration revision."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def export(root, revision, output):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use a full 40-character commit hash.')
    if git(root, 'rev-parse', revision + '^{commit}') != revision:
        raise ValueError('Revision must identify an exact commit.')
    template = git(root, 'show', revision + ':packaging/arch/source/PKGBUILD.in')
    metadata = json.loads(git(root, 'show', revision + ':packaging/arch/release.json'))
    version, release = metadata['pkgver'], metadata['pkgrel']
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version) or type(release) is not int or release < 1:
        raise ValueError('Invalid package release metadata.')
    for name, value in [('PROJECT_REVISION', revision), ('PKGVER', version), ('PKGREL', str(release))]:
        template = template.replace('@' + name + '@', value)
    if re.search(r'@[A-Z_]+@', template):
        raise ValueError('Unresolved recipe variable.')
    output.mkdir(parents=True, exist_ok=True)
    recipe = output / 'PKGBUILD'
    recipe.write_text(template + '\n')
    metadata_result = subprocess.check_output(['makepkg', '--printsrcinfo'], cwd=output, text=True)
    (output / '.SRCINFO').write_text(metadata_result)
    return recipe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', help='Exact committed release revision; defaults to clean HEAD')
    parser.add_argument('--output', type=Path, help='Destination directory; defaults to dist/arch-source')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.revision is None and git(root, 'status', '--porcelain'):
            raise ValueError('Commit the integration first, or explicitly select a committed --revision.')
        revision = args.revision or git(root, 'rev-parse', 'HEAD')
        result = export(root, revision, args.output or root / 'dist/arch-source')
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Cannot export the source recipe: {exc}\n')
    print(f'Exported {result.name} for {revision}. Publish that commit before distributing the recipe.')


if __name__ == '__main__':
    main()
