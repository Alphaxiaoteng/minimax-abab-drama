"""跨境/电商多平台差评洞察与回复草稿生成.

设计说明:
1. **纯本地启发式, 零外部依赖、零网络** —— 关键词到主题表 + 中英混合分词,
   保证离线可跑且结果确定 (同输入必同输出), 赛题现场演示不依赖任何 API 配额.
2. 分词策略: 英文按 ``[^A-Za-z0-9]+`` 切分并小写, 中文抽取连续汉字串的 2-gram;
   词组型关键词 (含空格, 如 ``not as described``) 走归一化子串匹配,
   单英文词走词边界匹配 (避免 ``fit`` 命中 ``benefit``), 中文词走子串匹配.
3. ``marketplace`` 不改变主题归因 (差评语义与渠道无关), 只影响两处运营口径:
   ``analyze_reviews`` 追加该渠道的履约建议, ``draft_reply`` 的合规自检项
   (亚马逊禁止以补偿换好评, 站内即时通讯渠道需走 IM 话术).
4. 批量入参的 ``max_length`` 在 :class:`Param` 里只对字符串生效, 因此数组条数与
   元素类型必须在 handler 内二次防御; 与 ``text_compliance`` 保持同一策略:
   业务级输入问题一律 **抛 ToolError** (由 runner 转成失败 ToolResult).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from coze_skills.core.spec import Param, ToolError, ToolResult, ToolSpec

# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

#: 中文停用单字 (2-gram 过滤用)
CN_STOP_WORDS: Tuple[str, ...] = ("的", "了", "是", "很", "都", "就", "也", "和", "与", "但", "这", "那")

#: 英文停用词 (小写)
EN_STOP_WORDS: Tuple[str, ...] = ("the", "is", "and", "for", "with", "this", "that", "it", "i", "a")

#: 负面情绪词 (命中即该条评论记为 negative)
NEGATIVE_WORDS: Tuple[str, ...] = (
    "bad", "awful", "terrible", "worst", "useless", "差", "垃圾", "失望", "退货",
)

#: 主题 -> 关键词表 (中英混合, 覆盖跨境差评八类高频归因)
THEME_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "物流时效": ("物流", "快递", "发货", "配送", "慢", "delivery", "shipping", "late", "arrived"),
    "包装破损": ("包装", "箱子", "破损", "摔坏", "package", "box", "broken", "damaged"),
    "尺寸偏差": ("尺寸", "尺码", "偏小", "偏大", "大小", "size", "fit", "too small", "too big"),
    "质量做工": ("质量", "做工", "掉色", "开线", "断裂", "quality", "cheap", "broke", "defective"),
    "客服响应": ("客服", "服务", "回复", "态度", "customer service", "refund", "response"),
    "描述不符": ("描述", "不符", "实物", "货不对板", "wrong", "not as described", "picture"),
    "价格价值": ("价格", "贵", "不值", "性价比", "price", "expensive", "worth"),
    "气味材质": ("材质", "面料", "气味", "味道", "刺鼻", "smell", "odor", "material", "fabric"),
}

#: 主题 -> 中文可执行改进建议 (面向运营动作, 不复述问题)
THEME_ACTIONS: Dict[str, str] = {
    "物流时效": "优先更换承运商或加发海外仓/平台仓备货，把承诺时效缩短 2 天",
    "包装破损": "升级缓冲气柱与更硬的运输箱，易碎点增加角贴并在装箱 SOP 里固化",
    "尺寸偏差": "详情页补充实测尺码表与真人身材参考，标题标注偏大/偏小方向",
    "质量做工": "加强来料抽检，把高频缺陷点列入工艺整改并设置退货返修台账",
    "客服响应": "设定 24 小时首响 SLA，预置退款/补发话术与审批权限",
    "描述不符": "重拍无滤镜实物图，逐项复核文案参数（颜色/尺寸/配件/材质成分）",
    "价格价值": "复核定价与赠品组合，明确价值锚点并给出可对比的配置差异",
    "气味材质": "更换面料/涂层供应商，出厂前增加通风去味与气味抽检工序",
    "其他": "补充差评关键词归因规则，把未覆盖表述加入主题词表",
}

#: 高危主题 (道歉强度直接拉满)
HIGH_APOLOGY_THEMES: Tuple[str, ...] = ("物流时效", "质量做工", "包装破损")

#: 渠道 -> 履约侧附加建议
MARKETPLACE_OPS_HINT: Dict[str, str] = {
    "amazon": "亚马逊侧优先入仓 FBA，避免自发货超时触发账号绩效预警",
    "shopee": "虾皮侧改用官方物流并前置发货，紧盯迟发货率扣分项",
    "tiktok": "TikTok Shop 侧优先本地仓发货，物流分直接影响直播间流量推荐",
    "temu": "Temu 侧改用 JIT/海外仓备货，配合平台核价前先压实物品质成本",
    "general": "通用渠道建议先做物流与包装两项低成本整改，再迭代详情页",
}

#: 渠道 -> 客服发送前合规自检项
MARKETPLACE_CHECKLIST: Dict[str, str] = {
    "amazon": "亚马逊站内信禁止以任何补偿换取或修改评价，删除一切改评引导语",
    "shopee": "虾皮走站内 IM 回复，确认未留站外邮箱/链接以免被判定导流",
    "tiktok": "TikTok Shop 回复需先安抚再引导站内订单号，避免私下转账承诺",
    "temu": "Temu 由平台代客服，确认工单口径与平台退款政策一致再发送",
    "general": "发送前确认话术符合所在平台的评价与客服规范",
}

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")

# ---------------------------------------------------------------------------
# 分词与匹配
# ---------------------------------------------------------------------------


def tokenize(text: str) -> List[str]:
    """中英混合分词 (小写, 已去停用词与长度 <2 的碎片).

    :param text: 原始评论文本.
    :returns: token 列表 (英文词 + 中文 2-gram), 供主题命中与统计使用.
    """
    tokens: List[str] = []
    for raw in _LATIN_SPLIT_RE.split(text.lower()):
        if len(raw) >= 2 and raw not in EN_STOP_WORDS:
            tokens.append(raw)
    for run in _CJK_RUN_RE.findall(text):
        for i in range(len(run) - 1):
            gram = run[i:i + 2]
            if gram[0] in CN_STOP_WORDS and gram[1] in CN_STOP_WORDS:
                continue
            tokens.append(gram)
    return tokens


def _normalized(text: str) -> str:
    """归一化文本: 小写 + 空白压平, 供词组型关键词做子串匹配."""
    return re.sub(r"\s+", " ", text.lower())


def _keyword_hits(text: str) -> List[str]:
    """返回文本命中的全部关键词 (原样, 按主题名+关键词序, 确定性输出).

    :param text: 原始评论.
    :returns: 命中的关键词列表 (同词只记一次).
    """
    norm = _normalized(text)
    latin = set(tokenize(text))
    hits: List[str] = []
    for theme in sorted(THEME_KEYWORDS):
        for kw in THEME_KEYWORDS[theme]:
            if kw in hits:
                continue
            if _ASCII_RE.match(kw):
                if " " in kw:
                    matched = kw in norm
                else:
                    matched = kw in latin
            else:
                matched = kw in norm
            if matched:
                hits.append(kw)
    return hits


def _theme_of(text: str) -> str:
    """评论主题归因: 命中关键词最多的主题; 平局取主题名排序靠前者; 无命中返回「其他」."""
    counts: Dict[str, int] = {}
    for theme, kws in THEME_KEYWORDS.items():
        for kw in kws:
            if _keyword_matches(text, kw):
                counts[theme] = counts.get(theme, 0) + 1
    if not counts:
        return "其他"
    return sorted(counts, key=lambda t: (-counts[t], t))[0]


_ASCII_RE = re.compile(r"^[A-Za-z0-9]")


def _keyword_matches(text: str, kw: str) -> bool:
    """单个关键词是否命中评论 (英文单词走词边界, 词组/中文走归一化子串)."""
    norm = _normalized(text)
    if _ASCII_RE.match(kw):
        if " " in kw:
            return kw in norm
        return kw in set(tokenize(text))
    return kw in norm


def _is_negative(text: str) -> bool:
    """评论是否带明显负面情绪 (词表命中, 英文单词走词边界)."""
    return any(_keyword_matches(text, w) for w in NEGATIVE_WORDS)


def _truncate(text: str, limit: int = 80) -> str:
    """截断到 limit 字符 (含省略号), 保留原始大小写."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 1:
        return cleaned[:limit]
    return cleaned[:limit - 1] + "…"


