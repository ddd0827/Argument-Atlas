from __future__ import annotations

import unittest

from app.llm import _normalize_payload


class NormalizePayloadTests(unittest.TestCase):
    def test_coerces_invalid_fields_and_enums(self) -> None:
        payload = {
            "title": "   ",
            "thesis": "  一个主张  ",
            "stance": "赞同",
            "summary": 3,
            "verdict": None,
            "nodes": [
                {
                    "id": 1,
                    "kind": "reason",
                    "text": "  节点  ",
                    "detail": None,
                    "parent": None,
                    "strength": "5",
                    "quote": None,
                }
            ],
        }
        clean = _normalize_payload(payload)
        self.assertEqual(clean["title"], "未命名拆解")
        self.assertEqual(clean["thesis"], "一个主张")
        self.assertEqual(clean["stance"], "不明确")
        self.assertEqual(clean["summary"], "")
        self.assertEqual(clean["verdict"], "")
        self.assertEqual(clean["nodes"][0]["id"], "1")
        self.assertEqual(clean["nodes"][0]["kind"], "claim")
        self.assertEqual(clean["nodes"][0]["parent"], "thesis")
        self.assertEqual(clean["nodes"][0]["strength"], 5)
        self.assertEqual(clean["nodes"][0]["quote"], "")

    def test_clamps_strength_and_drops_non_objects(self) -> None:
        clean = _normalize_payload(
            {
                "title": "标题",
                "thesis": "主张",
                "stance": "支持",
                "summary": "",
                "verdict": "",
                "nodes": [
                    {"kind": "evidence", "strength": 99, "id": "e1", "text": "x", "detail": "", "parent": "c1", "quote": ""},
                    "not-a-node",
                ],
            }
        )
        self.assertEqual(len(clean["nodes"]), 1)
        self.assertEqual(clean["nodes"][0]["strength"], 5)

    def test_non_dict_payload_is_empty(self) -> None:
        self.assertEqual(_normalize_payload(["not", "a", "dict"]), {})


if __name__ == "__main__":
    unittest.main()
