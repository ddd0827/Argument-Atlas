#!/usr/bin/env python
"""Freeze-set evaluation for Argument Atlas.

Default is offline Mock mode. Use --live to spend real model tokens.

    ATLAS_MODE=mock python scripts/eval.py
    python scripts/eval.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_FILE = ROOT / "eval" / "questions.json"
REPORT_FILE = ROOT / "docs" / "eval-report.md"
RAW_FILE = ROOT / "eval" / "last-run.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate argument extraction on a frozen set.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the real LLM API (spends tokens)")
    mode.add_argument("--mock", action="store_true", help="force the offline Mock provider (default)")
    parser.add_argument("--limit", type=int, default=0, help="only evaluate the first N questions")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="markdown report path")
    return parser.parse_args()


def load_questions(limit: int) -> list[dict[str, Any]]:
    questions = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    if limit > 0:
        questions = questions[:limit]
    return questions


def percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def yes_no(value: bool | None) -> str:
    if value is None:
        return "—"
    return "✓" if value else "✗"


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    ok_records = [record for record in records if record["ok"]]
    stance_records = [record for record in ok_records if record.get("stance_ok") is not None]
    grounded = sum(record["grounding_grounded"] for record in ok_records)
    quotes = sum(record["grounding_quotes"] for record in ok_records)
    latencies = [record["latency_s"] for record in ok_records]
    keyword_rates = [record["keywords_rate"] for record in ok_records]
    return {
        "total": len(records),
        "valid": len(ok_records),
        "graph_ok": sum(1 for record in ok_records if record["graph_ok"]),
        "stance_ok": sum(1 for record in stance_records if record["stance_ok"]),
        "stance_total": len(stance_records),
        "kinds_ok": sum(1 for record in ok_records if record["kinds_ok"]),
        "node_range_ok": sum(1 for record in ok_records if record["node_count_ok"]),
        "grounded": grounded,
        "quotes": quotes,
        "grounding_rate": (grounded / quotes) if quotes else None,
        "keyword_mean": statistics.fmean(keyword_rates) if keyword_rates else None,
        "median_latency": statistics.median(latencies) if latencies else None,
    }


def render_report(
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    provider_name: str,
    model: str,
    mode: str,
    limit: int,
) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    sample_note = f"{summary['total']} 条" + (f"（前 {limit} 条）" if limit else "（全量）")
    lines = [
        "# 论点地图 · 论证拆解评估报告",
        "",
        f"> 自动生成于 {now}",
        f"> provider：`{provider_name}`　mode：`{mode}`　model：`{model}`　样本：{sample_note}",
        "",
        "这份报告只检查**结构、可追溯性与主题覆盖**，不评价论证深度的好坏，也不代表真实业务效果。",
        "",
        "## 设置",
        "",
        "- 评估集：[`eval/questions.json`](../eval/questions.json)，运行前冻结；",
        "- 每题人工标注：必备节点类型、主题关键词、作者立场、节点数范围；",
        "- 引用落地：节点 `quote` 必须是原文的**精确连续片段**（忽略空白）；改写、省略号或编造都算失败；",
        "- 图结构：id 唯一、parent 可解析、无保留 id `thesis`、至少一个 `claim`；",
        "- 逐题表中「必备节点」列的「—」表示没有缺失；",
        "- 延迟：单次模型调用到结构化结果返回的墙钟时间，受网络与模型版本影响。",
        "",
        "## 总体结果",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        f"| 调用与结构校验成功 | {summary['valid']} / {summary['total']} |",
        f"| 图结构完整 | {summary['graph_ok']} / {summary['valid']} |",
        f"| 必备节点齐全 | {summary['kinds_ok']} / {summary['valid']} |",
        f"| 节点数在标注范围内 | {summary['node_range_ok']} / {summary['valid']} |",
    ]
    if summary["stance_total"]:
        lines.append(f"| 立场判断一致 | {summary['stance_ok']} / {summary['stance_total']} |")
    if summary["grounding_rate"] is not None:
        lines.append(
            f"| 原文引用落地率 | {summary['grounded']} / {summary['quotes']} "
            f"({percentage(summary['grounding_rate'])}) |"
        )
    else:
        lines.append("| 原文引用落地率 | 无引用可评 |")
    if summary["keyword_mean"] is not None:
        lines.append(f"| 主题关键词平均召回 | {percentage(summary['keyword_mean'])} |")
    if summary["median_latency"] is not None:
        lines.append(f"| 中位延迟 | {summary['median_latency']:.2f} s |")
    lines.extend(
        [
            "",
            "## 逐题结果",
            "",
            "| ID | 标题 | 结果 | 节点 | 立场 | 必备节点 | 引用落地 | 关键词召回 | 延迟 |",
            "| --- | --- | --- | ---: | :---: | :---: | ---: | ---: | ---: |",
        ]
    )
    for record in records:
        title = record["title"].replace("|", "\\|")
        if not record["ok"]:
            error = (record.get("error") or "unknown").replace("|", "\\|")[:80]
            lines.append(
                f"| {record['id']} | {title} | 失败：{error} | — | — | — | — | — | "
                f"{record['latency_s']:.2f} s |"
            )
            continue
        missing = "、".join(record["missing_kinds"]) or "—"
        grounding = (
            f"{record['grounding_grounded']}/{record['grounding_quotes']} "
            f"({percentage(record['grounding_rate'])})"
            if record["grounding_quotes"]
            else "无引用"
        )
        stance = f"{record['stance']} {yes_no(record['stance_ok'])}"
        lines.append(
            f"| {record['id']} | {title} | {yes_no(record['graph_ok'])} | "
            f"{record['node_count']} | {stance} | {missing} | {grounding} | "
            f"{percentage(record['keywords_rate'])} | {record['latency_s']:.2f} s |"
        )
    lines.extend(
        [
            "",
            "## 观察与局限",
            "",
            "- 样本只有 10 条自建示例，主题集中在观点评论，**不代表真实用户分布**；",
            "- 自动指标无法判断论证是否深刻、事实是否正确，只能检查结构、引用与关键词；",
            "- 引用落地采用严格字符串匹配，模型改写原文或加入省略号会被判失败；这能暴露“看似引用”的问题；",
            "- 立场是单标签人工标注，复杂文本可能同时包含支持与反对；",
            "- Mock 模式是规则引擎，数字只用于回归与离线演示，**不代表模型能力**；",
            "- 模型、prompt 或温度变化后应重新运行，并保留旧报告做对照。",
            "",
            "## 复现",
            "",
            "```bash",
            "# 离线、可复现（CI 使用这一条）",
            "ATLAS_MODE=mock python scripts/eval.py",
            "",
            "# 真实模型（需要 DEEPSEEK_API_KEY，会消耗 token）",
            "python scripts/eval.py --live",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    from app.evaluation import EvalExpectation, score_analysis
    from app.llm import get_provider
    from app.service import sanitize_analysis

    questions = load_questions(args.limit)
    provider = get_provider()

    if args.live and provider.mode != "live":
        print("错误：请求了 --live，但没有可用的 DeepSeek 凭证；未调用付费接口。")
        print("请在 .env 中配置 DEEPSEEK_API_KEY，或去掉 --live 使用离线 Mock。")
        return 1

    print(
        f"评估开始：{len(questions)} 题 | provider={provider.name} "
        f"mode={provider.mode} model={provider.model}"
    )
    if provider.mode == "live":
        print("提示：live 模式会真实消耗 token。")

    records: list[dict[str, Any]] = []
    for index, question in enumerate(questions, 1):
        expected = EvalExpectation.from_dict(question)
        started = time.perf_counter()
        try:
            analysis = await provider.analyze(question["text"])
            analysis = sanitize_analysis(analysis)
            score = score_analysis(analysis, question["text"], expected)
            record = {
                "id": question["id"],
                "title": question["title"],
                "ok": True,
                "error": None,
                **score,
            }
        except Exception as exc:  # 单题失败不终止整轮评估
            record = {
                "id": question["id"],
                "title": question["title"],
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "stance": None,
                "stance_ok": None,
                "graph_ok": None,
                "graph_problems": [],
                "kinds_ok": None,
                "missing_kinds": [],
                "node_count": 0,
                "node_count_ok": None,
                "keywords_rate": 0.0,
                "keywords_missing": [],
                "grounding_rate": 0.0,
                "grounding_grounded": 0,
                "grounding_quotes": 0,
            }
        record["latency_s"] = time.perf_counter() - started
        records.append(record)
        status = "OK" if record["ok"] else "FAIL"
        print(
            f"[{index:02d}/{len(questions):02d}] {question['id']} {status} "
            f"{record['latency_s']:.2f}s"
        )

    summary = summarize(records)
    report = render_report(
        records,
        summary,
        provider.name,
        provider.model,
        provider.mode,
        args.limit,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    RAW_FILE.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(
        f"完成：{summary['valid']}/{summary['total']} 成功 | "
        f"图结构 {summary['graph_ok']}/{summary['valid']} | "
        f"必备节点 {summary['kinds_ok']}/{summary['valid']}"
    )
    if summary["grounding_rate"] is not None:
        print(
            f"引用落地 {summary['grounded']}/{summary['quotes']} "
            f"({percentage(summary['grounding_rate'])})"
        )
    if summary["keyword_mean"] is not None:
        print(f"关键词平均召回 {percentage(summary['keyword_mean'])}")
    print(f"报告：{args.out}")
    return 0


def main() -> int:
    args = parse_args()
    os.environ["ATLAS_MODE"] = "live" if args.live else "mock"
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
