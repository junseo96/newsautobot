import tempfile
import unittest
from pathlib import Path
from project_paths import evidence_path, LEGACY_ROOT


class MigrationPaths(unittest.TestCase):
    def test_legacy_path_maps_without_touching_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'work/runs/example/receipt.json'
            target.parent.mkdir(parents=True)
            original = b'{"message_text":"unchanged\\r\\n"}'
            target.write_bytes(original)
            result = evidence_path(str(LEGACY_ROOT / 'work/runs/example/receipt.json'), root=root)
            self.assertEqual(result, target.resolve())
            self.assertEqual(result.read_bytes(), original)

    def test_case_and_separator_variants(self):
        root = Path(tempfile.gettempdir()) / 'news-test'
        self.assertEqual(evidence_path(str(LEGACY_ROOT).lower() + '/work/a.json', root=root), (root / 'work/a.json').resolve())

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            evidence_path(str(LEGACY_ROOT) + r'\..\outside.json')

    def test_similar_prefix_is_not_mapped(self):
        value = str(LEGACY_ROOT) + r'-other\file.json'
        self.assertEqual(evidence_path(value), Path(value).resolve())

    def test_new_and_relative_paths_unchanged(self):
        root = Path(tempfile.gettempdir())
        self.assertEqual(evidence_path('a.json', base=root), (root / 'a.json').resolve())

if __name__ == '__main__':
    unittest.main()
