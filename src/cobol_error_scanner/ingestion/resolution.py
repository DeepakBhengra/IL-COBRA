"""Retrieval and resolution suggestion for operational documents."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from cobol_error_scanner.llm_client import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    LLM_BACKEND_PROVIDERS,
    chat_completion,
)
from cobol_error_scanner.ingestion.knowledge_store import (
    accepted_evidence_items,
    has_high_confidence_accepted,
)
from cobol_error_scanner.ingestion.models import (
    EvidenceItem,
    OperationalDocument,
    ResolutionSuggestion,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}")


@dataclass
class ResolverConfig:
    provider: str = "heuristic"
    model: str = DEFAULT_OPENAI_MODEL
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))
    top_k: int = 3

    def __post_init__(self) -> None:
        if self.provider == "ollama":
            if self.model == DEFAULT_OPENAI_MODEL:
                self.model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
            self.base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _term_matched_docs(corpus: list[OperationalDocument]) -> list[OperationalDocument]:
    return [d for d in corpus if d.metadata.get("term_matched") is True]


def retrieve_similar(
    doc: OperationalDocument,
    corpus: list[OperationalDocument],
    *,
    top_k: int = 3,
    term_matched_only: bool = False,
) -> list[OperationalDocument]:
    if term_matched_only:
        corpus = _term_matched_docs(corpus)
    if not corpus:
        return []
    doc_codes = {lnk.error_code.upper() for lnk in doc.links if lnk.error_code}
    doc_progs = {lnk.program.upper() for lnk in doc.links if lnk.program}
    doc_tokens = _tokens(doc.search_text)

    scored: list[tuple[float, OperationalDocument]] = []
    for other in corpus:
        if other.id == doc.id:
            continue
        score = 0.0
        other_codes = {lnk.error_code.upper() for lnk in other.links if lnk.error_code}
        other_progs = {lnk.program.upper() for lnk in other.links if lnk.program}
        score += 3.0 * len(doc_codes & other_codes)
        score += 2.0 * len(doc_progs & other_progs)
        overlap = doc_tokens & _tokens(other.search_text)
        score += 0.1 * len(overlap)
        if other.doc_type in (doc.doc_type,):
            score += 0.5
        if score > 0:
            scored.append((score, other))

    scored.sort(key=lambda x: -x[0])
    return [item[1] for item in scored[:top_k]]


def _append_confirmed_resolution(
    steps: list[str],
    evidence: list[EvidenceItem],
    confirmed: dict[str, Any],
) -> None:
    selected = str(confirmed.get("selected_text", "")).strip()
    if not selected:
        return
    src = str(confirmed.get("source", "")).strip().lower()
    src_label = "Historical Resolution" if src == "historical" else "Condition"
    steps.insert(0, f"Confirmed resolution ({src_label}): {selected[:220]}")
    comment = str(confirmed.get("comment", "")).strip()
    if comment:
        steps.insert(1, f"Analyst note: {comment[:220]}")
    evidence.insert(
        0,
        EvidenceItem(
            type="confirmed_resolution",
            ref=f"error_code:{confirmed.get('error_code', '')}",
            excerpt=selected[:300],
        ),
    )


def _append_accepted_evidence(
    steps: list[str],
    evidence: list[EvidenceItem],
    accepted: dict[str, Any],
) -> None:
    items = accepted_evidence_items(accepted)
    if not items and accepted.get("evidence_index") is not None:
        items = [accepted]
    shared_summary = str(accepted.get("summary", "")).strip()
    shared_steps = list(accepted.get("steps") or [])
    insert_at = 0
    for item in items:
        idx = item.get("evidence_index", "?")
        ref = str(item.get("ref", ""))
        excerpt = str(item.get("excerpt", ""))[:300]
        summary = str(item.get("summary", "")).strip() or shared_summary
        if summary:
            steps.insert(insert_at, f"Confirmed evidence #{idx} ({ref}): {summary[:220]}")
            insert_at += 1
        elif excerpt:
            steps.insert(insert_at, f"Confirmed evidence #{idx} ({ref}): {excerpt[:220]}")
            insert_at += 1
        evidence.insert(
            0,
            EvidenceItem(
                type=str(item.get("type", "document")),
                ref=f"{ref} (confirmed #{idx})",
                excerpt=excerpt or summary[:300],
                document_id=str(item.get("document_id", "")),
            ),
        )
        for step in item.get("steps") or shared_steps:
            st = str(step).strip()
            if st and st not in steps:
                steps.append(st)


def filter_mapping_detail_steps(steps: list[str]) -> list[str]:
    """Drop COBOL mapping_detail bullets from operational resolution steps."""
    return [s for s in steps if "check mapping detail" not in s.lower()]


def _append_aggregated_resolution(
    steps: list[str],
    evidence: list[EvidenceItem],
    aggregated: dict[str, Any],
    *,
    error_code: str = "",
    max_steps: int = 5,
) -> None:
    summary = str(aggregated.get("summary", "")).strip()
    if summary:
        label = error_code or "code"
        steps.insert(0, f"From knowledge index ({label}): {summary[:250]}")
        evidence.append(
            EvidenceItem(
                type="document",
                ref=f"knowledge:{label}",
                excerpt=summary[:300],
            )
        )
    for step in (aggregated.get("steps") or [])[:max_steps]:
        st = str(step).strip()
        if st:
            steps.append(f"Knowledge ({error_code or 'code'}): {st[:200]}")


def operational_body_excerpt(
    document_id: str,
    documents_by_id: dict[str, dict[str, Any]] | None = None,
    *,
    max_chars: int = 300,
) -> str:
    """Return ingested document body text for evidence display (not resolution summary)."""
    if not document_id or not documents_by_id:
        return ""
    row = documents_by_id.get(document_id)
    if not row:
        return ""
    text = str(row.get("body_text") or row.get("body_preview") or "").strip()
    return text[:max_chars]


def build_documents_by_id(
    *doc_lists: list[OperationalDocument],
    stored_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge in-run documents with knowledge-store rows (run bodies win on id clash)."""
    out: dict[str, dict[str, Any]] = {}
    for docs in doc_lists:
        for doc in docs:
            out[doc.id] = {
                "title": doc.title,
                "body_text": doc.body_text,
                "body_preview": (doc.body_text or "")[:500],
            }
    for doc_id, row in (stored_records or {}).items():
        out.setdefault(doc_id, row)
    return out


