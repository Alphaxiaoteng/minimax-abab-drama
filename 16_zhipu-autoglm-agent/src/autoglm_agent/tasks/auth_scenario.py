from __future__ import annotations

"""第三条业务闭环：手机端「政务/银行 App 指纹下发」场景。

真实痛点：政务、公积金、银行类 App 打开必弹权限/协议弹窗，会话过期需重新登录，
登录还要收一次短信验证码——链条长、外部依赖多、人工每天重复。
本闭环演示框架在同一套容错脚本层上如何处理：
  ① 开屏广告 + 权限弹窗（治理层消化）
  ② 会话过期重登（表单输入 + 失败重试 + 回退）
  ③ OTP 挑战（演示码下发，输入框带噪声，输入后必须回读校验）
  ④ 登录态分流（同一入口按登录态直达余额页，证明流程不是硬编码顺序）
  ⑤ 结果取证（金额解析 + 屏幕文本快照，落盘成可审计产物）
"""

import json
import os
import re
import time
from typing import Any, Dict, Optional

from ..act.actions import Controller
from ..config import Settings
from ..flow.engine import FlowEngine, FlowResult
from ..flow.step import Flow, Step
from ..locate.spec import ElementSpec
from ..perception.screen import Screen, capture

ACCOUNT = "13800138000"
DEMO_CODE = "111111"
BALANCE_RX = re.compile(r"公积金余额\s*¥([\d,]+(?:\.\d+)?)")

PHONE = ElementSpec(name="phone", texts=["手机号"], patterns=["手机号|账号|请输入手机号"],
                    editable=True, resource_ids=["gov.phone"])
OTP_INPUT = ElementSpec(name="otp_input", texts=["验证码"], patterns=["验证码|短信码"],
                        editable=True, resource_ids=["gov.otp"])
SEND_CODE = ElementSpec(name="send_code", texts=["获取验证码", "发送验证码"],
                        patterns=["获取验证码|发送验证码"])
SUBMIT_OTP = ElementSpec(name="submit_otp", texts=["提交", "确认登录"],
                         patterns=["^提交$|^确认登录$"])
LOGIN = ElementSpec(name="login", texts=["登录"], require_clickable=True, patterns=["^登录$"])
ENTRY = ElementSpec(name="entry", texts=["公积金查询"], patterns=["公积金"])
BACK = ElementSpec(name="back_home", texts=["返回首页"], patterns=["返回首页"])


def build_flow(account: str = ACCOUNT, code: str = DEMO_CODE) -> Flow:
    flow = Flow(flow_id="mobile-gov-auth-balance", title="政务 App 会话过期重登与余额取证 Agent")

    def open_app(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.launch("govapp")
        if _logged_in(ctrl):
            # 会话仍有效：App 直接进办事大厅（真实政务 App 的常见行为）。
            # 登录页此时只是开屏过渡，需要显式进入首页，否则后续入口不可见。
            ctrl.tap_if_present(LOGIN)
        ctx["account"] = account

    def login(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        if _logged_in(ctrl):
            ctx["login"] = "reused-session"
            return
        ctrl.type_text(PHONE, account)
        ctrl.click(SEND_CODE)
        screen = ctrl.wait_for(lambda s: s.contains("验证码"), timeout=ctrl.settings.locate_timeout,
                               message="验证码页未出现")
        ctx["challenge_sent"] = "验证码" in "".join(screen.all_texts())
        ctrl.type_text(OTP_INPUT, code)
        if ctrl.tap_if_present(SUBMIT_OTP):
            ctx["login"] = "otp-submitted"
        else:
            ctrl.click(LOGIN)
            ctx["login"] = "password-submitted"

    def read_balance(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        ctrl.click(ENTRY)
        screen = ctrl.expect_texts("公积金余额", timeout=ctrl.settings.locate_timeout)
        raw = _find_balance(screen)
        ctx["balance"] = raw
        ctx["balance_page_texts"] = len(screen.all_texts())

    def collect_evidence(ctrl: Controller, ctx: Dict[str, Any]) -> None:
        screen = ctrl.snapshot()
        ctx["evidence"] = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "texts": len(screen.all_texts()),
            "balance": ctx.get("balance"),
            "sample": screen.all_texts()[:8],
            "device": getattr(ctrl.device, "name", "unknown"),
        }

    flow.add(Step("open_app", "启动政务 App 并治理开屏广告/权限弹窗", open_app,
                  verify=lambda c, x: _logged_in(c) or c.snapshot().contains("登录")
                  or c.snapshot().contains("手机号") or c.snapshot().contains("办事大厅"),
                  verify_message="未到达登录页或办事大厅", retries=2, on_fail="recover_back"))
    flow.add(Step("login", "会话过期重登（手机号→验证码→提交）", login,
                  verify=lambda c, x: _logged_in(c), verify_message="登录态未置位",
                  retries=2, on_fail="recover_back"))
    flow.add(Step("balance", "进入公积金查询并解析余额", read_balance,
                  verify=lambda c, x: isinstance(x.get("balance"), float),
                  verify_message="余额未解析", retries=2, on_fail="recover_back"))
    flow.add(Step("evidence", "采集可审计证据（金额+屏幕快照）", collect_evidence,
                  verify=lambda c, x: (x.get("evidence") or {}).get("texts", 0) > 0,
                  verify_message="证据为空", retries=1))
    return flow


def _logged_in(ctrl: Controller) -> bool:
    world = getattr(ctrl.device, "world", None)
    if isinstance(world, dict):
        return bool(world.get("vars", {}).get("logged_in"))
    return False


def _find_balance(screen: Screen) -> Optional[float]:
    for text in screen.all_texts():
        for raw in BALANCE_RX.findall(text):
            return float(raw.replace(",", ""))
    return None


def run(controller: Controller, settings: Settings, resume: bool = True) -> FlowResult:
    engine = FlowEngine(controller, settings)
    return engine.run(build_flow(), resume=resume)


def write_artifact(result: FlowResult, settings: Settings) -> str:
    os.makedirs(settings.artifact_dir, exist_ok=True)
    path = os.path.join(settings.artifact_dir, "auth_report.json")
    evidence = result.ctx.get("evidence") or {}
    payload = {
        "success": result.success,
        "steps": [o.__dict__ for o in result.outcomes],
        "report": {
            "account": result.ctx.get("account"),
            "login": result.ctx.get("login"),
            "challenge_sent": result.ctx.get("challenge_sent"),
            "balance": result.ctx.get("balance"),
            "evidence_at": evidence.get("at"),
            "screen_texts": evidence.get("texts"),
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
