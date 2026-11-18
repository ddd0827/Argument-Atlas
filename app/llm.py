from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import openai

from .config import API_KEY, BASE_URL, MODEL, has_credentials, resolve_mode
from .models import Analysis, ArgumentNode, ChallengeTarget
from .prompts import ANALYSIS_SYSTEM, build_challenge_system

log = logging.getLogger("atlas.llm")


class ProviderError(RuntimeError):
    """可以直接展示给用户的模型调用错误。"""


def _clip(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip("，。；、,;: ") + "…"


def _exact_quote(value: str, limit: int) -> str:
    """生成可回溯到原文的引用：只截取前缀，不添加省略号。"""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    return normalized[:limit].rstrip("，。；、,;: ")


def _loads_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 模型偶尔会在一个对象后面再补一段 JSON；取第一个可解析的对象。
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", text):
            try:
                value, _ = decoder.raw_decode(text[match.start() :])
                return value
            except json.JSONDecodeError:
                continue
        raise


_STANCES = {"支持", "反对", "混合", "不明确"}
_KINDS = {"claim", "evidence", "assumption", "counter", "question", "fallacy"}


def _normalize_payload(payload: Any) -> dict:
    """模型偶尔会少一个字段或多一点空白；先把形状收拢，再做严格校验。"""
    if not isinstance(payload, dict):
        return {}

    for key in ("title", "thesis", "stance", "summary", "verdict"):
        value = payload.get(key)
        payload[key] = value.strip() if isinstance(value, str) else ""

    if payload["stance"] not in _STANCES:
        payload["stance"] = "不明确"

    raw_nodes = payload.get("nodes")
    nodes = []
    for item in (raw_nodes if isinstance(raw_nodes, list) else [])[:24]:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in _KINDS:
            kind = "claim"
        try:
            strength = int(item.get("strength", 3))
        except (TypeError, ValueError):
            strength = 3
        nodes.append(
            {
                "id": str(item.get("id") or "").strip(),
                "kind": kind,
                "text": str(item.get("text") or "").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "parent": str(item.get("parent") or "thesis").strip() or "thesis",
                "strength": min(5, max(1, strength)),
                "quote": str(item.get("quote") or "").strip(),
            }
        )
    payload["nodes"] = nodes

    if not payload["title"]:
        payload["title"] = "未命名拆解"
    if not payload["thesis"]:
        payload["thesis"] = "（模型没有提取到明确主张）"
    return payload


def _friendly_api_error(exc: openai.APIError) -> ProviderError:
    if isinstance(exc, openai.AuthenticationError):
        return ProviderError("DeepSeek API Key 无效或已过期，请检查 .env 中的 DEEPSEEK_API_KEY。")
    if isinstance(exc, openai.RateLimitError):
        return ProviderError("请求过于频繁或账户余额不足，请稍后再试。")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("无法连接 DeepSeek 接口，请检查网络或 DEEPSEEK_BASE_URL。")
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        if status == 402:
            return ProviderError("DeepSeek 账户余额不足，请充值后重试。")
        if status == 400:
            return ProviderError("模型请求被拒绝：当前模型可能不支持 JSON 模式，请检查 ATLAS_MODEL。")
        if status >= 500:
            return ProviderError("DeepSeek 服务暂时不可用，请稍后重试。")
        return ProviderError(f"模型请求失败（HTTP {status}）。")
    return ProviderError("模型调用失败，请稍后重试。")


class DeepSeekProvider:
    """DeepSeek 的 OpenAI 兼容接口。换成其他兼容服务只需改 BASE_URL / ATLAS_MODEL。"""

    mode = "live"
    name = "deepseek"

    def __init__(self) -> None:
        if not API_KEY:
            raise ProviderError("缺少 DEEPSEEK_API_KEY，无法启用真实模型。")
        self.model = MODEL
        self.client = openai.AsyncOpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=150.0,
            max_retries=2,
        )

    async def analyze(self, text: str) -> Analysis:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                max_tokens=8192,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM},
                    {
                        "role": "user",
                        "content": f"请拆解下面这段文字：\n\n<article>\n{text}\n</article>",
                    },
                ],
            )
        except openai.APIError as exc:
            raise _friendly_api_error(exc) from exc

        if not response.choices:
            raise ProviderError("模型没有返回内容，请重试。")

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ProviderError("模型输出被截断，请重试一次，或缩短输入后再试。")
        if choice.finish_reason == "content_filter":
            raise ProviderError("模型基于内容安全策略未完成分析，请换一段文本。")

        try:
            payload = _normalize_payload(_loads_json(choice.message.content or ""))
            return Analysis.model_validate(payload)
        except (ValueError, TypeError) as exc:
            log.warning("DeepSeek returned unusable JSON: %s", exc)
            raise ProviderError("模型返回的结构不完整，请再试一次。") from exc

    async def challenge_stream(
        self,
        analysis: Analysis,
        target: ChallengeTarget,
        history: list[dict],
        message: str,
    ) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": build_challenge_system(analysis, target)},
            *history,
            {"role": "user", "content": message},
        ]
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                temperature=0.6,
                max_tokens=1200,
                stream=True,
                messages=messages,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except openai.APIError as exc:
            raise _friendly_api_error(exc) from exc


