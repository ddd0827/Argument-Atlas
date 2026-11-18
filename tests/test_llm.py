from __future__ import annotations

import asyncio
import json

import pytest

from app.evaluation import normalize_text
from app.llm import MockProvider, _loads_json
from app.models import ChallengeTarget
from app.prompts import build_challenge_system
from app.service import _clean_history

TEXT = (
    "远程办公一定会提高效率。有研究显示，某公司员工在家办公后产出提高了百分之二十。"
    "因此所有公司都应该立刻全面远程办公。"
)


def test_loads_json_accepts_fenced_surrounded_and_duplicated_objects():
    assert _loads_json('{"a": 1}') == {"a": 1}
    assert _loads_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _loads_json('prefix {"a": 1} suffix') == {"a": 1}
    assert _loads_json('{"a": 1}\n{"b": 2}') == {"a": 1}
    with pytest.raises(json.JSONDecodeError):
        _loads_json("not json")


def test_mock_provider_quotes_are_grounded_and_graph_is_usable():
    provider = MockProvider()
    analysis = asyncio.run(provider.analyze(TEXT))

    assert any(node.kind == "claim" for node in analysis.nodes)
    assert any(node.kind == "counter" for node in analysis.nodes)
    assert any(node.kind == "question" for node in analysis.nodes)

    source = normalize_text(TEXT)
    quotes = [node.quote for node in analysis.nodes if node.quote]
    assert quotes
    for quote in quotes:
        assert normalize_text(quote) in source


def test_mock_challenge_stream_and_prompt_context():
    provider = MockProvider()
    analysis = asyncio.run(provider.analyze(TEXT))
    claim = next(node for node in analysis.nodes if node.kind == "claim")
    target = ChallengeTarget(
        id=claim.id,
        kind=claim.kind,
        text=claim.text,
        detail=claim.detail,
        quote=claim.quote,
        strength=claim.strength,
    )

    async def collect() -> str:
        pieces = []
        async for piece in provider.challenge_stream(analysis, target, [], "这条成立吗？"):
            pieces.append(piece)
        return "".join(pieces)

    reply = asyncio.run(collect())
    assert "如果你来改写" in reply
    assert reply.strip().endswith("？")

    system = build_challenge_system(analysis, target)
    assert analysis.thesis in system
    assert target.text in system


def test_clean_history_drops_invalid_and_leading_assistant():
    history = [
        {"role": "assistant", "content": "孤立回答"},
        "not-a-dict",
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
        {"role": "user", "content": "   "},
    ]
    assert _clean_history(history) == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
    ]
