from starlette.testclient import TestClient
from service.api import app

client = TestClient(app)

def test_health():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

def test_config():
    res = client.get("/api/v1/config")
    assert res.status_code == 200
    assert "scenes" in res.json()

def test_scenes():
    res = client.get("/api/v1/scenes")
    assert res.status_code == 200
    assert len(res.json()["scenes"]) == 4

def test_demo_inspect():
    res = client.post("/api/v1/inspect/demo", json={"scene_id": "gear_surface"})
    assert res.status_code == 200
    data = res.json()
    assert "result" in data
    assert "decision" in data["result"]
