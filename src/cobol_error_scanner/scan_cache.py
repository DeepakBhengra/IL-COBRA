"""Saved COBOL scan results.

A search result is reused when the COBOL sources under the scanned folder
have the same paths, sizes, and modification times. Any added, removed, or
edited ``.cob`` / ``.cbl`` / ``.cpy`` file makes the saved copy stale.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from cobol_error_scanner.scanner import iter_cobol_files

_CACHE_DIRNAME = "saved_scans"


def source_fingerprint(source_root: Path) -> str:
    """Hash COBOL file identity under *source_root*. Content edits change mtime."""
    root = source_root.resolve()
    digest = hashlib.sha256()
    digest.update(str(root).encode("utf-8"))
    if not root.is_dir():
        digest.update(b"missing")
        return digest.hexdigest()
    for path in iter_cobol_files(root):
        stat = path.stat()
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def query_key(error_code: str, error_field: str, summarizer: str) -> str:
    field = error_field.strip().upper()
    code = error_code.strip().upper()
    if field:
        label = f"field:{field}"
    elif code:
        label = f"code:{code}"
    else:
        label = "full"
    return f"{label}|{summarizer.strip().lower() or 'heuristic'}"


def _entry_dir(out_dir: Path, key: str) -> Path:
    slug = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return out_dir.resolve() / _CACHE_DIRNAME / slug


def restore_saved_scan(
    *,
    source_root: Path,
    out_dir: Path,
    error_code: str,
    error_field: str,
    summarizer: str,
) -> dict[str, object] | None:
    """Copy a saved result into *out_dir* when the COBOL sources are unchanged."""
    key = query_key(error_code, error_field, summarizer)
    folder = _entry_dir(out_dir, key)
    meta_path = folder / "meta.json"
    errors_path = folder / "errors.jsonl"
    manifest_path = folder / "manifest.json"
    if not meta_path.is_file() or not errors_path.is_file() or not manifest_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    if meta.get("query") != key:
        return None
    if meta.get("source_root") != str(source_root.resolve()):
        return None
    if meta.get("fingerprint") != source_fingerprint(source_root):
        return None
    table_name = str(meta.get("table_name") or "")
    table_path = folder / table_name
    if not table_name or not table_path.is_file():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(errors_path, out_dir / "errors.jsonl")
    shutil.copy2(manifest_path, out_dir / "manifest.json")
    shutil.copy2(table_path, out_dir / table_name)
    return {
        "program_count": int(meta.get("program_count") or 0),
        "finding_count": int(meta.get("finding_count") or 0),
        "table_name": table_name,
    }


def save_scan_result(
    *,
    source_root: Path,
    out_dir: Path,
    error_code: str,
    error_field: str,
    summarizer: str,
    program_count: int,
    finding_count: int,
    table_name: str,
) -> None:
    """Store the scan artifacts just written to *out_dir*."""
    key = query_key(error_code, error_field, summarizer)
    errors_path = out_dir / "errors.jsonl"
    manifest_path = out_dir / "manifest.json"
    table_path = out_dir / table_name
    if not errors_path.is_file() or not manifest_path.is_file() or not table_path.is_file():
        return
    folder = _entry_dir(out_dir, key)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(errors_path, folder / "errors.jsonl")
    shutil.copy2(manifest_path, folder / "manifest.json")
    shutil.copy2(table_path, folder / table_name)
    meta = {
        "query": key,
        "source_root": str(source_root.resolve()),
        "fingerprint": source_fingerprint(source_root),
        "program_count": program_count,
        "finding_count": finding_count,
        "table_name": table_name,
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
