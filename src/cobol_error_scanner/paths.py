"""Repository path detection and default locations."""

from __future__ import annotations

from pathlib import Path


def detect_repo_root() -> Path:
    """Directory containing config/ and pyproject.toml (editable install layout)."""
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent
    if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
        return candidate
    return Path.cwd()


REPO_ROOT = detect_repo_root()
DEFAULT_SOURCE_ROOT = REPO_ROOT / "samples"
DEFAULT_RULES_PATH = REPO_ROOT / "config" / "error_rules.json"
DEFAULT_OUT_DIR = REPO_ROOT / "out"
DEFAULT_CORORA_MAPPINGS = REPO_ROOT / "error_mapping_files"
DASHBOARD_PORT = 8504
