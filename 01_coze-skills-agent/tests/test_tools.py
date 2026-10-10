"""垂类工具行为测试 (合规检测 / 差评洞察 / 回复草稿).

只钉业务语义与边界: 高危词必须被拦截且给出可用的改写文本、
主题排序必须确定、草稿必须保留客服占位符, 不钉具体词表和措辞.
"""

from __future__ import annotations

import pytest

from coze_skills.core.registry import build_default_registry
from coze_skills.core.runner import ToolRunner
from coze_skills.core.spec import ToolResult

REVIEWS = [
    "Package arrived completely broken, the box was crushed",
    "Delivery was late by two weeks, very disappointed",
    "Size too small, does not fit at all",
    "Terrible quality, broke after 3 days",
    "Customer service never replied to my refund request",
]


@pytest.fixture(scope="module")
def runner() -> ToolRunner:
    """基于真实注册表构造执行器, 保证测的是线上同一条链路."""
    return ToolRunner(build_default_registry())


def _data(result: ToolResult) -> dict:
    """断言调用成功并取出 data. 失败时直接暴露 error 便于定位."""
    assert result.ok, result.error
    return result.data


# ---------------------------------------------------------- 合规检测 ----
def test_check_compliance_flags_high_risk_words(runner: ToolRunner) -> None:
    """绝对化 + 医疗功效同时命中必须判为 high, 并给出去词后的改写文本."""
    data = _data(runner.invoke("check_compliance", {"text": "全网第一！治疗脱发神器，7天见效，100%有效"}))
    assert data["risk_level"] == "high"
    words = {hit["word"] for hit in data["hits"]}
    assert {"全网第一", "治疗", "脱发", "100%"} <= words
    for hit in data["hits"]:
        assert hit["suggestion"], "每个命中项都必须给出可执行的合规改写建议"
        assert hit["positions"]
    assert [h["severity"] for h in data["hits"] if h["word"] in ("全网第一", "治疗", "脱发", "100%")] == ["high"] * 4
    for banned in ("全网第一", "治疗", "脱发"):
        assert banned not in data["rewritten_text"]


def test_check_compliance_clean_text_is_low_risk(runner: ToolRunner) -> None:
    """干净文案不应误报, 否则工具会被运营直接弃用."""
    data = _data(runner.invoke("check_compliance", {"text": "纯棉透气, 日常通勤百搭, 洗涤简单"}))
    assert data["risk_level"] == "low"
    assert data["hit_count"] == 0
    assert data["hits"] == []
    assert data["rewritten_text"] == "纯棉透气, 日常通勤百搭, 洗涤简单"


def test_check_compliance_soft_words_are_medium(runner: ToolRunner) -> None:
    """软性风险词不应升级为 high, 否则高危告警失去区分度."""
    data = _data(runner.invoke("check_compliance", {"text": "限时秒杀, 爆款回归, 超值套装"}))
    assert data["risk_level"] == "medium"
    assert all(hit["severity"] == "medium" for hit in data["hits"])


def test_check_compliance_extra_words_and_dedup(runner: ToolRunner) -> None:
    """品牌自定义禁词必须生效; 同词多处出现只报一次且带全部位置."""
    data = _data(
        runner.invoke("check_compliance", {"text": "某品牌词很好用, 某品牌词再出现一次", "extra_words": ["某品牌词"]})
    )
    hit = next(h for h in data["hits"] if h["word"] == "某品牌词")
    assert hit["category"] == "品牌自定义词"
    assert len(hit["positions"]) == 2
    assert len([h for h in data["hits"] if h["word"] == "某品牌词"]) == 1


def test_batch_check_keeps_input_order_and_counts(runner: ToolRunner) -> None:
    """批量结果必须与输入等长同序, 否则运营无法把结论回填到原表."""
    texts = ["纯净文案一条", "全网第一！包治百病", "", "销量第一的神器"]
    data = _data(runner.invoke("batch_check", {"texts": texts}))
    assert data["total"] == len(texts)
    assert [r["index"] for r in data["results"]] == [0, 1, 2, 3]
    assert data["results"][0]["risk_level"] == "low"
    assert data["results"][1]["risk_level"] == "high"
    assert data["high_risk_count"] == 2
    assert data["summary"]["high"] == 2
    assert data["results"][1]["top_hits"]
    assert len(data["results"][1]["top_hits"]) <= 3
    assert data["verdict"]


