from __future__ import annotations

import asyncio
import unittest

from app.llm import MockProvider
from app.models import Analysis, ArgumentNode
from app.service import sanitize_analysis


def make_analysis(*nodes: ArgumentNode) -> Analysis:
    return Analysis(
        title="测试",
        thesis="一个需要检验的主张",
        stance="混合",
        summary="摘要",
        nodes=list(nodes),
        verdict="总评",
    )


class SanitizeTests(unittest.TestCase):
    def test_duplicate_ids_are_made_unique(self) -> None:
        node = ArgumentNode(
            id="c1",
            kind="claim",
            text="论点",
            detail="说明",
            parent="thesis",
            strength=3,
            quote="",
        )
        clean = sanitize_analysis(make_analysis(node, node))
        ids = [item.id for item in clean.nodes]
        self.assertEqual(len(ids), len(set(ids)))

    def test_bad_parent_falls_back_to_thesis(self) -> None:
        node = ArgumentNode(
            id="e1",
            kind="evidence",
            text="证据",
            detail="说明",
            parent="missing",
            strength=3,
            quote="",
        )
        clean = sanitize_analysis(make_analysis(node))
        evidence = next(item for item in clean.nodes if item.id == "e1")
        self.assertEqual(evidence.parent, "thesis")

    def test_missing_claim_is_inserted(self) -> None:
        node = ArgumentNode(
            id="q1",
            kind="question",
            text="问题？",
            detail="说明",
            parent="thesis",
            strength=2,
            quote="",
        )
        clean = sanitize_analysis(make_analysis(node))
        self.assertTrue(any(item.kind == "claim" for item in clean.nodes))

    def test_reserved_thesis_id_is_renamed(self) -> None:
        node = ArgumentNode(
            id="thesis",
            kind="claim",
            text="冒充核心主张的节点",
            detail="说明",
            parent="thesis",
            strength=3,
            quote="",
        )
        clean = sanitize_analysis(make_analysis(node))
        self.assertNotIn("thesis", [item.id for item in clean.nodes])

    def test_mock_provider_builds_a_usable_map(self) -> None:
        text = (
            "远程办公一定会提高效率。有公司说产出提升了百分之二十。"
            "所以所有公司都应该立刻全面远程办公。"
        )
        analysis = asyncio.run(MockProvider().analyze(text))
        clean = sanitize_analysis(analysis)
        self.assertTrue(clean.nodes)
        self.assertTrue(any(node.kind == "claim" for node in clean.nodes))
        self.assertTrue(any(node.kind == "counter" for node in clean.nodes))


if __name__ == "__main__":
    unittest.main()
