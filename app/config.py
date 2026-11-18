from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_dotenv() -> None:
    """极简 .env 读取器，避免为一个小项目额外引入依赖。"""
    path = BASE_DIR / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("ATLAS_MODEL", "deepseek-flash")
MIN_INPUT_CHARS = int(os.getenv("ATLAS_MIN_INPUT_CHARS", "30"))
MAX_INPUT_CHARS = int(os.getenv("ATLAS_MAX_INPUT_CHARS", "12000"))
APP_VERSION = "0.1.0"

_db_setting = os.getenv("ATLAS_DB", "atlas.db")
DB_PATH = Path(_db_setting)
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH


def has_credentials() -> bool:
    """当前进程是否能拿到 DeepSeek 凭证。

    每次读取环境变量，便于测试用 monkeypatch 切换；.env 已在导入时写入环境。
    """
    return bool(os.getenv("DEEPSEEK_API_KEY"))


def resolve_mode() -> str:
    """auto 模式：有凭证就用真实模型，否则用演示引擎。"""
    explicit = os.getenv("ATLAS_MODE", "auto").strip().lower()
    if explicit in {"mock", "live"}:
        return explicit
    return "live" if has_credentials() else "mock"
