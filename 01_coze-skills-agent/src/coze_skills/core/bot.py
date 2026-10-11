"""Coze Bot 演练场的本地意图路由 (Function Calling 的确定性替身) + Token 预估.

为什么需要这一层
----------------
Studio 的「🤖 Coze Bot 演练」要在**不依赖任何外部大模型**的前提下, 复现扣子线上
「自然语言 -> 选工具 -> 填参 -> 结构化回复」这条链路. 做法是把大模型那一跳换成
本模块的**确定性规则路由**: 同一句话永远命中同一个工具、产出同一份入参, 因此
① 评委现场演示不会因模型抖动而翻车, ② 这套映射可被 pytest 逐条钉死.

与线上形态的对应关系 (刻意保持一致, 换成真模型时可整层替换而接口不变):
``route()``           -> Coze 的 ``function_call`` 决策 (工具名 + arguments)
``run_turn()``        -> 工具执行 + 结果回填给模型后的卡片渲染
``estimate_tokens()`` -> 该轮对话的 token 成本预估

隐私边界: 本模块只做路由与展示, 不写日志; 调用日志仍由
:class:`~coze_skills.core.runner.ToolRunner` 统一记录, 且只记参数名不记参数值.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .registry import ToolRegistry
from .runner import ToolRunner
from .schema import tool_to_operation
from .spec import ToolResult

#: 意图信号词: 命中即 +1 分. 键顺序即同分时的优先序 (越具体越靠前).
INTENT_SIGNALS: Dict[str, Tuple[str, ...]] = {
    "draft_reply": (
        "回复", "答复", "草稿", "话术", "安抚", "道歉", "邮件", "私信",
        "reply", "respond", "answer",
    ),
    "analyze_reviews": (
        "差评", "评价", "评论", "客诉", "退货", "投诉", "归因", "舆情", "口碑", "主题",
        "占比", "分布", "review", "reviews", "feedback",
    ),
    "batch_check": ("批量", "一批", "整批", "这几条", "逐条", "文案库", "盘点", "多条", "batch"),
    "check_compliance": (
        "合规", "违禁", "禁词", "敏感词", "极限词", "广告法", "违规", "审核", "能不能发",
        "能上架吗", "检测", "检查", "改写", "文案", "标题", "笔记", "封面",
    ),
}

#: 平台/渠道口语别名 -> 工具 enum 值. 覆盖用户不会照着 enum 打字名的真实说法.
PLATFORM_ALIASES: Dict[str, str] = {
    "小红书": "xhs", "xhs": "xhs",
    "抖音": "douyin", "douyin": "douyin",
    "淘宝": "taobao", "taobao": "taobao", "天猫": "taobao",
    "亚马逊": "amazon", "amazon": "amazon",
    "虾皮": "shopee", "shopee": "shopee",
    "tiktok": "tiktok",
    "temu": "temu",
    "通用": "general", "general": "general",
}

#: 语气口语别名 -> ``draft_reply.tone`` 枚举值.
TONE_ALIASES: Dict[str, str] = {
    "正式": "professional", "professional": "professional", "商务": "professional",
    "亲和": "friendly", "friendly": "friendly", "友好": "friendly", "温柔": "friendly",
    "极简": "concise", "concise": "concise", "简短": "concise",
}

#: 表达「只改参数、不换业务对象」的追问信号 —— 无意图信号命中时据此继承上一轮载荷.
FOLLOWUP_SIGNALS: Tuple[str, ...] = (
    "改成", "换成", "换个", "再查", "再看", "重新", "语气", "退款", "补偿", "详细", "前",
)

_REFUND_SIGNALS: Tuple[str, ...] = ("退款", "补偿", "赔偿")

#: 引号形态 (含中文书名号), 用于「先把业务对象摘出来」.
_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("「", "」"), ("『", "』"), ("“", "”"), ("'", "'"), ('"', '"'), ("《", "》"),
)

#: 快问快答按钮文案: 前端直接渲染, 后端同时把它当回归用例的天然输入.
QUICK_PROMPTS: Tuple[str, ...] = (
    "这条文案能不能直接发:「这款面膜全网销量第一, 药效显著, 七天美白立竿见影!」",
    "帮我批量体检这几条上新文案, 换成淘宝平台:「全网最低价, 错过再等一年!」「新中式缠花发簪, 手工绕线, 日常通勤也能戴」",
    "这批差评到底卡在哪儿:快递太慢了, 盒子都压烂了\n鞋子偏小两码根本穿不进去, 客服半天不回\n做工粗糙, 线头到处都是",
    "给这条差评写封英文回复, 语气亲和一点, 已经给他退款了:「Two stars. Delivery took three weeks and the package arrived damaged.」",
)


class BotError(ValueError):
    """演练场路由阶段的不可恢复输入错误 (由调用方收敛为业务失败)."""


@dataclass(frozen=True)
class BotDecision:
    """一次「自然语言 -> 工具调用」的决策结果 (等价于 Coze 的 function_call).

    :param tool: 命中的工具名; 无法判定时为 ``None``.
    :param params: 收敛后的调用参数 (只含该工具声明过的键).
    :param score: 意图信号命中总分, 供前端展示置信度.
    :param signals: 实际命中的信号词 (去重保序).
    :param inherited: 业务载荷是否继承自上一轮 (多轮上下文).
    :param overrides: 本轮被显式改写的参数名.
    :param rejected: 未识别成工具调用时的友好说明 (与 ``tool`` 互斥).
    """

    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    score: int = 0
    signals: Tuple[str, ...] = ()
    inherited: bool = False
    overrides: Tuple[str, ...] = ()
    rejected: Optional[str] = None


def estimate_tokens(text: str) -> int:
    """确定性 token 粗估 (不引 tokenizer 依赖, 同一文本永远同一结果).

    口径: CJK 字符按 1 token/字, 其余字符按 4 字符/token —— 主流中文分词器的经验量级.
    这是**成本量级预估**而非某家模型的精确计数, UI 上也据此标注为「预估」.

    :param text: 待估文本.
    :returns: 非负整数; 空串为 0.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    return cjk + int(math.ceil((len(text) - cjk) / 4.0))


