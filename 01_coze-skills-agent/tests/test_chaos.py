"""容灾沙箱测试: 畸形入参电池 + 429 限流 + 504 超时降级 + 链路追踪头.

这一层证明的是「恶劣环境下依然诚实」:
* 每一条畸形入参都打到**真实** ``POST /tools/{name}``, 由线上同一条校验链路拦截,
  因此 Studio 里的红字诊断不是演示专用代码, 而 `expect` 子串把这份诊断钉成契约;
* 全程 HTTP 200 + ok=false, 零 5xx、零堆栈外泄 —— 否则扣子会当成网络故障自动重试;
* 限流/超时两个仿真端点**无隐藏状态**, 结果完全由入参决定, 评委反复点也能复现。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from coze_skills.core.chaos import (
    DEFAULT_CLIENT_BUDGET_MS,
    FAULT_CASES,
    SIM_TIMEOUT_MAX_MS,
    THROTTLE_DEFAULT_REJECTIONS,
    THROTTLE_RETRY_AFTER_SECONDS,
    FaultCase,
    cases_payload,
)
from coze_skills.core.registry import build_default_registry
from coze_skills.gateway import PROCESS_MS_HEADER, REQUEST_ID_HEADER, create_app

#: 电池里唯一的「工具不存在」用例, 它命中的是注册表查找而不是参数校验
UNKNOWN_TOOL_CASE = "unknown-tool"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _case(code: str) -> FaultCase:
    return next(case for case in FAULT_CASES if case.code == code)


# ------------------------------------------------------------ 用例集自身 ----
def test_fault_case_set_covers_the_declared_layers() -> None:
    """用例集是「单一事实来源」: 代号唯一、每条都带断言子串与处置建议."""
    codes = [case.code for case in FAULT_CASES]
    assert len(codes) == len(set(codes)) == 10
    for case in FAULT_CASES:
        assert case.expect, case.code
        assert case.advice, case.code
        assert case.title and case.layer
        assert (case.payload is None) != (case.raw is None), f"{case.code} 必须二选一"


def test_every_fault_case_targets_a_real_endpoint() -> None:
    """畸形入参必须打真工具, 只有「幻觉工具名」那条例外 —— 否则演示的是另一条代码路径."""
    names = set(build_default_registry().names())
    for case in FAULT_CASES:
        if case.code == UNKNOWN_TOOL_CASE:
            assert case.tool not in names
        else:
            assert case.tool in names, case.code


def test_cases_payload_is_what_the_frontend_renders() -> None:
    """前端不另抄一份用例: /sim/cases 的字段与顺序就是渲染契约."""
    payload = cases_payload()
    assert payload["count"] == len(FAULT_CASES) == len(payload["cases"])
    assert payload["client_budget_ms"] == DEFAULT_CLIENT_BUDGET_MS
    assert payload["throttle_rejections"] == THROTTLE_DEFAULT_REJECTIONS
    assert payload["retry_after_seconds"] == THROTTLE_RETRY_AFTER_SECONDS
    for row, case in zip(payload["cases"], FAULT_CASES):
        assert set(row) == {"code", "title", "tool", "body", "expect", "layer", "advice"}
        assert row["code"] == case.code and row["tool"] == case.tool
        assert row["body"] == case.request_body()


def test_request_body_is_the_exact_text_sent() -> None:
    """``raw`` 优先于 ``payload`` —— 非法 JSON 只有靠原文注入才演示得出来."""
    assert _case("truncated-json").request_body() == '{"text": "全网销量第一"'
    assert _case("missing-required").request_body() == '{"platform": "xhs"}'


# ------------------------------------------------------ 打真实校验链路 ----
@pytest.mark.parametrize("case", list(FAULT_CASES), ids=[c.code for c in FAULT_CASES])
def test_malformed_payload_is_blocked_by_the_real_chain(
    client: TestClient, case: FaultCase
) -> None:
    """十种模型幻觉入参: 一律 200 + ok=false + 友好诊断含预期子串, 不进 handler 也不外泄堆栈."""
    resp = client.post(
        f"/tools/{case.tool}",
        content=case.request_body().encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, (case.code, resp.status_code)
    body: Dict[str, Any] = resp.json()
    assert body["ok"] is False, case.code
    assert case.expect in (body["error"] or ""), (case.code, body["error"])
    assert "Traceback" not in resp.text and "File \"" not in resp.text


def test_battery_produces_no_server_errors(client: TestClient) -> None:
    """整电池跑一遍的总结口径必须与面板结论一致: 零 5xx, 且每条都被拦下."""
    statuses: List[int] = []
    blocked = 0
    for case in FAULT_CASES:
        resp = client.post(
            f"/tools/{case.tool}",
            content=case.request_body().encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        statuses.append(resp.status_code)
        blocked += 1 if resp.status_code == 200 and resp.json()["ok"] is False else 0
    assert blocked == len(FAULT_CASES)
    assert not [code for code in statuses if code >= 500]


def test_sim_cases_endpoint_serves_the_same_battery(client: TestClient) -> None:
    payload = client.get("/sim/cases").json()
    assert payload["ok"] is True
    assert payload["data"] == cases_payload()


# ------------------------------------------------------------ 429 限流 ----
@pytest.mark.parametrize("attempt", [0, 1])
def test_throttle_rejects_within_budget_with_retry_after(client: TestClient, attempt: int) -> None:
    resp = client.get(f"/sim/throttle?attempt={attempt}&reject_times={THROTTLE_DEFAULT_REJECTIONS}")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == str(THROTTLE_RETRY_AFTER_SECONDS)
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    payload = resp.json()
    assert payload["ok"] is False and f"第 {attempt + 1} 次" in payload["error"]
    assert payload["data"]["retry_after_seconds"] == THROTTLE_RETRY_AFTER_SECONDS


def test_throttle_recovers_after_backoff(client: TestClient) -> None:
    """退避到第 N+1 次必须真放行 —— 只演示拒绝不演示恢复就是假稳."""
    resp = client.get(f"/sim/throttle?attempt={THROTTLE_DEFAULT_REJECTIONS}&reject_times=2")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["recovered_after"] == THROTTLE_DEFAULT_REJECTIONS + 1
    assert "未产生重复扣量" in data["note"]


def test_throttle_is_stateless(client: TestClient) -> None:
    """无隐藏状态: 同一入参重复调用永远同一结果, 评委连点也不会「碰巧通过」."""
    urls = ["/sim/throttle?attempt=0&reject_times=2"] * 3
    assert {r.status_code for r in map(client.get, urls)} == {429}
    assert client.get("/sim/throttle?attempt=0&reject_times=0").status_code == 200


# ------------------------------------------------------------ 504 超时 ----
def test_timeout_within_budget_is_a_plain_success(client: TestClient) -> None:
    resp = client.get("/sim/timeout?ms=0&budget=1200")
    assert resp.status_code == 200
    assert resp.headers["X-Degrade"] == "none"
    data = resp.json()["data"]
    assert data["degraded"] is False and data["slept_ms"] == 0


def test_timeout_beyond_budget_degrades_with_envelope(client: TestClient) -> None:
    """越过预算要给出**可消费**的降级封套: 504 + 结构化 error + 回退策略说明."""
    resp = client.get("/sim/timeout?ms=50&budget=10")
    assert resp.status_code == 504
    assert resp.headers["X-Degrade"] == "cached-result"
    payload = resp.json()
    assert payload["ok"] is False
    assert "网关超时" in payload["error"]
    assert "回退" in payload["data"]["fallback"]


def test_timeout_bounds_reject_demo_hazards(client: TestClient) -> None:
    """``ms`` 上限存在, 否则评委手滑能把演示进程睡死."""
    assert client.get(f"/sim/timeout?ms={SIM_TIMEOUT_MAX_MS + 1000}").status_code == 422
    assert client.get("/sim/timeout?ms=-1").status_code == 422
    assert client.get("/sim/throttle?attempt=99").status_code == 422


# ---------------------------------------------------------- 链路追踪头 ----
def test_trace_headers_are_on_every_response(client: TestClient) -> None:
    """瀑布图的「网关段」来自 X-Process-Ms: 缺了这个头前端就只能猜."""
    resp = client.get("/healthz")
    assert len(resp.headers[REQUEST_ID_HEADER]) == 16
    assert float(resp.headers[PROCESS_MS_HEADER]) >= 0.0


def test_trace_header_reuses_incoming_request_id(client: TestClient) -> None:
    """客户端带来的 id 必须原样回显, 否则扣子侧日志与 Studio 对不上同一次调用."""
    assert (
        client.get("/healthz", headers={REQUEST_ID_HEADER: "upstream-77"}).headers[REQUEST_ID_HEADER]
        == "upstream-77"
    )