_ABSOLUTE = re.compile(r"必然|一定|所有|任何|永远|完全|唯一|注定|不惜一切|都会")


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[。！？!?；;])", text)
    result = [chunk.strip() for chunk in chunks if len(chunk.strip()) >= 6]
    return result or [text.strip()[:80] or "（空文本）"]


class MockProvider:
    """离线演示引擎：不联网也能完整体验交互，输出明确标注为演示内容。"""

    mode = "mock"
    name = "mock"
    model = "atlas-demo-v1"

    async def analyze(self, text: str) -> Analysis:
        await asyncio.sleep(0.55)
        sentences = _sentences(text)
        first = sentences[0]
        topic = re.sub(r"^(很多人说|有人认为|有人说|我认为|我们必须承认)[，,\s]*", "", first)
        topic = _clip(topic, 18).rstrip("，。！？；：… ")
        title = topic or "一段待检验的论证"
        thesis = _clip(first, 100)

        claim_sentences = sentences[1:4]
        if len(claim_sentences) < 2:
            clauses = [
                clause.strip()
                for clause in re.split(r"[，,]", first)
                if len(clause.strip()) >= 8
            ]
            claim_sentences = (claim_sentences + clauses)[:3]
        if not claim_sentences:
            claim_sentences = ["文中的判断需要更明确的限定条件"]

        nodes: list[ArgumentNode] = []
        claim_meta: list[tuple[str, str, str]] = []
        for index, sentence in enumerate(claim_sentences[:3], 1):
            claim_id = f"c{index}"
            claim_text = _clip(sentence, 44)
            nodes.append(
                ArgumentNode(
                    id=claim_id,
                    kind="claim",
                    text=claim_text,
                    detail="这是作者给出的一个分论点。它把结论往前推了一步，但成立与否取决于后面的支撑材料。",
                    parent="thesis",
                    strength=4 if index == 1 else 3,
                    quote=_exact_quote(sentence, 40),
                )
            )
            claim_meta.append((claim_id, claim_text, sentence))

        for index, (claim_id, claim_text, sentence) in enumerate(claim_meta[:2], 1):
            candidates = [
                candidate
                for candidate in sentences
                if _clip(candidate, 20) != _clip(claim_text, 20)
            ]
            quote = (
                _exact_quote(candidates[min(index - 1, len(candidates) - 1)], 40)
                if candidates
                else _exact_quote(sentence, 40)
            )
            nodes.append(
                ArgumentNode(
                    id=f"e{index}",
                    kind="evidence",
                    text=f"以「{_clip(quote, 18)}」为例",
                    detail="这是一条单点材料：它能说明方向，却没有交代样本范围、对照条件或反例；如果它是被挑选出来的例子，结论就会被高估。",
                    parent=claim_id,
                    strength=3,
                    quote=quote,
                )
            )

        for index, (claim_id, claim_text, _sentence) in enumerate(claim_meta[:2], 1):
            nodes.append(
                ArgumentNode(
                    id=f"a{index}",
                    kind="assumption",
                    text=f"默认「{_clip(claim_text, 16)}」普遍成立",
                    detail="论证需要这个前提，但文中没有为它提供理由。只要它只在特定条件下成立，分论点的适用范围就要缩小。",
                    parent=claim_id,
                    strength=2,
                    quote="",
                )
            )

        for index, (claim_id, claim_text, _sentence) in enumerate(claim_meta[:2], 1):
            nodes.append(
                ArgumentNode(
                    id=f"r{index}",
                    kind="counter",
                    text=f"「{_clip(claim_text, 16)}」可能只在特定条件下成立",
                    detail="把局部经验推广到所有情形，是这类论证最常见的跳跃。一个重要的反例场景就足以要求作者补充限定条件。",
                    parent=claim_id,
                    strength=4,
                    quote="",
                )
            )
        if len(claim_meta) < 2:
            nodes.append(
                ArgumentNode(
                    id="r2",
                    kind="counter",
                    text="结论可能由其他因素解释",
                    detail="文本把相关性当成了因果关系；成本、激励、样本选择等替代解释没有被排除。",
                    parent="thesis",
                    strength=4,
                    quote="",
                )
            )

        nodes.append(
            ArgumentNode(
                id="q1",
                kind="question",
                text="换一个样本或行业，这个结论还成立吗？",
                detail="用可迁移性检验结论的边界，是最便宜也最有效的反问。",
                parent="thesis",
                strength=3,
                quote="",
            )
        )
        nodes.append(
            ArgumentNode(
                id="q2",
                kind="question",
                text=f"「{_clip(thesis, 16)}」成立的最小前提是什么？",
                detail="把隐含前提说出来，才能判断论证究竟在什么范围内有效。",
                parent=claim_meta[-1][0] if claim_meta else "thesis",
                strength=3,
                quote="",
            )
        )

        absolute = _ABSOLUTE.search(text)
        if absolute:
            left = max(0, absolute.start() - 12)
            right = min(len(text), absolute.end() + 12)
            nodes.append(
                ArgumentNode(
                    id="f1",
                    kind="fallacy",
                    text=f"绝对化措辞：「{absolute.group(0)}」",
                    detail="这类措辞把一个有条件的判断说成了无条件的规律。只要存在一个反例，整句话就会被推翻；更稳妥的写法是补充条件和概率。",
                    parent="thesis",
                    strength=2,
                    quote=_exact_quote(text[left:right], 40),
                )
            )

        if re.search(r"然而|但是|当然|另一方面|也有人", text):
            stance = "混合"
        elif re.search(r"可能|也许|未必|难以|不确定", text):
            stance = "不明确"
        else:
            stance = "支持"

        return Analysis(
            title=title,
            thesis=thesis,
            stance=stance,
            summary=f"这段文字围绕「{_clip(topic, 14)}」提出主张，主要依靠经验性例子和未明说的前提推进。",
            nodes=nodes,
            verdict="论证方向清楚，但关键前提、反面证据和结论的适用边界都没有展开。",
        )

    async def challenge_stream(
        self,
        analysis: Analysis,
        target: ChallengeTarget,
        history: list[dict],
        message: str,
    ) -> AsyncIterator[str]:
        reply = _mock_reply(analysis, target, message)
        await asyncio.sleep(0.18)
        for index in range(0, len(reply), 4):
            yield reply[index : index + 4]
            await asyncio.sleep(0.012)


