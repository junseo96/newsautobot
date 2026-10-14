"""Synthetic fixtures only: no operational state or credentials are read."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import state


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "original"
        (self.root / "work/v11").mkdir(parents=True)
        (self.root / "work/v11/supervisor.lock").write_bytes(b"0")
        (self.root / "work/evidence/empty").mkdir(parents=True)
        self.private_bytes = b"private mail fixture\x00\xff\r\n"
        (self.root / "work/evidence/message.eml").write_bytes(self.private_bytes)
        self.archive = self.base / "archive"
        self.target = self.base / "restored"

    def export(self):
        return state.export_state(self.root, self.archive, stopped=True)

    def mutate_manifest(self, mutate):
        path = self.archive / "manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_round_trip_preserves_bytes_empty_directories_and_source_metadata(self):
        self.export()
        manifest = state.verify_state(self.archive)
        self.assertEqual(manifest["source_root"], str(self.root))
        state.restore_state(self.archive, self.target)
        self.assertEqual((self.target / "work/evidence/message.eml").read_bytes(), self.private_bytes)
        self.assertTrue((self.target / "work/evidence/empty").is_dir())
        metadata = json.loads((self.target / state.METADATA_NAME).read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_root"], str(self.root))
        self.assertEqual((self.root / "work/evidence/message.eml").read_bytes(), self.private_bytes)
        if os.name != "nt":
            self.assertEqual(self.archive.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.target / "work/evidence/message.eml").stat().st_mode & 0o777, 0o600)

    def test_requires_explicit_stopped_assertion(self):
        with self.assertRaisesRegex(state.MigrationError, "--stopped"):
            state.export_state(self.root, self.archive)
        self.assertFalse(self.archive.exists())

    def test_supervisor_lock_prevents_export(self):
        with state._supervisor_lock(self.root):
            with self.assertRaisesRegex(state.MigrationError, "Supervisor is running"):
                self.export()
        self.assertFalse(self.archive.exists())

    def test_missing_lock_fails_without_creating_source_files(self):
        lock = self.root / "work/v11/supervisor.lock"
        lock.unlink()
        with self.assertRaisesRegex(state.MigrationError, "lock is missing"):
            self.export()
        self.assertFalse(lock.exists())

    def test_excludes_credentials_and_locks(self):
        (self.root / "work/grid-bridge").mkdir()
        (self.root / "work/grid-bridge/connection.json").write_bytes(b"synthetic secret fixture")
        (self.root / "work/evidence/transient.lock").write_bytes(b"temporary lock")
        self.export()
        state.verify_state(self.archive)
        self.assertFalse((self.archive / "work/grid-bridge/connection.json").exists())
        self.assertFalse((self.archive / "work/v11/supervisor.lock").exists())
        self.assertFalse((self.archive / "work/evidence/transient.lock").exists())
        self.assertTrue((self.root / "work/grid-bridge/connection.json").exists())

    def test_sqlite_backup_includes_committed_wal_and_preserves_original(self):
        path = self.root / "work/v11/queue.db"
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE receipts (id INTEGER PRIMARY KEY, status TEXT)")
        connection.execute("INSERT INTO receipts VALUES (1, 'delivered')")
        connection.commit()
        wal = Path(str(path) + "-wal")
        self.assertGreater(wal.stat().st_size, 0)
        before = {file.name: file.read_bytes() for file in (path, wal)}
        self.export()
        self.assertEqual({file.name: file.read_bytes() for file in (path, wal)}, before)
        self.assertFalse((self.archive / "work/v11/queue.db-wal").exists())
        self.assertFalse((self.archive / "work/v11/queue.db-shm").exists())
        state.restore_state(self.archive, self.target)
        with contextlib.closing(sqlite3.connect(self.target / "work/v11/queue.db")) as restored:
            self.assertEqual(restored.execute("SELECT * FROM receipts").fetchall(), [(1, "delivered")])

    def test_corrupt_archive_refuses_restore_before_destination_creation(self):
        self.export()
        (self.archive / "work/evidence/message.eml").write_bytes(b"altered")
        with self.assertRaisesRegex(state.MigrationError, "checksum mismatch"):
            state.restore_state(self.archive, self.target)
        self.assertFalse(self.target.exists())

    def test_sqlite_integrity_verified_even_when_checksum_matches(self):
        with contextlib.closing(sqlite3.connect(self.root / "work/v11/queue.db")) as connection:
            connection.execute("CREATE TABLE receipts (id INTEGER)")
            connection.commit()
        self.export()
        database = self.archive / "work/v11/queue.db"
        database.write_bytes(b"This is not SQLite")

        def update(value):
            entry = next(item for item in value["files"] if item["path"].endswith("queue.db"))
            entry["size"] = database.stat().st_size
            entry["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()

        self.mutate_manifest(update)
        with self.assertRaisesRegex(state.MigrationError, "integrity check failed"):
            state.verify_state(self.archive)

    def test_extra_archive_file_is_rejected(self):
        self.export()
        (self.archive / "work/untracked").write_bytes(b"unexpected")
        with self.assertRaisesRegex(state.MigrationError, "files differ"):
            state.verify_state(self.archive)

    def test_manifest_path_traversal_and_windows_paths_are_rejected(self):
        self.export()
        manifest = (self.archive / "manifest.json").read_bytes()
        for unsafe in ("work/../../outside", "work/../outside", "/work/absolute", "work\\..\\outside", "work/C:/outside", "work//file"):
            with self.subTest(path=unsafe):
                (self.archive / "manifest.json").write_bytes(manifest)
                self.mutate_manifest(lambda value: value["files"][0].update(path=unsafe))
                with self.assertRaisesRegex(state.MigrationError, "Unsafe path"):
                    state.restore_state(self.archive, self.target)
                self.assertFalse(self.target.exists())

    def test_symlinks_in_source_archive_and_destination_are_rejected(self):
        outside = self.base / "outside"
        outside.write_bytes(b"private outside fixture")
        link = self.root / "work/evidence/link"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks is unavailable")
        with self.assertRaisesRegex(state.MigrationError, "Symlinks"):
            self.export()
        link.unlink()
        self.export()
        (self.archive / "work/link").symlink_to(outside)
        with self.assertRaisesRegex(state.MigrationError, "Symlinks"):
            state.verify_state(self.archive)
        (self.archive / "work/link").unlink()
        self.target.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(state.MigrationError, "Symlinks"):
            state.restore_state(self.archive, self.target)

    def test_existing_destination_is_never_overwritten(self):
        self.archive.mkdir()
        sentinel = self.archive / "existing"
        sentinel.write_bytes(b"do not replace")
        with self.assertRaisesRegex(state.MigrationError, "already exists"):
            self.export()
        self.assertEqual(sentinel.read_bytes(), b"do not replace")
        sentinel.unlink()
        self.archive.rmdir()
        self.export()
        self.target.mkdir()
        (self.target / "existing").write_bytes(b"do not replace")
        with self.assertRaisesRegex(state.MigrationError, "new or empty"):
            state.restore_state(self.archive, self.target)
        self.assertEqual((self.target / "existing").read_bytes(), b"do not replace")

    def test_restore_accepts_empty_destination(self):
        self.export()
        self.target.mkdir()
        state.restore_state(self.archive, self.target)
        self.assertTrue((self.target / "work/evidence/message.eml").is_file())

    def test_export_cannot_target_source_tree(self):
        with self.assertRaisesRegex(state.MigrationError, "outside the source"):
            state.export_state(self.root, self.root / "backup", stopped=True)
        self.assertFalse((self.root / "backup").exists())

    def test_restore_cannot_target_archive_tree(self):
        self.export()
        with self.assertRaisesRegex(state.MigrationError, "outside the archive"):
            state.restore_state(self.archive, self.archive / "restored")

    def test_cli_success_prints_only_local_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(state.main(["export", "--root", str(self.root), "--destination", str(self.archive), "--stopped"]), 0)
            self.assertEqual(state.main(["verify", "--archive", str(self.archive)]), 0)
        self.assertEqual(output.getvalue(), f"{self.archive}\n{self.archive}\n")


if __name__ == "__main__":
    unittest.main()