# ---------------------------------------------------------- 差评洞察 ----
def test_analyze_reviews_ranks_themes_and_actions(runner: ToolRunner) -> None:
    """主题必须可复现地排序, 且每条主题都要落到可执行建议."""
    first = _data(runner.invoke("analyze_reviews", {"reviews": REVIEWS, "marketplace": "amazon", "top_n": 5}))
    second = _data(runner.invoke("analyze_reviews", {"reviews": REVIEWS, "marketplace": "amazon", "top_n": 5}))
    assert first["total"] == len(REVIEWS)
    assert first["themes"] == second["themes"], "相同输入必须产生相同排序 (确定性)"
    assert {"物流时效", "包装破损", "质量做工"} & {t["theme"] for t in first["themes"]}
    counts = [t["count"] for t in first["themes"]]
    assert counts == sorted(counts, reverse=True)
    assert first["action_items"]
    assert 0.0 <= first["negative_ratio"] <= 1.0


def test_analyze_reviews_respects_top_n_and_quotes(runner: ToolRunner) -> None:
    """top_n 必须生效; 引用截断到 80 字符以内防止撑爆模型上下文."""
    data = _data(runner.invoke("analyze_reviews", {"reviews": REVIEWS, "top_n": 2}))
    assert len(data["themes"]) <= 2
    for quotes in data["sample_quotes"].values():
        assert len(quotes) <= 2
        assert all(len(q) <= 80 for q in quotes)


def test_analyze_reviews_handles_chinese_input(runner: ToolRunner) -> None:
    """中文差评同样要能被分词与主题命中, 不能只支持英文."""
    data = _data(
        runner.invoke("analyze_reviews", {"reviews": ["物流太慢了，等了两周", "包装破损，盒子压扁了", "质量很差，用两天就坏了"]})
    )
    themes = {t["theme"] for t in data["themes"]}
    assert {"物流时效", "包装破损", "质量做工"} <= themes


# ---------------------------------------------------------- 回复草稿 ----
def test_draft_reply_always_keeps_placeholder(runner: ToolRunner) -> None:
    """占位符缺失会导致 Bot 侧无法替换真实客服邮箱, 属硬性契约."""
    for tone in ("professional", "friendly", "concise"):
        data = _data(runner.invoke("draft_reply", {"review": REVIEWS[0], "tone": tone}))
        assert "{{support_email}}" in data["reply_draft"]
        assert data["tone"] == tone
        assert data["word_count"] > 0
        assert data["checklist"]


def test_draft_reply_tones_differ(runner: ToolRunner) -> None:
    """三种语气必须产出不同文本, 否则 tone 参数形同虚设."""
    drafts = {
        tone: _data(runner.invoke("draft_reply", {"review": REVIEWS[1], "tone": tone}))["reply_draft"]
        for tone in ("professional", "friendly", "concise")
    }
    assert len(set(drafts.values())) == 3
    assert len(drafts["concise"]) < len(drafts["professional"])


def test_draft_reply_refund_raises_apology_level(runner: ToolRunner) -> None:
    """已备好补偿方案时应体现更高歉意等级, 但不能越过上限."""
    without = _data(runner.invoke("draft_reply", {"review": REVIEWS[2], "refund_ready": False}))
    with_refund = _data(runner.invoke("draft_reply", {"review": REVIEWS[2], "refund_ready": True}))
    assert with_refund["apology_level"] in ("medium", "high")
    assert {"low", "medium", "high"} >= {with_refund["apology_level"]}
    assert without["apology_level"] in ("medium", "high")
    order = {"low": 0, "medium": 1, "high": 2}
    assert order[with_refund["apology_level"]] >= order[without["apology_level"]]


def test_tools_reject_bad_input_via_runner(runner: ToolRunner) -> None:
    """参数契约由 runner 统一拦截, 工具实现无需重复写类型判断."""
    assert not runner.invoke("check_compliance", {}).ok
    assert not runner.invoke("draft_reply", {"review": ""}).ok
    assert not runner.invoke("analyze_reviews", {"reviews": REVIEWS, "top_n": 999}).ok
    assert not runner.invoke("check_compliance", {"text": "x", "platform": "myspace"}).ok

    # 逗号分隔字符串会被 Param.coerce 收敛成数组, 这是为 LLM 传参做的兼容, 属预期行为
    coerced = runner.invoke("batch_check", {"texts": "全网第一, 纯净文案"})
    assert coerced.ok and coerced.data["total"] == 2
    # 非字符串元素必须被工具自身拒绝, 不能静默跳过
    assert not runner.invoke("batch_check", {"texts": [1, 2]}).ok
