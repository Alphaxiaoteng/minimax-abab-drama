"""核心契约层单元测试 (spec / registry / schema / runner).

测试原则: 只钉「消费者可见的行为契约」—— 参数收敛、必填拦截、统一返回结构、
Schema 的 required/properties 对齐、runner 的永不抛异常与硬超时, 不测实现细节.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from coze_skills.core.registry import ToolRegistry, build_default_registry
from coze_skills.core.runner import CallLog, ToolRunner
from coze_skills.core.schema import build_openapi, openapi_json, validate_openapi
from coze_skills.core.spec import Param, SpecError, ToolError, ToolResult, ToolSpec


def _echo(params=(), handler=None, **kwargs) -> ToolSpec:
    """构造一个用于测试的最小工具声明."""

    def _default(**received: Any) -> ToolResult:
        return ToolResult.success(received=received)

    return ToolSpec(
        name=kwargs.pop("name", "echo"),
        title=kwargs.pop("title", "回显"),
        description=kwargs.pop("description", "把入参原样返回, 用于自测"),
        params=tuple(params),
        handler=handler or _default,
        **kwargs,
    )


# ---------------------------------------------------------------- spec ----
def test_param_rejects_illegal_name() -> None:
    """Coze 参数名不支持中文/横线, 必须在声明期直接失败."""
    with pytest.raises(SpecError):
        Param(name="中文参数")


def test_param_rejects_required_with_default() -> None:
    """required 与 default 语义冲突, 不允许同时声明."""
    with pytest.raises(SpecError):
        Param(name="n", type="integer", required=True, default=3)


def test_param_requires_items_type_for_array() -> None:
    """array 缺 items_type 会导致生成的 JSON Schema 非法."""
    with pytest.raises(SpecError):
        Param(name="xs", type="array")


def test_param_coerce_llm_stringified_inputs() -> None:
    """大模型常把数字/布尔写成字符串, 应在网关层收敛而非让工具重复判断."""
    int_param = Param(name="n", type="integer")
    assert int_param.coerce("7") == 7
    assert int_param.coerce(3.0) == 3

    bool_param = Param(name="flag", type="boolean")
    assert bool_param.coerce("true") is True
    assert bool_param.coerce("0") is False

    arr_param = Param(name="xs", type="array", items_type="string")
    assert arr_param.coerce("a, b ,c") == ["a", "b", "c"]


def test_param_validate_reports_chinese_reason() -> None:
    """校验失败必须给出可读中文原因, 而不是布尔值."""
    param = Param(name="n", type="integer", minimum=1, maximum=10)
    assert param.validate(5) is None
    assert "不得小于" in (param.validate(0) or "")
    assert "期望 integer" in (param.validate("x") or "")
    # bool 是 int 的子类, 必须被拒绝, 否则 true 会被当成 1 混进数值参数
    assert param.validate(True) == "期望 integer, 实际 bool"


def test_tool_result_fail_requires_error() -> None:
    """失败结果没有 error 文案会导致下游无法解释失败原因."""
    with pytest.raises(SpecError):
        ToolResult(ok=False)
    assert ToolResult.fail("boom").model_dump() == {"ok": False, "error": "boom", "data": {}}


def test_tool_spec_rejects_duplicate_param() -> None:
    """重复参数会让 OpenAPI properties 相互覆盖."""
    with pytest.raises(SpecError):
        _echo(params=[Param(name="a"), Param(name="a")])


def test_coerce_and_validate_rejects_unknown_param() -> None:
    """未知参数必须报错而不是静默忽略, 否则调用方以为传生效了."""
    spec = _echo(params=[Param(name="a", required=True)])
    cleaned, errors = spec.coerce_and_validate({"a": "x", "typo": 1})
    assert cleaned == {"a": "x"}
    assert any("未知参数" in e for e in errors)

    _, errors = spec.coerce_and_validate({})
    assert any("缺少必填参数" in e for e in errors)


# ------------------------------------------------------------ registry ----
def test_registry_rejects_duplicate_registration() -> None:
    """线上工具被二次注册覆盖是最危险的静默事故."""
    registry = ToolRegistry()
    registry.register(_echo(name="dup"))
    with pytest.raises(SpecError):
        registry.register(_echo(name="dup"))


def test_registry_search_and_by_category() -> None:
    """工具数超过 20 后 Agent 需要按分类/关键词做两级导航."""
    registry = ToolRegistry().register_all(
        [_echo(name="alpha", category="text"), _echo(name="beta", category="review", tags=("差评",))]
    )
    assert registry.names() == ["alpha", "beta"]
    assert registry.by_category()["text"][0].name == "alpha"
    assert [s.name for s in registry.search("差评")] == ["beta"]
    assert registry.search("") == []
    assert registry.stats() == (2, 0)


def test_discover_finds_tools_without_circular_import() -> None:
    """真实工具包必须能被自动发现 (core 不反向 import tools)."""
    registry = build_default_registry()
    assert {"check_compliance", "batch_check", "analyze_reviews", "draft_reply"} <= set(registry.names())


# -------------------------------------------------------------- schema ----
def test_build_openapi_aligns_required_with_properties() -> None:
    """required 里出现 properties 中不存在的名字, 会让整条工具在 Coze 端不可调用."""
    spec = _echo(
        name="demo",
        params=[
            Param(name="text", required=True),
            Param(name="days", type="integer", minimum=1, maximum=30, default=7),
            Param(name="tags", type="array", items_type="string"),
            Param(name="mode", enum=["fast", "slow"], default="fast"),
        ],
    )
    doc = build_openapi(ToolRegistry().register_all([spec]), title="t", version="9.9.9")
    assert doc["info"]["version"] == "9.9.9"
    body = doc["paths"]["/tools/demo"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["text"]
    assert set(body["required"]) <= set(body["properties"])
    assert body["properties"]["tags"]["items"] == {"type": "string"}
    assert body["properties"]["mode"]["enum"] == ["fast", "slow"]
    assert body["properties"]["days"]["default"] == 7
    assert doc["paths"]["/tools/demo"]["post"]["operationId"] == "demo"
    assert validate_openapi(doc) == []


def test_validate_openapi_detects_dangling_required() -> None:
    """校验器必须能自己抓出悬空 required (回归保护)."""
    doc = build_openapi(ToolRegistry().register_all([_echo(name="x", params=[Param(name="a")])]), title="t")
    schema = doc["paths"]["/tools/x"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    schema["required"] = ["ghost"]
    problems = validate_openapi(doc)
    assert any("ghost" in p for p in problems)


def test_openapi_json_is_stable_and_unescaped() -> None:
    """Schema 输出要可直接粘进 Coze 控制台且 diff 友好 (中文不转义/键有序)."""
    registry = ToolRegistry().register_all([_echo(name="x", title="中文标题")])
    payload = openapi_json(registry, title="中文标题")
    assert "中文标题" in payload
    assert payload == openapi_json(registry, title="中文标题")
    assert payload.index('"info"') < payload.index('"paths"')


# -------------------------------------------------------------- runner ----
def test_runner_invoke_success_path() -> None:
    """正常调用必须返回收敛后的参数."""
    registry = ToolRegistry().register_all(
        [_echo(name="add", params=[Param(name="n", type="integer", required=True)], handler=lambda n: ToolResult.success(v=n + 1))]
    )
    result = ToolRunner(registry).invoke("add", {"n": "41"})
    assert result.ok and result.data == {"v": 42}


def test_runner_never_raises_on_any_failure_mode() -> None:
    """网关层依赖「invoke 永不抛异常」这一契约, 必须逐条覆盖失败模式."""

    def raises_tool_error() -> ToolResult:
        raise ToolError("下游 429")

    def raises_unexpected() -> ToolResult:
        raise ValueError("kaboom")

    def returns_wrong_type() -> Dict[str, Any]:  # type: ignore[return-value]
        return {"ok": True}

    registry = ToolRegistry().register_all(
        [
            _echo(name="te", handler=raises_tool_error),
            _echo(name="ue", handler=raises_unexpected),
            _echo(name="wt", handler=returns_wrong_type),
            _echo(name="ok"),
        ]
    )
    runner = ToolRunner(registry)
    assert runner.invoke("te").error == "下游 429"
    assert "内部错误" in (runner.invoke("ue").error or "")
    assert "必须返回 ToolResult" in (runner.invoke("wt").error or "")
    assert "未注册" in (runner.invoke("ghost").error or "")
    assert runner.invoke("ok").ok


def test_runner_enforces_hard_timeout_without_blocking() -> None:
    """超时必须立即返回, 不能等慢 handler 跑完, 否则网关线程会被拖垮."""
    registry = ToolRegistry().register_all(
        [_echo(name="slow", timeout_seconds=0.2, handler=lambda: (time.sleep(2), ToolResult.success())[1])]
    )
    started = time.perf_counter()
    result = ToolRunner(registry).invoke("slow")
    elapsed = time.perf_counter() - started
    assert not result.ok and "执行超时" in (result.error or "")
    assert elapsed < 1.0, f"超时路径阻塞了 {elapsed:.2f}s"


def test_call_log_summary_math() -> None:
    """成功率/均值算错会让运维误判线上健康度."""
    log = CallLog(capacity=10)
    runner = ToolRunner(ToolRegistry().register_all([_echo(name="ok")]), log=log)
    runner.invoke("ok")
    runner.invoke("missing")
    runner.invoke("missing")
    runner.invoke("missing")
    summary = runner.describe()["log"]
    assert summary["total"] == 4 and summary["ok"] == 1 and summary["failed"] == 3
    assert summary["success_rate"] == 0.25
    assert len(log.records()) == 4
    assert summary["by_tool"]["ok"]["calls"] == 1


def test_call_log_records_keys_not_values() -> None:
    """日志只能留字段名, 避免把用户文案/密钥落盘."""
    log = CallLog(capacity=5)
    registry = ToolRegistry().register_all([_echo(name="p", params=[Param(name="secret_key")])])
    ToolRunner(registry, log=log).invoke("p", {"secret_key": "sk-super-secret"})
    record = log.records()[0].to_dict()
    assert list(record["params_keys"]) == ["secret_key"]
    assert "sk-super-secret" not in str(record)


def test_call_log_capacity_eviction() -> None:
    """环形日志必须丢最旧, 防止长跑进程内存无界增长."""
    log = CallLog(capacity=2)
    runner = ToolRunner(ToolRegistry().register_all([_echo(name="ok")]), log=log)
    for _ in range(5):
        runner.invoke("ok")
    assert len(log.records()) == 2
    with pytest.raises(ValueError):
        CallLog(capacity=0)
