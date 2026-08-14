"""Discover operational document files under a root directory."""

from __future__ import annotations

from pathlib import Path

DOCUMENT_SUFFIXES = frozenset(
    {
        ".eml",
        ".pdf",
        ".docx",
        ".md",
        ".txt",
        ".json",
        ".csv",
        ".xlsx",
        ".xls",
        ".html",
        ".htm",
        ".log",
        ".jsonl",
    }
)

DENY_PATTERNS = (
    ".env",
    "credentials",
    "secret",
    "password",
)


def _is_denied(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("."):
        return name in {".env", ".gitignore"}
    for pat in DENY_PATTERNS:
        if pat in name:
            return True
    return False


def iter_document_files(root: Path) -> list[Path]:
    """Return sorted paths to ingestible operational documents."""
    root = root.resolve()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _is_denied(p):
            continue
        if p.suffix.lower() in DOCUMENT_SUFFIXES:
            out.append(p)
    return sorted(out)
