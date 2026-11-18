from __future__ import annotations

import json
from pathlib import Path

from app.evaluation import (
    EvalExpectation,
    graph_integrity,
    keyword_recall,
    missing_kinds,
    normalize_text,
    quote_grounding,
    score_analysis,
)
from app.models import Analysis, ArgumentNode


def make_analysis(*nodes: ArgumentNode) -> Analysis:
    return Analysis(
        title="测试",
        thesis="远程办公能提高效率",
        stance="支持",
        summary="摘要",
        nodes=list(nodes),
        verdict="总评",
    )


def node(
    node_id: str,
    kind: str,
    parent: str = "thesis",
    quote: str = "",
    text: str = "节点",
) -> ArgumentNode:
    return ArgumentNode(
        id=node_id,
        kind=kind,
        text=text,
        detail="说明",
        parent=parent,
        strength=3,
        quote=quote,
    )


def test_normalize_text_ignores_whitespace_only():
    assert normalize_text(" 远程 办公\n提高 ") == "远程办公提高"
    assert normalize_text(None) == ""  # type: ignore[arg-type]


def test_quote_grounding_is_strict_about_exact_substrings():
    source = "远程办公提高了产出，但也增加了协作成本。"
    analysis = make_analysis(
        node("c1", "claim", quote="远程办公提高了产出"),
        node("q1", "question", quote="远程办公必然提高所有公司效率"),
    )
    result = quote_grounding(analysis, source)
    assert result == {"rate": 0.5, "grounded": 1, "quotes": 2}


def test_keyword_recall_and_missing_kinds():
    analysis = make_analysis(
        node("c1", "claim", text="远程办公可以提高效率"),
        node("q1", "question", text="哪些岗位不适合？"),
    )
    recall = keyword_recall(analysis, ["远程办公", "效率", "不存在的词"])
    assert recall["matched"] == 2
    assert recall["missing"] == ["不存在的词"]
    assert missing_kinds(analysis, ["claim", "counter", "question"]) == ["counter"]


def test_graph_integrity_detects_bad_parent_duplicate_and_no_claim():
    analysis = make_analysis(
        node("c1", "claim"),
        node("c1", "evidence", parent="missing"),
        node("q1", "question", parent="q1"),
    )
    result = graph_integrity(analysis)
    assert result["ok"] is False
    assert "duplicate_ids" in result["problems"]
    assert "bad_parent:c1" in result["problems"]
    assert "self_parent:q1" in result["problems"]
    assert "no_claim" not in result["problems"]


def test_score_analysis_returns_all_checks():
    source = "远程办公提高了产出，但也增加了协作成本。"
    analysis = make_analysis(
        node("c1", "claim", quote="远程办公提高了产出", text="远程办公提高效率"),
        node("q1", "question", text="协作成本怎么算？"),
    )
    expected = EvalExpectation.from_dict(
        {
            "required_kinds": ["claim", "counter", "question"],
            "thesis_keywords": ["远程办公", "效率"],
            "expected_stance": "支持",
            "min_nodes": 1,
            "max_nodes": 10,
        }
    )
    score = score_analysis(analysis, source, expected)
    assert score["graph_ok"] is True
    assert score["node_count_ok"] is True
    assert score["kinds_ok"] is False
    assert score["missing_kinds"] == ["counter"]
    assert score["grounding_rate"] == 1.0
    assert score["keywords_rate"] == 1.0
    assert score["stance_ok"] is True


def test_frozen_eval_set_is_well_formed():
    path = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
    questions = json.loads(path.read_text(encoding="utf-8"))
    assert len(questions) == 10
    ids = [question["id"] for question in questions]
    assert len(ids) == len(set(ids))
    for question in questions:
        assert question["text"].strip()
        expected = EvalExpectation.from_dict(question)
        assert expected.required_kinds
        assert expected.thesis_keywords
        assert expected.min_nodes <= expected.max_nodes
