"""AI / heuristic summarization of extracted COBOL error logic."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from cobol_error_scanner.llm_client import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    LLM_BACKEND_PROVIDERS,
    chat_completion,
)
from cobol_error_scanner.models import ErrorOccurrence, ProgramSummary


@dataclass
class SummarizerConfig:
    provider: str = "heuristic"  # heuristic | openai | ollama
    model: str = DEFAULT_OPENAI_MODEL
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))

    def __post_init__(self) -> None:
        if self.provider == "ollama":
            if self.model == DEFAULT_OPENAI_MODEL:
                self.model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
            self.base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url)


def summarize_row(occ: ErrorOccurrence) -> str:
    """
    Short business-facing summary for table output.
    With ``openai`` or ``ollama`` you can replace/extend this; heuristics use message + condition.
    """
    msg_raw = occ.error_message_literal.strip()
    msg_u = msg_raw.upper()
    cond_u = occ.condition.upper()
    params_u = (occ.parameters_text or "").upper()

    if "INVALID" in msg_u and "CUSTOMER" in msg_u and ("CUST" in cond_u or "CUST" in params_u):
        return "Customer ID missing"

    if msg_raw:
        return msg_raw.replace("'", "").replace('"', "").title()
    if occ.condition:
        ids = occ.parameters_text or ""
        if ids:
            return f"Check failed ({ids})"
        return f"Failed when {occ.condition.strip()[:120]}"
    return f"Error {occ.code}"


def summarize_program(summary: ProgramSummary, cfg: SummarizerConfig | None = None) -> str:
    cfg = cfg or SummarizerConfig()
    if cfg.provider in LLM_BACKEND_PROVIDERS:
        llm_text = _summarize_llm(summary, cfg)
        if llm_text:
            return llm_text
        fallback_note = (
            " (openai package not installed; fallback used)"
            if cfg.provider == "openai"
            else " (ollama unavailable; fallback used)"
        )
        return _summarize_heuristic(summary) + fallback_note
    return _summarize_heuristic(summary)


def _summarize_heuristic(p: ProgramSummary) -> str:
    parts: list[str] = []
    parts.append(f"Program {p.program_id} defines error handling in {len(p.occurrences)} place(s).")
    for occ in p.occurrences[:50]:
        loc = f"line {occ.location.line}"
        para = f" in paragraph {occ.paragraph}" if occ.paragraph else ""
        stmt = occ.setting_statement.strip()[:200]
        rs = (occ.row_summary or "").strip()
        if rs and "Nested control path" in rs:
            rshort = rs if len(rs) <= 500 else rs[:497] + "…"
            parts.append(f"Error code {occ.code} ({loc}{para}): {stmt}. {rshort}")
            continue
        cond_txt = (occ.condition or "").strip()
        if len(cond_txt) > 200:
            cond_txt = cond_txt[:197] + "…"
        cond = f"; condition fields: {cond_txt}" if cond_txt else ""
        parts.append(
            f"Error code {occ.code} is assigned ({loc}{para}){cond}: {stmt}"
        )
    if len(p.occurrences) > 50:
        parts.append(f"... and {len(p.occurrences) - 50} more occurrence(s).")
    return " ".join(parts)


def _summarize_llm(p: ProgramSummary, cfg: SummarizerConfig) -> str | None:
    bullets = []
    for occ in p.occurrences:
        bullets.append(
            f"- {occ.code} at line {occ.location.line} ({occ.paragraph or '?'}): {occ.setting_statement}"
        )
    user = (
        "Summarize the business meaning of these COBOL error assignments for a modernization architect. "
        "Use short paragraphs, mention likely business checks, and avoid repeating raw COBOL.\n\n"
        + "\n".join(bullets[:80])
    )
    return chat_completion(
        provider=cfg.provider,
        model=cfg.model,
        messages=[
            {
                "role": "system",
                "content": "You explain legacy COBOL error handling in plain English for auditors and migration teams.",
            },
            {"role": "user", "content": user},
        ],
        api_key_env=cfg.api_key_env,
        base_url=cfg.base_url,
        temperature=0.2,
    )
