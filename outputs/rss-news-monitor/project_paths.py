"""Resolve explicitly migrated evidence paths without rewriting historic data."""
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = PureWindowsPath(r'C:\Users\ds\Documents\Codex\2026-09-02\gdgd')


def evidence_path(value, base=None, root=None):
    root = Path(root or ROOT).resolve()
    windows = PureWindowsPath(str(value))
    try:
        relative = windows.relative_to(LEGACY_ROOT)
    except ValueError:
        path = Path(value)
        if base is not None and not path.is_absolute():
            path = Path(base) / path
        return path.resolve()
    if any(part in {'.', '..'} or ':' in part for part in relative.parts):
        raise ValueError('Migrated evidence path escapes the allowed project root')
    mapped = root.joinpath(*relative.parts).resolve()
    if not mapped.is_relative_to(root):
        raise ValueError('Migrated evidence path escapes the allowed project root')
    return mapped


def same_evidence_path(left, right):
    if left is None or right is None:
        return left == right
    return evidence_path(left) == evidence_path(right)
