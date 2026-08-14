"""Format-specific document adapters."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.ingestion.adapters.base import DocumentAdapter
from cobol_error_scanner.ingestion.adapters.chat import ChatAdapter
from cobol_error_scanner.ingestion.adapters.csv_generic import CsvGenericAdapter
from cobol_error_scanner.ingestion.adapters.email import EmailAdapter
from cobol_error_scanner.ingestion.adapters.excel import ExcelAdapter
from cobol_error_scanner.ingestion.adapters.html import HtmlAdapter
from cobol_error_scanner.ingestion.adapters.log import LogAdapter
from cobol_error_scanner.ingestion.adapters.pdf import PdfAdapter
from cobol_error_scanner.ingestion.adapters.text import TextAdapter
from cobol_error_scanner.ingestion.adapters.ticket import TicketAdapter
from cobol_error_scanner.ingestion.adapters.unknown import UnknownAdapter
from cobol_error_scanner.ingestion.adapters.word import WordAdapter
from cobol_error_scanner.ingestion.models import OperationalDocument

_SPECIFIC_ADAPTERS: list[DocumentAdapter] = [
    EmailAdapter(),
    HtmlAdapter(),
    PdfAdapter(),
    WordAdapter(),
    TicketAdapter(),
    ChatAdapter(),
    CsvGenericAdapter(),
    ExcelAdapter(),
    LogAdapter(),
    TextAdapter(),
]
_FALLBACK = UnknownAdapter()


def extract_document(path: Path) -> OperationalDocument:
    for adapter in _SPECIFIC_ADAPTERS:
        if adapter.supports(path):
            return adapter.extract(path)
    return _FALLBACK.extract(path)
