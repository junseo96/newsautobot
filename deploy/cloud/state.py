"""Export and restore private operational state without starting the news service.

Stop the local supervisor AND its scheduled tasks before export, and keep them
stopped through cloud cutover. ``--stopped`` confirms this prerequisite. The
supervisor lock prevents a concurrent supervisor export; unrelated tools must
also be stopped. Copy this script with the checkout to the original machine.

    python deploy/cloud/state.py export --root PROJECT --destination ARCHIVE --stopped
    python deploy/cloud/state.py verify --archive ARCHIVE
    python deploy/cloud/state.py restore --archive ARCHIVE --destination EMPTY_PROJECT

ARCHIVE is a directory containing private mail, receipts, queues, and evidence.
Transfer it over an authenticated, encrypted channel; never add it to Git.
Credentials are deliberately excluded and must be provisioned separately.
Restore retains source_root in .news-state-migration.json. Use that original
Windows root as NEWS_LEGACY_ROOT for historic evidence-path resolution.
Checksums detect corruption, not an attacker who replaces the entire archive.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time


class MigrationError(ValueError):
    pass


DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
MANIFEST_NAME = "manifest.json"
METADATA_NAME = ".news-state-migration.json"


def _plain_path(path):
    """Reject symlinks and Windows junctions, including ancestor directories."""
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
            raise MigrationError(f"Symlinks/junctions are not supported: {candidate}")
    return path


def _excluded(relative):
    lower = relative.as_posix().casefold()
    if lower == "work/grid-bridge/connection.json" or lower.endswith(".lock"):
        return True
    return any(lower.endswith(suffix + tail)
               for suffix in DATABASE_SUFFIXES for tail in ("-wal", "-shm", "-journal"))


def _inventory(root):
    def unreadable(error):
        raise MigrationError(f"Could not read the complete state directory: {error.filename}") from error

    directories, files = [], []
    for parent, child_dirs, child_files in os.walk(root, followlinks=False, onerror=unreadable):
        for name in sorted(child_dirs + child_files):
            path = _plain_path(Path(parent) / name)
            mode = path.stat().st_mode
            if stat.S_ISDIR(mode):
                directories.append(path.relative_to(root).as_posix())
            elif stat.S_ISREG(mode):
                files.append(path.relative_to(root).as_posix())
            else:
                raise MigrationError(f"Only regular files and directories are supported: {path}")
    return sorted(directories), sorted(files)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path):
    try:
        # Exported databases are standalone snapshots, never live WAL databases.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise MigrationError(f"SQLite integrity check failed: {path}")
    except sqlite3.Error as error:
        raise MigrationError(f"SQLite integrity check failed: {path}") from error


def _backup_database(source, destination):
    deadline = time.monotonic() + 60

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise MigrationError(f"SQLite backup timed out: {source}")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as original:
            with closing(sqlite3.connect(destination)) as backup:
                original.backup(backup, pages=128, progress=progress, sleep=0.05)
                backup.execute("PRAGMA journal_mode=DELETE")
        _integrity(destination)
        destination.chmod(0o600)
    except sqlite3.Error as error:
        raise MigrationError(f"Could not back up SQLite database: {source}") from error


@contextmanager
def _supervisor_lock(root):
    """Use the runtime's OS lock protocol without constructing its Service."""
    path = _plain_path(root / "work/v11/supervisor.lock")
    if not path.is_file():
        raise MigrationError("Source work/v11/supervisor.lock is missing; select the stopped operational project")
    # The supervisor keeps this file after exiting. Never delete or replace it:
    # doing so could create two independently locked inodes on Linux.
    with path.open("r+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise MigrationError("Supervisor is running or its lock is unavailable; stop it before export") from error
        yield


def _new_destination(path):
    path = _plain_path(path)
    if path.exists():
        raise MigrationError(f"Destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    return path


def export_state(root, destination, *, stopped=False):
    if not stopped:
        raise MigrationError("Stop the supervisor and scheduled tasks, then supply --stopped")
    root, destination = _plain_path(root), _plain_path(destination)
    if destination == root or root in destination.parents:
        raise MigrationError("Export destination must be outside the source project")
    if not (root / "work").is_dir():
        raise MigrationError("Source project has no work directory")
    _plain_path(root / "work")
    with _supervisor_lock(root):
        directories, files = _inventory(root / "work")
        destination = _new_destination(destination)
        try:
            archive_dirs = ["work"] + ["work/" + name for name in directories]
            for name in archive_dirs:
                (destination / name).mkdir(mode=0o700)
            entries = []
            for name in files:
                relative = PurePosixPath("work") / name
                if _excluded(relative):
                    continue
                source, target = root / relative, destination / relative
                database = source.suffix.casefold() in DATABASE_SUFFIXES
                if database:
                    _backup_database(source, target)
                else:
                    with source.open("rb") as original, target.open("xb") as copied:
                        shutil.copyfileobj(original, copied, 1024 * 1024)
                    target.chmod(0o600)
                entries.append({"path": relative.as_posix(), "size": target.stat().st_size,
                                "sha256": _sha256(target), "sqlite": database})
            manifest = {"version": 1, "classification": "private-operational-state",
                        "source_root": str(root),
                        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "directories": archive_dirs, "files": entries}
            manifest_path = destination / MANIFEST_NAME
            with manifest_path.open("x", encoding="utf-8") as output:
                json.dump(manifest, output, ensure_ascii=False, indent=2)
                output.write("\n")
            manifest_path.chmod(0o600)
            verify_state(destination)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def _relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise MigrationError("Unsafe path in archive manifest")
    parts = value.split("/")
    if parts[0] != "work" or any(part in {"", ".", ".."} for part in parts):
        raise MigrationError("Unsafe path in archive manifest")
    return value


def verify_state(archive):
    archive = _plain_path(archive)
    if not archive.is_dir():
        raise MigrationError("Archive must be an exported state directory")
    directories, files = _inventory(archive)
    try:
        manifest = json.loads((archive / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MigrationError("Archive manifest is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("classification") != "private-operational-state":
        raise MigrationError("Unsupported archive manifest")
    source_root = manifest.get("source_root")
    if (not isinstance(source_root, str) or not source_root or any(c in source_root for c in "\r\n\x00")
            or not (PurePosixPath(source_root).is_absolute() or PureWindowsPath(source_root).is_absolute())):
        raise MigrationError("Invalid source root metadata")
    if not isinstance(manifest.get("directories"), list) or not isinstance(manifest.get("files"), list):
        raise MigrationError("Invalid archive inventory")
    expected_dirs = [_relative_name(name) for name in manifest["directories"]]
    if len(set(expected_dirs)) != len(expected_dirs) or sorted(expected_dirs) != directories or "work" not in expected_dirs:
        raise MigrationError("Archive directories differ from manifest")
    expected_files = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise MigrationError("Invalid archive file entry")
        name = _relative_name(entry.get("path"))
        if name in expected_files or _excluded(PurePosixPath(name)):
            raise MigrationError("Duplicate or forbidden file in archive")
        expected_files.add(name)
        if (type(entry.get("size")) is not int or entry["size"] < 0
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                or type(entry.get("sqlite")) is not bool
                or entry["sqlite"] != (PurePosixPath(name).suffix.casefold() in DATABASE_SUFFIXES)):
            raise MigrationError("Invalid archive checksum metadata")
    if expected_files | {MANIFEST_NAME} != set(files):
        raise MigrationError("Archive files differ from manifest")
    for entry in manifest["files"]:
        path = archive / entry["path"]
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise MigrationError(f"Archive checksum mismatch: {entry['path']}")
        if entry["sqlite"]:
            _integrity(path)
    return manifest


def restore_state(archive, destination):
    archive, destination = _plain_path(archive), _plain_path(destination)
    if destination == archive or archive in destination.parents:
        raise MigrationError("Restore destination must be outside the archive")
    manifest = verify_state(archive)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise MigrationError("Restore destination must be new or empty; existing state is never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".news-state-", dir=destination.parent))
    try:
        for name in manifest["directories"]:
            (staging / name).mkdir(mode=0o700)
        for entry in manifest["files"]:
            target = staging / entry["path"]
            with (archive / entry["path"]).open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            target.chmod(0o600)
            if target.stat().st_size != entry["size"] or _sha256(target) != entry["sha256"]:
                raise MigrationError("Archive changed during restore")
        metadata = {"source_root": manifest["source_root"],
                    "archive_manifest_sha256": _sha256(archive / MANIFEST_NAME),
                    "classification": "private-operational-state"}
        metadata_path = staging / METADATA_NAME
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metadata_path.chmod(0o600)
        if destination.exists():
            # rmdir refuses a directory that became nonempty after our check.
            destination.rmdir()
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export a stopped local project to a new private directory")
    export.add_argument("--root", type=Path, required=True)
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--stopped", action="store_true")
    verify = commands.add_parser("verify", help="Verify checksums and SQLite integrity without exposing data")
    verify.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser("restore", help="Restore into a new or empty project directory")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_state(args.root, args.destination, stopped=args.stopped)
        elif args.command == "verify":
            verify_state(args.archive)
            result = _plain_path(args.archive)
        else:
            result = restore_state(args.archive, args.destination)
        print(result)
        return 0
    except (MigrationError, OSError) as error:
        print(f"State migration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
