import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('export_arch', ROOT / 'scripts/export-arch-recipe.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@unittest.skipUnless(shutil.which('makepkg'), 'makepkg is required for source recipe validation')
class ArchRecipeTests(unittest.TestCase):
    def test_recipe_uses_committed_metadata_and_exact_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / 'repo'
            repo.mkdir()
            packaging = repo / 'packaging/arch/source'
            packaging.mkdir(parents=True)
            (packaging / 'PKGBUILD.in').write_text((ROOT / 'packaging/arch/source/PKGBUILD.in').read_text())
            metadata = packaging.parent / 'release.json'
            metadata.write_text('{"pkgver":"1.2.3","pkgrel":2}')
            for args in [('init', '-q'), ('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')]:
                subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
            revision = exporter.git(repo, 'rev-parse', 'HEAD')
            metadata.write_text('{"pkgver":"9.9.9","pkgrel":1}')
            recipe = exporter.export(repo, revision, base / 'recipe')
            text = recipe.read_text()
            self.assertIn('pkgver=1.2.3', text)
            self.assertIn('pkgrel=2', text)
            self.assertIn("_project_revision='" + revision + "'", text)
            self.assertNotIn('@PROJECT_REVISION@', text)
            srcinfo = (recipe.parent / '.SRCINFO').read_text()
            self.assertIn('checkdepends = bubblewrap', srcinfo)
            self.assertIn('makedepends = rust', srcinfo)
            self.assertIn('#commit=' + revision, srcinfo)
            subprocess.run(['bash', '-n', str(recipe)], check=True)

    def test_shorthand_revision_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'recipe'
            with self.assertRaises(ValueError):
                exporter.export(ROOT, 'HEAD', destination)
            self.assertFalse(destination.exists())

    def test_package_version_matches_local_recipe(self):
        metadata = json.loads((ROOT / 'packaging/arch/release.json').read_text())
        result = subprocess.check_output(['bash', '-c', 'source "$1"; printf "%s-%s" "$pkgver" "$pkgrel"',
                                          'test', str(ROOT / 'packaging/arch/PKGBUILD')], text=True)
        self.assertEqual(result, f"{metadata['pkgver']}-{metadata['pkgrel']}")


if __name__ == '__main__':
    unittest.main()
