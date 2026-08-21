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


def _write_multi_family_one_char(base: Path) -> Path:
    mapping = base / "error_mapping_files"
    mapping.mkdir()
    (mapping / "CORORA_ONE_CHAR_ERROR").write_text(
        "       10 CORORA-R-ERROR-TYPE PIC X(01).\n"
        "           88 CORORA-R-ERROR-BACKORDER-FLAG VALUE 'B'.\n",
        encoding="utf-8",
    )
    (mapping / "CORORH_ONE_CHAR_ERROR").write_text(
        "       10 CORORH-R-ERROR-TYPE PIC X(01).\n"
        "           88 CORORH-R-ERROR-BACKORDER-FLAG VALUE 'B'.\n",
        encoding="utf-8",
    )
    return mapping


def test_field_matched_in_two_families_reports_family_without_cobol_logic(
    tmp_path: Path,
) -> None:
    # BACKORDER-FLAG is defined in both CORORA and CORORH, but only CORORA is set
    # in COBOL. The CORORH family must still be represented (defined, not set).
    mapping_dir = _write_multi_family_one_char(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "PROG010.cob").write_text(
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           SET CORORA-R-ERROR-BACKORDER-FLAG TO TRUE.\n",
        encoding="utf-8",
    )

    programs = resolve_mapped_error_field(
        src, "ERROR-BACKORDER-FLAG", mapping_dir_explicit=mapping_dir
    )

    fields = {o.error_field for p in programs for o in p.occurrences}
    assert "CORORA-R-ERROR-BACKORDER-FLAG" in fields
    assert "CORORH-R-ERROR-BACKORDER-FLAG" in fields

    # CORORA is a real COBOL finding; CORORH is a mapping-definition record.
    corora = [
        o
        for p in programs
        for o in p.occurrences
        if o.error_field == "CORORA-R-ERROR-BACKORDER-FLAG"
    ][0]
    cororh = [
        o
        for p in programs
        for o in p.occurrences
        if o.error_field == "CORORH-R-ERROR-BACKORDER-FLAG"
    ][0]
    assert "no COBOL SET/MOVE logic" not in (corora.mapping_detail or "")
    assert "no COBOL SET/MOVE logic" in (cororh.mapping_detail or "")


def test_indirect_error_type_feeder_move_is_detected(tmp_path: Path) -> None:
    # Error type is staged in a work field that is later moved into
    # CORORH-R-ERROR-TYPE, rather than SET directly. The MOVE '<char>' TO <feeder>
    # site must be reported with the mapped 88-level name as its error field.
    mapping = tmp_path / "error_mapping_files"
    mapping.mkdir()
    (mapping / "CORORH_ONE_CHAR_ERROR").write_text(
        "       10 CORORH-R-ERROR-TYPE PIC X(01).\n"
        "           88 CORORH-R-ERROR-BACKORDER-FLAG VALUE 'B'.\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "PROG020.cob").write_text(
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           IF CORORH-BCK-ALLOW-BACKORDERS\n"
        "              NEXT SENTENCE\n"
        "           ELSE\n"
        "              MOVE 'B' TO WS-LU6ORH-ERROR-SW\n"
        "           END-IF.\n"
        "           MOVE WS-LU6ORH-ERROR-SW TO CORORH-R-ERROR-TYPE.\n",
        encoding="utf-8",
    )

    programs = resolve_mapped_error_field(
        src, "ERROR-BACKORDER-FLAG", mapping_dir_explicit=mapping
    )

    assert len(programs) == 1
    assert programs[0].program_id == "PROG020"
    occ = programs[0].occurrences[0]
    assert occ.code == "EB"
    assert occ.error_field == "CORORH-R-ERROR-BACKORDER-FLAG"
    assert "WS-LU6ORH-ERROR-SW" in occ.setting_statement
    # The nested IF condition is captured in the row summary.
    assert "CORORH-BCK-ALLOW-BACKORDERS" in (occ.row_summary or "")


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
