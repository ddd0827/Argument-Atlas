from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app.* 之前设置，避免测试碰真实数据库或真实模型。
TEST_ROOT = Path(tempfile.mkdtemp(prefix="argument-atlas-tests-"))
os.environ["ATLAS_MODE"] = "mock"
os.environ["ATLAS_DB"] = str(TEST_ROOT / "atlas-test.db")
os.environ["ATLAS_MIN_INPUT_CHARS"] = "30"
os.environ["ATLAS_MAX_INPUT_CHARS"] = "12000"


@pytest.fixture(autouse=True)
def clean_database():
    from app import db
    from app.config import DB_PATH

    db.init_db()
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM chats")
        connection.execute("DELETE FROM analyses")
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
