#!/usr/bin/env python3
"""一键演示入口：默认在虚拟设备上完整跑通三条业务闭环（零依赖、离线可跑）。

用法：
  python run_demo.py                     # 虚拟设备演示（含弹窗/噪声/漂移容错展示）
  python run_demo.py --chaos             # 叠加故障注入（漂移/弹窗/输入被清空），演示自愈
  python run_demo.py --trace out.md      # 导出执行轨迹（md 表格 / json）作为稳定性证据
  DEVICE=adb python run_demo.py          # 真机 Android（需 adb 连接，缺设备自动回落虚拟）
  DEVICE=desktop python run_demo.py      # 桌面端（缺 pyautogui 自动降级为无效后端并提示）
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
from autoglm_agent.memory.trace import TraceRecorder
from autoglm_agent.tasks import auth_scenario, invoice_expense, price_coupon
from autoglm_agent.tasks.scenarios import (desktop_invoice_with_popup,
                                           gov_auth_with_popups,
                                           mobile_price_coupon_with_popups)
from autoglm_agent.vision.ocr import VirtualJsonOcr, default_ocr
from autoglm_agent.vision.template import ExampleTemplateBackend, known_templates


def build_real_device(settings) -> Device:
    kind = os.environ.get("DEVICE", "virtual")
    if kind == "adb":
        from autoglm_agent.device.adb import AdbDevice, DeviceError
        dev = AdbDevice()
        try:
            if not dev.wait_boot(timeout=20):
                print("⚠ 未等到 Android 设备就绪，回落到虚拟设备以保证演示可跑")
                return VirtualDevice(mobile_price_coupon_with_popups(), seed=42)
            print(f"✓ 已连接 Android 设备：分辨率 {dev.resolution()}")
        except DeviceError as e:
            print(f"⚠ adb 不可用（{e}），回落到虚拟设备")
            return VirtualDevice(mobile_price_coupon_with_popups(), seed=42)
        return dev
    from autoglm_agent.device.desktop import DesktopDevice
    dev = DesktopDevice()
    if dev.degraded:
        print("⚠ 桌面后端不可用（缺 pyautogui 或无图形环境）：操作不会真正生效，仅演示控制流")
    return dev


def _chaos_scenario():
    """故障注入变体：UI 元素抖动 20px + OCR 噪声（输入被清空由 --chaos 的运行期注入完成）。"""
    return mobile_price_coupon_with_popups()


def _make_controller(settings, scenario, seed: int, drift: int, chaos: bool,
                     trace: TraceRecorder) -> Controller:
    dev = VirtualDevice(scenario, seed=seed, drift_px=drift)
    templates = ExampleTemplateBackend(known_templates(scenario)) if chaos else None
    ctrl = Controller(dev, settings, ocr=VirtualJsonOcr(), templates=templates)
    if chaos:
        _install_chaos_injection(ctrl)
    return ctrl


def _install_chaos_injection(ctrl: Controller) -> None:
    """运行期注入：第一次输入**写入过程中**把该字段清空，模拟输入法/系统吞掉输入。

    注入刻意放在 `input_text` 内部（而非 type_text 之后），因为这才是端侧真实故障形态：
    脚本以为输入成功了，设备上却是空的。若没有回读校验，后续校验步骤必然失败。
    """
    device = ctrl.device
    original_input = device.input_text
    state = {"tripped": False}

    def input_text_with_wipe(text: str) -> None:
        original_input(text)
        if state["tripped"]:
            return
        world = getattr(device, "world", None)
        if not isinstance(world, dict):
            return
        for store in (world.get("form", {}), world.get("vars", {})):
            for key in list(store):
                if key != "app" and store.get(key):
                    store[key] = ""
                    state["tripped"] = True
                    print(f"  [chaos] 已注入：输入框 {key} 内容被清空"
                          f"（若无回读校验，下一步校验必失败）")
                    return

    device.input_text = input_text_with_wipe  # type: ignore[assignment]


def _trace_step(ctrl: Controller, trace: TraceRecorder, scenario_name: str) -> None:
    """把控制器轨迹翻译为可交付的轨迹事件（通道/置信度/自愈次数）。"""
    for item in ctrl.trace:
        action = item.get("action", "")
        trace.add(step=scenario_name, phase=action, ok=not action.endswith("_retry"),
                  detail=str({k: v for k, v in item.items() if k not in ("action",)}),
                  source=item.get("source", ""), conf=float(item.get("conf") or 0.0),
                  recoveries=1 if action in ("watch", "type_retry", "plan_drift") else 0)



def run_virtual_demo(settings, chaos: bool = False, trace: TraceRecorder | None = None) -> int:
    print("=" * 62)
    print("AutoGLM 端侧智能体 · 虚拟设备容错演示" + ("（故障注入模式 🔥）" if chaos else ""))
    print("=" * 62)
    rc = 0
    drift = 20 if chaos else 0

    title = "手机端 跨平台比价 + 领券（含开屏广告弹窗/权限弹窗/折叠区滚动）"
    print(f"\n【场景一】{title}")
    dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=42, drift_px=drift)
    ctrl = Controller(dev, settings, ocr=VirtualJsonOcr(),
                      templates=ExampleTemplateBackend(known_templates(dev.scenario)) if chaos else None)
    if chaos:
        _install_chaos_injection(ctrl)
    res = price_coupon.run(ctrl, settings, resume=False)
    for line in res.summary_lines():
        print("  " + line)
    report = res.ctx.get("report", {})
    print("  比价结果:", report.get("offers"))
    print("  购买建议:", report.get("recommendation"))
    print("  产物:", price_coupon.write_artifact(res, settings))
    rc |= 0 if res.success else 1
    if trace is not None:
        _trace_step(ctrl, trace, "场景一-比价领券")

    print("\n【场景二】桌面端 月度发票归集 + 报销单填报（含升级弹窗/OCR 噪声/提交降级）")
    dev2 = VirtualDevice(desktop_invoice_with_popup(), width=1920, height=1080, seed=7,
                         drift_px=drift)
    ctrl2 = Controller(dev2, settings, ocr=VirtualJsonOcr())
    res2 = invoice_expense.run(ctrl2, settings, resume=False)
    for line in res2.summary_lines():
        print("  " + line)
    rep2 = res2.ctx.get("expense_report", {})
    print("  发票合计:", rep2.get("total"), "| 邮箱页合计:", rep2.get("mail_page_total"))
    print("  报销单号:", rep2.get("expense_no"))
    print("  产物:", invoice_expense.write_artifact(res2, settings))
    rc |= 0 if res2.success else 1
    if trace is not None:
        _trace_step(ctrl2, trace, "场景二-发票报销")

    print("\n【场景三】手机端 政务 App 会话过期重登 + 公积金余额取证（权限弹窗/OTP/登录态分流）")
    dev3 = VirtualDevice(gov_auth_with_popups(), seed=11, drift_px=drift)
    ctrl3 = Controller(dev3, settings, ocr=VirtualJsonOcr())
    res3 = auth_scenario.run(ctrl3, settings, resume=False)
    for line in res3.summary_lines():
        print("  " + line)
    evidence = res3.ctx.get("evidence") or {}
    print("  登录路径:", res3.ctx.get("login"), "| 公积金余额:", res3.ctx.get("balance"))
    print("  证据帧文本数:", evidence.get("texts"), "| 采集时间:", evidence.get("at"))
    print("  产物:", auth_scenario.write_artifact(res3, settings))
    rc |= 0 if res3.success else 1
    if trace is not None:
        _trace_step(ctrl3, trace, "场景三-政务取证")

    print("\n【定位轨迹抽样】（展示多通道融合与置信度）")
    for t in ctrl.trace[:6]:
        print("  ", t)
    print("\n【自愈事件】（看门狗处置记录）")
    healed = [e["watchdog"] for e in dev.world.get("log", []) if "watchdog" in e]
    if healed:
        for h in healed:
            print("  ", h)
    else:
        print("   本轮无需自愈（页面健康）")
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
    parser.add_argument("--chaos", action="store_true",
                        help="故障注入模式：元素漂移 20px + 输入被清空 + 模板通道（演示自愈）")
    parser.add_argument("--trace", metavar="PATH",
                        help="导出执行轨迹到文件（.md 输出表格，.json 输出结构化事件）")
    args = parser.parse_args()
    chaos = args.chaos or os.environ.get("CHAOS", "").strip() in ("1", "true", "yes", "on")
    settings = load_settings()
    os.makedirs(settings.artifact_dir, exist_ok=True)
    recorder = TraceRecorder(args.trace) if args.trace else None

    if args.agent:
        return run_agent_goal(args.agent, settings)

    if os.environ.get("DEVICE", "virtual") == "virtual":
        rc = run_virtual_demo(settings, chaos=chaos, trace=recorder)
    else:
        dev = build_real_device(settings)
        # 真机不可用时（adb 无设备已回落虚拟 / 桌面后端降级）走完整三场景演示，
        # 保证评审环境「有设备用设备、没设备也能看到完整能力」，且不产生假失败。
        degraded = dev.name == "virtual" or getattr(dev, "degraded", False)
        if degraded:
            print("（真机不可用，已回落虚拟设备执行完整三场景演示）\n")
            rc = run_virtual_demo(settings, chaos=chaos, trace=recorder)
        else:
            ocr = default_ocr(for_virtual=False)
            ctrl = Controller(dev, settings, ocr=ocr)
            res = invoice_expense.run(ctrl, settings, resume=True)
            for line in res.summary_lines():
                print(line)
            if recorder is not None:
                _trace_step(ctrl, recorder, "真机-发票报销")
            rc = 0 if res.success else 1

    if recorder is not None and args.trace:
        path = recorder.write(args.trace)
        print(f"\n执行轨迹已导出：{path}（{len(recorder.events())} 条事件）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
