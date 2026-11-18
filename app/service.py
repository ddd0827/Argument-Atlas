from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from . import db
from .config import MAX_INPUT_CHARS, MIN_INPUT_CHARS
from .llm import ProviderError, get_provider
from .models import Analysis, ArgumentNode, ChallengeTarget

log = logging.getLogger("atlas.service")


class InputError(ValueError):
    """用户输入不合法。"""


def _clip(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip("，。；、,;: ") + "…"


def validate_input(text: str) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) < MIN_INPUT_CHARS:
        raise InputError(f"文本太短了，至少需要 {MIN_INPUT_CHARS} 个字符。")
    if len(cleaned) > MAX_INPUT_CHARS:
        raise InputError(f"文本太长了，请控制在 {MAX_INPUT_CHARS} 个字符以内。")
    return cleaned


def sanitize_analysis(analysis: Analysis) -> Analysis:
    """把模型输出收拾成前端可以放心渲染的形状。"""
    nodes: list[ArgumentNode] = []
    used_ids: set[str] = set()

    for index, node in enumerate(analysis.nodes[:24]):
        raw_id = re.sub(r"[^A-Za-z0-9_-]", "", node.id or "")[:24] or f"n{index + 1}"
        if raw_id == "thesis":
            raw_id = f"n{index + 1}"
        node_id = raw_id
        suffix = 2
        while node_id in used_ids:
            node_id = f"{raw_id}-{suffix}"
            suffix += 1
        used_ids.add(node_id)
        nodes.append(
            node.model_copy(
                update={
                    "id": node_id,
                    "text": (node.text.strip() or "未命名节点")[:80],
                    "detail": node.detail.strip()[:600],
                    "strength": min(5, max(1, int(node.strength))),
                    "quote": node.quote.strip()[:160],
                }
            )
        )

    ids = {node.id for node in nodes}
    nodes = [
        node.model_copy(
            update={
                "parent": (
                    node.parent
                    if node.parent == "thesis" or (node.parent in ids and node.parent != node.id)
                    else "thesis"
                )
            }
        )
        for node in nodes
    ]

    if not any(node.kind == "claim" for node in nodes):
        nodes.insert(
            0,
            ArgumentNode(
                id="c1",
                kind="claim",
                text=_clip(analysis.thesis, 44) or "待检验的核心主张",
                detail="由核心主张整理出的可检验分论点。",
                parent="thesis",
                strength=3,
                quote="",
            ),
        )

    return analysis.model_copy(
        update={
            "title": _clip(analysis.title, 48) or "未命名拆解",
            "thesis": _clip(analysis.thesis, 400) or "（未提取到明确主张）",
            "summary": _clip(analysis.summary, 600),
            "verdict": _clip(analysis.verdict, 400),
            "nodes": nodes,
        }
    )


async def stream_analysis(text: str) -> AsyncIterator[dict]:
    try:
        text = validate_input(text)
    except InputError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    provider = get_provider()
    yield {
        "type": "stage",
        "stage": "reading",
        "message": "正在通读全文，定位作者的核心主张",
    }
    if provider.mode == "mock":
        await asyncio.sleep(0.35)

    yield {
        "type": "stage",
        "stage": "mapping",
        "message": "正在拆解论据、隐含假设与反方观点",
    }
    try:
        analysis = await provider.analyze(text)
    except ProviderError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    except Exception:
        log.exception("analysis call failed")
        yield {"type": "error", "message": "分析失败，请稍后重试。"}
        return

    yield {
        "type": "stage",
        "stage": "weaving",
        "message": "正在编织论证地图",
    }
    if provider.mode == "mock":
        await asyncio.sleep(0.35)

    analysis = sanitize_analysis(analysis)
    try:
        record = db.save_analysis(analysis, text)
    except Exception:
        log.exception("failed to save analysis")
        yield {"type": "error", "message": "分析结果保存失败，请检查数据库权限。"}
        return

    yield {
        "type": "result",
        "id": record["id"],
        "created_at": record["created_at"],
        "provider": provider.name,
        "model": provider.model,
        "mode": provider.mode,
        "analysis": analysis.model_dump(),
    }


def _clean_history(history: list[dict] | None) -> list[dict]:
    cleaned: list[dict] = []
    for item in (history or [])[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content[:4000]})
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


async def stream_challenge(
    analysis_id: str,
    node_id: str,
    history: list[dict] | None,
    message: str,
) -> AsyncIterator[dict]:
    message = (message or "").strip()
    if not message:
        yield {"type": "error", "message": "先写下一个问题吧。"}
        return
    if len(message) > 2000:
        yield {"type": "error", "message": "问题太长了，请控制在 2000 字以内。"}
        return

    record = db.get_analysis(analysis_id)
    if record is None:
        yield {"type": "error", "message": "找不到这次拆解，请重新分析。"}
        return

    analysis = Analysis.model_validate(record["analysis"])
    if node_id == "thesis":
        target = ChallengeTarget(
            id="thesis",
            kind="thesis",
            text=analysis.thesis,
            detail=analysis.summary,
            quote="",
            strength=0,
        )
    else:
        node = next((item for item in analysis.nodes if item.id == node_id), None)
        if node is None:
            yield {"type": "error", "message": "找不到这个节点。"}
            return
        target = ChallengeTarget(
            id=node.id,
            kind=node.kind,
            text=node.text,
            detail=node.detail,
            quote=node.quote,
            strength=node.strength,
        )

    provider = get_provider()
    yield {
        "type": "meta",
        "node_id": target.id,
        "provider": provider.name,
        "mode": provider.mode,
    }

    pieces: list[str] = []
    try:
        async for piece in provider.challenge_stream(
            analysis, target, _clean_history(history), message
        ):
            pieces.append(piece)
            yield {"type": "delta", "text": piece}
    except ProviderError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    except Exception:
        log.exception("challenge call failed")
        yield {"type": "error", "message": "追问失败，请稍后重试。"}
        return

    answer = "".join(pieces).strip()
    if answer:
        try:
            db.save_chat_pair(analysis_id, target.id, message, answer)
        except Exception:
            log.exception("failed to save chat")
    yield {"type": "done"}
