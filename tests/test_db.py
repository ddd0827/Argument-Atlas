from __future__ import annotations

import sqlite3

from app import db
from app.config import DB_PATH
from app.models import Analysis, ArgumentNode


def make_analysis(title: str = "测试拆解") -> Analysis:
    return Analysis(
        title=title,
        thesis="一个需要检验的主张",
        stance="混合",
        summary="摘要",
        nodes=[
            ArgumentNode(
                id="c1",
                kind="claim",
                text="分论点",
                detail="说明",
                parent="thesis",
                strength=3,
                quote="",
            ),
            ArgumentNode(
                id="q1",
                kind="question",
                text="问题？",
                detail="说明",
                parent="c1",
                strength=2,
                quote="",
            ),
        ],
        verdict="总评",
    )


def test_save_get_list_and_delete():
    record = db.save_analysis(make_analysis(), "原文")
    assert len(record["id"]) > 0

    detail = db.get_analysis(record["id"])
    assert detail is not None
    assert detail["analysis"]["title"] == "测试拆解"
    assert detail["chats"] == {}

    items = db.list_analyses()
    assert [item["id"] for item in items] == [record["id"]]

    assert db.delete_analysis(record["id"]) is True
    assert db.get_analysis(record["id"]) is None
    assert db.delete_analysis(record["id"]) is False


def test_chat_pair_is_persisted_and_cascade_deleted():
    record = db.save_analysis(make_analysis("带追问"), "原文")
    db.save_chat_pair(record["id"], "c1", "问题？", "回答。")

    detail = db.get_analysis(record["id"])
    assert detail is not None
    assert detail["chats"]["c1"] == [
        {"role": "user", "content": "问题？"},
        {"role": "assistant", "content": "回答。"},
    ]

    db.delete_analysis(record["id"])
    with sqlite3.connect(DB_PATH) as connection:
        count = connection.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    assert count == 0


def test_init_db_is_idempotent():
    db.init_db()
    db.init_db()
    assert db.list_analyses() == []
