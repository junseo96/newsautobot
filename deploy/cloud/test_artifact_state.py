"""Synthetic age adapter tests; optional real-age round trip uses disposable keys."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import artifact_state
import state


TEST_IDENTITY = "AGE-SECRET-KEY-1SYNTHETICUNITTESTONLY"


class FakeAge:
    """Not cryptography: opaque mock handles map to in-memory test tar bytes."""
    def __init__(self):
        self.payloads = {}
        self.identity = None
        self.calls = []

    def register(self, plaintext, identity=TEST_IDENTITY):
        handle = f"synthetic-age-handle-{len(self.payloads)}".encode()
        self.payloads[handle] = (plaintext, identity)
        return handle

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        assert not any(name.startswith("NEWS_") for name in kwargs["env"])
        assert TEST_IDENTITY not in " ".join(command)
        if command[0] == "age-keygen":
            keyfile = Path(command[-1])
            if os.name != "nt":
                assert keyfile.stat().st_mode & 0o777 == 0o600
            self.identity = keyfile.read_text().strip()
            return subprocess.CompletedProcess(command, 0, b"age1syntheticrecipient\n", b"")
        output = Path(command[command.index("--output") + 1])
        source = Path(command[-1])
        if "--encrypt" in command:
            output.write_bytes(self.register(source.read_bytes(), self.identity))
        else:
            keyfile = Path(command[command.index("--identity") + 1])
            entry = self.payloads.get(source.read_bytes())
            if entry is None or entry[1] != keyfile.read_text().strip():
                return subprocess.CompletedProcess(command, 1, b"", b"private failure " + TEST_IDENTITY.encode())
            output.write_bytes(entry[0])
        return subprocess.CompletedProcess(command, 0, b"", b"")


class ArtifactStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        (self.root / "work/v11").mkdir(parents=True)
        (self.root / "work/v11/supervisor.lock").write_bytes(b"0")
        (self.root / "work/receipt.json").write_bytes(b'{"private":"synthetic receipt"}\r\n')
        with contextlib.closing(sqlite3.connect(self.root / "work/v11/queue.db")) as database:
            database.execute("CREATE TABLE receipts (id INTEGER PRIMARY KEY, status TEXT)")
            database.execute("INSERT INTO receipts VALUES (1, 'delivered')")
            database.commit()
        self.archive, self.restored = self.base / "state.tar.age", self.base / "restored"
        self.fake = FakeAge()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"NEWS_STATE_AGE_KEY": TEST_IDENTITY}).start()
        patch.object(artifact_state.subprocess, "run", side_effect=self.fake).start()

    def encrypt(self):
        return artifact_state.encrypt_state(self.root, self.archive, stopped=True)

    def test_round_trip_restores_receipts_database_and_local_source_root(self):
        self.encrypt()
        artifact_state.decrypt_state(self.archive, self.restored)
        self.assertEqual((self.restored / "work/receipt.json").read_bytes(), (self.root / "work/receipt.json").read_bytes())
        with contextlib.closing(sqlite3.connect(self.restored / "work/v11/queue.db")) as database:
            self.assertEqual(database.execute("SELECT * FROM receipts").fetchall(), [(1, "delivered")])
        marker = json.loads((self.restored / state.METADATA_NAME).read_text())
        self.assertEqual(marker["source_root"], str(self.root))
        self.assertFalse((self.restored / "work/v11/supervisor.lock").exists())
        if os.name != "nt":
            self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)

    def test_original_windows_root_survives_repeated_actions_snapshots(self):
        legacy_root = r"C:\Users\owner\newsautobot"
        (self.root / state.METADATA_NAME).write_text(json.dumps({"source_root": legacy_root}))
        self.encrypt()
        artifact_state.decrypt_state(self.archive, self.restored)
        self.assertEqual(json.loads((self.restored / state.METADATA_NAME).read_text())["source_root"], legacy_root)
        # The next finite worker has started/stopped and left its standard lock.
        (self.restored / "work/v11/supervisor.lock").write_bytes(b"0")
        second_archive, second_restore = self.base / "second.tar.age", self.base / "second"
        artifact_state.encrypt_state(self.restored, second_archive, stopped=True)
        artifact_state.decrypt_state(second_archive, second_restore)
        self.assertEqual(json.loads((second_restore / state.METADATA_NAME).read_text())["source_root"], legacy_root)

    def test_private_key_and_credentials_are_not_archived_or_passed_in_argv(self):
        (self.root / "work/grid-bridge").mkdir()
        (self.root / "work/grid-bridge/connection.json").write_text('{"token":"synthetic connection secret"}')
        self.encrypt()
        plaintext, _ = self.fake.payloads[self.archive.read_bytes()]
        self.assertNotIn(TEST_IDENTITY.encode(), plaintext)
        self.assertNotIn(b"synthetic connection secret", plaintext)
        with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:") as archive:
            self.assertNotIn("identity.txt", archive.getnames())
        for command, kwargs in self.fake.calls:
            self.assertNotIn(TEST_IDENTITY, " ".join(command))
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            self.assertNotIn("NEWS_STATE_AGE_KEY", kwargs["env"])
        key_path = Path(self.fake.calls[0][0][-1])
        self.assertFalse(key_path.exists())

    def test_export_refuses_running_source_and_missing_stopped_assertion(self):
        with self.assertRaisesRegex(artifact_state.ArtifactError, "--stopped"):
            artifact_state.encrypt_state(self.root, self.archive)
        with state._supervisor_lock(self.root):
            with self.assertRaisesRegex(state.MigrationError, "Supervisor is running"):
                self.encrypt()
        self.assertFalse(self.archive.exists())

    def test_wrong_identity_and_tampered_ciphertext_do_not_create_destination(self):
        self.encrypt()
        with patch.dict(os.environ, {"NEWS_STATE_AGE_KEY": "AGE-SECRET-KEY-1WRONGTESTKEY"}):
            with self.assertRaisesRegex(artifact_state.ArtifactError, "authentication failed"):
                artifact_state.decrypt_state(self.archive, self.restored)
        self.assertFalse(self.restored.exists())
        self.archive.write_bytes(self.archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(artifact_state.ArtifactError, "authentication failed"):
            artifact_state.decrypt_state(self.archive, self.restored)
        self.assertFalse(self.restored.exists())

    def test_existing_ciphertext_and_restored_files_are_never_overwritten(self):
        self.archive.write_bytes(b"keep existing ciphertext")
        with self.assertRaisesRegex(artifact_state.ArtifactError, "already exists"):
            self.encrypt()
        self.assertEqual(self.archive.read_bytes(), b"keep existing ciphertext")
        self.archive.unlink()
        self.encrypt()
        self.restored.mkdir()
        (self.restored / "sentinel").write_bytes(b"keep existing state")
        with self.assertRaisesRegex(artifact_state.ArtifactError, "new or empty"):
            artifact_state.decrypt_state(self.archive, self.restored)
        self.assertEqual((self.restored / "sentinel").read_bytes(), b"keep existing state")

    def test_tar_traversal_links_and_devices_are_rejected_before_restore(self):
        entries = []
        for name in ("../outside", "/outside", "work/../outside", "work\\outside"):
            entries.append(tarfile.TarInfo(name))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            entry = tarfile.TarInfo("work/unsafe")
            entry.type, entry.linkname = kind, "../../outside"
            entries.append(entry)
        for entry in entries:
            with self.subTest(name=entry.name, kind=entry.type):
                payload = io.BytesIO()
                with tarfile.open(fileobj=payload, mode="w") as archive:
                    archive.addfile(entry)
                self.archive.write_bytes(self.fake.register(payload.getvalue()))
                with self.assertRaises(artifact_state.ArtifactError):
                    artifact_state.decrypt_state(self.archive, self.restored)
                self.assertFalse(self.restored.exists())
                self.assertFalse((self.base / "outside").exists())

    def test_authenticated_but_corrupt_state_fails_checksum_validation(self):
        self.encrypt()
        plaintext, _ = self.fake.payloads[self.archive.read_bytes()]
        self.assertIn(b"synthetic receipt", plaintext)
        modified = plaintext.replace(b"synthetic receipt", b"corrupted receipt")
        self.archive.write_bytes(self.fake.register(modified))
        with self.assertRaisesRegex(state.MigrationError, "checksum mismatch"):
            artifact_state.decrypt_state(self.archive, self.restored)
        self.assertFalse(self.restored.exists())

    def test_invalid_legacy_root_fails_export(self):
        (self.root / state.METADATA_NAME).write_text('{"source_root":"relative-root"}')
        with self.assertRaisesRegex(artifact_state.ArtifactError, "restoration metadata"):
            self.encrypt()
        self.assertFalse(self.archive.exists())

    def test_secret_errors_never_reach_cli_output(self):
        self.archive.write_bytes(b"unknown ciphertext")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = artifact_state.main(["decrypt", "--archive", str(self.archive), "--destination", str(self.restored)])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn(TEST_IDENTITY, stderr.getvalue())
        self.assertNotIn("private failure", stderr.getvalue())

    def test_age_identity_file_comments_are_supported(self):
        with patch.dict(os.environ, {"NEWS_STATE_AGE_KEY": "# created: synthetic\n# public key: age1test\n" + TEST_IDENTITY + "\n"}):
            self.encrypt()
        self.assertTrue(self.archive.is_file())


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "distro age tools are not installed")
class RealAgeIntegrationTests(unittest.TestCase):
    def test_real_age_round_trip_and_tamper_detection_with_disposable_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            key = base / "disposable.identity"
            subprocess.run(["age-keygen", "--output", str(key)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            root, restored, archive = base / "root", base / "restored", base / "state.tar.age"
            (root / "work/v11").mkdir(parents=True)
            (root / "work/v11/supervisor.lock").write_bytes(b"0")
            (root / "work/fixture").write_bytes(b"synthetic private operational data")
            with patch.dict(os.environ, {"NEWS_STATE_AGE_KEY": key.read_text()}):
                artifact_state.encrypt_state(root, archive, stopped=True)
                self.assertNotIn(b"synthetic private operational data", archive.read_bytes())
                artifact_state.decrypt_state(archive, restored)
                self.assertEqual((restored / "work/fixture").read_bytes(), b"synthetic private operational data")
                tampered = bytearray(archive.read_bytes())
                tampered[-1] ^= 1
                archive.write_bytes(tampered)
                with self.assertRaises(artifact_state.ArtifactError):
                    artifact_state.decrypt_state(archive, base / "must-not-exist")
                self.assertFalse((base / "must-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
