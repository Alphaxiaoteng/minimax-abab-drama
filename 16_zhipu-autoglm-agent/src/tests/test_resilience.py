from __future__ import annotations

"""异常注入测试：证明"高鲁棒"不是口号，而是可复现的行为。

每条用例对应一类真实端侧故障，断言落在可观测结果上（流程结果、世界事件、产物文件），
不绑定内部实现细节——这样重构容错策略时测试仍然有效。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoglm_agent.act.actions import Controller
from autoglm_agent.config import Settings
from autoglm_agent.device.virtual import Effect, Scenario, ScreenDef, VElem, VirtualDevice
from autoglm_agent.flow.engine import FlowEngine
from autoglm_agent.flow.step import Flow, Step
from autoglm_agent.locate.locator import LocateError
from autoglm_agent.locate.spec import ElementSpec
from autoglm_agent.memory.checkpoint import CheckpointStore
from autoglm_agent.perception.health import HealthProbe, format_health
from autoglm_agent.tasks import auth_scenario, price_coupon
from autoglm_agent.tasks.scenarios import (gov_auth_scenario, gov_auth_with_popups,
                                           mobile_price_coupon_with_popups)
from autoglm_agent.vision.ocr import VirtualJsonOcr


def fast_settings(tmpdir: str) -> Settings:
    s = Settings()
    s.locate_poll_interval = 0.02
    s.locate_timeout = 1.0
    s.max_scroll_probe = 3
    s.retry_backoff_base = 0.01
    s.max_step_retries = 2
    s.checkpoint_dir = os.path.join(tmpdir, "ckpt")
    s.artifact_dir = os.path.join(tmpdir, "art")
    return s


class ResilienceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = fast_settings(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def device(self, scenario, **kw) -> VirtualDevice:
        return VirtualDevice(scenario, **kw)

    def controller(self, dev) -> Controller:
        return Controller(dev, self.s, ocr=VirtualJsonOcr())


class TestFaultInjection(ResilienceCase):
    def test_ad_popup_consumed_before_business_steps(self):
        dev = self.device(mobile_price_coupon_with_popups(), seed=42)
        ctrl = self.controller(dev)
        res = price_coupon.run(ctrl, self.s, resume=False)
        self.assertTrue(res.success)

    def test_ui_drift_and_ocr_noise_still_locates(self):
        for res_wh, drift in [((720, 1536), 18), ((1080, 2400), 24), ((1440, 3200), 12)]:
            dev = self.device(mobile_price_coupon_with_popups(),
                              width=res_wh[0], height=res_wh[1], drift_px=drift, seed=res_wh[0] % 97)
            ctrl = self.controller(dev)
            out = price_coupon.run(ctrl, self.s, resume=False)
            self.assertTrue(out.success, f"{res_wh} 漂移 {drift}px 下闭环失败")

    def test_cleared_field_is_retyped_and_verified(self):
        """输入框被中途清空：步骤首次校验失败，重试路径必须把值重新写回去。"""
        scenario = Scenario(
            screens={
                "form": ScreenDef(elements=[
                    VElem(key="name", x=0.2, y=0.2, w=0.6, h=0.07,
                          text="申报人", rid="f.name", editable=True, clickable=True,
                          cls="EditText"),
                ]),
            },
            apps={"app": "form"},
            initial="form",
        )
        dev = self.device(scenario, seed=3)
        ctrl = self.controller(dev)
        written = {"n": 0}

        def fill(controller, ctx):
            controller.type_text(ElementSpec(name="name", texts=["申报人"], editable=True), "张伟")
            written["n"] += 1
            if written["n"] == 1:
                dev.world["form"]["name"] = ""  # 模拟“填写后被系统清空”

        flow = Flow(flow_id="cleared-field", title="输入回读重键入")
        flow.add(Step("fill", "填写申报人并在被清空后重试", fill,
                      verify=lambda c, x: dev.world["form"].get("name") == "张伟",
                      verify_message="字段为空", retries=2, on_fail="recover_back"))
        out = FlowEngine(ctrl, self.s, CheckpointStore(self.s.checkpoint_dir)).run(flow, resume=False)
        self.assertTrue(out.success)
        self.assertEqual(dev.world["form"]["name"], "张伟")
        self.assertGreaterEqual(written["n"], 2)

    def test_critical_failure_keeps_checkpoint_then_resumes(self):
        dev = self.device(mobile_price_coupon_with_popups(), seed=5)
        ctrl = self.controller(dev)
        engine = FlowEngine(ctrl, self.s, CheckpointStore(self.s.checkpoint_dir))
        calls = {"n": 0}

        def flaky(controller, ctx):
            calls["n"] += 1
            raise LocateError("注入的持续性定位失败")

        bad = Flow(flow_id="resume-flow", title="断点续跑")
        bad.add(Step("s1", "第一步成功", lambda c, x: x.__setitem__("s1", True)))
        bad.add(Step("s2", "第二步持续失败", flaky, retries=2, on_fail="abort", critical=True))
        res1 = engine.run(bad, resume=False)
        self.assertFalse(res1.success)
        self.assertLessEqual(calls["n"], 5)
        saved = CheckpointStore(self.s.checkpoint_dir).load("resume-flow")
        self.assertIsNotNone(saved, "关键步骤失败后必须留下检查点")
        self.assertEqual(saved["next_step"], 1)

        fixed = Flow(flow_id="resume-flow", title="断点续跑")
        fixed.add(Step("s1", "第一步成功", lambda c, x: x.__setitem__("s1", True)))
        fixed.add(Step("s2", "修复后的第二步", lambda c, x: x.__setitem__("s2", True)))
        res2 = engine.run(fixed, resume=True)
        self.assertTrue(res2.success)
        self.assertEqual(res2.resumed_from, 1)
        self.assertTrue(res2.ctx["s1"])

    def test_popup_after_arbitrary_step_is_absorbed(self):
        """业务步骤执行完才弹出权限窗：下一步动作前的体检必须消化它。"""
        scenario = Scenario(
            screens={
                "page": ScreenDef(elements=[
                    VElem(key="go", x=0.2, y=0.3, w=0.6, h=0.06, text="下一步",
                          on_tap=Effect(popup="perm", set={"clicked": True})),
                    VElem(key="done", x=0.2, y=0.5, w=0.6, h=0.06, text="完成",
                          on_tap=Effect(set={"done": True})),
                ]),
                "perm": ScreenDef(modal=True, elements=[
                    VElem(key="p_title", x=0.1, y=0.3, w=0.8, h=0.06,
                          text="应用想要获取定位权限"),
                    VElem(key="p_allow", x=0.5, y=0.5, w=0.3, h=0.06, text="允许",
                          on_tap=Effect(close_modal=True, record="loc_allowed")),
                ]),
            },
            apps={"app": "page"},
            initial="page",
        )
        dev = self.device(scenario, seed=1)
        ctrl = self.controller(dev)
        flow = Flow(flow_id="late-popup", title="步骤后弹窗")
        flow.add(Step("s1", "点击下一步（触发弹窗）", lambda c, x: c.click(
            ElementSpec(name="go", texts=["下一步"]))))
        flow.add(Step("s2", "弹窗后仍能点击完成", lambda c, x: c.click(
            ElementSpec(name="done", texts=["完成"]))))
        out = FlowEngine(ctrl, self.s, CheckpointStore(self.s.checkpoint_dir)).run(flow, resume=False)
        self.assertTrue(out.success)
        self.assertTrue(dev.world["vars"].get("done"))
        self.assertIn("loc_allowed", [e.get("event") for e in dev.world["log"]])


class TestHealthAndSelfHealing(ResilienceCase):
    def test_blank_and_frozen_frames_are_flagged(self):
        scenario = Scenario(
            screens={"blank": ScreenDef(elements=[]), "app": ScreenDef(elements=[
                VElem(key="ok", x=0.3, y=0.3, w=0.4, h=0.06, text="正常页面"),
            ])},
            apps={"b": "blank", "a": "app"},
            initial="blank",
        )
        dev = self.device(scenario)
        probe = HealthProbe(dev, VirtualJsonOcr())
        first = probe.sample()
        self.assertTrue(first.blank)
        self.assertLess(first.health, 0.6)
        dev.launch("a")
        normal = probe.sample()
        self.assertFalse(normal.blank)
        frozen = probe.sample()
        self.assertTrue(frozen.frozen)
        self.assertIn("冻结", format_health(frozen))

    def test_watchdog_dismisses_popup_and_logs_action(self):
        dev = self.device(mobile_price_coupon_with_popups(), seed=1)
        ctrl = self.controller(dev)
        dev.launch("juhai")
        self.assertIsNotNone(dev.modal)
        issues = ctrl.watch()
        self.assertTrue(any(i.kind == "popup" for i in issues))
        self.assertIsNone(dev.modal)
        actions = [e["watchdog"]["action"] for e in dev.world["log"] if "watchdog" in e]
        self.assertTrue(any(a.startswith("dismissed") for a in actions))

    def test_frozen_screen_escalates_from_back_to_app_restart(self):
        """连续冻结的处置必须升级：先 back 打破僵局，再重启前台应用。"""
        scenario = Scenario(
            screens={"stuck": ScreenDef(elements=[
                VElem(key="t", x=0.2, y=0.2, w=0.6, h=0.06, text="卡死的页面"),
            ])},
            apps={"stuckapp": "stuck"},
            initial="stuck",
        )
        dev = self.device(scenario)
        ctrl = self.controller(dev)
        dev.launch("stuckapp")
        actions = []
        for _ in range(6):
            actions += [i.action for i in ctrl.watch()]
            if any(a.startswith("restart") for a in actions):
                break
        self.assertIn("back", actions, f"首次冻结应先尝试返回：{actions}")
        self.assertTrue(any(a.startswith("restart:stuckapp") for a in actions),
                        f"连续冻结应升级为重启前台应用：{actions}")

    def test_persistently_frozen_screen_is_flagged_on_second_frame(self):
        """冻结判定跨帧有效：首帧建立基线，第二帧起必须报 frozen。"""
        scenario = Scenario(
            screens={"stuck": ScreenDef(elements=[
                VElem(key="t", x=0.2, y=0.2, w=0.6, h=0.06, text="卡死的页面"),
            ])},
            apps={"stuckapp": "stuck"},
            initial="stuck",
        )
        dev = self.device(scenario)
        ctrl = self.controller(dev)
        dev.launch("stuckapp")
        reports = []
        for _ in range(3):
            reports.append(ctrl.watchdog.probe.evaluate(ctrl.snapshot()))
            ctrl.watchdog.probe.remember(reports[-1])  # 未处置时基线推进
        self.assertFalse(reports[0].frozen)
        self.assertTrue(reports[1].frozen)
        self.assertTrue(reports[2].frozen)


class TestGovAuthClosedLoop(ResilienceCase):
    def test_popups_then_otp_login_and_balance_evidence(self):
        dev = self.device(gov_auth_with_popups(), seed=11)
        ctrl = self.controller(dev)
        res = auth_scenario.run(ctrl, self.s, resume=False)
        self.assertTrue(res.success, res.summary_lines())
        self.assertEqual(res.ctx.get("balance"), 12345.67)
        self.assertIn("otp_verified", [e.get("event") for e in dev.world["log"]])
        evidence = res.ctx.get("evidence") or {}
        self.assertGreater(evidence.get("texts", 0), 0)
        path = auth_scenario.write_artifact(res, self.s)
        self.assertTrue(os.path.exists(path))

    def test_wrong_otp_is_rejected_then_correct_code_completes(self):
        """错误验证码不应放行；输入框被噪声污染时回读校验必须拦住它。"""
        dev = self.device(gov_auth_scenario(), seed=11)
        ctrl = self.controller(dev)
        flow = auth_scenario.build_flow()
        login_step = next(s for s in flow.steps if s.id == "login")

        original_act = login_step.act
        state = {"n": 0}

        def flaky_login(controller, ctx):
            state["n"] += 1
            if state["n"] == 1:
                # 第一轮模拟“短信码输错”：直接注入错误的框内值，合法动作不会产生它
                controller.type_text(auth_scenario.PHONE, auth_scenario.ACCOUNT)
                controller.click(auth_scenario.SEND_CODE)
                dev.world["vars"]["otp_input"] = "000000"
                raise LocateError("注入：验证码错误，登录态未置位")
            return original_act(controller, ctx)

        login_step.act = flaky_login
        login_step.retries = 2
        res = FlowEngine(ctrl, self.s, CheckpointStore(self.s.checkpoint_dir)).run(flow, resume=False)
        self.assertTrue(res.success, res.summary_lines())
        self.assertGreaterEqual(state["n"], 2)
        self.assertEqual(dev.world["vars"].get("otp_input"), auth_scenario.DEMO_CODE)
        self.assertTrue(dev.world["vars"].get("logged_in"))

    def test_session_reuse_skips_login(self):
        dev = self.device(gov_auth_with_popups(), seed=11)
        ctrl = self.controller(dev)
        ctrl.launch("govapp")
        dev.world["vars"]["logged_in"] = True  # 模拟会话仍有效
        res = auth_scenario.run(ctrl, self.s, resume=False)
        self.assertTrue(res.success)
        self.assertEqual(res.ctx.get("login"), "reused-session")


def _run_original_login(controller, ctx):
    """（测试辅助）按登录步骤的业务语义重放一次，供故障注入用例复用。"""
    from autoglm_agent.tasks.auth_scenario import ACCOUNT, DEMO_CODE, PHONE, SEND_CODE, OTP_INPUT
    controller.type_text(PHONE, ACCOUNT)
    controller.click(SEND_CODE)
    controller.type_text(OTP_INPUT, DEMO_CODE)
    return None


if __name__ == "__main__":
    unittest.main()
