"""Coze Bot 演练场测试: 确定性意图路由 + 卡片契约 + Token 预估 + /bot HTTP 表面.

钉住的是「评委在浏览器里点下的那一下会发生什么」:
* 快问快答的每一句都必须命中预期的那个技能 (路由错位 = 演示当场翻车);
* 追问「换成 X 平台再查一遍」要继承上一轮业务对象, 只覆盖被点名的参数;
* 识别不出来时必须给一句人话澄清, 而不是硬调一个工具产出空结果;
* 卡片里那份 Coze 请求头**永远只有占位符**, 绝不落任何可用凭据。
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from coze_skills.core.bot import (
    QUICK_PROMPTS,
    BotError,
    coze_headers,
    estimate_tokens,
    extract_items,
    greet,
    manifest_tokens,
    route,
    run_turn,
    tool_schema,
)
from coze_skills.core.registry import ToolRegistry, build_default_registry
from coze_skills.core.runner import ToolRunner
from coze_skills.gateway import REQUEST_ID_HEADER, create_app


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return build_default_registry()


@pytest.fixture(scope="module")
def runner(registry) -> ToolRunner:
    return ToolRunner(registry)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ------------------------------------------------------------ 意图路由 ----
@pytest.mark.parametrize(
    "index,expected",
    [
        (0, "check_compliance"),
        (1, "batch_check"),
        (2, "analyze_reviews"),
        (3, "draft_reply"),
    ],
)
def test_quick_prompt_routes_to_its_own_tool(
    registry: ToolRegistry, index: int, expected: str
) -> None:
    """四个快问快答按钮各自命中四个不同技能 —— 一个都不许串台."""
    decision = route(QUICK_PROMPTS[index], registry)
    assert decision.tool == expected, (QUICK_PROMPTS[index], decision.tool, decision.signals)
    assert decision.score >= 1 and decision.signals


def test_quick_prompts_cover_every_registered_tool(registry: ToolRegistry) -> None:
    """注册表新增技能却忘了加快问快答, 演示面板就会少一个入口 —— 用集合等式钉死."""
    assert {route(p, registry).tool for p in QUICK_PROMPTS} == set(registry.names())


def test_route_fills_required_param_from_quoted_payload(registry: ToolRegistry) -> None:
    """引号内的原文才是业务对象, 提问的那半句不许混进参数里."""
    decision = route("帮我看看这条文案能不能发:「这款面膜全网销量第一, 药效显著」", registry)
    assert decision.tool == "check_compliance"
    text = decision.params["text"]
    assert text == "这款面膜全网销量第一, 药效显著"
    assert "能不能发" not in text


def test_route_maps_colloquial_platform_to_enum_value(registry: ToolRegistry) -> None:
    """用户说「淘宝」而 enum 里存的是 taobao —— 口语别名必须收敛成合法取值."""
    decision = route("这条小红书文案有没有极限词:「新中式缠花发簪, 手工绕线日常通勤也能戴」", registry)
    assert decision.params.get("platform") == "xhs"
    assert "platform" in decision.overrides


def test_route_inherits_payload_on_followup_and_overrides_only_named_param(
    registry: ToolRegistry,
) -> None:
    """多轮上下文: 「换成淘宝再查一遍」只改 platform, 业务文案沿用上一轮."""
    first = route(QUICK_PROMPTS[0], registry)
    context = {"tool": first.tool, "params": first.params}
    second = route("换成淘宝平台再查一遍", registry, context)
    assert second.tool == first.tool
    assert second.inherited is True
    assert second.params["text"] == first.params["text"]
    assert second.params["platform"] == "taobao"
    assert list(second.overrides) == ["platform"]


def test_route_asks_for_content_instead_of_calling_a_tool(registry: ToolRegistry) -> None:
    """意图明确但没给内容: 必须澄清, 绝不能拿空串去跑一次「0 命中」的假安全结论."""
    decision = route("帮我做一下合规检测", registry)
    assert decision.tool is None
    assert "没摘到要处理的内容" in (decision.rejected or "")


def test_route_rejects_greeting_without_context(registry: ToolRegistry) -> None:
    """无信号词又无上下文时不猜工具, 给出可操作的引导."""
    decision = route("你好呀", registry)
    assert decision.tool is None
    assert decision.rejected


def test_route_errors_on_empty_or_unknown_context(registry: ToolRegistry) -> None:
    """空输入与引用未注册工具的上下文都是调用方 bug, 必须显式报错而非静默兜底."""
    with pytest.raises(BotError):
        route("   ", registry)
    with pytest.raises(BotError):
        route("再查一遍", registry, {"tool": "no_such_tool", "params": {}})


def test_extract_items_prefers_quotes_then_lines_then_sentence() -> None:
    """载荷摘取的三级优先序: 引号 > 冒号后逐行 > 剥掉疑问前缀的整句."""
    assert extract_items("看这条:「全网最低价, 错过再等一年」") == ["全网最低价, 错过再等一年"]
    assert extract_items("这几条差评:\n快递太慢包装破损\n客服半天不回消息") == [
        "快递太慢包装破损",
        "客服半天不回消息",
    ]
    assert extract_items("这条新中式缠花发簪的文案到底有没有违规风险") == [
        "这条新中式缠花发簪的文案到底有没有违规风险"
    ]
    assert extract_items("这个能发吗？") == []


# ------------------------------------------------------------ Token 预估 ----
@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("中文", 2),
        ("abcd", 1),
        ("abcde", 2),
        ("中文abcd", 3),
    ],
)
def test_estimate_tokens_is_deterministic_and_documented(text: str, expected: int) -> None:
    """口径写进 UI 文案: CJK 1 token/字, 其余 4 字符/token —— 改口径必须同时改测试."""
    assert estimate_tokens(text) == expected
    assert estimate_tokens(text) == estimate_tokens(text)


def test_manifest_tokens_is_the_context_floor(registry: ToolRegistry) -> None:
    """系统提示里塞的是工具清单: 它必须是本轮总消耗的下界."""
    floor = manifest_tokens(registry)
    assert floor > 0
    card = run_turn(registry, ToolRunner(registry), QUICK_PROMPTS[0], None, request_id="r1")
    assert card["tokens"]["context"] == floor
    assert card["tokens"]["total"] >= floor + card["tokens"]["prompt"]


# ---------------------------------------------------------------- 卡片 ----
def test_run_turn_card_carries_every_collapsible_section(
    registry: ToolRegistry, runner: ToolRunner
) -> None:
    """卡片契约: 折叠面板要展示的 Schema / 请求头 / 耗时 / Token / 决策依据都得在场."""
    card = run_turn(registry, runner, QUICK_PROMPTS[2], None, request_id="req-42", process_ms=12.3456)
    assert card["ok"] is True and card["type"] == "call"
    assert card["tool"] == "analyze_reviews"
    assert card["request_id"] == "req-42"
    assert card["summary"] and card["chips"]
    assert card["schema"]["type"] == "object"
    assert card["schema"]["properties"]["reviews"]["type"] == "array"
    assert card["http"]["path"] == "/tools/analyze_reviews"
    assert card["timings"] == {"server_ms": 12.346}
    assert set(card["tokens"]) == {"context", "prompt", "tool_output", "completion", "total"}
    assert card["decision"]["signals"] and card["result"]["ok"] is True
    assert card["context"] == {"tool": "analyze_reviews", "params": card["params"]}


def test_run_turn_clarify_card_still_reports_tokens(registry: ToolRegistry, runner: ToolRunner) -> None:
    """澄清轮也要计费: 上下文与提问照样进模型, 不能因为「没调工具」就报 0 token."""
    card = run_turn(registry, runner, "你好呀", None, request_id="req-0")
    assert card["ok"] is False and card["type"] == "clarify"
    assert card["message"]
    assert card["tokens"]["prompt"] == estimate_tokens("你好呀")
    assert card["tokens"]["total"] == card["tokens"]["context"] + card["tokens"]["prompt"]
    assert card["decision"]["signals"] == []


def test_run_turn_survives_a_failing_tool_call(registry: ToolRegistry, runner: ToolRunner) -> None:
    """客户端回传的 context 不可信: 被篡改的 top_n=999 照样被同一条校验链路拦下, 卡片如实说明而非抛异常."""
    card = run_turn(
        registry,
        runner,
        "换个平台再查一遍",
        {"tool": "analyze_reviews", "params": {"reviews": ["快递太慢包装破损"], "top_n": 999}},
        request_id="req-bad",
    )
    assert card["type"] == "call" and card["decision"]["inherited"] is True
    assert card["ok"] is False
    assert "没有跑通" in card["summary"]
    assert card["result"]["ok"] is False and card["result"]["error"]


def test_tool_schema_matches_openapi_operation(registry: ToolRegistry) -> None:
    """折叠面板里那份 Schema 必须与 /openapi.coze.json 同源, 否则「照着调」会失败."""
    doc = json.loads(TestClient(create_app(registry)).get("/openapi.coze.json").content)
    schema = tool_schema(registry, "draft_reply")
    assert schema == doc["paths"]["/tools/draft_reply"]["post"]["requestBody"]["content"]["application/json"]["schema"]


# -------------------------------------------------------------- 请求头 ----
def test_coze_headers_only_ever_show_a_placeholder() -> None:
    """凭据边界: 演练场展示的 Authorization 只能是 ${COZE_PLUGIN_TOKEN} 占位符."""
    http = coze_headers(request_id="r9", tool="check_compliance", body_length=42)
    headers: Dict[str, str] = http["headers"]
    assert headers["Authorization"] == "Bearer ${COZE_PLUGIN_TOKEN}"
    assert headers["Content-Length"] == "42"
    assert "${" in json.dumps(http)
    for value in headers.values():
        assert not value.startswith("Bearer ") or value.endswith("${COZE_PLUGIN_TOKEN}")


# ---------------------------------------------------------------- HTTP ----
def test_bot_greet_endpoint_lists_skills(client: TestClient) -> None:
    payload = client.get("/bot/greet").json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["type"] == "greet"
    assert len(data["quick_prompts"]) == len(QUICK_PROMPTS)
    assert data["tokens"]["total"] == data["tokens"]["context"]


def test_bot_chat_echoes_the_same_request_id_in_card_and_header(client: TestClient) -> None:
    """瀑布图与扣子侧日志靠同一个 id 对齐 —— 卡片里的 id 必须与响应头逐字相同."""
    resp = client.post(
        "/bot/chat",
        json={"message": QUICK_PROMPTS[0]},
        headers={REQUEST_ID_HEADER: "studio-abc123"},
    )
    assert resp.status_code == 200
    assert resp.headers[REQUEST_ID_HEADER] == "studio-abc123"
    assert resp.json()["data"]["request_id"] == "studio-abc123"


def test_bot_chat_generates_request_id_when_client_sends_none(client: TestClient) -> None:
    resp = client.post("/bot/chat", json={"message": QUICK_PROMPTS[3]})
    echoed = resp.headers[REQUEST_ID_HEADER]
    assert echoed and resp.json()["data"]["request_id"] == echoed


def test_bot_chat_keeps_the_envelope_on_garbage_bodies(client: TestClient) -> None:
    """评委手滑贴进非 JSON 也不能 500: 一律收敛成 200 + 澄清卡片."""
    for body in (b"not json at all", b"[1,2,3]", b"{}"):
        resp = client.post("/bot/chat", content=body, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200, body
        payload = resp.json()
        assert payload["ok"] is False
        assert payload["data"]["type"] == "clarify"


def test_bot_chat_reuses_context_sent_by_the_client(client: TestClient) -> None:
    """多轮: 前端把上一轮 context 回传, 服务端据此只改点名参数, 不重新索要文案."""
    first: Dict[str, Any] = client.post("/bot/chat", json={"message": QUICK_PROMPTS[0]}).json()["data"]
    second: Dict[str, Any] = client.post(
        "/bot/chat", json={"message": "换成抖音平台再看一遍", "context": first["context"]}
    ).json()["data"]
    assert second["decision"]["inherited"] is True
    assert second["params"]["text"] == first["params"]["text"]
    assert second["params"]["platform"] == "douyin"


def test_greet_mentions_deterministic_stand_in(registry: ToolRegistry) -> None:
    """诚实声明: 开场白必须说清「大模型那一跳由确定性路由替身完成」, 不冒充线上模型."""
    card = greet(registry)
    assert "确定性意图路由" in card["message"]
    assert card["quick_prompts"] == list(QUICK_PROMPTS)
    assert card["tokens"]["total"] == manifest_tokens(registry)