def _severity(ratio: float) -> str:
    """主题严重度: ratio>=0.5 high, >=0.25 medium, 否则 low."""
    if ratio >= 0.5:
        return "high"
    if ratio >= 0.25:
        return "medium"
    return "low"


def _validate_reviews(reviews: Sequence[Any], param_name: str) -> List[str]:
    """批量评论入参防御: 元素非字符串/空列表/超上限一律抛 ToolError.

    与 ``text_compliance`` 同一策略 (业务级输入问题抛异常, 由 runner 转失败结果),
    避免 handler 出现 dict 与 ToolResult 两套返回形状.

    :param reviews: 调用方传入的评论数组.
    :param param_name: 参数名, 用于错误文案.
    :returns: 过滤空白条目后的评论字符串列表 (空白条目不参与统计, 避免稀释比例).
    :raises ToolError: 元素非字符串、有效条数为 0 或超过 500 条.
    """
    cleaned: List[str] = []
    for idx, item in enumerate(reviews):
        if not isinstance(item, str):
            raise ToolError(f"{param_name} 第 {idx} 个元素期望 string, 实际 {type(item).__name__}")
        if item.strip():
            cleaned.append(item)
    if not cleaned:
        raise ToolError(f"{param_name} 不能为空 (空白条目不计数)")
    if len(cleaned) > 500:
        raise ToolError(f"{param_name} 最多 500 条, 实际 {len(cleaned)}")
    return cleaned


