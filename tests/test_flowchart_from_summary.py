"""Tests for IF branch direction in flowchart generation."""

from __future__ import annotations

import re

from cobol_error_scanner.flowchart_from_summary import (
    DecisionStep,
    ParsedSummary,
    build_dot,
    build_mermaid,
    parse_row_summary,
)


def _if_diamond_ids(mermaid: str) -> list[str]:
    return re.findall(r"\b(IF\d+)\{", mermaid)


def _skip_ids(mermaid: str) -> list[str]:
    return re.findall(r"\b(Skip\d+)\(\[", mermaid)


def test_unmarked_if_defaults_to_false_leading_to_error_path() -> None:
    # Legacy summaries without branch markers keep the old default: False -> error.
    summary = (
        "Nested control path (inner to outer): IF INNER -> IF OUTER. "
        "MOVE X TO ERR-FIELD"
    )
    parsed = parse_row_summary(summary)
    mmd = build_mermaid(parsed, outcome_title="Test")

    if_ids = _if_diamond_ids(mmd)
    assert len(if_ids) == 2  # if_ids[0] == outer, if_ids[1] == inner

    # Start flows into the outermost diamond (no decision label on the entry edge).
    assert re.search(rf"Start0 --> {if_ids[0]}\b", mmd)
    # Outer IF: False -> inner IF (error path), True -> skip
    assert re.search(rf'{if_ids[0]} -->\|"False"\| {if_ids[1]}', mmd)
    assert re.search(rf'{if_ids[0]} -->\|"True"\| Skip\d+', mmd)
    # Inner IF: False -> Set (error action)
    assert re.search(rf'{if_ids[1]} -->\|"False"\| Set\d+', mmd)


def test_branch_markers_route_error_on_true_or_false() -> None:
    # INNER is reached via ELSE (false); OUTER is reached when TRUE.
    summary = (
        "Nested control path (inner to outer): IF INNER [false] -> IF OUTER [true]. "
        "SET CORORH-R-ERR-X TO TRUE"
    )
    parsed = parse_row_summary(summary)
    # Markers are stripped from predicates.
    assert parsed.steps[0].predicate == "INNER"
    assert parsed.steps[0].branch == "else"
    assert parsed.steps[1].predicate == "OUTER"
    assert parsed.steps[1].branch == "then"

    mmd = build_mermaid(parsed, outcome_title="Test")
    if_ids = _if_diamond_ids(mmd)  # [0]=outer(then), [1]=inner(else)
    assert len(if_ids) == 2

    # Outer IF (error when TRUE): True -> inner IF, False -> skip
    assert re.search(rf'{if_ids[0]} -->\|"True"\| {if_ids[1]}', mmd)
    assert re.search(rf'{if_ids[0]} -->\|"False"\| Skip\d+', mmd)
    # Inner IF (error via ELSE / FALSE): False -> Set, True -> skip
    assert re.search(rf'{if_ids[1]} -->\|"False"\| Set\d+', mmd)
    assert re.search(rf'{if_ids[1]} -->\|"True"\| Skip\d+', mmd)


def test_build_dot_branch_markers() -> None:
    parsed = ParsedSummary(
        steps=[
            DecisionStep(kind="IF", predicate="INNER", branch="else"),
            DecisionStep(kind="IF", predicate="OUTER", branch="then"),
        ],
        action="SET CORORH-R-ERR-X TO TRUE",
    )
    dot = build_dot(parsed, outcome_title="Test")

    if_ids = re.findall(r"\b(IF\d+) \[shape=diamond", dot)
    assert len(if_ids) == 2  # [0]=outer(then), [1]=inner(else)
    assert re.search(rf'{if_ids[0]} -> {if_ids[1]} \[label="True"\]', dot)
    assert re.search(rf'{if_ids[0]} -> Skip\d+ \[label="False"\]', dot)
    assert re.search(rf'{if_ids[1]} -> Set\d+ \[label="False"\]', dot)


def test_build_mermaid_single_if_unmarked_false_labels_error_action() -> None:
    parsed = ParsedSummary(
        steps=[DecisionStep(kind="IF", predicate="ORH-DEBIT-MEMO OR ORH-RTC-ORDER")],
        action="SET CORORA-R-ERROR-ORDER-STATUS TO TRUE",
    )
    mmd = build_mermaid(parsed, outcome_title="Test")
    if_id = _if_diamond_ids(mmd)[0]
    assert re.search(rf'{if_id} -->\|"False"\| Set\d+', mmd)


def test_build_mermaid_single_if_true_marker() -> None:
    parsed = ParsedSummary(
        steps=[DecisionStep(kind="IF", predicate="TB-IL-FRT-FWD-ALLOW", branch="then")],
        action="SET CORORH-R-ERR-INACTIVE-FFWDR TO TRUE",
    )
    mmd = build_mermaid(parsed, outcome_title="Test")
    if_id = _if_diamond_ids(mmd)[0]
    assert re.search(rf'{if_id} -->\|"True"\| Set\d+', mmd)
    assert re.search(rf'{if_id} -->\|"False"\| Skip\d+', mmd)


def test_build_mermaid_when_branches_unchanged() -> None:
    parsed = ParsedSummary(
        steps=[DecisionStep(kind="WHEN", predicate="VALUE-A")],
        action="MOVE X TO ERR",
    )
    mmd = build_mermaid(parsed, outcome_title="Test")

    when_ids = re.findall(r"\b(WHEN\d+)\{", mmd)
    else_ids = re.findall(r"\b(Else\d+)\(\[", mmd)
    assert len(when_ids) == 1
    assert len(else_ids) == 1
    assert re.search(rf"Start0 --> {when_ids[0]}\b", mmd)
    assert re.search(rf'{when_ids[0]} -->\|"Match"\| Set\d+', mmd)
    assert re.search(rf'{when_ids[0]} -->\|"No match"\| {else_ids[0]}', mmd)
