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


def test_build_mermaid_if_false_leads_to_error_path_true_to_skip() -> None:
    summary = (
        "Nested control path (inner to outer): IF INNER -> IF OUTER. "
        "MOVE X TO ERR-FIELD"
    )
    parsed = parse_row_summary(summary)
    mmd = build_mermaid(parsed, outcome_title="Test")

    if_ids = _if_diamond_ids(mmd)
    skip_ids = _skip_ids(mmd)
    assert len(if_ids) == 2
    assert len(skip_ids) == 2

    # Outer IF (first diamond after Start): False -> inner IF, True -> skip
    assert re.search(rf'Start0 -->\|"False"\| {if_ids[0]}', mmd)
    assert re.search(rf'Start0 -->\|"True"\| {skip_ids[0]}', mmd)

    # Inner IF: False -> Set (error action), True -> skip
    assert re.search(rf'{if_ids[0]} -->\|"False"\| {if_ids[1]}', mmd)
    assert re.search(rf'{if_ids[0]} -->\|"True"\| {skip_ids[1]}', mmd)
    assert re.search(rf'{if_ids[1]} -->\|"False"\| Set\d+', mmd)


def test_build_dot_if_false_leads_to_error_path_true_to_skip() -> None:
    parsed = ParsedSummary(
        steps=[
            DecisionStep(kind="IF", predicate="OUTER"),
            DecisionStep(kind="IF", predicate="INNER"),
        ],
        action="MOVE X TO ERR",
    )
    dot = build_dot(parsed, outcome_title="Test")

    if_ids = re.findall(r"\b(IF\d+) \[shape=diamond", dot)
    skip_ids = re.findall(r"\b(Skip\d+) \[shape=box", dot)
    assert len(if_ids) == 2
    assert len(skip_ids) == 2

    assert re.search(rf"Start0 -> {if_ids[0]} \[label=\"False\"\]", dot)
    assert re.search(rf"Start0 -> {skip_ids[0]} \[label=\"True\"\]", dot)
    assert re.search(rf"{if_ids[0]} -> {if_ids[1]} \[label=\"False\"\]", dot)
    assert re.search(rf"{if_ids[0]} -> {skip_ids[1]} \[label=\"True\"\]", dot)
    assert re.search(rf"{if_ids[1]} -> Set\d+ \[label=\"False\"\]", dot)


def test_build_mermaid_single_if_false_labels_error_action() -> None:
    parsed = ParsedSummary(
        steps=[DecisionStep(kind="IF", predicate="ORH-DEBIT-MEMO OR ORH-RTC-ORDER")],
        action="SET CORORA-R-ERROR-ORDER-STATUS TO TRUE",
    )
    mmd = build_mermaid(parsed, outcome_title="Test")
    if_id = _if_diamond_ids(mmd)[0]
    assert re.search(rf'{if_id} -->\|"False"\| Set\d+', mmd)


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
    assert re.search(rf'Start0 -->\|"Match"\| {when_ids[0]}', mmd)
    assert re.search(rf'Start0 -->\|"No match"\| {else_ids[0]}', mmd)
    assert re.search(rf'{when_ids[0]} -->\|"Match"\| Set\d+', mmd)