def _marketplace_or_error(marketplace: str, default: str) -> str:
    """归一化渠道标识; 非法值抛 ToolError (网关已枚举校验, 此处兜直连调用)."""
    key = (marketplace or default).strip().lower()
    if key not in MARKETPLACE_OPS_HINT:
        raise ToolError(f"不支持的渠道 {marketplace!r}, 可选: {sorted(MARKETPLACE_OPS_HINT)}")
    return key


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------


def analyze_reviews(
    reviews: List[str],
    marketplace: str = "amazon",
    top_n: int = 5,
) -> ToolResult:
    """对差评列表做本地关键词归因, 输出主题分布、负面占比与可执行改进清单.

    :param reviews: 差评原文列表 (最多 500 条, 支持中英文); 纯空白条目被忽略.
    :param marketplace: 销售渠道 amazon/shopee/tiktok/temu/general, 决定追加的履约建议.
    :param top_n: 返回的主题数量上限 (1-20).
    :returns: data 含 total / negative_ratio / themes / sample_quotes / action_items.
    :raises ToolError: 评论元素非字符串、有效条数为 0 或超上限、渠道非法.
    """
    items = _validate_reviews(reviews, "reviews")
    market = _marketplace_or_error(marketplace, "amazon")

    total = len(items)
    negative_count = sum(1 for r in items if _is_negative(r))

    theme_count: Dict[str, int] = {}
    theme_quotes: Dict[str, List[str]] = {}
    for r in items:
        theme = _theme_of(r)
        theme_count[theme] = theme_count.get(theme, 0) + 1
        quotes = theme_quotes.setdefault(theme, [])
        if len(quotes) < 2:
            quotes.append(_truncate(r))

    ranked = sorted(theme_count, key=lambda t: (-theme_count[t], t))[:top_n]
    themes: List[Dict[str, Any]] = []
    sample_quotes: Dict[str, List[str]] = {}
    action_items: List[str] = []
    for theme in ranked:
        count = theme_count[theme]
        ratio = round(count / total, 4)
        themes.append({"theme": theme, "count": count, "ratio": ratio, "severity": _severity(ratio)})
        sample_quotes[theme] = theme_quotes.get(theme, [])
        action_items.append(f"{theme}占 {int(round(ratio * 100))}%：{THEME_ACTIONS[theme]}")
    action_items.append(f"渠道建议（{market}）：{MARKETPLACE_OPS_HINT[market]}")

    return ToolResult.success(
        total=total,
        negative_ratio=round(negative_count / total, 4),
        themes=themes,
        sample_quotes=sample_quotes,
        action_items=action_items,
    )


