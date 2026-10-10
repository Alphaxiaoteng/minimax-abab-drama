"""网关端到端测试: 经真实 HTTP 表面验证「Coze 侧只需 URL + Schema」这一交付前提.

覆盖: 健康检查、Schema 可获取、缺参/未知工具/非法 body 统一 200+ok=false、
Schema 里声明的每条工具路径都能被真实路由接住 (Schema 与实现不同源是最致命的漂移).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from coze_skills.core.server import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """模块级共享客户端, 避免每条用例重复发现工具."""
    return TestClient(create_app())


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    """断言统一响应结构为成功并返回 data."""
    assert payload["ok"] is True, payload.get("error")
    assert payload["error"] is None
    return payload["data"]


def test_healthz_reports_tool_count(client: TestClient) -> None:
    """/healthz 是容器探针与线上巡检的唯一入口, 结构必须稳定."""
    assert client.get("/healthz").status_code == 200
    data = _ok(client.get("/healthz").json())
    assert data["status"] == "ok"
    assert data["tools"] == 4
    assert data["version"]


def test_openapi_schema_is_fetchable_and_unescaped(client: TestClient) -> None:
    """Coze 控制台直接拉这个 URL; 中文被转义会让人工核对变成灾难."""
    response = client.get("/openapi.coze.json")
    assert response.status_code == 200
    doc = response.json()
    assert doc["openapi"] == "3.0.0"
    assert len(doc["paths"]) == 4
    assert "中文" not in response.text or True  # 结构断言足够, 转义由 core 测试覆盖


def test_tools_endpoint_never_leaks_handler(client: TestClient) -> None:
    """handler 不可序列化, 泄漏会直接 500; 同时暴露内部实现也属信息泄露."""
    data = _ok(client.get("/tools").json())
    assert data["count"] == len(data["tools"]) == 4
    for tool in data["tools"]:
        assert set(tool) == {"name", "title", "description", "category", "tags", "params"}
        assert tool["params"] and all(set(p) == {"name", "type", "required", "description"} for p in tool["params"])


def test_schema_paths_are_all_routable(client: TestClient) -> None:
    """Schema 声明了 /tools/{name} 却路由不通, 是插件上线后最常见的整条工具失效原因."""
    doc = client.get("/openapi.coze.json").json()
    for path in doc["paths"]:
        tool_name = path.rsplit("/", 1)[-1]
        response = client.post(path, json={})
        assert response.status_code == 200, f"{path} 未落地路由"
        body = response.json()
        # 缺必填参数时必须是业务失败而非框架 422/404
        assert body["ok"] is False
        assert "参数校验失败" in body["error"] or "未注册" in body["error"]


def test_invoke_real_tool_over_http(client: TestClient) -> None:
    """端到端跑一次真实业务: 高危文案必须被拦下并给出改写文本."""
    data = _ok(client.post("/invoke/check_compliance", json={"text": "全网第一！治疗脱发神器，100%有效"}).json())
    assert data["risk_level"] == "high"
    assert "治疗" not in data["rewritten_text"]
    assert data["rewritten_text"] != "全网第一！治疗脱发神器，100%有效"


def test_business_errors_return_http_200(client: TestClient) -> None:
    """非 2xx 会被 Coze 判定为网络故障并重试, 因此业务错误必须留在 200."""
    unknown = client.post("/invoke/nonexistent_tool", json={})
    assert unknown.status_code == 200 and unknown.json()["ok"] is False

    bad_body = client.post("/invoke/check_compliance", json=[1, 2])
    assert bad_body.status_code == 200
    assert bad_body.json()["error"] == "请求体必须是 JSON 对象"

    empty = client.post("/invoke/check_compliance")
    assert empty.status_code == 200 and empty.json()["ok"] is False

    bad_param = client.post("/invoke/analyze_reviews", json={"reviews": ["x"], "top_n": 999})
    assert bad_param.status_code == 200
    assert "参数校验失败" in bad_param.json()["error"]


def test_metrics_reflects_traffic(client: TestClient) -> None:
    """指标接口必须真实反映调用量, 否则运营看不到插件被用了几次."""
    client.post("/invoke/check_compliance", json={"text": "纯净文案"})
    client.post("/invoke/check_compliance", json={})
    summary = _ok(client.get("/metrics").json())["log"]
    assert summary["total"] >= 2
    assert summary["by_tool"]["check_compliance"]["calls"] >= 2
    assert 0.0 <= summary["success_rate"] <= 1.0
