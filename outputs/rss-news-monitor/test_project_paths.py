import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_paths import evidence_path, LEGACY_ROOT


class MigrationPaths(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict('os.environ', {'NEWS_LEGACY_ROOT': '', 'NEWS_DATA_DIR': ''})
        self.environment.start()
        self.addCleanup(self.environment.stop)

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

    def test_configured_root_maps_case_insensitively_and_retains_default(self):
        root = Path(tempfile.gettempdir()) / 'news-test'
        with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': r'D:\News Bot'}):
            self.assertEqual(evidence_path(r'd:\news bot/work/receipt.json', root=root),
                             (root / 'work/receipt.json').resolve())
            self.assertEqual(evidence_path(str(LEGACY_ROOT / 'work/receipt.json'), root=root),
                             (root / 'work/receipt.json').resolve())
            similar = r'D:\News Bot-other\work\receipt.json'
            self.assertEqual(evidence_path(similar, root=root), Path(similar).resolve())

    def test_configured_root_does_not_modify_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'NEWS_LEGACY_ROOT': r'D:\News Bot'}):
            root = Path(directory)
            original = b'{"decision_file":"D:\\\\News Bot\\\\work\\\\decision.json"}\r\n'
            (root / 'receipt.json').write_bytes(original)
            self.assertEqual(evidence_path(r'D:\News Bot\receipt.json', root=root).read_bytes(), original)

    def test_explicit_posix_root_maps_case_sensitively_and_retains_default(self):
        root = Path(tempfile.gettempdir()) / 'news-test'
        with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': '/old/News Bot'}):
            self.assertEqual(evidence_path('/old/News Bot/work/receipt.json', root=root),
                             (root / 'work/receipt.json').resolve())
            self.assertEqual(evidence_path(str(LEGACY_ROOT / 'work/receipt.json'), root=root),
                             (root / 'work/receipt.json').resolve())
            for unmatched in ('/old/news bot/work/receipt.json', '/old/News Bot-other/work/receipt.json'):
                self.assertEqual(evidence_path(unmatched, root=root), Path(unmatched).resolve())

    def test_explicit_posix_root_rejects_escape_and_preserves_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'NEWS_LEGACY_ROOT': '/old/News Bot'}):
            root = Path(directory)
            original = b'{"decision_file":"/old/News Bot/work/decision.json"}\n'
            (root / 'receipt.json').write_bytes(original)
            self.assertEqual(evidence_path('/old/News Bot/receipt.json', root=root).read_bytes(), original)
            for suffix in ('/../outside.json', '/work/../../outside.json'):
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    evidence_path('/old/News Bot' + suffix, root=root)

    def test_configured_root_rejects_path_escape_and_alternate_streams(self):
        with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': r'D:\News Bot'}):
            for suffix in (r'\..\outside.json', r'\work\..\..\outside.json', r'\work\file.json:stream'):
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    evidence_path(r'D:\News Bot' + suffix)

    def test_configured_root_must_be_absolute_without_traversal(self):
        for configured in ('relative', r'D:relative', r'D:\News Bot\..\elsewhere', '/old/News Bot/../elsewhere'):
            with self.subTest(configured=configured), patch.dict('os.environ', {'NEWS_LEGACY_ROOT': configured}):
                with self.assertRaisesRegex(ValueError, 'NEWS_LEGACY_ROOT'):
                    evidence_path('work/receipt.json')

    def test_symlink_cannot_escape_mapped_root(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'NEWS_LEGACY_ROOT': r'D:\News Bot'}):
            root = Path(directory) / 'project'
            root.mkdir()
            try:
                (root / 'outside').symlink_to(Path(directory), target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            with self.assertRaises(ValueError):
                evidence_path(r'D:\News Bot\outside\receipt.json', root=root)

    def test_explicit_persistent_work_anchor_allows_windows_and_posix_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'disk/state'
            root.mkdir()
            (data / 'work/runs').mkdir(parents=True)
            try:
                (root / 'work').symlink_to(data / 'work', target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            receipt = data / 'work/runs/receipt.json'
            receipt.write_bytes(b'{"original":"unchanged"}\r\n')
            for legacy, value in ((r'D:\News Bot', r'D:\News Bot\work\runs\receipt.json'),
                                  ('/old/News Bot', '/old/News Bot/work/runs/receipt.json')):
                with self.subTest(legacy=legacy), patch.dict('os.environ', {'NEWS_LEGACY_ROOT': legacy, 'NEWS_DATA_DIR': str(data)}):
                    self.assertEqual(evidence_path(value, root=root), receipt.resolve())
                    self.assertEqual(evidence_path(value, root=root).read_bytes(), b'{"original":"unchanged"}\r\n')
                with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': legacy}):
                    with self.assertRaises(ValueError):
                        evidence_path(value, root=root)

    def test_persistent_anchor_does_not_allow_nested_escape_even_back_into_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'disk/state'
            root.mkdir()
            (data / 'work').mkdir(parents=True)
            try:
                (root / 'work').symlink_to(data / 'work', target_is_directory=True)
                (data / 'work/escape').symlink_to(Path(directory), target_is_directory=True)
                (data / 'work/code').symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            for legacy in (r'D:\News Bot', '/old/News Bot'):
                with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': legacy, 'NEWS_DATA_DIR': str(data)}):
                    for suffix in ('/work/escape/receipt.json', '/work/code/receipt.json'):
                        with self.subTest(legacy=legacy, suffix=suffix), self.assertRaises(ValueError):
                            evidence_path(legacy + suffix, root=root)

    def test_persistent_config_cannot_authorize_an_arbitrary_other_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'disk/state'
            unrelated = Path(directory) / 'unrelated'
            root.mkdir()
            (data / 'work').mkdir(parents=True)
            unrelated.mkdir()
            try:
                (root / 'work').symlink_to(unrelated, target_is_directory=True)
                (root / 'outputs').symlink_to(data / 'work', target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': '/old/project', 'NEWS_DATA_DIR': str(data)}):
                for value in ('/old/project/work/receipt.json', '/old/project/outputs/receipt.json'):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        evidence_path(value, root=root)

    def test_relative_persistent_directory_does_not_authorize_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'disk/state'
            root.mkdir()
            (data / 'work').mkdir(parents=True)
            try:
                (root / 'work').symlink_to(data / 'work', target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            with patch.dict('os.environ', {'NEWS_LEGACY_ROOT': '/old/project', 'NEWS_DATA_DIR': '../disk/state'}):
                with self.assertRaises(ValueError):
                    evidence_path('/old/project/work/receipt.json', root=root)

if __name__ == '__main__':
    unittest.main()
