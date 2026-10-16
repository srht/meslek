import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.graph import load_graph
from app.llm_extract import GeminiError, GeminiExtractor

graph = load_graph()


def gemini_reply(skills: list[dict], status: int = 200):
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"skills": skills})}]}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(status, json=payload if status == 200 else {"error": "boom"})

    return handler


def make(handler) -> GeminiExtractor:
    return GeminiExtractor(graph, "test-key", model="gemini-test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parses_validates_and_dedupes():
    handler = gemini_reply([
        {"skill_id": "java", "level": 3, "years": 6, "evidence": "6 yıl Java"},
        {"skill_id": "java", "level": 1, "evidence": "tekrar"},
        {"skill_id": "erp_concepts", "level": 9, "evidence": "sipariş ve stok süreçleri"},
        {"skill_id": "uydurma_beceri", "level": 2, "evidence": "x"},
    ])
    found = {s.skill_id: s for s in make(handler).extract("CV")}
    assert set(found) == {"java", "erp_concepts"}
    assert found["java"].level == 3 and found["java"].years == 6
    assert found["erp_concepts"].level == 3  # 1-3 aralığına kırpılır
    assert all(s.source == "gemini" for s in found.values())

    req = handler.request
    assert req.headers["x-goog-api-key"] == "test-key"
    assert "models/gemini-test:generateContent" in str(req.url)
    body = json.loads(req.content)
    enum = body["generationConfig"]["responseSchema"]["properties"]["skills"]["items"]["properties"]["skill_id"]["enum"]
    assert set(enum) == set(graph.skills)


def test_http_error_raises():
    with pytest.raises(GeminiError):
        make(gemini_reply([], status=429)).extract("CV")


def test_bad_json_raises():
    def handler(request):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})

    with pytest.raises(GeminiError):
        make(handler).extract("CV")


def test_api_uses_gemini_and_falls_back(monkeypatch):
    client = TestClient(main.app)

    monkeypatch.setattr(main, "gemini", make(gemini_reply([{"skill_id": "apex", "level": 2, "evidence": "Apex"}])))
    res = client.post("/api/extract", json={"text": "Salesforce Apex"}).json()
    assert res["method"] == "gemini"
    assert [s["skill_id"] for s in res["skills"]] == ["apex"]

    monkeypatch.setattr(main, "gemini", make(gemini_reply([], status=500)))
    res = client.post("/api/extract", json={"text": "Java ve SQL"}).json()
    assert res["method"] == "sozluk" and res["note"]
    assert {s["skill_id"] for s in res["skills"]} >= {"java", "sql"}
