"""Field-query fallback: a mapping-defined field with no COBOL logic still returns a record."""

from __future__ import annotations

from pathlib import Path

from cobol_error_scanner.mapping_resolve import resolve_mapped_error_field


def _write_mapping_dir(base: Path) -> Path:
    mapping = base / "error_mapping_files"
    mapping.mkdir()
    # Commented-out (column 7 '*') entry -> defined but disabled.
    (mapping / "CORORH_TWO_CHAR_ERROR").write_text(
        "027600     05  CORORH-R-ERROR-TYPE-NEW    PIC X(02).\n"
        "027700*          88 CORORH-R-ERROR-DENIED-ADD1     VALUE 'B2'.\n"
        "027800           88 CORORH-R-ERROR-ACTIVE-CODE     VALUE 'B3'.\n",
        encoding="utf-8",
    )
    return mapping


def test_commented_mapping_field_returns_definition_fallback(tmp_path: Path) -> None:
    mapping_dir = _write_mapping_dir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    # COBOL source with no SET/MOVE for the queried field.
    (src / "PROG001.cob").write_text(
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           DISPLAY 'NOTHING TO SET HERE'.\n",
        encoding="utf-8",
    )

    programs = resolve_mapped_error_field(
        src, "CORORH-R-ERROR-DENIED-ADD1", mapping_dir_explicit=mapping_dir
    )

    assert len(programs) == 1
    occ = programs[0].occurrences[0]
    assert occ.error_field == "CORORH-R-ERROR-DENIED-ADD1"
    assert occ.code == "B2"
    assert "CORORH" in occ.mapping_detail
    assert "commented-out" in occ.mapping_detail.lower()
    assert "no COBOL SET/MOVE logic" in occ.mapping_detail


def test_active_mapping_field_with_logic_is_not_a_fallback(tmp_path: Path) -> None:
    mapping_dir = _write_mapping_dir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    # Active entry (B3) has real COBOL logic; must resolve to the COBOL source, not the copybook.
    (src / "PROG002.cob").write_text(
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           SET CORORH-R-ERROR-ACTIVE-CODE TO TRUE.\n",
        encoding="utf-8",
    )

    programs = resolve_mapped_error_field(
        src, "CORORH-R-ERROR-ACTIVE-CODE", mapping_dir_explicit=mapping_dir
    )

    assert len(programs) == 1
    assert programs[0].program_id == "PROG002"
    occ = programs[0].occurrences[0]
    assert occ.code == "B3"
    assert "no COBOL SET/MOVE logic" not in (occ.mapping_detail or "")
