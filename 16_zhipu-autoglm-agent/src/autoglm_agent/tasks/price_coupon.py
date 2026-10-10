from __future__ import annotations

"""手机端「跨平台比价 + 领券」业务闭环：
聚海搜型号比价 → 淘享岛比价 → 比邻红包领券 → 输出到手最低价购买建议。"""

import json
import os
import re
import time
from typing import Any, Dict

from ..act.actions import Controller
from ..config import Settings
from ..flow.engine import FlowEngine, FlowResult
from ..flow.step import Flow, Step
from ..locate.spec import ElementSpec
from ..perception.screen import Screen

PRICE_RX = re.compile(r"¥(\d+(?:\.\d+)?)")

SEARCH_BOX = ElementSpec(
    name="search_box", texts=["搜索商品"], patterns=["搜索"], editable=True)
SEARCH_GO = ElementSpec(name="search_go", texts=["搜索"], require_clickable=True)
CLAIM = ElementSpec(name="claim", texts=["立即领取", "领 取"], patterns=["^立即领[取戗]$"])


def _collect_prices(ctrl: Controller, ctx: Dict[str, Any], key: str, max_pages: int = 4) -> None:
    prices = set(ctx.get(key, []))
    last_sig = None
    for _ in range(max_pages):
        screen = ctrl.snapshot()
        for t in screen.all_texts():
            prices.update(PRICE_RX.findall(t))
        sig = "|".join(screen.all_texts()[:25])
        if sig == last_sig:
            break
        last_sig = sig
        ctrl.device.scroll_down(0.7)
        time.sleep(0.2)
    ctx[key] = sorted(p for p in prices if p)


def build_flow() -> Flow:
    flow = Flow(flow_id="mobile-price-coupon", title="跨平台比价领券助手")

    def open_juhai(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("juhai")

    def search_juhai(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.type_text(SEARCH_BOX, "无线蓝牙耳机")
        ctrl.click(SEARCH_GO)

    def read_juhai(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        _collect_prices(ctrl, ctx, "juhai_prices")

    def open_taoxiang(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("taoxiang")
        ctrl.type_text(SEARCH_BOX, "无线蓝牙耳机")
        ctrl.click(SEARCH_GO)

    def read_taoxiang(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        _collect_prices(ctrl, ctx, "taoxiang_prices")

    def open_bilin(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("bilin")

    def claim(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.click(CLAIM)

    def read_final(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        _collect_prices(ctrl, ctx, "coupon_prices")

    def report(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        all_offers = {
            "聚海严选": [float(p) for p in ctx.get("juhai_prices", [])],
            "淘享岛": [float(p) for p in ctx.get("taoxiang_prices", [])],
            "比邻券后价": [float(p) for p in ctx.get("coupon_prices", [])],
        }
        best_platform, best_price = None, None
        for platform, vals in all_offers.items():
            if not vals:
                continue
            v = min(vals)
            if best_price is None or v < best_price:
                best_platform, best_price = platform, v
        ctx["report"] = {
            "goal": "无线蓝牙耳机 跨平台比价领券",
            "offers": all_offers,
            "recommendation": {"platform": best_platform, "price": best_price},
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def has_prices(key: str, min_count: int):
        def _v(ctrl: Controller, ctx: Dict[str, Any]) -> bool:
            return len(ctx.get(key, [])) >= min_count
        return _v

    flow.add(Step("launch_juhai", "启动聚海App并治理广告弹窗", open_juhai,
                  verify=lambda c, x: c.snapshot().contains("搜索商品"),
                  verify_message="聚海搜索页未就绪", retries=2, on_fail="recover_back"))
    flow.add(Step("search_juhai", "聚海搜索目标商品", search_juhai,
                  verify=lambda c, x: c.snapshot().contains("到手价"),
                  verify_message="聚海结果页未出现价格", retries=2, on_fail="recover_back"))
    flow.add(Step("read_juhai", "滚动采集聚海全部报价", read_juhai,
                  verify=has_prices("juhai_prices", 2),
                  verify_message="聚海报价不足", retries=1))
    flow.add(Step("launch_taoxiang", "切换淘享岛搜索比价", open_taoxiang,
                  verify=lambda c, x: c.snapshot().contains("淘享岛"),
                  verify_message="淘享岛结果页未就绪", retries=2, on_fail="recover_back"))
    flow.add(Step("read_taoxiang", "采集淘享岛报价", read_taoxiang,
                  verify=has_prices("taoxiang_prices", 1),
                  verify_message="淘享岛报价缺失", retries=1))
    flow.add(Step("launch_bilin", "切换比邻红包（自动允许权限弹窗）", open_bilin,
                  verify=lambda c, x: c.snapshot().contains("无门槛券"),
                  verify_message="券中心未就绪", retries=2, on_fail="recover_back"))
    flow.add(Step("claim", "领取耳机品类券", claim,
                  verify=lambda c, x: c.snapshot().contains("券已领取"),
                  verify_message="领券后状态未确认", retries=2,
                  on_fail="recover_back"))
    flow.add(Step("read_final", "读取券后价", read_final,
                  verify=has_prices("coupon_prices", 1), retries=1))
    flow.add(Step("report", "生成比价购买建议", report,
                  verify=lambda c, x: bool(x.get("report")), retries=1))
    return flow


def run(controller: Controller, settings: Settings, resume: bool = True) -> FlowResult:
    engine = FlowEngine(controller, settings)
    return engine.run(build_flow(), resume=resume)


def write_artifact(result: FlowResult, settings: Settings) -> str:
    os.makedirs(settings.artifact_dir, exist_ok=True)
    path = os.path.join(settings.artifact_dir, "price_coupon_report.json")
    payload = {"success": result.success,
               "steps": [o.__dict__ for o in result.outcomes],
               "report": result.ctx.get("report")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
