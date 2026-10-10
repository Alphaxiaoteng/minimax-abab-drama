"""Plugin Debugger Studio 端到端测试: gateway.py 静态挂载 + GET / 根路由 + API 同进程可用.

钉住评委体验链路: 浏览器打开 / 即深色工作台, 工作台 JS/CSS 可达,
且 4 个技能经由同一 app 的 POST /tools/{name} 真实可调用 (Studio 与扣子同源)。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from coze_skills.gateway import STATIC_DIR, create_app, studio_available


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    assert payload["ok"] is True, payload.get("error")
    return payload["data"]


def test_studio_assets_ship_with_package() -> None:
    assert studio_available(), "static/index.html 与 static/app.js 必须随包存在"
    assert (STATIC_DIR / "studio.css").is_file()


def test_root_serves_dark_studio_page(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Plugin Debugger Studio" in body
    assert 'data-studio="plugin-debugger-studio"' in body
    assert "data-tab=\"compliance\"" in body and "data-tab=\"insight\"" in body


@pytest.mark.parametrize("name", ["app.js", "studio.css"])
def test_static_mount_serves_assets(client: TestClient, name: str) -> None:
    resp = client.get(f"/studio/{name}")
    assert resp.status_code == 200
    assert len(resp.content) > 500


def test_studio_page_links_point_to_mounted_paths(client: TestClient) -> None:
    body = client.get("/").text
    assert 'href="/studio/studio.css"' in body
    assert 'src="/studio/app.js"' in body


def test_core_api_remains_intact_under_gateway(client: TestClient) -> None:
    _ok(client.get("/healthz").json())
    doc = client.get("/openapi.coze.json").json()
    assert len(doc["paths"]) == 4
    data = _ok(client.post("/tools/check_compliance", json={"text": "全网第一，包治百病"}).json())
    assert data["risk_level"] == "high"
    insight = _ok(client.post(
        "/tools/analyze_reviews",
        json={"reviews": ["快递太慢包装破损", "客服不回态度差"], "marketplace": "tiktok"},
    ).json())
    assert insight["total"] == 2
    assert insight["themes"], "差评归因必须产出主题 (工作台进度条的数据源)"


def test_studio_ui_contains_four_skill_panels_and_key_widgets(client: TestClient) -> None:
    """页面骨架必须覆盖 4 个技能与需求点名的控件: 高亮下划线/风险徽章/改写对比/主题进度条."""
    html = client.get("/").text
    for marker in [
        "c-backdrop",        # 实时高危词高亮下划线层
        "c-risk-badge",      # 风险等级徽章
        "c-rewritten",       # 一键合规改写侧边对比
        "i-bars",            # 8 大主题占比进度条
        "i-quotes",          # 原文引用
        "i-actions",         # 中英文改进清单
        "b-results",         # 批量体检
        "r-draft",           # 英文回复草稿
    ]:
        assert marker in html, f"index.html 缺少控件 {marker}"
    css = (STATIC_DIR / "studio.css").read_text(encoding="utf-8")
    assert ".mk.sev-high" in css and "border-bottom" in css
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "/tools/" in app_js, "工作台必须走与扣子同源的 /tools/{name} 链路"
