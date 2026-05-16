"""Discover COBOL source files under a root directory."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SUFFIXES = frozenset({".cbl", ".cob", ".cpy", ".CBL", ".COB", ".CPY"})


def iter_cobol_files(root: Path, *, suffixes: frozenset[str] | None = None) -> list[Path]:
    """Return sorted paths to likely COBOL sources."""
    suf = suffixes or DEFAULT_SUFFIXES
    root = root.resolve()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in suf:
            out.append(p)
    return sorted(out)
