"""Plugin Debugger Studio 端到端测试: gateway.py 静态挂载 + GET / 根路由 + API 同进程可用.

钉住评委体验链路: 浏览器打开 / 即深色工作台, 工作台 JS/CSS 可达,
且 4 个技能经由同一 app 的 POST /tools/{name} 真实可调用 (Studio 与扣子同源)。
"""

from __future__ import annotations

import re
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from coze_skills.gateway import STATIC_DIR, create_app, studio_available
from coze_skills.tools.review_insight import THEME_KEYWORDS


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


# ------------------------------------------------- 浏览器实测发现的缺陷回归 ----
# 以下四条来自真实 Chromium 逐项点检, 都是「评委肉眼可见」的失败模式;
# CI 里没有浏览器, 因此对前端行为做源码级钉桩, 对数据源做行为级断言。

#: 与 index.html 中 #i-demo 按钮填入的示例保持同一份文案
DEMO_REVIEWS = [
    "快递太慢了，等了整整一周才到，到手盒子都压烂了",
    "鞋子偏小两码根本穿不进去，申请退款客服半天不回",
    "The stitching came apart after one wash, very poor quality",
    "和图片完全不符，颜色差太多了",
    "味道刺鼻，放在阳台晾了三天还是有气味",
    "这个价格太贵了，不值这个钱",
    "发货三天没动静，催了才说没库存",
    "做工粗糙，线头到处都是",
]


def test_insight_bars_do_not_depend_on_animation_frame() -> None:
    """后台标签页会节流 requestAnimationFrame, 依赖它写宽度会让进度条停在 0%."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "requestAnimationFrame" not in app_js
    assert "void bars.offsetHeight" in app_js, "必须强制回流后再同步写 .fill 宽度"


def test_insight_panel_always_renders_all_eight_themes() -> None:
    """面板标题承诺「8 大主题占比」: 未命中的主题也要补 0% 灰条, 不能只画命中的."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const THEME_ORDER = \[(.*?)\];", app_js, re.S)
    assert match, "app.js 缺少 THEME_ORDER 常量"
    names = [item.strip().strip('"') for item in match.group(1).split(",")]
    assert len(names) == 8 and len(set(names)) == 8
    assert set(names) == set(THEME_KEYWORDS), "工作台主题序必须与工具词表一一对应"


def test_compare_pane_keeps_text_after_the_last_hit() -> None:
    """原文对比必须拼上最后一次命中之后的尾巴, 否则评委看到的是半句话."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "orig.innerHTML = html + esc(text.slice(pos))" in app_js


def test_studio_demo_sample_reads_as_negative_reviews(client: TestClient) -> None:
    """示例清一色是差评: 负面占比低于 3/4 说明情绪词表覆盖不足, 面板结论即失真."""
    data = _ok(client.post(
        "/tools/analyze_reviews",
        json={"reviews": DEMO_REVIEWS, "marketplace": "amazon", "top_n": 8},
    ).json())
    assert data["total"] == len(DEMO_REVIEWS)
    assert data["negative_ratio"] >= 0.75, data["negative_ratio"]
    assert len(data["themes"]) < len(THEME_KEYWORDS), "示例应留出未命中主题, 以验证 0% 灰条链路"


# ------------------------------------------- 第二阶段: 演练场 / 沙箱 / 导出 ----
#: 三个新面板的骨架控件 id —— 前端 JS 按这些 id 找节点, 缺一个就是白屏
NEW_PANEL_WIDGETS = [
    "panel-bot", "bot-log", "bot-quicks", "bot-input", "bot-send", "bot-reset", "bot-ctx",
    "panel-chaos", "th-run", "th-log", "to-abort", "to-degrade", "bat-run", "bat-log",
    "panel-schema", "audit-list", "audit-badge", "ex-format", "ex-download", "ex-preview",
]


def test_three_new_panels_are_mounted_as_tabs(client: TestClient) -> None:
    """评委点开的就是这三个 tab: 面板、tab 按钮、控件 id 三者必须同时对上."""
    html = client.get("/").text
    for tab in ("bot", "chaos", "schema"):
        assert f'data-tab="{tab}"' in html, f"缺少 {tab} 标签页"
        assert f'id="panel-{tab}"' in html, f"缺少 panel-{tab} 面板"
    for marker in NEW_PANEL_WIDGETS:
        assert marker in html, f"index.html 缺少控件 {marker}"


def test_studio_scripts_call_the_new_surfaces() -> None:
    """前端只走真实端点, 不在浏览器里另写一套假逻辑."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for endpoint in ("/bot/greet", "/bot/chat", "/sim/cases", "/sim/throttle", "/sim/timeout", "/audit", "/export/openapi"):
        assert endpoint in app_js, f"app.js 未接入 {endpoint}"
    assert "AbortController" in app_js, "504 演示必须由客户端真正掐断连接"
    assert "Retry-After" in app_js, "429 退避必须读服务端的 Retry-After, 而不是前端猜一个数"
    assert "X-Process-Ms" in app_js, "瀑布图的网关段来自服务端回传, 客户端量不到"


def test_studio_never_renders_unescaped_model_output() -> None:
    """工具返回与用户输入都要过 esc(): 差评原文里带 <script> 是真实场景, 不是假设."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function esc(" in app_js or "const esc = " in app_js
    assert app_js.count("esc(") > 30, "渲染路径上几乎每处插值都该过 esc"
    assert "innerHTML = card" not in app_js, "卡片正文不许绕过 esc 直接塞进 DOM"


def test_fault_battery_is_rendered_from_the_backend(client: TestClient) -> None:
    """畸形入参用例只在 Python 里声明一次: 前端拿 /sim/cases, 不许另抄一份."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "必填参数缺失" not in app_js, "用例文案泄漏到前端 = 双份事实来源"
    cases = _ok(client.get("/sim/cases").json())
    assert cases["count"] == 10
    for row in cases["cases"]:
        assert row["expect"] and row["advice"] and row["body"]