def _is_cjk(ch: str) -> bool:
    """判断单个字符是否落在中日韩书写区 (含全角标点)."""
    code = ord(ch)
    return (
        0x3000 <= code <= 0x303F
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFF65
    )


def extract_items(message: str) -> List[str]:
    """从自然语言里摘出「要被处理的业务对象」列表.

    优先级: 引号内文本 (可多段, 天然对应批量/多条评论) > 冒号之后的多行内容 > 疑问前缀
    剥离后的整句. 摘出来的东西必须像业务数据而不像提问, 因此设最短长度门槛.

    :param message: 用户原始输入.
    :returns: 业务条目列表 (可能为空).
    """
    text = (message or "").strip()
    if not text:
        return []

    chunks: List[str] = []
    for open_ch, close_ch in _QUOTE_PAIRS:
        pattern = re.escape(open_ch) + r"(.*?)" + re.escape(close_ch)
        for match in re.finditer(pattern, text, re.S):
            chunk = match.group(1).strip()
            if len(chunk) >= 6:
                chunks.append(chunk)
    if chunks:
        return chunks

    for sep in ("：", ":"):
        idx = text.find(sep)
        if idx != -1:
            tail = text[idx + 1:].strip()
            if len(tail) >= 6:
                lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
                return lines or [tail]

    body = re.split(r"[?？!！]", text)[0].strip()
    return [body] if len(body) >= 12 else []


def _score_intents(message: str) -> List[Tuple[str, int, Tuple[str, ...]]]:
    """按 :data:`INTENT_SIGNALS` 给每个工具打分, 返回降序榜 (同分按声明序)."""
    lowered = message.lower()
    board = []
    for order, (tool, words) in enumerate(INTENT_SIGNALS.items()):
        hits = tuple(w for w in words if w in lowered)
        if hits:
            board.append((tool, len(hits), hits, order))
    board.sort(key=lambda item: (-item[1], item[3]))
    return [(tool, score, hits) for tool, score, hits, _ in board]


def _detect_enums(message: str, spec_params) -> Dict[str, str]:
    """把用户口语点名的平台/语气映射成工具 enum 值.

    :param message: 用户输入.
    :param spec_params: 目标工具的 :class:`Param` 序列.
    :returns: ``{参数名: enum 值}``; 未点名则为空.
    """
    lowered = message.lower()
    found: Dict[str, str] = {}
    for p in spec_params:
        if p.enum is None:
            continue
        table = TONE_ALIASES if p.name == "tone" else PLATFORM_ALIASES
        for alias, value in table.items():
            if alias in lowered and value in list(p.enum):
                found[p.name] = value
                break
    return found


