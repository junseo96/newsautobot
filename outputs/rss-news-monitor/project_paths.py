"""Resolve explicitly migrated evidence paths without rewriting historic data."""
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = PureWindowsPath(r'C:\Users\ds\Documents\Codex\2026-09-02\gdgd')


def legacy_roots():
    roots = [LEGACY_ROOT]
    configured = os.environ.get('NEWS_LEGACY_ROOT')
    if configured:
        legacy = PureWindowsPath(configured)
        if not legacy.is_absolute():
            legacy = PurePosixPath(configured)
        if not legacy.is_absolute() or any(part in {'.', '..'} or ':' in part for part in legacy.parts[1:]):
            raise ValueError('NEWS_LEGACY_ROOT must be an absolute project path without traversal')
        if legacy not in roots:
            roots.insert(0, legacy)
    return roots


def evidence_path(value, base=None, root=None):
    root = Path(root or ROOT).resolve()
    for legacy in legacy_roots():
        source = PureWindowsPath(str(value)) if isinstance(legacy, PureWindowsPath) else PurePosixPath(str(value))
        try:
            relative = source.relative_to(legacy)
            break
        except ValueError:
            continue
    else:
        path = Path(value)
        if base is not None and not path.is_absolute():
            path = Path(base) / path
        return path.resolve()
    if any(part in {'.', '..'} or ':' in part for part in relative.parts):
        raise ValueError('Migrated evidence path escapes the allowed project root')
    mapped = root.joinpath(*relative.parts).resolve()
    allowed_root = root
    data = os.environ.get('NEWS_DATA_DIR')
    if relative.parts and relative.parts[0] == 'work' and data and Path(data).is_absolute():
        work_anchor = (Path(data) / 'work').resolve()
        if (root / 'work').resolve() == work_anchor:
            # A cloud checkout may mount only work/ on its configured persistent
            # disk. Nested links must stay inside that explicit work anchor.
            allowed_root = work_anchor
    if not mapped.is_relative_to(allowed_root):
        raise ValueError('Migrated evidence path escapes the allowed project root')
    return mapped


def same_evidence_path(left, right):
    if left is None or right is None:
        return left == right
    return evidence_path(left) == evidence_path(right)
