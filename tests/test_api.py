from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Meslek Köprüsü" in r.text


def test_extract_then_recommend():
    res = client.post("/api/extract", json={"text": "Java, PostgreSQL, REST API, Git"}).json()
    assert res["method"] == "sozluk"
    skills = res["skills"]
    assert {s["skill_id"] for s in skills} >= {"java", "sql", "rest_api", "git"}
    body = {"skills": [{"skill_id": s["skill_id"], "level": s["level"]} for s in skills]}
    data = client.post("/api/recommend", json=body).json()
    assert 1 <= len(data["recommendations"]) <= 5
    top = data["recommendations"][0]
    assert top["reasons"] and 0 <= top["score"] <= 1


def test_recommend_validates_level():
    r = client.post("/api/recommend", json={"skills": [{"skill_id": "java", "level": 7}]})
    assert r.status_code == 422


def test_graph_export():
    g = client.get("/api/graph").json()
    assert {e["type"] for e in g["edges"]} == {"REQUIRES", "RELATED_TO"}


def test_healthz():
    assert client.get("/healthz").json()["status"] == "ok"
