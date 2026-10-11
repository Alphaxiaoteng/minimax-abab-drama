"""容灾沙箱 (Fault & Edge Simulator) 的异常注入用例集.

设计原则
--------
1. **不造假数据**: 每一条畸形入参都打到真实 ``POST /tools/{name}``, 由
   :class:`~coze_skills.core.runner.ToolRunner` 的同一条校验链路拦截, 因此
   Studio 里看到的红字诊断就是线上扣子调用失败时大模型看到的原文.
2. **单一事实来源**: 用例集只在 Python 里声明一次, 经 ``GET /sim/cases``
   吐给前端渲染, pytest 也拿同一份断言 —— 杜绝「前端演示过了但后端早改了」的漂移.
3. **只读**: 这些用例全部在参数校验阶段就被挡住, 不会进入 handler, 不产生副作用.

``expect`` 是错误原文必须包含的子串: 一旦校验链路文案变化, 测试立刻失败,
等于给「友好诊断」上了一道锁.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: 429 限流仿真默认拒绝次数 (前 N 次返回 429, 之后放行) —— 与前端退避重试演示配套
THROTTLE_DEFAULT_REJECTIONS = 2

#: 限流仿真返回的 ``Retry-After`` 秒数 (前端按指数退避真正 sleep)
THROTTLE_RETRY_AFTER_SECONDS = 1

#: 超时仿真的合法时长区间 (毫秒): 上限防止评委误操作把演示进程睡死
SIM_TIMEOUT_MIN_MS = 0
SIM_TIMEOUT_MAX_MS = 5000

#: 客户端超时预算默认值 (毫秒): 超过即中断请求并走降级回退
DEFAULT_CLIENT_BUDGET_MS = 1200


@dataclass(frozen=True)
class FaultCase:
    """一条畸形入参用例.

    :param code: 用例代号, 前端展示与测试断言的锚点.
    :param title: 人类可读的故障名.
    :param tool: 目标工具名.
    :param payload: JSON 对象形态的畸形入参; 与 ``raw`` 互斥.
    :param raw: 原文形态的请求体 (用于演示「根本不是 JSON 对象」这类传输层脏数据).
    :param expect: 网关返回的 ``error`` 必须包含的子串.
    :param layer: 拦截层名称, 说明「在哪一档被挡住」.
    :param advice: 给运营/大模型的处置建议, 即红字卡片里的「怎么办」.
    """

    code: str
    title: str
    tool: str
    payload: Optional[Dict[str, Any]] = None
    raw: Optional[str] = None
    expect: str = ""
    layer: str = "参数校验 (coerce_and_validate)"
    advice: str = ""

    def request_body(self) -> str:
        """序列化成实际请求体文本 (``raw`` 优先, 便于注入非法 JSON)."""
        if self.raw is not None:
            return self.raw
        return json.dumps(self.payload or {}, ensure_ascii=False)


#: 畸形入参用例集 —— 覆盖 Coze 线上最常见的四类模型幻觉入参.
FAULT_CASES: Tuple[FaultCase, ...] = (
    FaultCase(
        code="missing-required",
        title="必填参数缺失",
        tool="check_compliance",
        payload={"platform": "xhs"},
        expect="缺少必填参数",
        advice="大模型漏传 text; 在插件描述里已写明必填, 若线上频发应把该参数设为对话必填槽位。",
    ),
    FaultCase(
        code="wrong-container-type",
        title="容器类型错误 (对象当数组)",
        tool="analyze_reviews",
        payload={"reviews": {"first": "快递太慢"}},
        expect="期望 array",
        layer="类型校验 (Param.validate)",
        advice="模型把列表包成了 dict; 网关直接拒收, 不做猜测式兼容, 避免归因结果静默失真。",
    ),
    FaultCase(
        code="enum-violation",
        title="枚举取值越界 (臆造平台)",
        tool="check_compliance",
        payload={"text": "全网销量第一", "platform": "pinduoduo"},
        expect="取值必须是",
        layer="枚举白名单校验",
        advice="模型臆造了词库里没有的平台; 响应已列出合法取值, 可据此自纠后重试。",
    ),
    FaultCase(
        code="range-violation",
        title="数值越界 (top_n 超上限)",
        tool="analyze_reviews",
        payload={"reviews": ["快递太慢"], "top_n": 999},
        expect="不得大于 20",
        layer="边界校验 (maximum)",
        advice="把 top_n 收敛到 1-20; 越界调用被拒, 不会拖垮下游统计。",
    ),
    FaultCase(
        code="empty-required",
        title="空串冒充必填",
        tool="check_compliance",
        payload={"text": ""},
        expect="不能为空",
        advice="空文案没有检测意义, 拦下来比返回「0 命中」更诚实 —— 后者会让运营误判为安全。",
    ),
    FaultCase(
        code="unknown-param",
        title="未声明参数 (模型多加字段)",
        tool="draft_reply",
        payload={"review": "Package arrived damaged", "refund": True},
        expect="未知参数",
        layer="Schema 严格模式 (拒绝静默吞参数)",
        advice="模型把 refund_ready 写成了 refund; 严格模式当场报出, 而不是悄悄丢掉补偿承诺。",
    ),
    FaultCase(
        code="array-item-type",
        title="数组元素类型不一致",
        tool="check_compliance",
        payload={"text": "全网销量第一", "extra_words": [123, "旗舰店"]},
        expect="第 0 个元素期望 string",
        layer="元素级类型校验",
        advice="混合类型会让词库匹配报错; 逐元素校验能把问题定位到下标而不是整包拒收后无线索。",
    ),
    FaultCase(
        code="non-object-body",
        title="请求体不是 JSON 对象",
        tool="batch_check",
        raw="[\"全网最低价\", \"错过再等一年\"]",
        expect="请求体必须是 JSON 对象",
        layer="请求体解析 (_dispatch)",
        advice="模型把参数数组当 body 发出; 网关在解析层就收敛成业务失败, 全程 HTTP 200 不触发平台重试。",
    ),
    FaultCase(
        code="truncated-json",
        title="被截断的 JSON (网络撕裂)",
        tool="check_compliance",
        raw='{"text": "全网销量第一"',
        expect="请求体必须是 JSON 对象",
        layer="请求体解析 (_dispatch)",
        advice="长文案在网关前被截断是真实故障; 这里仍返回结构化错误, 而不是 500 堆栈。",
    ),
    FaultCase(
        code="unknown-tool",
        title="调用不存在的工具",
        tool="sentiment_probe",
        payload={"text": "还行吧"},
        expect="未注册",
        layer="注册表查找 (ToolRegistry)",
        advice="模型幻觉出未部署的工具名; 报「未注册」而不是 404, 让对话层可以就地换工具重试。",
    ),
)


def cases_payload() -> Dict[str, Any]:
    """把用例集序列化为前端可直接渲染的清单.

    :returns: ``{"count", "client_budget_ms", "cases": [...]}`` 纯 dict.
    """
    items: List[Dict[str, Any]] = []
    for case in FAULT_CASES:
        items.append(
            {
                "code": case.code,
                "title": case.title,
                "tool": case.tool,
                "body": case.request_body(),
                "expect": case.expect,
                "layer": case.layer,
                "advice": case.advice,
            }
        )
    return {
        "count": len(items),
        "client_budget_ms": DEFAULT_CLIENT_BUDGET_MS,
        "throttle_rejections": THROTTLE_DEFAULT_REJECTIONS,
        "retry_after_seconds": THROTTLE_RETRY_AFTER_SECONDS,
        "cases": items,
    }
