"""Tests for the external scan-and-lookup API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cobol_error_scanner.api.server import create_app  # noqa: E402


@pytest.fixture
def isolated_app_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
                "resolver": {
                    "provider": "heuristic",
                    "model": "gpt-4o-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "top_k": 3,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COBOL_APP_CONFIG", str(cfg_path))
    return kdir


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _lookup_headers(api_key: str = "test-api-key", application_key: str = "test-app-key") -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "X-Application-Key": application_key,
    }


def _lookup_payload(tmp_path: Path, **overrides: str) -> dict[str, str]:
    payload = {
        "error_code": "SE",
        "error_field": "",
        "source_root": str(ROOT / "samples"),
        "rules_path": str(ROOT / "config" / "error_rules.json"),
        "out_dir": str(tmp_path / "out"),
        "corora_mappings": str(ROOT / "error_mapping_files"),
        "summarizer": "heuristic",
    }
    payload.update(overrides)
    return payload


def test_lookup_requires_configured_keys(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("COBOL_EXTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("COBOL_EXTERNAL_APPLICATION_KEY", raising=False)

    response = client.post("/api/v1/lookup", json=_lookup_payload(tmp_path), headers=_lookup_headers())

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_lookup_rejects_wrong_keys(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COBOL_EXTERNAL_API_KEY", "good-api")
    monkeypatch.setenv("COBOL_EXTERNAL_APPLICATION_KEY", "good-app")

    response = client.post("/api/v1/lookup", json=_lookup_payload(tmp_path), headers=_lookup_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API credentials"


def test_lookup_validates_exactly_one_filter(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COBOL_EXTERNAL_API_KEY", "good-api")
    monkeypatch.setenv("COBOL_EXTERNAL_APPLICATION_KEY", "good-app")
    headers = _lookup_headers("good-api", "good-app")

    both = client.post(
        "/api/v1/lookup",
        json=_lookup_payload(tmp_path, error_field="ERR-NO-SEC-TERM-OVRD"),
        headers=headers,
    )
    neither = client.post(
        "/api/v1/lookup",
        json=_lookup_payload(tmp_path, error_code="", error_field=""),
        headers=headers,
    )

    assert both.status_code == 400
    assert neither.status_code == 400
    assert "exactly one" in both.json()["detail"]
    assert "exactly one" in neither.json()["detail"]


def test_lookup_returns_all_findings_for_error_code(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COBOL_EXTERNAL_API_KEY", "good-api")
    monkeypatch.setenv("COBOL_EXTERNAL_APPLICATION_KEY", "good-app")

    response = client.post(
        "/api/v1/lookup",
        json=_lookup_payload(tmp_path),
        headers=_lookup_headers("good-api", "good-app"),
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["query"]["error_code"] == "SE"
    assert data["query"]["error_field"] == ""
    assert data["finding_count"] >= 1
    assert len(data["findings"]) == data["finding_count"]
    first = data["findings"][0]
    assert set(first) == {
        "error_code",
        "error_field",
        "program",
        "line",
        "paragraph",
        "condition",
        "summary",
        "historical_resolution",
    }


def test_lookup_populates_historical_resolution_from_ingested_docs(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COBOL_EXTERNAL_API_KEY", "good-api")
    monkeypatch.setenv("COBOL_EXTERNAL_APPLICATION_KEY", "good-app")

    docs_path = isolated_app_config / "documents.jsonl"
    docs_path.write_text(
        json.dumps(
            {
                "document_id": "se-runbook",
                "title": "SE runbook",
                "body_preview": "Error code SE requires security override check.",
                "body_text": "Error code SE requires security override check. Verify operator SEC-TERM-05 access.",
                "links": [],
                "metadata": {"mentioned_error_codes": ["SE"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/lookup",
        json=_lookup_payload(tmp_path),
        headers=_lookup_headers("good-api", "good-app"),
    )

    assert response.status_code == 200, response.text
    historical_values = [row["historical_resolution"] for row in response.json()["findings"]]
    assert any("SEC-TERM-05 access" in text for text in historical_values)


def test_lookup_returns_empty_historical_resolution_without_ingest_artifacts(
    client: TestClient,
    isolated_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COBOL_EXTERNAL_API_KEY", "good-api")
    monkeypatch.setenv("COBOL_EXTERNAL_APPLICATION_KEY", "good-app")

    response = client.post(
        "/api/v1/lookup",
        json=_lookup_payload(tmp_path),
        headers=_lookup_headers("good-api", "good-app"),
    )

    assert response.status_code == 200, response.text
    assert all(row["historical_resolution"] == "" for row in response.json()["findings"])
