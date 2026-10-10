#!/usr/bin/env python3
"""一键演示入口：默认在虚拟设备上完整跑通两条业务闭环（零依赖、离线可跑）。

用法：
  python run_demo.py                 # 虚拟设备演示（含弹窗/噪声/漂移容错展示）
  DEVICE=adb python run_demo.py      # 真机 Android（需 adb 连接）
  ZHIPU_API_KEY=sk-xxx python run_demo.py --agent "帮我给老婆买一束花"  # 在线 AutoGLM 自主规划
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autoglm_agent.act.actions import Controller
from autoglm_agent.config import load_settings
from autoglm_agent.device.base import Device
from autoglm_agent.device.virtual import VirtualDevice
from autoglm_agent.tasks import invoice_expense, price_coupon
from autoglm_agent.tasks.scenarios import (desktop_invoice_with_popup,
                                           mobile_price_coupon_with_popups)
from autoglm_agent.vision.ocr import VirtualJsonOcr, default_ocr


def build_real_device(settings) -> Device:
    kind = os.environ.get("DEVICE", "virtual")
    if kind == "adb":
        from autoglm_agent.device.adb import AdbDevice
        return AdbDevice()
    from autoglm_agent.device.desktop import DesktopDevice
    return DesktopDevice()


def run_virtual_demo(settings) -> int:
    print("=" * 62)
    print("AutoGLM 端侧智能体 · 虚拟设备容错演示")
    print("=" * 62)
    rc = 0

    print("\n【场景一】手机端 跨平台比价 + 领券（含开屏广告弹窗/权限弹窗/折叠区滚动）")
    dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=42)
    ctrl = Controller(dev, settings, ocr=VirtualJsonOcr())
    res = price_coupon.run(ctrl, settings, resume=False)
    for line in res.summary_lines():
        print("  " + line)
    report = res.ctx.get("report", {})
    print("  比价结果:", report.get("offers"))
    print("  购买建议:", report.get("recommendation"))
    print("  产物:", price_coupon.write_artifact(res, settings))
    rc |= 0 if res.success else 1

    print("\n【场景二】桌面端 月度发票归集 + 报销单填报（含升级弹窗/OCR 噪声/提交降级）")
    dev2 = VirtualDevice(desktop_invoice_with_popup(), width=1920, height=1080, seed=7)
    ctrl2 = Controller(dev2, settings, ocr=VirtualJsonOcr())
    res2 = invoice_expense.run(ctrl2, settings, resume=False)
    for line in res2.summary_lines():
        print("  " + line)
    rep2 = res2.ctx.get("expense_report", {})
    print("  发票合计:", rep2.get("total"), "| 邮箱页合计:", rep2.get("mail_page_total"))
    print("  报销单号:", rep2.get("expense_no"))
    print("  产物:", invoice_expense.write_artifact(res2, settings))
    rc |= 0 if res2.success else 1

    print("\n【定位轨迹抽样】（展示多通道融合与置信度）")
    for t in ctrl.trace[:6]:
        print("  ", t)
    print("\n结果:", "全部闭环通过 ✅" if rc == 0 else "存在失败步骤 ❌")
    return rc


def run_agent_goal(goal: str, settings) -> int:
    from autoglm_agent.agent.client import AgentUnavailable, make_planner, AutoGLMPlanner, AutonomousRunner, GLMClient

    dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=42)
    ctrl = Controller(dev, settings, ocr=VirtualJsonOcr())
    planner: AutoGLMPlanner = make_planner(settings)
    if planner is None:
        print("未配置 ZHIPU_API_KEY：在线 AutoGLM 规划不可用（脚本闭环不受影响）。")
        return 2
    runner = AutonomousRunner(ctrl, planner)
    try:
        out = runner.run(goal)
    except AgentUnavailable as e:
        print("Agent 不可用:", e)
        return 2
    print("Agent 结果:", out.get("status"), out.get("summary") or out.get("reason"))
    return 0 if out.get("status") == "done" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoGLM 端侧智能体演示入口")
    parser.add_argument("--agent", metavar="GOAL", help="以在线 AutoGLM 规划执行自然语言目标")
    args = parser.parse_args()
    settings = load_settings()
    os.makedirs(settings.artifact_dir, exist_ok=True)
    if args.agent:
        return run_agent_goal(args.agent, settings)
    if os.environ.get("DEVICE", "virtual") == "virtual":
        return run_virtual_demo(settings)
    dev = build_real_device(settings)
    ocr = default_ocr(for_virtual=False)
    ctrl = Controller(dev, settings, ocr=ocr)
    res = invoice_expense.run(ctrl, settings, resume=True)
    for line in res.summary_lines():
        print(line)
    return 0 if res.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
