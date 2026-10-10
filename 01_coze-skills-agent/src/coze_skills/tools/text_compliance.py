"""小红书/电商文案「合规禁限词 + 敏感表述」检测.

设计说明:
1. 词库全部内置为纯 Python 常量 —— 插件网关跑在最小镜像里, 不读外部文件、不发网络.
2. 不同平台词库宽松度不同 (见 ``PLATFORM_BANK_RULES``): 国内内容电商 (xhs/douyin/taobao)
   同时启用「平台软性词」, 而 amazon/general 只查法定高危词, 避免误杀正常促销表达.
3. 命中结果按 (词库类别, 严重度) 汇总为风险等级, 并生成把高危词替换为合规建议词后的
   ``rewritten_text``, 供 Agent 直接回给用户「一键改写」.
4. 类型收敛/长度校验已由 ``ToolSpec.coerce_and_validate`` 在网关层完成, handler 内只做
   业务级防御 (批量元素非字符串、批量条数超限); 非字符串元素统一 **抛 ToolError**
   (由 runner 转成失败 ToolResult), ``check_compliance`` 与 ``batch_check`` 保持同一策略.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from coze_skills.core.spec import Param, ToolError, ToolResult, ToolSpec

#: 绝对化用语 —— 《广告法》第九条高危词
ABSOLUTE_WORDS: Tuple[str, ...] = (
    "国家级", "世界级", "最高级", "最佳", "第一", "全网第一", "唯一", "首个",
    "顶级", "极致", "王牌", "销量第一", "全国第一", "绝无仅有", "史无前例",
    "万能", "100%",
)

#: 普通商品禁用医疗功效宣称
MEDICAL_WORDS: Tuple[str, ...] = (
    "治疗", "治愈", "根治", "消炎", "止痛", "药效", "修复受损细胞", "抗癌",
    "降血压", "降血糖", "丰胸", "壮阳", "脱发再生",
    # 「脱发」单列: 「治疗脱发」「防脱」类症状宣称同样违规, 不能被 13 字长词漏掉.
    "脱发",
)

#: 金融/投资类合规禁语
FINANCE_WORDS: Tuple[str, ...] = (
    "稳赚", "保本", "无风险", "零风险", "高收益", "日入过万", "躺赚", "内幕消息", "必涨",
)

#: 软性风险词 —— 非法定禁词, 但平台限流/易被举报, 提示改写
SOFT_RISK_WORDS: Tuple[str, ...] = (
    "超值", "爆款", "限时秒杀", "亏本", "史上最低", "免费送",
)

#: 正则型极限表述
SUPERLATIVE_PATTERNS: Tuple[str, ...] = (
    r"最[低价好优劣佳]",
    r"第[0-9一二三四五六七八九十]+名",
    r"[0-9]+%有效",
    r"永久(有效|使用)",
    r"包治百病",
)

#: 词 -> 合规改写建议
SUGGESTIONS: Dict[str, str] = {
    # 绝对化用语
    "国家级": "高标准", "世界级": "国际水准", "最高级": "高等级", "最佳": "优选",
    "第一": "领先", "全网第一": "销量领先", "唯一": "少有", "首个": "首批",
    "顶级": "高端", "极致": "出色", "王牌": "明星", "销量第一": "销量领先",
    "全国第一": "销量领先", "绝无仅有": "少见", "史无前例": "突破以往",
    "万能": "多功能", "100%": "百分百",
    # 医疗功效
    "治疗": "改善", "治愈": "缓解", "根治": "调理", "消炎": "舒缓", "止痛": "更舒适",
    "药效": "成分作用", "修复受损细胞": "呵护肌肤", "抗癌": "健康饮食",
    "降血压": "关注血压健康", "降血糖": "关注血糖健康", "丰胸": "自信曲线",
    "壮阳": "活力状态", "脱发再生": "头皮养护", "脱发": "头皮状态",
    # 金融合规
    "稳赚": "收益存在波动", "保本": "本金随市场波动", "无风险": "存在风险",
    "零风险": "亦有风险", "高收益": "历史回报", "日入过万": "理性看待收益",
    "躺赚": "被动收入", "内幕消息": "公开信息", "必涨": "可能上涨",
    # 平台软性词
    "超值": "性价比高", "爆款": "热销", "限时秒杀": "限时优惠", "亏本": "让利",
    "史上最低": "价格实惠", "免费送": "赠送活动",
    # 正则模式
    "最[低价好优劣佳]": "较低/较好", "第[0-9一二三四五六七八九十]+名": "排名靠前",
    "[0-9]+%有效": "效果显著", "永久(有效|使用)": "长期使用", "包治百病": "多种用途",
}

#: (词库, 类别, 严重度) —— 顺序即报告顺序
_WORD_BANKS: Tuple[Tuple[Tuple[str, ...], str, str], ...] = (
    (ABSOLUTE_WORDS, "绝对化用语", "high"),
    (MEDICAL_WORDS, "医疗功效", "high"),
    (FINANCE_WORDS, "金融合规", "high"),
    (SOFT_RISK_WORDS, "平台软性词", "medium"),
)

#: 平台 -> 启用的词库类别 (宽松度差异的唯一开关)
PLATFORM_BANK_RULES: Dict[str, Tuple[str, ...]] = {
    "xhs": ("绝对化用语", "医疗功效", "金融合规", "平台软性词", "正则模式"),
    "douyin": ("绝对化用语", "医疗功效", "金融合规", "平台软性词", "正则模式"),
    "taobao": ("绝对化用语", "医疗功效", "金融合规", "平台软性词", "正则模式"),
    "general": ("绝对化用语", "医疗功效", "金融合规", "正则模式"),
    "amazon": ("绝对化用语", "医疗功效", "金融合规", "正则模式"),
}

#: 正则模式建议改写后的兜底文案
_PATTERN_FALLBACK = "删除或改为客观描述"

_COMPILED: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), p) for p in SUPERLATIVE_PATTERNS
)


def _find_all(haystack: str, needle: str) -> List[int]:
    """返回 needle 在 haystack 中全部出现位置 (含重叠, needle 非空)."""
    positions: List[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return positions
        positions.append(idx)
        start = idx + 1


def _match_words(text: str, lower: str) -> List[Dict[str, Any]]:
    """把整段文本对全部词库做一次扫描, 返回原始命中 (未按平台过滤).

    :param text: 原文 (提供位置索引).
    :param lower: 原文小写副本 (英文词库大小写不敏感匹配).
    :returns: 命中记录列表, 每个词只出现一次并附全部位置.
    """
    hits: List[Dict[str, Any]] = []
    for bank, category, severity in _WORD_BANKS:
        for word in bank:
            positions = _find_all(lower, word.lower())
            if positions:
                hits.append({
                    "word": word,
                    "category": category,
                    "severity": severity,
                    "suggestion": SUGGESTIONS.get(word, _PATTERN_FALLBACK),
                    "positions": positions,
                })
    return hits


def _match_patterns(lower: str) -> List[Dict[str, Any]]:
    """正则型极限表述扫描, word 字段记录实际命片.

    :param lower: 原文小写副本.
    :returns: 命中记录 (category=正则模式, severity=medium, 同一命片去重).
    """
    hits: List[Dict[str, Any]] = []
    seen: Dict[str, List[int]] = {}
    for compiled, raw_pattern in _COMPILED:
        for m in compiled.finditer(lower):
            snippet = m.group(0)
            key = snippet.lower()
            if key in seen:
                seen[key].append(m.start())
            else:
                seen[key] = [m.start()]
                hits.append({
                    "word": snippet,
                    "category": "正则模式",
                    "severity": "medium",
                    "suggestion": SUGGESTIONS.get(raw_pattern, _PATTERN_FALLBACK),
                    "positions": seen[key],
                })
    return hits


def _risk_level(hits: List[Dict[str, Any]]) -> str:
    """按命中列表汇总风险等级: 任一 high -> high; 有命中 -> medium; 无 -> low."""
    if any(h["severity"] == "high" for h in hits):
        return "high"
    if hits:
        return "medium"
    return "low"


def _rewrite(text: str, hits: List[Dict[str, Any]]) -> str:
    """按建议词改写高危表述.

    替换顺序: 命片长度降序 (先换 「100%有效」 再换 「100%」, 先换 「全网第一」 再换 「第一」),
    同长度按命中原词字典序, 保证对同一输入的改写结果确定可复现.

    :param text: 原文.
    :param hits: 过滤后的命中列表.
    :returns: 改写后文本; 无命中时返回原文.
    """
    ordered = sorted(hits, key=lambda h: (-len(h["word"]), h["word"]))
    rewritten = text
    for hit in ordered:
        suggestion = hit["suggestion"]
        if hit["category"] == "正则模式":
            # 正则命中是片段, 直接按片段替换为建议词
            rewritten = rewritten.replace(hit["word"], suggestion)
            continue
        rewritten = _replace_case_insensitive(rewritten, hit["word"], suggestion)
    return rewritten


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    """大小写不敏感地把 text 中全部 needle 替换为 replacement (needle 非空)."""
    lower, needle_lower = text.lower(), needle.lower()
    out: List[str] = []
    cursor = 0
    while True:
        idx = lower.find(needle_lower, cursor)
        if idx < 0:
            out.append(text[cursor:])
            return "".join(out)
        out.append(text[cursor:idx])
        out.append(replacement)
        cursor = idx + len(needle)


def _detect_one(text: str, platform: str, extra_words: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
    """单条文案的完整检测流程 (词库过滤 + 正则 + 品牌自定义词).

    :param text: 待检测文案.
    :param platform: 平台标识, 决定启用哪些词库类别.
    :param extra_words: 品牌自定义补充禁词, 命中记为「品牌自定义词」/severity=high.
    :returns: 命中列表.
    """
    lower = text.lower()
    enabled = PLATFORM_BANK_RULES.get(platform, PLATFORM_BANK_RULES["general"])
    hits = [h for h in _match_words(text, lower) if h["category"] in enabled]
    if "正则模式" in enabled:
        hits.extend(_match_patterns(lower))
    for word in extra_words:
        if not word:
            continue
        positions = _find_all(lower, word.lower())
        if positions:
            hits.append({
                "word": word,
                "category": "品牌自定义词",
                "severity": "high",
                "suggestion": "按品牌法务意见删除或改写",
                "positions": positions,
            })
    return hits


def _validate_batch_items(items: Any, param_name: str) -> List[str]:
    """批量入参的元素类型防御; 非字符串直接抛 ToolError.

    与 ``check_compliance`` 保持同一策略: 业务级输入问题一律抛 ``ToolError``,
    由 runner 统一转成 ``ToolResult.fail``, 避免 handler 内外两套返回形状.

    :param items: 调用方传入的数组参数.
    :param param_name: 参数名, 用于错误文案.
    :returns: 校验通过的字符串列表.
    :raises ToolError: 元素不是字符串.
    """
    result: List[str] = []
    for idx, item in enumerate(items):
        if not isinstance(item, str):
            raise ToolError(f"{param_name} 第 {idx} 个元素期望 string, 实际 {type(item).__name__}")
        result.append(item)
    return result


def _platform_or_error(platform: str) -> str:
    """归一化平台名; 非法值抛 ToolError (网关已枚举校验, 此处兜直连调用)."""
    key = (platform or "xhs").strip().lower()
    if key not in PLATFORM_BANK_RULES:
        raise ToolError(f"不支持的平台 {platform!r}, 可选: {sorted(PLATFORM_BANK_RULES)}")
    return key


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------

def check_compliance(
    text: str,
    platform: str = "xhs",
    extra_words: Optional[List[str]] = None,
) -> ToolResult:
    """检测单条商品文案/笔记正文的合规禁限词与敏感表述.

    :param text: 待检测文本 (非空, 已由网关完成长度校验).
    :param platform: 平台标识 xhs/douyin/taobao/amazon/general, 决定词库宽松度.
    :param extra_words: 品牌自定义补充禁词, 命中即 high.
    :returns: data 含 risk_level / hit_count / hits / rewritten_text / platform.
    :raises ToolError: 平台非法或 extra_words 含非字符串元素.
    """
    norm_platform = _platform_or_error(platform)
    extras = _validate_batch_items(extra_words or [], "extra_words")

    hits = _detect_one(text, norm_platform, tuple(extras))
    return ToolResult.success(
        risk_level=_risk_level(hits),
        hit_count=len(hits),
        hits=hits,
        rewritten_text=_rewrite(text, hits),
        platform=norm_platform,
    )


def batch_check(texts: List[str], platform: str = "xhs") -> ToolResult:
    """批量检测多条文案, 输出高危占比与一句话结论.

    :param texts: 待检文案列表 (最多 200 条); 空字符串条目跳过检测、记为 low, 不报错.
    :param platform: 平台标识, 同 ``check_compliance``.
    :returns: data 含 total / high_risk_count / summary / results / verdict.
    :raises ToolError: 批量为空、超过 200 条、元素非字符串或平台非法.
    """
    norm_platform = _platform_or_error(platform)
    items = _validate_batch_items(texts, "texts")
    if not items:
        raise ToolError("texts 不能为空列表")
    if len(items) > 200:
        raise ToolError(f"texts 最多 200 条, 实际 {len(items)}")

    results: List[Dict[str, Any]] = []
    summary: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    category_counter: Dict[str, int] = {}
    for idx, item in enumerate(items):
        if not item:
            # 防御: 空文案跳过检测, 但仍占位以保持 results 与 texts 等长同序
            results.append({"index": idx, "risk_level": "low", "hit_count": 0, "top_hits": []})
            summary["low"] += 1
            continue
        hits = _detect_one(item, norm_platform)
        level = _risk_level(hits)
        summary[level] += 1
        ordered = sorted(hits, key=lambda h: (0 if h["severity"] == "high" else 1, h["word"]))
        for hit in hits:
            category_counter[hit["category"]] = category_counter.get(hit["category"], 0) + 1
        results.append({
            "index": idx,
            "risk_level": level,
            "hit_count": len(hits),
            "top_hits": [h["word"] for h in ordered[:3]],
        })

    high = summary["high"]
    if high == 0 and summary["medium"] == 0:
        verdict = f"{len(items)} 条均未命中禁限词, 可直接发布"
    elif high == 0:
        verdict = f"{len(items)} 条中 {summary['medium']} 条存在软性风险, 建议按提示微调措辞"
    else:
        top_category = max(category_counter, key=lambda k: category_counter[k])
        verdict = f"{len(items)} 条中 {high} 条高危, 建议优先改写{top_category}"

    return ToolResult.success(
        total=len(items),
        high_risk_count=high,
        summary=summary,
        results=results,
        verdict=verdict,
    )


_PARAMS_PLATFORM = Param(
    name="platform",
    type="string",
    required=False,
    default="xhs",
    enum=["xhs", "douyin", "taobao", "amazon", "general"],
    description=(
        "投放平台标识, 不同平台词库宽松度不同: xhs/douyin/taobao 额外启用「平台软性词」"
        "(超值/爆款/亏本等易限流表达); amazon/general 仅查法定高危词与正则极限表述。默认 xhs。"
    ),
    example="douyin",
)

TOOLS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        name="check_compliance",
        title="文案合规禁限词检测",
        description=(
            "检测小红书/抖音/淘宝/亚马逊商品文案中的广告法禁限词与敏感表述: "
            "绝对化用语、医疗功效宣称、金融违规承诺、极限词正则、平台软性风险词, "
            "输出风险等级、命中详情(含出现位置与合规建议)以及可直接使用的改写文本。"
        ),
        params=(
            Param(
                name="text",
                type="string",
                required=True,
                min_length=1,
                max_length=5000,
                description="待检测的商品文案/笔记正文, 1-5000 字符。",
                example="这款面膜全网销量第一, 药效显著, 七天美白立竿见影, 绝对无效全额退款!",
            ),
            _PARAMS_PLATFORM,
            Param(
                name="extra_words",
                type="array",
                required=False,
                items_type="string",
                description="品牌自定义补充禁词列表; 命中记为「品牌自定义词」且风险为 high。",
                example=["旗舰店", "官方指定"],
            ),
        ),
        category="compliance",
        tags=("合规", "文案", "广告法", "小红书"),
        handler=check_compliance,
    ),
    ToolSpec(
        name="batch_check",
        title="批量文案合规体检",
        description=(
            "一次检测多条商品文案/笔记 (最多 200 条), 返回每条的风险等级与 Top 命中词、"
            "高危条数、风险分布汇总, 以及「N 条中 M 条高危, 建议优先改写XX」的一句话结论, "
            "适合发笔记前对文案库做整体体检。"
        ),
        params=(
            Param(
                name="texts",
                type="array",
                required=True,
                items_type="string",
                max_length=200,
                description="批量待检文案列表, 最多 200 条; 空字符串条目跳过检测并记为 low。",
                example=[
                    "全网最低价, 错过再等一年!",
                    "新中式缠花发簪, 手工绕线, 日常通勤也能戴",
                ],
            ),
            _PARAMS_PLATFORM,
        ),
        category="compliance",
        tags=("合规", "批量", "文案", "体检"),
        handler=batch_check,
    ),
)