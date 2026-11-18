#!/usr/bin/env python
"""One-shot model smoke test. Never prints the API key.

    python scripts/smoke.py           # uses .env mode (auto/mock/live)
    python scripts/smoke.py --live    # force live and fail if no key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_FILE = ROOT / "eval" / "questions.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the configured LLM provider.")
    parser.add_argument("--live", action="store_true", help="force live mode (spends tokens)")
    return parser.parse_args()


async def run(force_live: bool) -> int:
    from app.llm import get_provider
    from app.service import sanitize_analysis

    if force_live:
        os.environ["ATLAS_MODE"] = "live"

    provider = get_provider()
    if force_live and provider.mode != "live":
        print("错误：--live 但没有可用的 DEEPSEEK_API_KEY。")
        return 1

    question = json.loads(EVAL_FILE.read_text(encoding="utf-8"))[0]
    started = time.perf_counter()
    analysis = await provider.analyze(question["text"])
    analysis = sanitize_analysis(analysis)
    elapsed = time.perf_counter() - started

    print(f"provider={provider.name}")
    print(f"mode={provider.mode}")
    print(f"model={provider.model}")
    print(f"latency={elapsed:.2f}s")
    print(f"title={analysis.title}")
    print(f"stance={analysis.stance}")
    print(f"nodes={len(analysis.nodes)}")
    print("kinds=" + ",".join(sorted({node.kind for node in analysis.nodes})))
    return 0


def main() -> int:
    args = parse_args()
    if not args.live:
        os.environ.setdefault("ATLAS_MODE", "auto")
    return asyncio.run(run(args.live))


if __name__ == "__main__":
    raise SystemExit(main())