_TONE_OPENER: Dict[str, str] = {
    "professional": "Thank you for taking the time to share this feedback, and please accept our sincere apologies.",
    "friendly": "Thanks so much for letting us know — we're really sorry this happened to you!",
    "concise": "Sorry about this. Thank you for reporting it.",
}

_TONE_ACCOUNTABILITY: Dict[str, str] = {
    "professional": "This falls short of the standard we hold ourselves to, and the issue is on us.",
    "friendly": "That's definitely not the experience we want you to have, and we own this one.",
    "concise": "The issue is ours to fix.",
}

_TONE_REMEDY: Dict[str, str] = {
    "professional": "We have flagged it to our operations team for an immediate corrective action.",
    "friendly": "We've already shared it with our warehouse team so it gets better next time.",
    "concise": "Flagged for immediate correction.",
}

_TONE_CLOSING: Dict[str, str] = {
    "professional": "Please reply to this message or write to {{support_email}} with your order number.",
    "friendly": "Just drop us a line at {{support_email}} with your order number and we'll sort it right out!",
    "concise": "Send your order number to {{support_email}}.",
}

_COMPENSATION_LINE: Dict[str, str] = {
    "professional": (
        "A full refund or a free replacement is ready for you now — whichever you prefer, "
        "and no return shipment is required."
    ),
    "friendly": (
        "A refund or a brand-new replacement is already set aside for you — just tell us which "
        "you'd like and we'll take care of it today!"
    ),
    "concise": "A full refund or free replacement is ready — your choice.",
}

_APOLOGY_INTENSIFIER: Dict[str, str] = {
    "professional": "We understand how disruptive this must have been.",
    "friendly": "We know how frustrating that feels, and we're truly sorry.",
    "concise": "We understand the disruption.",
}


def draft_reply(
    review: str,
    tone: str = "professional",
    marketplace: str = "amazon",
    refund_ready: bool = False,
) -> ToolResult:
    """根据单条差评生成英文客服回复草稿与发送前自检项.

    草稿结构固定为: 致谢 → 复述具体问题 → 责任承担 → (补偿承诺) → 补救动作 →
    联系方式占位, 且 ``{{support_email}}`` **始终出现**, 供 Bot 侧二次替换真实邮箱.

    :param review: 差评原文 (1-2000 字符).
    :param tone: 语气 professional(正式) / friendly(亲和) / concise(极简).
    :param marketplace: 渠道标识, 决定合规自检项 (如亚马逊禁止以补偿换好评).
    :param refund_ready: 是否已备好退款/补偿方案; True 时草稿写入补偿承诺并提升道歉强度.
    :returns: data 含 theme / tone / apology_level / reply_draft / checklist / word_count.
    :raises ToolError: 语气非法或渠道非法.
    """
    key = tone.strip().lower()
    if key not in _TONE_OPENER:
        raise ToolError(f"不支持的语气 {tone!r}, 可选: {sorted(_TONE_OPENER)}")
    market = _marketplace_or_error(marketplace, "amazon")
    normalized_tone = key

    theme = _theme_of(review)
    matched = _keyword_hits(review)

    apology_level = "high" if theme in HIGH_APOLOGY_THEMES else "medium"
    if refund_ready and apology_level == "medium":
        apology_level = "high"

    if matched:
        detail = "、".join(matched[:3])
    else:
        detail = _truncate(review, 60)

    if apology_level == "high":
        opener = f"{_TONE_OPENER[normalized_tone]} {_APOLOGY_INTENSIFIER[normalized_tone]}"
    else:
        opener = _TONE_OPENER[normalized_tone]

    parts = [
        opener,
        f"You mentioned the issue of {theme} ({detail}).",
        _TONE_ACCOUNTABILITY[normalized_tone],
    ]
    if refund_ready:
        parts.append(_COMPENSATION_LINE[normalized_tone])
    parts.append(_TONE_REMEDY[normalized_tone])
    parts.append(_TONE_CLOSING[normalized_tone])
    reply_draft = " ".join(parts)

    checklist = [
        "把 {{support_email}} 替换为真实客服邮箱后再发送",
        f"确认回复中的问题归因（{theme}）与买家实际描述一致",
        "核对订单号/买家 ID 已填写，补偿金额与已审批方案一致" if refund_ready
        else "发送前确认补偿口径已获授权，避免超额承诺",
        MARKETPLACE_CHECKLIST[market],
        "检查未使用绝对化承诺（如 100%、永久）等易触发平台审核的措辞",
    ]

    return ToolResult.success(
        theme=theme,
        tone=normalized_tone,
        apology_level=apology_level,
        reply_draft=reply_draft,
        checklist=checklist,
        word_count=len(reply_draft.split()),
    )


