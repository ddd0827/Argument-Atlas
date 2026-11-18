from __future__ import annotations

import json

from app.examples import EXAMPLES


def parse_events(response):
    return [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]


def analyze(client, text: str = EXAMPLES[0]["text"]):
    response = client.post("/api/analyze", json={"text": text})
    assert response.status_code == 200, response.text
    events = parse_events(response)
    result = next(event for event in events if event["type"] == "result")
    return events, result


def test_health_reports_mock_mode(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True
    assert data["mode"] == "mock"
    assert data["provider"] == "mock"
    assert data["limits"] == {"min_chars": 30, "max_chars": 12000}


def test_examples_and_index(client):
    examples = client.get("/api/examples").json()["examples"]
    assert len(examples) == 3
    assert all(example["text"] for example in examples)

    index = client.get("/")
    assert index.status_code == 200
    assert "论点地图" in index.text


def test_short_input_is_rejected(client):
    response = client.post("/api/analyze", json={"text": "太短"})
    assert response.status_code == 400
    assert "至少需要" in response.json()["detail"]


def test_static_assets_have_javascript_mime(client):
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "text/javascript" in response.headers["content-type"]

    css = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "text/css" in css.headers["content-type"]


def test_analysis_challenge_persistence_and_delete(client):
    events, result = analyze(client)
    assert [event["type"] for event in events[:3]] == ["stage", "stage", "stage"]
    assert events[-1]["type"] == "result"

    analysis = result["analysis"]
    assert len(analysis["nodes"]) >= 5
    kinds = {node["kind"] for node in analysis["nodes"]}
    assert {"claim", "counter", "question"}.issubset(kinds)

    detail = client.get(f"/api/analyses/{result['id']}").json()
    assert detail["analysis"]["title"] == analysis["title"]
    assert detail["chats"] == {}

    claim = next(node for node in analysis["nodes"] if node["kind"] == "claim")

    missing_node = client.post(
        "/api/challenge",
        json={
            "analysis_id": result["id"],
            "node_id": "not-a-node",
            "message": "这条成立吗？",
            "history": [],
        },
    )
    assert missing_node.status_code == 404

    empty_message = client.post(
        "/api/challenge",
        json={
            "analysis_id": result["id"],
            "node_id": claim["id"],
            "message": "   ",
            "history": [],
        },
    )
    assert empty_message.status_code == 400

    challenge = client.post(
        "/api/challenge",
        json={
            "analysis_id": result["id"],
            "node_id": claim["id"],
            "message": "这个分论点最薄弱的环节是什么？",
            "history": [],
        },
    )
    assert challenge.status_code == 200
    challenge_events = parse_events(challenge)
    assert any(event["type"] == "meta" for event in challenge_events)
    assert any(event["type"] == "delta" for event in challenge_events)
    assert challenge_events[-1]["type"] == "done"

    detail = client.get(f"/api/analyses/{result['id']}").json()
    messages = detail["chats"][claim["id"]]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert len(messages[1]["content"]) > 50

    assert client.delete(f"/api/analyses/{result['id']}").status_code == 200
    assert client.get(f"/api/analyses/{result['id']}").status_code == 404


def test_challenge_rejects_unknown_analysis(client):
    response = client.post(
        "/api/challenge",
        json={
            "analysis_id": "missing",
            "node_id": "c1",
            "message": "你好？",
            "history": [],
        },
    )
    assert response.status_code == 404


def test_list_analyses_after_analysis(client):
    assert client.get("/api/analyses").json()["items"] == []
    _, result = analyze(client)
    items = client.get("/api/analyses").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == result["id"]
    assert items[0]["node_count"] == len(result["analysis"]["nodes"])