_OPENERS = {
    "thesis": "你直接顶到了整张地图的承重墙。核心主张越大，它需要承担的举证责任就越重。",
    "claim": "这个分论点看起来合理，但它目前更像一个结论，而不是一段完整的论证。",
    "evidence": "这条论据的问题不在于真假，而在于它能承载多少结论。",
    "assumption": "这是整条论证链里最值得停一下的地方：作者没有说出口的前提。",
    "counter": "反方观点本身也需要被检验，否则它只是把天平往另一边推。",
    "question": "这个问题问到了论证的边界；关键不在于作者有没有想过，而在于它会不会改变结论。",
    "fallacy": "这里的问题不是措辞激烈，而是推理形式本身滑了一步。",
}

_MIDDLE = {
    "thesis": "它需要说明在什么范围内成立、有哪些例外，否则读者无法判断它适用于哪些情形。",
    "claim": "它需要明确成立的条件，否则读者无法判断它适用于哪些情形。",
    "evidence": "它能说明一个点，却不能自动说明一个面。",
    "assumption": "这个前提一旦不成立，后面的结论就会失去支点。",
    "counter": "要让它真正有力，需要指出作者忽略了哪个具体机制。",
    "question": "一个关键问题应该能区分两种可能的世界。",
    "fallacy": "识别谬误之后，还要试着写出一个更严谨的版本。",
}

_CLOSERS = {
    "thesis": "一个更小、更可检验的主张，往往比一个宏大的断言更有说服力。",
    "claim": "把条件补上，比再加一个例子更能增强它。",
    "evidence": "至少需要一个反面案例或对照，才能知道这个例子有没有代表性。",
    "assumption": "最有效的补强，是直接为这个前提提供理由，或者把结论缩小到它成立的范围。",
    "counter": "否则它只是换了一个立场，而不是提高了论证质量。",
    "question": "好的追问不是让对方难堪，而是让结论变得更精确。",
    "fallacy": "否则指出谬误只是拆掉房子，没有给出可以住的地方。",
}


def _mock_reply(analysis: Analysis, target: ChallengeTarget, message: str) -> str:
    kind = target.kind if target.kind in _OPENERS else "claim"
    quote_line = f"原文的依据是：「{_clip(target.quote, 36)}」。" if target.quote else ""
    return (
        f"你问的是「{_clip(message, 40)}」。\n\n"
        f"{_OPENERS[kind]}以「{_clip(target.text, 30)}」为例，{_MIDDLE[kind]}{quote_line}\n\n"
        f"放回整张地图看，它和核心主张「{_clip(analysis.thesis, 26)}」之间还隔着一步推理。{_CLOSERS[kind]}\n\n"
        "如果你来改写这个节点，你会保留它的哪一部分、又删掉哪一部分？"
    )


_provider: DeepSeekProvider | MockProvider | None = None


def get_provider() -> DeepSeekProvider | MockProvider:
    global _provider
    if _provider is not None:
        return _provider

    mode = resolve_mode()
    if mode == "live":
        if not has_credentials():
            log.warning("ATLAS_MODE=live 但没有检测到 DEEPSEEK_API_KEY，回退到演示模式")
            mode = "mock"
        else:
            _provider = DeepSeekProvider()
            return _provider

    _provider = MockProvider()
    return _provider
