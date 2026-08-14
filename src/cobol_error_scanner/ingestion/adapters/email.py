"""Email (.eml) adapter."""

from __future__ import annotations

import email
from email import policy
from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import _base_document
from cobol_error_scanner.ingestion.models import DocumentType, OperationalDocument


class EmailAdapter:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".eml"

    def extract(self, path: Path) -> OperationalDocument:
        raw = path.read_bytes()
        msg = email.message_from_bytes(raw, policy=policy.default)
        subject = str(msg.get("Subject", "") or path.stem)
        sender = str(msg.get("From", ""))
        date = str(msg.get("Date", ""))
        parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ("text/plain", "text/html"):
                    payload = part.get_content()
                    if isinstance(payload, str):
                        parts.append(payload)
        else:
            payload = msg.get_content()
            if isinstance(payload, str):
                parts.append(payload)
        body = "\n\n".join(parts)
        return _base_document(
            path,
            doc_type=DocumentType.email,
            title=subject,
            body=body,
            metadata={"sender": sender, "subject": subject, "date": date},
        )
