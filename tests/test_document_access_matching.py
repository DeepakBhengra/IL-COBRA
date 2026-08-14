"""Unit tests for per-code operational document matching."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cobol_error_scanner.document_access import (  # noqa: E402
    _enrich_matched_document,
    _expand_confirmed_resolution,
    _historical_resolution_excerpt,
    _index_document_resolutions,
    _link_evidence_for_finding,
    _doc_matches_finding,
    _technical_resolution_from_finding,
)
from cobol_error_scanner.ingestion.operational_docs_filter import (  # noqa: E402
    document_row_matches_active_codes,
)


def _se_doc_no_links() -> dict:
    return {
        "document_id": "se-incident",
        "title": "SE terms override incident",
        "body_preview": "Customer hit error code SE on CORORA-R-ERR-NO-SEC-TERM-OVRD.",
        "body_text": "Customer hit error code SE on CORORA-R-ERR-NO-SEC-TERM-OVRD.",
        "links": [],
        "metadata": {"mentioned_error_codes": ["SE"]},
    }


def _d6_doc_no_links() -> dict:
    return {
        "document_id": "d6-incident",
        "title": "D6 no agreement",
        "body_preview": "Order failed with error code D6 (CORORA-R-ERROR-NO-AGREEMENT).",
        "body_text": "Order failed with error code D6 (CORORA-R-ERROR-NO-AGREEMENT).",
        "links": [],
        "metadata": {"mentioned_error_codes": ["D6"]},
    }


def test_text_fallback_matches_finding_code_without_links() -> None:
    ok, score = _doc_matches_finding(
        _se_doc_no_links(),
        finding_key="ORP676|SE|CORORA-R-ERR-NO-SEC-TERM-OVRD|100|",
        error_code="SE",
        error_field="CORORA-R-ERR-NO-SEC-TERM-OVRD",
        program="ORP676",
    )
    assert ok is True
    assert score == 0.75


def test_cross_code_exclusion_se_doc_on_d6_finding() -> None:
    ok, _ = _doc_matches_finding(
        _se_doc_no_links(),
        finding_key="ORP673|D6|CORORA-R-ERROR-NO-AGREEMENT|50|",
        error_code="D6",
        error_field="CORORA-R-ERROR-NO-AGREEMENT",
        program="ORP673",
    )
    assert ok is False


def test_cross_code_exclusion_d6_doc_on_se_finding() -> None:
    ok, _ = _doc_matches_finding(
        _d6_doc_no_links(),
        finding_key="ORP676|SE|CORORA-R-ERR-NO-SEC-TERM-OVRD|100|",
        error_code="SE",
        error_field="CORORA-R-ERR-NO-SEC-TERM-OVRD",
        program="ORP676",
    )
    assert ok is False


def test_operational_docs_filter_text_mention() -> None:
    assert document_row_matches_active_codes(_se_doc_no_links(), {"SE"}) is True
    assert document_row_matches_active_codes(_se_doc_no_links(), {"D6"}) is False
    assert document_row_matches_active_codes(_d6_doc_no_links(), {"D6"}) is True


def test_weak_match_gets_text_evidence_and_stored_resolution() -> None:
    doc = {
        "document_id": "doc-d6-alert",
        "title": "D6 alert email",
        "body_preview": "order create throwing D6 error\nInsideline team please check this error",
        "body_text": "order create throwing D6 error\nInsideline team please check this error",
        "links": [],
        "metadata": {"mentioned_error_codes": ["D6"]},
        "resolution_summary": "",
        "resolution_steps": [],
    }
    resolutions = [
        {
            "scope": "document",
            "document_id": "doc-d6-alert",
            "summary": "Address D6 in ORP673 based on linked COBOL logic.",
            "steps": ["Review COBOL program ORP673 for error code D6."],
            "confidence": "medium",
            "linked_error_codes": "D6",
        }
    ]
    finding_row = {
        "program": "ORP673",
        "error_code": "D6",
        "error_field": "CORORL-R-ERROR-LINE1-NOT-CMNT",
        "line": 10720,
        "paragraph": "PARA-1",
        "statement": "SET CORORL-R-ERROR-LINE1-NOT-CMNT TO TRUE",
    }
    enriched = _enrich_matched_document(
        doc,
        score=0.75,
        finding_key="ORP673|D6|CORORL-R-ERROR-LINE1-NOT-CMNT|50|",
        error_code="D6",
        error_field="CORORL-R-ERROR-LINE1-NOT-CMNT",
        program="ORP673",
        finding_row=finding_row,
        resolutions_by_doc=_index_document_resolutions(resolutions),
    )
    assert enriched["link_evidence"]
    assert "D6" in enriched["link_evidence"].upper()
    assert enriched["resolution_summary"] == "Address D6 in ORP673 based on linked COBOL logic."
    assert enriched["resolution_steps"]


def test_link_evidence_prefers_formal_link_over_text() -> None:
    doc = {
        "document_id": "doc-ec",
        "body_preview": "order created is throwing 'EC' error code",
        "body_text": "order created is throwing 'EC' error code",
        "links": [
            {
                "finding_key": "ORP676|EC|CORORA-R-ERROR-SHIP-COMPLETE|10|",
                "error_code": "EC",
                "error_field": "CORORA-R-ERROR-SHIP-COMPLETE",
                "program": "ORP676",
                "score": 1.0,
                "evidence": "'EC'",
            }
        ],
    }
    evidence = _link_evidence_for_finding(
        doc,
        finding_key="ORP676|EC|CORORA-R-ERROR-SHIP-COMPLETE|10|",
        error_code="EC",
        error_field="CORORA-R-ERROR-SHIP-COMPLETE",
        program="ORP676",
    )
    assert evidence == "'EC'"


def test_enriched_document_historical_and_technical_resolution() -> None:
    finding_row = {
        "program": "ORP676",
        "file": r"C:\samples\ORP676.cob",
        "error_code": "EC",
        "error_field": "CORORA-R-ERROR-SHIP-COMPLETE",
        "line": 5425,
        "paragraph": "120-EDIT-SHIPMENT-HEADER",
        "condition": "ORH-FROM-XML",
        "row_summary": "SET error on ship complete",
        "related": [{"name": "ORH-FROM-XML", "role": "if_or_when_condition"}],
    }
    doc = {
        "document_id": "doc-ec",
        "body_preview": "order create throwing EC error",
        "body_text": "order create throwing EC error",
        "links": [
            {
                "finding_key": "ORP676|EC|CORORA-R-ERROR-SHIP-COMPLETE|5425|120-EDIT-SHIPMENT-HEADER",
                "error_code": "EC",
                "evidence": "order create throwing EC error",
                "score": 1.0,
            }
        ],
    }
    enriched = _enrich_matched_document(
        doc,
        score=1.0,
        finding_key="ORP676|EC|CORORA-R-ERROR-SHIP-COMPLETE|5425|120-EDIT-SHIPMENT-HEADER",
        error_code="EC",
        error_field="CORORA-R-ERROR-SHIP-COMPLETE",
        program="ORP676",
        finding_row=finding_row,
        resolutions_by_doc={},
    )
    assert enriched["link_evidence"] == "order create throwing EC error"
    assert enriched["historical_resolution"] == "order create throwing EC error"
    assert "EC" in enriched["historical_resolution"].upper()
    tech = enriched["technical_resolution"]
    assert tech["program"] == "ORP676"
    assert tech["error_code"] == "EC"
    assert tech["line"] == 5425
    assert tech["file"] == "ORP676.cob"
    assert tech["related"][0]["name"] == "ORH-FROM-XML"


def test_historical_resolution_returns_full_runbook_text() -> None:
    body = (
        "# Runbook: order processing\n"
        "Error code - D1\n"
        "Acheck  if the vendors of order lines are linked with one master vendor."
    )
    doc = {
        "document_id": "doc-d1-runbook",
        "body_preview": body,
        "body_text": body,
        "links": [],
        "metadata": {"mentioned_error_codes": ["D1"]},
    }
    excerpt = _historical_resolution_excerpt(doc, "D1")
    assert "master vendor" in excerpt
    assert excerpt.endswith("master vendor.")
    assert "one ma" != excerpt[-6:]


def test_expand_confirmed_resolution_upgrades_truncated_historical() -> None:
    confirmed = {
        "selected_text": "# Runbook: order processing Error code - D1 Acheck if the vendors of order lines are linked with one ma",
        "source": "historical",
        "error_code": "D1",
    }
    documents = [
        {
            "historical_resolution": (
                "# Runbook: order processing Error code - D1 Acheck if the vendors of order "
                "lines are linked with one master vendor."
            )
        }
    ]
    expanded = _expand_confirmed_resolution(confirmed, documents)
    assert "master vendor." in expanded["selected_text"]


def test_technical_resolution_omits_empty_fields() -> None:
    tech = _technical_resolution_from_finding({"program": "ORP676", "error_code": "EC"})
    assert tech == {"program": "ORP676", "error_code": "EC"}
    assert "condition" not in tech