def _append_index_document_summaries(
    evidence: list[EvidenceItem],
    summaries: list[dict],
    *,
    max_docs: int = 5,
) -> None:
    for item in summaries[:max_docs]:
        title = str(item.get("title") or item.get("document_id", ""))
        excerpt = str(item.get("excerpt", ""))[:300]
        if excerpt:
            evidence.append(
                EvidenceItem(
                    type="document",
                    ref=f"{title} (indexed)",
                    excerpt=excerpt,
                    document_id=str(item.get("document_id", "")),
                )
            )


def _append_historical_steps(
    steps: list[str],
    evidence: list[EvidenceItem],
    historical_resolutions: list[dict],
    *,
    max_history: int = 3,
    documents_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    for row in historical_resolutions[:max_history]:
        title = str(row.get("title") or row.get("document_id", "prior"))
        status = str(row.get("status", "proposed"))
        for step in row.get("steps") or []:
            steps.append(f"Prior resolution ({title}, {status}): {str(step)[:200]}")
        doc_id = str(row.get("document_id", ""))
        summary = str(row.get("summary", ""))
        excerpt = operational_body_excerpt(doc_id, documents_by_id)
        if not excerpt:
            excerpt = summary[:300]
        if excerpt:
            evidence.append(
                EvidenceItem(
                    type="document",
                    ref=f"{title} (history)",
                    excerpt=excerpt,
                    document_id=doc_id,
                )
            )


def suggest_resolution(
    doc: OperationalDocument,
    *,
    findings_by_key: dict[str, dict],
    similar: list[OperationalDocument],
    cfg: ResolverConfig | None = None,
    include_similar_documents: bool = True,
    focused_error_code: str = "",
    historical_resolutions: list[dict] | None = None,
    aggregated_resolution: dict[str, Any] | None = None,
    index_document_summaries: list[dict] | None = None,
    accepted_evidence: dict[str, Any] | None = None,
    confirmed_resolution: dict[str, Any] | None = None,
    documents_by_id: dict[str, dict[str, Any]] | None = None,
) -> ResolutionSuggestion:
    cfg = cfg or ResolverConfig()
    if cfg.provider in LLM_BACKEND_PROVIDERS:
        if cfg.provider != "openai" or os.environ.get(cfg.api_key_env):
            result = _suggest_llm(doc, findings_by_key, similar, cfg)
            if result is not None:
                return result
    return _suggest_heuristic(
        doc,
        findings_by_key,
        similar,
        cfg,
        include_similar_documents=include_similar_documents,
        focused_error_code=focused_error_code,
        historical_resolutions=historical_resolutions,
        aggregated_resolution=aggregated_resolution,
        index_document_summaries=index_document_summaries,
        accepted_evidence=accepted_evidence,
        confirmed_resolution=confirmed_resolution,
        documents_by_id=documents_by_id,
    )


def _linked_findings(doc: OperationalDocument, findings_by_key: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for lnk in doc.links:
        row = findings_by_key.get(lnk.finding_key)
        if row:
            out.append(row)
    return out


def _suggest_heuristic(
    doc: OperationalDocument,
    findings_by_key: dict[str, dict],
    similar: list[OperationalDocument],
    cfg: ResolverConfig,
    *,
    include_similar_documents: bool = True,
    focused_error_code: str = "",
    historical_resolutions: list[dict] | None = None,
    aggregated_resolution: dict[str, Any] | None = None,
    index_document_summaries: list[dict] | None = None,
    accepted_evidence: dict[str, Any] | None = None,
    confirmed_resolution: dict[str, Any] | None = None,
    documents_by_id: dict[str, dict[str, Any]] | None = None,
) -> ResolutionSuggestion:
    findings = _linked_findings(doc, findings_by_key)
    evidence: list[EvidenceItem] = []
    steps: list[str] = []

    if accepted_evidence and has_high_confidence_accepted(accepted_evidence):
        _append_accepted_evidence(steps, evidence, accepted_evidence)
    elif confirmed_resolution and str(confirmed_resolution.get("selected_text", "")).strip():
        _append_confirmed_resolution(steps, evidence, confirmed_resolution)

    if not doc.metadata.get("term_matched", True) and not findings:
        return ResolutionSuggestion(
            document_id=doc.id,
            summary="Document not matched to focused error code or field.",
            steps=[],
            confidence="low",
            evidence=[],
            provider="heuristic",
        )

    if findings:
        row = findings[0]
        code = row.get("error_code", "")
        prog = row.get("program", "")
        summary = row.get("row_summary") or row.get("error_message") or ""
        cond = row.get("condition", "")
        mapping = row.get("mapping_detail", "")
        evidence.append(
            EvidenceItem(
                type="cobol_finding",
                ref=f"{prog}:{code}",
                excerpt=(summary or cond or mapping)[:300],
            )
        )
        steps.append(f"Review COBOL program {prog} for error code {code}.")
        if cond:
            steps.append(f"Validate business condition: {str(cond)[:200]}.")
        if summary:
            steps.append(f"Expected behavior: {str(summary)[:200]}.")
        confidence = "high"
        headline = f"Address {code} in {prog} based on linked COBOL logic."
    else:
        confidence = "low"
        headline = "No COBOL findings linked; review document context manually."
        steps.append("Search COBOL scan results for matching symptoms or program names.")
        if doc.entities:
            ent_vals = ", ".join(e.value for e in doc.entities[:5])
            steps.append(f"Investigate extracted references: {ent_vals}.")

    if include_similar_documents:
        for sim in similar[: cfg.top_k]:
            if not sim.metadata.get("term_matched", True):
                continue
            evidence.append(
                EvidenceItem(
                    type="document",
                    ref=sim.title,
                    excerpt=(sim.body_text or "")[:200],
                    document_id=sim.id,
                )
            )
            steps.append(f"Compare with similar document: {sim.title} ({sim.doc_type.value}).")

    if aggregated_resolution:
        _append_aggregated_resolution(
            steps,
            evidence,
            aggregated_resolution,
            error_code=focused_error_code,
        )
    if index_document_summaries:
        _append_index_document_summaries(evidence, index_document_summaries)

    history = historical_resolutions or []
    if history:
        _append_historical_steps(steps, evidence, history, documents_by_id=documents_by_id)

    if not steps:
        steps.append("Gather more operational context and re-run ingestion after COBOL scan.")

    step_cap = 12 if aggregated_resolution else 8
    return ResolutionSuggestion(
        document_id=doc.id,
        summary=headline,
        steps=filter_mapping_detail_steps(steps)[:step_cap],
        confidence=confidence,
        evidence=evidence,
        provider="heuristic",
    )


def _suggest_llm(
    doc: OperationalDocument,
    findings_by_key: dict[str, dict],
    similar: list[OperationalDocument],
    cfg: ResolverConfig,
) -> ResolutionSuggestion | None:
    findings = _linked_findings(doc, findings_by_key)
    if not findings and not similar and len(doc.body_text) < 50:
        return ResolutionSuggestion(
            document_id=doc.id,
            summary="Insufficient evidence to suggest a resolution.",
            steps=["Provide more context or run a COBOL scan and re-ingest."],
            confidence="low",
            evidence=[],
            provider=cfg.provider,
        )

    blocks: list[str] = [f"Document: {doc.title}\nType: {doc.doc_type.value}\n"]
    blocks.append((doc.body_text or "")[:3000])
    blocks.append("\n--- COBOL findings ---")
    for row in findings[:10]:
        blocks.append(
            f"program={row.get('program')} code={row.get('error_code')} "
            f"field={row.get('error_field')} summary={row.get('row_summary')} "
            f"condition={row.get('condition')} mapping={row.get('mapping_detail')}"
        )
    blocks.append("\n--- Similar documents ---")
    for sim in similar[: cfg.top_k]:
        blocks.append(f"{sim.title}: {(sim.body_text or '')[:500]}")

    raw = chat_completion(
        provider=cfg.provider,
        model=cfg.model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You suggest operational resolutions for legacy production issues. "
                    "Only use evidence provided. If evidence is thin, say so and give cautious steps. "
                    "Respond in JSON: {\"summary\": str, \"steps\": [str], \"confidence\": \"high|medium|low\"}"
                ),
            },
            {"role": "user", "content": "\n".join(blocks)},
        ],
        api_key_env=cfg.api_key_env,
        base_url=cfg.base_url,
        temperature=0.2,
    )
    if not raw:
        return None

    try:
        parsed = raw
        if "```" in parsed:
            parsed = parsed.split("```")[1]
            if parsed.startswith("json"):
                parsed = parsed[4:]
        data = json.loads(parsed)
    except json.JSONDecodeError:
        return ResolutionSuggestion(
            document_id=doc.id,
            summary=raw[:500],
            steps=[raw[:500]],
            confidence="medium",
            evidence=[
                EvidenceItem(type="document", ref=doc.title, excerpt=doc.body_text[:200])
            ],
            provider=cfg.provider,
        )

    evidence = [
        EvidenceItem(
            type="cobol_finding",
            ref=f"{row.get('program')}:{row.get('error_code')}",
            excerpt=str(row.get("row_summary", ""))[:200],
        )
        for row in findings[:5]
    ]
    for sim in similar[:2]:
        evidence.append(
            EvidenceItem(type="document", ref=sim.title, excerpt=sim.body_text[:200])
        )

    return ResolutionSuggestion(
        document_id=doc.id,
        summary=str(data.get("summary", "")),
        steps=[str(s) for s in data.get("steps", [])][:8],
        confidence=str(data.get("confidence", "medium")),
        evidence=evidence,
        provider=cfg.provider,
    )
