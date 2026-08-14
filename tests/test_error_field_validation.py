"""Tests for reserved error-field keyword validation."""

from __future__ import annotations

import pytest

from cobol_error_scanner.mapping_catalog import (
    error_field_query_violation,
    validate_error_field_query,
)


@pytest.mark.parametrize(
    "raw",
    [
        "ERR",
        "err",
        "ERROR",
        "error",
        "ERROR-",
        "error-",
        "-ERROR",
        "-error",
        "-ERROR-",
        "-error-",
        "CORORA-R-ERR",
        "CORORL-R-ERROR",
        "CORORL-R-ERROR-",
    ],
)
def test_reserved_tokens_are_rejected(raw: str) -> None:
    violation = error_field_query_violation(raw)
    assert violation is not None
    assert "too generic" in violation
    with pytest.raises(ValueError, match="too generic"):
        validate_error_field_query(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "ERR-NO-SEC-EDD-OVRD",
        "CORORA-R-ERR-NO-SEC",
        "CORORA-R-ERROR-TYPE",
        "CORORL-R-ERR-NO-SEC-TERM-OVRD",
        "NO-AGREEMENT",
    ],
)
def test_specific_fragments_are_allowed(raw: str) -> None:
    assert error_field_query_violation(raw) is None
    normalized = validate_error_field_query(raw)
    if raw.strip():
        assert normalized == raw.strip().upper()[:30]
    else:
        assert normalized == ""


def test_validate_error_field_query_raises_with_specific_token() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_error_field_query("ERROR")
    assert "'ERROR'" in str(exc_info.value)
    assert "ERR-NO-SEC-EDD-OVRD" in str(exc_info.value)
