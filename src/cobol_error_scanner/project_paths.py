"""Path helpers shared by ingestion and scan tooling."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.paths import DEFAULT_RULES_PATH, detect_repo_root


def repo_root() -> Path:
    """Repository root (contains ``pyproject.toml`` and ``config/`` when installed editable)."""
    return detect_repo_root()


def default_rules_path() -> Path:
    return DEFAULT_RULES_PATH


def resolve_rules_path(rules: Path | str | None = None) -> Path:
    """
    Resolve COBOL error-rules JSON.

    Accepts an absolute/relative file path, or a path relative to the repo root.
    """
    if rules is None:
        return default_rules_path()
    p = Path(rules)
    if p.is_file():
        return p.resolve()
    candidate = repo_root() / p
    if candidate.is_file():
        return candidate.resolve()
    return p.resolve()
