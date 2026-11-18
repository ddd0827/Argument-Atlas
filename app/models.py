from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

NodeKind = Literal["claim", "evidence", "assumption", "counter", "question", "fallacy"]
Stance = Literal["支持", "反对", "混合", "不明确"]


class ArgumentNode(BaseModel):
    id: str = Field(description="短标识，例如 c1、e1、a1；全图唯一")
    kind: NodeKind = Field(description="节点类型")
    text: str = Field(description="节点的一句话内容，不超过 40 字")
    detail: str = Field(description="1-3 句话的展开说明")
    parent: str = Field(description="父节点 id；直接挂在核心主张下时使用 thesis")
    strength: int = Field(ge=1, le=5, description="该节点的论证强度，1 弱 - 5 强")
    quote: str = Field(description="来自原文的连续片段，最多 40 字；没有则为空字符串")


class Analysis(BaseModel):
    title: str = Field(description="这段文字的主题标题，不超过 20 字")
    thesis: str = Field(description="作者的核心主张，用一句话概括")
    stance: Stance = Field(description="作者对核心主张的立场")
    summary: str = Field(description="一两句话概括文本的论证方式")
    nodes: list[ArgumentNode] = Field(description="4-14 个论证节点，不含核心主张本身")
    verdict: str = Field(description="一句话总评，指出论证最关键的问题或优点")


class ChallengeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


@dataclass(frozen=True)
class ChallengeTarget:
    """当前被追问的对象。thesis 是一个虚拟节点，不在 nodes 里。"""

    id: str
    kind: str
    text: str
    detail: str
    quote: str = ""
    strength: int = 0
