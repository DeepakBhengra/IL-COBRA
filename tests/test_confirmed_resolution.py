"""Tests for analyst-confirmed operational resolutions in the knowledge store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cobol_error_scanner.document_access import get_operational_docs_for_finding
from cobol_error_scanner.ingestion.knowledge_store import (
    get_confirmed_resolution,
    knowledge_dir,
    load_code_field_index,
    save_code_field_index,
    set_confirmed_resolution,
)


@pytest.fixture
def temp_knowledge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    cfg_path = tmp_path / "app_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "ingest": {"max_file_mb": 25, "max_documents": 500},
                "knowledge": {
                    "dir": str(kdir),
                    "incremental": True,
                    "merge_on_write": True,
                    "index_by_code_field": True,
                    "skip_full_doc_scan_when_accepted": True,
                    "skip_doc_scan_when_accepted": True,
                    "max_indexed_excerpt_chars": 2000,
                    "max_aggregated_steps": 20,
                },
                "resolver": {"provider": "heuristic", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY", "top_k": 3},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COBOL_APP_CONFIG", str(cfg_path))
    return kdir


def test_set_and_get_confirmed_resolution_round_trip(temp_knowledge: Path) -> None:
    saved = set_confirmed_resolution(
        "EC",
        "order created is throwing 'EC'",
        "Check back order flag",
        "historical",
        kdir=temp_knowledge,
    )
    assert saved["error_code"] == "EC"
    assert saved["source"] == "historical"
    assert saved["comment"] == "Check back order flag"

    loaded = get_confirmed_resolution("EC", kdir=temp_knowledge)
    assert loaded["selected_text"] == "order created is throwing 'EC'"
    assert loaded["comment"] == "Check back order flag"


def test_confirmed_resolution_overwrites_same_error_code(temp_knowledge: Path) -> None:
    set_confirmed_resolution("EC", "first selection", "", "historical", kdir=temp_knowledge)
    set_confirmed_resolution("EC", "ORH-FROM-XML", "Updated root cause", "condition", kdir=temp_knowledge)

    loaded = get_confirmed_resolution("EC", kdir=temp_knowledge)
    assert loaded["selected_text"] == "ORH-FROM-XML"
    assert loaded["source"] == "condition"
    assert loaded["comment"] == "Updated root cause"


def test_set_confirmed_resolution_validates_source(temp_knowledge: Path) -> None:
    with pytest.raises(ValueError, match="source must be"):
        set_confirmed_resolution("EC", "text", "", "invalid", kdir=temp_knowledge)


def test_operational_docs_includes_confirmed_resolution(
    temp_knowledge: Path,
    tmp_path: Path,
) -> None:
    set_confirmed_resolution(
        "EC",
        "order created is throwing 'EC'",
        "Production note",
        "historical",
        kdir=temp_knowledge,
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    finding_row = {
        "program": "ORP676",
        "error_code": "EC",
        "error_field": "CORORA-R-ERROR-SHIP-COMPLETE",
        "line": 5425,
        "paragraph": "120-EDIT-SHIPMENT-HEADER",
    }

    result = get_operational_docs_for_finding(finding_row, out_dir)
    assert result["confirmed_resolution"]["selected_text"] == "order created is throwing 'EC'"
    assert result["confirmed_resolution"]["comment"] == "Production note"


def test_rebuild_preserves_confirmed_resolution(temp_knowledge: Path) -> None:
    set_confirmed_resolution("SE", "stored text", "note", "condition", kdir=temp_knowledge)
    index = load_code_field_index(temp_knowledge)
    index["SE"] = dict(index.get("SE", {}))
    index["SE"]["confirmed_resolution"] = {
        "selected_text": "stored text",
        "comment": "note",
        "source": "condition",
        "error_code": "SE",
    }
    save_code_field_index(index, temp_knowledge)

    from cobol_error_scanner.ingestion.knowledge_store import rebuild_code_field_index

    rebuild_code_field_index(kdir=temp_knowledge)
    assert get_confirmed_resolution("SE", kdir=temp_knowledge)["selected_text"] == "stored text"
