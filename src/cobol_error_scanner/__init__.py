"""COBOL Error Logic Scanner — pipeline stages for legacy impact analysis."""

__version__ = "0.1.0"


def _load_dotenv_files() -> None:
    """Load environment variables from a ``.env`` file, if present.

    Looks for ``.env`` in the repository root (the directory containing
    ``pyproject.toml`` / ``config/``) and then the current working directory.
    Real, already-exported environment variables always win (``override=False``),
    so this only fills in values that are not already set. Used for keys such as
    ``COBOL_EXTERNAL_API_KEY`` / ``COBOL_EXTERNAL_APPLICATION_KEY`` and
    ``OPENAI_API_KEY``. No-op if python-dotenv is unavailable.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    from pathlib import Path

    from cobol_error_scanner.paths import detect_repo_root

    seen: set[str] = set()
    for candidate in (detect_repo_root() / ".env", Path.cwd() / ".env"):
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            load_dotenv(candidate, override=False)


_load_dotenv_files()
