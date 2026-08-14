"""Tests for shared LLM client and Ollama integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from cobol_error_scanner.ingestion.models import DocumentLink, DocumentType, OperationalDocument
from cobol_error_scanner.ingestion.resolution import ResolverConfig, _suggest_llm
from cobol_error_scanner.llm_client import chat_completion
from cobol_error_scanner.models import ErrorOccurrence, ProgramSummary, SourceLocation
from cobol_error_scanner.summarizer import SummarizerConfig, summarize_program


def _sample_program() -> ProgramSummary:
    return ProgramSummary(
        program_id="PAYM01",
        source_path=Path("samples/paym01.cbl"),
        occurrences=[
            ErrorOccurrence(
                code="E102",
                location=SourceLocation(path=Path("samples/paym01.cbl"), line=120),
                setting_statement="MOVE 'E102' TO WS-ERROR-CODE",
                paragraph="VALIDATE-CUST",
                condition="WS-CUST-ID = SPACES",
            )
        ],
    )


def _sample_document() -> OperationalDocument:
    return OperationalDocument(
        id="doc-1",
        title="Incident report",
        source_path=Path("samples/docs/incident.txt"),
        doc_type=DocumentType.incident,
        body_text="Customer ID validation failed in PAYM01 with error E102.",
        search_text="customer id paym01 e102",
    )


class TestChatCompletionOllama:
    def test_ollama_success(self) -> None:
        payload = json.dumps({"message": {"content": "Local summary text"}}).encode("utf-8")
        response = MagicMock()
        response.read.return_value = payload
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = chat_completion(
                provider="ollama",
                model="llama3.2",
                messages=[{"role": "user", "content": "hello"}],
            )

        assert result == "Local summary text"
        urlopen.assert_called_once()
        request = urlopen.call_args[0][0]
        assert request.full_url.endswith("/api/chat")

    def test_ollama_connection_failure_returns_none(self) -> None:
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = chat_completion(
                provider="ollama",
                model="llama3.2",
                messages=[{"role": "user", "content": "hello"}],
            )

        assert result is None

    def test_unknown_provider_returns_none(self) -> None:
        assert chat_completion(provider="heuristic", model="x", messages=[]) is None


class TestSummarizeProgramOllama:
    def test_uses_ollama_response(self) -> None:
        program = _sample_program()
        cfg = SummarizerConfig(provider="ollama", model="llama3.2")

        with patch(
            "cobol_error_scanner.summarizer.chat_completion",
            return_value="Program validates customer identifiers before posting.",
        ):
            text = summarize_program(program, cfg)

        assert text == "Program validates customer identifiers before posting."

    def test_falls_back_when_ollama_unavailable(self) -> None:
        program = _sample_program()
        cfg = SummarizerConfig(provider="ollama", model="llama3.2")

        with patch("cobol_error_scanner.summarizer.chat_completion", return_value=None):
            text = summarize_program(program, cfg)

        assert "Program PAYM01 defines error handling" in text
        assert "ollama unavailable; fallback used" in text


class TestResolverOllama:
    def test_suggest_llm_parses_json_response(self) -> None:
        doc = _sample_document()
        cfg = ResolverConfig(provider="ollama", model="llama3.2")
        findings = {
            "PAYM01:E102::120:VALIDATE-CUST": {
                "program": "PAYM01",
                "error_code": "E102",
                "error_field": "",
                "row_summary": "Customer ID missing",
                "condition": "WS-CUST-ID = SPACES",
                "mapping_detail": "",
            }
        }
        doc.links = [
            DocumentLink(
                document_id=doc.id,
                program="PAYM01",
                error_code="E102",
                finding_key="PAYM01:E102::120:VALIDATE-CUST",
            )
        ]

        llm_json = json.dumps(
            {
                "summary": "Validate customer ID before retrying payment.",
                "steps": ["Check WS-CUST-ID population in PAYM01."],
                "confidence": "high",
            }
        )

        with patch(
            "cobol_error_scanner.ingestion.resolution.chat_completion",
            return_value=llm_json,
        ):
            result = _suggest_llm(doc, findings, [], cfg)

        assert result is not None
        assert result.provider == "ollama"
        assert result.summary == "Validate customer ID before retrying payment."
        assert result.steps == ["Check WS-CUST-ID population in PAYM01."]
        assert result.confidence == "high"

    def test_suggest_llm_returns_none_when_ollama_unavailable(self) -> None:
        doc = _sample_document()
        cfg = ResolverConfig(provider="ollama", model="llama3.2")

        with patch(
            "cobol_error_scanner.ingestion.resolution.chat_completion",
            return_value=None,
        ):
            result = _suggest_llm(doc, {}, [], cfg)

        assert result is None