_PARAM_MARKETPLACE = Param(
    name="marketplace",
    type="string",
    required=False,
    default="amazon",
    enum=["amazon", "shopee", "tiktok", "temu", "general"],
    description=(
        "销售渠道标识。渠道不改变差评主题归因, 但决定运营口径: amazon 走站内信且严禁以补偿换好评, "
        "shopee/tiktok 走站内 IM, temu 由平台代客服, general 为通用兜底。默认 amazon。"
    ),
)

TOOLS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        name="analyze_reviews",
        title="多平台差评主题洞察",
        description=(
            "输入一行一条的中英文差评原文, 本地关键词归因出主题分布: "
            "物流时效/包装破损/尺寸偏差/质量做工/客服响应/描述不符/价格价值/气味材质, "
            "返回负面占比、Top 主题(含严重度与原文样例)、以及可直接落地的中文改进清单。"
            "全程离线计算, 不依赖外部接口。"
        ),
        params=(
            Param(
                name="reviews",
                type="array",
                required=True,
                items_type="string",
                max_length=500,
                description="差评原文列表, 一行一条, 支持中英文, 最多 500 条。",
            ),
            _PARAM_MARKETPLACE,
            Param(
                name="top_n",
                type="integer",
                required=False,
                default=5,
                minimum=1,
                maximum=20,
                description="返回的主题数量上限 1-20, 按命中条数降序、主题名升序取, 默认 5。",
            ),
        ),
        category="insight",
        tags=("差评", "电商", "洞察", "跨境"),
        handler=analyze_reviews,
    ),
    ToolSpec(
        name="draft_reply",
        title="差评英文回复草稿生成",
        description=(
            "针对单条差评生成英文客服回复草稿: 自动归因问题主题、按语气(正式/亲和/极简)套用模板, "
            "输出致谢+复述问题+责任承担+补救动作+联系方式占位的完整文本, "
            "并给出发送前自检项(含渠道合规提醒)。refund_ready 为 true 时写入退款/补偿承诺。"
        ),
        params=(
            Param(
                name="review",
                type="string",
                required=True,
                min_length=1,
                max_length=2000,
                description="单条差评原文, 1-2000 字符, 支持中英文。",
            ),
            Param(
                name="tone",
                type="string",
                required=False,
                default="professional",
                enum=["professional", "friendly", "concise"],
                description="回复语气: professional 正式 / friendly 亲和 / concise 极简, 默认 professional。",
            ),
            _PARAM_MARKETPLACE,
            Param(
                name="refund_ready",
                type="boolean",
                required=False,
                default=False,
                description="是否已准备好退款/补偿方案; true 时草稿写入补偿承诺并把道歉强度提升为 high。",
            ),
        ),
        category="insight",
        tags=("差评", "客服", "回复", "跨境"),
        handler=draft_reply,
    ),
)