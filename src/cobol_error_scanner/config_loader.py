"""Load application configuration for document ingestion and resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cobol_error_scanner.paths import detect_repo_root


class IngestSettings(BaseModel):
    max_file_mb: int = 25
    max_documents: int = 500


class KnowledgeSettings(BaseModel):
    dir: str = "knowledge/"
    incremental: bool = True
    merge_on_write: bool = True
    index_by_code_field: bool = True
    skip_full_doc_scan_when_accepted: bool = True
    skip_doc_scan_when_accepted: bool = True
    max_indexed_excerpt_chars: int = 2000
    max_aggregated_steps: int = 20


class ResolverSettings(BaseModel):
    provider: str = "heuristic"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "http://localhost:11434"
    top_k: int = 3


class AppConfig(BaseModel):
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    resolver: ResolverSettings = Field(default_factory=ResolverSettings)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _config_search_paths() -> list[Path]:
    root = detect_repo_root()
    return [
        root / "config" / "app_config.json",
        root / "config" / "app_config.yaml",
        root / "app_config.json",
    ]


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            f"PyYAML is required to load {path}. Install with: pip install pyyaml"
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_file(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml_file(path)
    return _load_json_file(path)


def resolve_config_path(explicit: Path | str | None = None) -> Path | None:
    """Return the first existing config file path, or None for defaults-only."""
    if explicit is not None:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"Config file not found: {p}")
    env = os.environ.get("COBOL_APP_CONFIG", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"COBOL_APP_CONFIG not found: {p}")
    for candidate in _config_search_paths():
        if candidate.is_file():
            return candidate
    return None


def load_app_config(config_path: Path | str | None = None) -> AppConfig:
    """Load ``AppConfig`` from file (if present) merged over built-in defaults."""
    defaults = AppConfig().model_dump()
    path = resolve_config_path(config_path)
    if path is None:
        return AppConfig()
    data = _load_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    merged = _deep_merge(defaults, data)
    return AppConfig.model_validate(merged)