def _detect_top_n(message: str) -> Optional[int]:
    """识别「前 3 个主题」「top 8」这类数量诉求; 只接受 1-20, 越界视为未识别."""
    match = re.search(r"(?:前|取|保留|列|top|topn|top_n)\s*([0-9]{1,2})", message.lower())
    if not match:
        return None
    n = int(match.group(1))
    return n if 1 <= n <= 20 else None


def route(
    message: str,
    registry: ToolRegistry,
    context: Optional[Dict[str, Any]] = None,
) -> BotDecision:
    """把一句自然语言路由成一次工具调用决策.

    :param message: 用户输入 (单句或多行, 允许内含业务载荷).
    :param registry: 工具注册表, 用于按声明收敛参数.
    :param context: 上一轮 ``{"tool","params"}``; 追问型输入据此继承业务对象.
    :returns: :class:`BotDecision`; 判定不了时 ``tool is None`` 且带 ``rejected`` 说明.
    :raises BotError: 输入为空, 或上下文引用了未注册的工具.
    """
    text = (message or "").strip()
    if not text:
        raise BotError("消息不能为空")
    if context is not None and context.get("tool") and registry.get(str(context["tool"])) is None:
        raise BotError(f"上下文引用了未注册的工具 {context['tool']!r}")

    board = _score_intents(text)
    items = extract_items(text)
    ctx_tool = str((context or {}).get("tool") or "")
    ctx_params = dict((context or {}).get("params") or {})

    if board:
        tool, score, signals = board[0]
        inherited = False
    elif ctx_tool and any(sig in text for sig in FOLLOWUP_SIGNALS):
        tool, score, signals, inherited = ctx_tool, 0, (), True
    elif ctx_tool:
        return BotDecision(
            rejected=(
                "这句话既没命中任何技能信号词, 也不像「只改参数重跑一遍」的追问, "
                "所以没有发起工具调用。可以直接说「换成淘宝平台再查一遍」。"
            )
        )
    else:
        return BotDecision(
            rejected=(
                "没能从这句话里识别出可执行的动作。可以点下面的快问快答, "
                "或把要处理的文案/差评用「」包起来再说一次。"
            )
        )

    spec = registry.require(tool)
    params: Dict[str, Any] = {}
    overrides: List[str] = []
    primary = spec.params[0].name
    list_like = spec.params[0].type == "array"

    if inherited:
        reused = ctx_params.get(primary)
        if reused in (None, "", []):
            return BotDecision(rejected="上一轮上下文里没有可复用的业务内容, 请重新给一段文案或差评。")
        params[primary] = reused
    elif list_like:
        if items:
            params[primary] = items
    elif items:
        params[primary] = items[0] if len(items) == 1 else "\n".join(items)

    if not params.get(primary):
        # 意图明确但本轮没带新内容: 若上一轮就是同一个工具, 复用它业务对象
        # (真实 Bot 听到「再改写一版」也是这么做的), 否则才要求用户补内容.
        reused = ctx_params.get(primary) if ctx_tool == tool else None
        if reused not in (None, "", []):
            params[primary] = reused
            inherited = True
        else:
            return BotDecision(
                rejected=(
                    f"识别到你想用「{spec.title}」, 但没摘到要处理的内容。"
                    "请把文案或差评用「」包起来, 或换行一条一条贴。"
                )
            )

    for name, value in _detect_enums(text, spec.params).items():
        params[name] = value
        overrides.append(name)

    if spec.param("top_n") is not None:
        top_n = _detect_top_n(text)
        if top_n is not None:
            params["top_n"] = top_n
            overrides.append("top_n")

    if spec.param("refund_ready") is not None and any(s in text for s in _REFUND_SIGNALS):
        params["refund_ready"] = True
        overrides.append("refund_ready")

    if inherited:
        # 参数改写优先于继承值, 已在 params 里的键自然覆盖; 其余沿用上一轮口径.
        for key, value in ctx_params.items():
            params.setdefault(key, value)

    params = {k: v for k, v in params.items() if spec.param(k) is not None}
    return BotDecision(
        tool=tool,
        params=params,
        score=score,
        signals=signals,
        inherited=inherited,
        overrides=tuple(dict.fromkeys(overrides)),
    )


