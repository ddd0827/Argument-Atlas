from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Analysis


def normalize_text(value: str) -> str:
    """评估用的宽松归一化：忽略空白，但不改写字符。"""
    return re.sub(r"\s+", "", value or "")


def quote_grounding(analysis: Analysis, source_text: str) -> dict[str, Any]:
    """原文引用是否真的落在原文里。没有引用时按 1.0 处理，并报告引用数。"""
    source_normalized = normalize_text(source_text)
    quotes = [node.quote.strip() for node in analysis.nodes if node.quote.strip()]
    grounded = [quote for quote in quotes if normalize_text(quote) in source_normalized]
    return {
        "rate": 1.0 if not quotes else len(grounded) / len(quotes),
        "grounded": len(grounded),
        "quotes": len(quotes),
    }


def keyword_recall(analysis: Analysis, keywords: list[str]) -> dict[str, Any]:
    """主题关键词是否出现在主张或节点文本中。"""
    haystack = normalize_text(
        " ".join(
            [analysis.thesis, analysis.summary, analysis.verdict]
            + [node.text for node in analysis.nodes]
        )
    )
    matched = [keyword for keyword in keywords if normalize_text(keyword) in haystack]
    missing = [keyword for keyword in keywords if keyword not in matched]
    return {
        "rate": 1.0 if not keywords else len(matched) / len(keywords),
        "matched": len(matched),
        "expected": len(keywords),
        "missing": missing,
    }


def graph_integrity(analysis: Analysis) -> dict[str, Any]:
    """检查节点图是否满足前端渲染所依赖的基本不变量。"""
    ids = [node.id for node in analysis.nodes]
    unique_ids = set(ids)
    problems: list[str] = []
    if len(ids) != len(unique_ids):
        problems.append("duplicate_ids")
    if "thesis" in unique_ids:
        problems.append("reserved_id")
    for node in analysis.nodes:
        if node.parent != "thesis" and node.parent not in unique_ids:
            problems.append(f"bad_parent:{node.id}")
        if node.parent == node.id:
            problems.append(f"self_parent:{node.id}")
    if not any(node.kind == "claim" for node in analysis.nodes):
        problems.append("no_claim")
    return {"ok": not problems, "problems": problems}


def missing_kinds(analysis: Analysis, required: list[str]) -> list[str]:
    present = {node.kind for node in analysis.nodes}
    return [kind for kind in required if kind not in present]


def stance_match(analysis: Analysis, expected: str | None) -> bool | None:
    if expected is None:
        return None
    return analysis.stance == expected


def node_count_in_range(analysis: Analysis, min_nodes: int, max_nodes: int) -> bool:
    return min_nodes <= len(analysis.nodes) <= max_nodes


@dataclass(frozen=True)
class EvalExpectation:
    required_kinds: tuple[str, ...]
    thesis_keywords: tuple[str, ...]
    expected_stance: str | None = None
    min_nodes: int = 4
    max_nodes: int = 16

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalExpectation:
        return cls(
            required_kinds=tuple(data.get("required_kinds", [])),
            thesis_keywords=tuple(data.get("thesis_keywords", [])),
            expected_stance=data.get("expected_stance"),
            min_nodes=int(data.get("min_nodes", 4)),
            max_nodes=int(data.get("max_nodes", 16)),
        )


def score_analysis(
    analysis: Analysis, source_text: str, expected: EvalExpectation
) -> dict[str, Any]:
    grounding = quote_grounding(analysis, source_text)
    keywords = keyword_recall(analysis, list(expected.thesis_keywords))
    integrity = graph_integrity(analysis)
    missing = missing_kinds(analysis, list(expected.required_kinds))
    return {
        "node_count": len(analysis.nodes),
        "node_count_ok": node_count_in_range(
            analysis, expected.min_nodes, expected.max_nodes
        ),
        "graph_ok": integrity["ok"],
        "graph_problems": integrity["problems"],
        "kinds_ok": not missing,
        "missing_kinds": missing,
        "keywords_rate": keywords["rate"],
        "keywords_missing": keywords["missing"],
        "grounding_rate": grounding["rate"],
        "grounding_grounded": grounding["grounded"],
        "grounding_quotes": grounding["quotes"],
        "stance": analysis.stance,
        "stance_ok": stance_match(analysis, expected.expected_stance),
    }
