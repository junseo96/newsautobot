"""Encrypt complete stopped operational state for GitHub Actions artifacts.

Set NEWS_STATE_AGE_KEY securely to one native age X25519 private identity. The
key is passed to distro age tools through a temporary 0600 file, never argv.
Never commit plaintext archives, operational state, or the private identity.

    python deploy/cloud/artifact_state.py encrypt --root DATA --destination state.tar.age --stopped
    python deploy/cloud/artifact_state.py decrypt --archive state.tar.age --destination EMPTY_DATA

Both commands refuse overwrites. Encryption preserves the original source root
from an existing restoration marker so Windows evidence paths still resolve in
future runs. Decryption authenticates ciphertext before inspecting the tar and
then delegates checksum/database verification and restoration to state.py.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import state


class ArtifactError(RuntimeError):
    """Fixed diagnostic text, never an upstream process error or secret."""


def _run(command):
    environment = {name: value for name, value in os.environ.items() if not name.startswith("NEWS_")}
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=environment, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise ArtifactError("State encryption tool could not complete") from None
    if result.returncode:
        raise ArtifactError("State encryption or authentication failed")
    return result.stdout


@contextmanager
def _identity_file(directory):
    value = os.environ.get("NEWS_STATE_AGE_KEY", "")
    lines = [line.strip() for line in value.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) != 1 or not re.fullmatch(r"AGE-SECRET-KEY-1[0-9A-Z]+", lines[0]):
        raise ArtifactError("NEWS_STATE_AGE_KEY must contain one native age private identity")
    path = directory / "identity.txt"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(lines[0] + "\n")
        yield path
    finally:
        path.unlink(missing_ok=True)


def _preserve_source_root(source, exported):
    marker = state._plain_path(source / state.METADATA_NAME)
    if not marker.exists():
        return
    if not marker.is_file() or marker.stat().st_size > 16384:
        raise ArtifactError("Invalid state restoration metadata")
    try:
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        original_root = metadata["source_root"]
        manifest_path = exported / state.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_root"] = original_root
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state.verify_state(exported)
    except (OSError, ValueError, KeyError, TypeError):
        raise ArtifactError("Invalid state restoration metadata") from None


def _pack(exported, destination):
    directories, files = state._inventory(exported)
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as archive:
        for name in directories + files:
            path = exported / name
            entry = archive.gettarinfo(str(path), arcname=name)
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            entry.mode = 0o700 if entry.isdir() else 0o600
            if entry.isdir():
                archive.addfile(entry)
            elif entry.isreg():
                with path.open("rb") as contents:
                    archive.addfile(entry, contents)
            else:
                raise ArtifactError("Unsupported state archive entry")
    destination.chmod(0o600)


def _member_name(entry):
    name = entry.name.rstrip("/") if entry.isdir() else entry.name
    if (not name or "\\" in name or ":" in name or "\x00" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ArtifactError("Unsafe state archive path")
    if name == state.MANIFEST_NAME:
        if not entry.isreg():
            raise ArtifactError("Invalid state archive manifest")
    elif name.split("/")[0] != "work":
        raise ArtifactError("Unexpected state archive path")
    if entry.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE} or entry.issparse():
        raise ArtifactError("State archive contains unsupported entry types")
    if entry.size < 0 or (entry.isdir() and entry.size):
        raise ArtifactError("Invalid state archive entry size")
    return name


def _unpack(source, destination):
    """Never extractall: validate all names/types before creating any files."""
    try:
        with tarfile.open(source, "r:") as archive:
            entries = [(entry, _member_name(entry)) for entry in archive.getmembers()]
            names = [name for _, name in entries]
            if len(names) != len(set(names)) or sum(entry.size for entry, _ in entries) > source.stat().st_size:
                raise ArtifactError("Invalid state archive inventory")
            directories = sorted((name for entry, name in entries if entry.isdir()), key=lambda name: (name.count("/"), name))
            if "work" not in directories or state.MANIFEST_NAME not in names:
                raise ArtifactError("Incomplete state archive")
            destination.mkdir(mode=0o700)
            for name in directories:
                (destination / name).mkdir(mode=0o700)
            for entry, name in entries:
                if entry.isdir():
                    continue
                contents = archive.extractfile(entry)
                if contents is None:
                    raise ArtifactError("Invalid state archive file")
                descriptor = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with contents, os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(contents, output, 1024 * 1024)
    except (tarfile.TarError, OSError, ValueError):
        raise ArtifactError("State archive could not be validated or extracted") from None


def _publish_new(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL also refuses a target that appears after the initial existence check.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as original, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(original, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def encrypt_state(root, destination, *, stopped=False):
    root, destination = state._plain_path(root), state._plain_path(destination)
    if not stopped:
        raise ArtifactError("Stop the supervisor and scheduled tasks, then supply --stopped")
    if destination.exists():
        raise ArtifactError("Encrypted state destination already exists")
    if destination == root or root in destination.parents:
        raise ArtifactError("Encrypted state destination must be outside the source")
    with tempfile.TemporaryDirectory(prefix="news-state-artifact-") as temporary:
        scratch = Path(temporary)
        with _identity_file(scratch) as identity:
            recipient = _run(["age-keygen", "-y", str(identity)]).decode("ascii").strip()
            if not re.fullmatch(r"age1[0-9a-z]+", recipient):
                raise ArtifactError("Invalid native age recipient")
            exported = state.export_state(root, scratch / "snapshot", stopped=True)
            _preserve_source_root(root, exported)
            state.verify_state(exported)
            plaintext, ciphertext = scratch / "state.tar", scratch / "state.tar.age"
            _pack(exported, plaintext)
            _run(["age", "--encrypt", "--recipient", recipient, "--output", str(ciphertext), str(plaintext)])
            if not ciphertext.is_file() or not ciphertext.stat().st_size:
                raise ArtifactError("State encryption produced no archive")
            _publish_new(ciphertext, destination)
    return destination


def decrypt_state(archive, destination):
    archive, destination = state._plain_path(archive), state._plain_path(destination)
    if not archive.is_file():
        raise ArtifactError("Encrypted state archive is missing")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ArtifactError("State restore destination must be new or empty")
    with tempfile.TemporaryDirectory(prefix="news-state-artifact-") as temporary:
        scratch = Path(temporary)
        with _identity_file(scratch) as identity:
            plaintext = scratch / "state.tar"
            _run(["age", "--decrypt", "--identity", str(identity), "--output", str(plaintext), str(archive)])
        exported = scratch / "snapshot"
        _unpack(plaintext, exported)
        state.verify_state(exported)
        state.restore_state(exported, destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    encrypt = commands.add_parser("encrypt")
    encrypt.add_argument("--root", type=Path, required=True)
    encrypt.add_argument("--destination", type=Path, required=True)
    encrypt.add_argument("--stopped", action="store_true")
    decrypt = commands.add_parser("decrypt")
    decrypt.add_argument("--archive", type=Path, required=True)
    decrypt.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = (encrypt_state(arguments.root, arguments.destination, stopped=arguments.stopped)
                  if arguments.command == "encrypt" else decrypt_state(arguments.archive, arguments.destination))
        print(result)
        return 0
    except ArtifactError as error:
        print("State artifact failed: " + str(error), file=sys.stderr)
    except (state.MigrationError, OSError, ValueError):
        print("State artifact failed: operational state validation or file access failed", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