def summarize(tool: str, data: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]], str]:
    """把工具返回压成「一句人话 + 关键指标 + 可选正文」, 供 Bot 气泡渲染.

    :param tool: 工具名.
    :param data: :class:`~coze_skills.core.spec.ToolResult` 的 ``data`` 字段.
    :returns: ``(summary, chips, body)``, 其中 chips 为 ``[(标签, 值), ...]``.
    """
    if tool == "check_compliance":
        hits = data.get("hits") or []
        words = "、".join(str(h.get("word", "")) for h in hits[:3]) or "无"
        level = {"high": "高风险", "medium": "软性风险", "low": "合规"}.get(
            str(data.get("risk_level")), str(data.get("risk_level"))
        )
        summary = (
            f"检测完成: {level}, 命中 {data.get('hit_count', len(hits))} 处禁限词({words})。"
            "已生成可直接发布的合规改写。"
        )
        chips = [
            ("风险等级", str(data.get("risk_level"))),
            ("命中数", str(data.get("hit_count", len(hits)))),
            ("平台", str(data.get("platform"))),
        ]
        return summary, chips, str(data.get("rewritten_text") or "")

    if tool == "batch_check":
        summary = str(data.get("verdict") or "批量体检完成。")
        chips = [
            ("条数", str(data.get("total"))),
            ("高危条数", str(data.get("high_risk_count"))),
            ("分布", json.dumps(data.get("summary") or {}, ensure_ascii=False)),
        ]
        return summary, chips, ""

    if tool == "analyze_reviews":
        themes = data.get("themes") or []
        top = "、".join(f"{t.get('theme')}({t.get('count')}条)" for t in themes[:3]) or "无"
        ratio = round(float(data.get("negative_ratio") or 0) * 100)
        summary = f"{data.get('total')} 条差评归因完成, 负面占比 {ratio}%, 主要卡在: {top}。"
        chips = [
            ("总条数", str(data.get("total"))),
            ("负面占比", f"{ratio}%"),
            ("改进项", str(len(data.get("action_items") or []))),
        ]
        return summary, chips, ""

    if tool == "draft_reply":
        summary = (
            f"已生成 {data.get('tone', 'professional')} 语气英文回复: "
            f"主题「{data.get('theme')}」, 道歉强度 {data.get('apology_level')}, "
            f"{data.get('word_count', 0)} 词。"
        )
        chips = [
            ("主题", str(data.get("theme"))),
            ("渠道", str(data.get("marketplace"))),
            ("补偿", "已承诺" if data.get("refund_ready") else "未承诺"),
        ]
        return summary, chips, str(data.get("reply_draft") or "")

    return f"{tool} 调用完成。", [("返回字段数", str(len(data)))], ""


def tool_schema(registry: ToolRegistry, tool: str) -> Dict[str, Any]:
    """取某工具请求体的 JSON Schema —— 与 OpenAPI 导出同一生成函数, 杜绝两处手写."""
    operation = tool_to_operation(registry.require(tool))
    return operation["requestBody"]["content"]["application/json"]["schema"]


def manifest_tokens(registry: ToolRegistry) -> int:
    """工具清单 (要塞进系统提示词的那部分) 的 token 开销 —— 每一轮都固定要付."""
    chunks: List[str] = []
    for spec in registry.all():
        chunks.append(f"{spec.name} {spec.title} {spec.description}")
        for p in spec.params:
            chunks.append(f"{p.name} {p.type} {p.description}")
    return estimate_tokens("\n".join(chunks))


def coze_headers(*, request_id: str, tool: str, body_length: int) -> Dict[str, Any]:
    """构造一份 Coze 插件调用的请求头样本.

    真实密钥由扣子平台侧注入, 演练场**只展示占位符**, 绝不落任何可用凭据.

    :param request_id: 本轮请求 id (与 ``X-Coze-Request-Id`` 响应头同源).
    :param tool: 工具名.
    :param body_length: 请求体 UTF-8 字节数.
    :returns: ``{"method", "path", "headers"}``.
    """
    return {
        "method": "POST",
        "path": f"/tools/{tool}",
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer ${COZE_PLUGIN_TOKEN}",
            "X-Coze-Request-Id": request_id,
            "X-Coze-Client": "plugin-debugger-studio",
            "User-Agent": "coze-skills-gateway/0.1.0",
            "Content-Length": str(body_length),
        },
    }


def run_turn(
    registry: ToolRegistry,
    runner: ToolRunner,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    request_id: str = "",
    process_ms: float = 0.0,
) -> Dict[str, Any]:
    """跑完一整轮: 路由 -> 工具调用 -> 组卡 -> 估 token -> 出结构化回复.

    :param registry: 工具注册表.
    :param runner: 执行器 (``invoke`` 永不抛异常).
    :param message: 用户输入.
    :param context: 上一轮上下文 ``{"tool","params"}``.
    :param request_id: 本轮请求 id.
    :param process_ms: 网关侧处理耗时 (与 ``X-Process-Ms`` 响应头同源).
    :returns: 前端可直接渲染的卡片 dict; ``type`` 为 ``call`` 或 ``clarify``.
    """
    try:
        decision = route(message, registry, context)
    except BotError as exc:
        decision = BotDecision(rejected=str(exc))

    tokens: Dict[str, int] = {
        "context": manifest_tokens(registry),
        "prompt": estimate_tokens(message),
        "tool_output": 0,
        "completion": 0,
    }

    if decision.tool is None:
        return {
            "ok": False,
            "type": "clarify",
            "request_id": request_id,
            "message": decision.rejected or "无法处理该输入",
            "decision": {
                "tool": None,
                "signals": [],
                "score": decision.score,
                "inherited": False,
                "overrides": [],
            },
            "tokens": {**tokens, "total": tokens["context"] + tokens["prompt"]},
            "context": dict(context or {}),
        }

    body_text = json.dumps(decision.params, ensure_ascii=False)
    result: ToolResult = runner.invoke(decision.tool, decision.params)
    tokens["tool_output"] = estimate_tokens(json.dumps(result.model_dump(), ensure_ascii=False))

    if result.ok:
        summary, chips, body = summarize(decision.tool, result.data)
    else:
        summary, chips, body = (
            f"工具 {decision.tool} 这次没有跑通: {result.error}",
            [("状态", "校验/执行未通过")],
            "",
        )
    tokens["completion"] = estimate_tokens(summary + body)

    return {
        "ok": bool(result.ok),
        "type": "call",
        "request_id": request_id,
        "tool": decision.tool,
        "title": registry.require(decision.tool).title,
        "summary": summary,
        "chips": chips,
        "body": body,
        "params": decision.params,
        "schema": tool_schema(registry, decision.tool),
        "http": coze_headers(
            request_id=request_id, tool=decision.tool, body_length=len(body_text.encode("utf-8"))
        ),
        "timings": {"server_ms": round(process_ms, 3)},
        "tokens": {**tokens, "total": sum(tokens.values())},
        "decision": {
            "signals": list(decision.signals),
            "score": decision.score,
            "inherited": decision.inherited,
            "overrides": list(decision.overrides),
        },
        "result": result.model_dump(),
        "context": {"tool": decision.tool, "params": decision.params},
    }


def greet(registry: ToolRegistry) -> Dict[str, Any]:
    """开场白卡片: 让评委一进面板就看清这套 Bot 会什么、怎么说才有效."""
    count, _ = registry.stats()
    names = " / ".join(f"{spec.name}({spec.title})" for spec in registry.all())
    return {
        "ok": True,
        "type": "greet",
        "message": (
            "我是这套插件的本地演练 Bot: 你用自然语言说诉求, 我按扣子 Function Calling 的形态"
            "选出工具、填好入参、直连同一个网关执行, 再把这一轮的入参 Schema、Coze 请求头、"
            "往返耗时瀑布与 Token 成本摊开给你看。\n"
            f"当前挂载 {count} 个技能: {names}。\n"
            "说明: 这里的大模型一跳由确定性意图路由替身完成, 与线上唯一的区别是选择环节不消耗 "
            "Token —— 其余链路 (Schema、参数校验、超时、响应结构) 与扣子完全同源。"
        ),
        "quick_prompts": list(QUICK_PROMPTS),
        "tokens": {
            "context": manifest_tokens(registry),
            "prompt": 0,
            "tool_output": 0,
            "completion": 0,
            "total": manifest_tokens(registry),
        },
    }
