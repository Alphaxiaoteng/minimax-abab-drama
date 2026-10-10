from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoglm_agent.act.actions import Controller
from autoglm_agent.config import Settings
from autoglm_agent.device.virtual import VirtualDevice
from autoglm_agent.flow.engine import FlowEngine
from autoglm_agent.flow.step import Flow, Step
from autoglm_agent.locate.spec import ElementSpec
from autoglm_agent.memory.checkpoint import CheckpointStore
from autoglm_agent.tasks import invoice_expense, price_coupon
from autoglm_agent.tasks.scenarios import (desktop_invoice_with_popup,
                                           mobile_price_coupon_with_popups)
from autoglm_agent.vision.ocr import VirtualJsonOcr

BAD = ElementSpec(name="bad", texts=["绝不存在"], patterns=["^NEVER$"])
GOOD = ElementSpec(name="go", texts=["搜索"], require_clickable=True)


def fast_settings(tmpdir: str) -> Settings:
    s = Settings()
    s.locate_poll_interval = 0.02
    s.locate_timeout = 0.8
    s.max_scroll_probe = 3
    s.retry_backoff_base = 0.01
    s.max_step_retries = 2
    s.checkpoint_dir = os.path.join(tmpdir, "ckpt")
    s.artifact_dir = os.path.join(tmpdir, "art")
    return s


class TestFlowEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = fast_settings(self.tmp.name)
        dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=5)
        self.ctrl = Controller(dev, self.s, ocr=VirtualJsonOcr())
        self.ctrl.launch("juhai")
        self.engine = FlowEngine(self.ctrl, self.s,
                                 CheckpointStore(self.s.checkpoint_dir))

    def tearDown(self):
        self.tmp.cleanup()

    def test_retry_then_fail_critical_stops_flow(self):
        calls = {"n": 0}

        def act(ctrl, ctx):
            calls["n"] += 1
            ctrl.click(BAD, timeout=0.1)

        flow = Flow(flow_id="f1", title="t")
        flow.add(Step("boom", "必败步骤", act, retries=1, on_fail="retry", critical=True))
        flow.add(Step("never", "不该执行", lambda c, x: calls.__setitem__("n", 99)))
        res = self.engine.run(flow, resume=False)
        self.assertFalse(res.success)
        self.assertEqual(res.outcomes[0].status, "failed")
        self.assertEqual(len(res.outcomes), 1)
        self.assertEqual(calls["n"], 1 + self.s.max_step_retries)
        self.assertNotEqual(calls["n"], 99)

    def test_fallback_path_recovers(self):
        def act(ctrl, ctx):
            ctrl.click(BAD, timeout=0.1)

        def fallback(ctrl, ctx):
            ctrl.click(GOOD, timeout=0.5)

        flow = Flow(flow_id="f2", title="t")
        flow.add(Step("submit", "提交搜索", act,
                      verify=lambda c, x: c.snapshot().contains("到手价"),
                      retries=0, fallback=fallback))
        res = self.engine.run(flow, resume=False)
        self.assertTrue(res.success)
        self.assertEqual(res.outcomes[0].error, "via-fallback")

    def test_non_critical_failure_skips(self):
        flow = Flow(flow_id="f3", title="t")
        flow.add(Step("opt", "可选步骤", lambda c, x: c.click(BAD, timeout=0.1),
                      retries=0, on_fail="retry", critical=False))
        flow.add(Step("after", "后续", lambda c, x: x.__setitem__("done", True)))
        res = self.engine.run(flow, resume=False)
        self.assertTrue(res.success)
        self.assertEqual(res.outcomes[0].status, "skipped")
        self.assertTrue(res.ctx.get("done"))

    def test_checkpoint_resume(self):
        flow = Flow(flow_id="f4", title="t")
        flow.add(Step("s1", "第一步", lambda c, x: x.__setitem__("s1", x.get("s1", 0) + 1)))
        flow.add(Step("s2", "第二步必败", lambda c, x: c.click(BAD, timeout=0.1), retries=0))

        res1 = self.engine.run(flow, resume=False)
        self.assertFalse(res1.success)
        self.assertEqual(res1.ctx["s1"], 1)

        fixed = Flow(flow_id="f4", title="t")
        fixed.add(Step("s1", "第一步", lambda c, x: x.__setitem__("s1", x.get("s1", 0) + 1)))
        fixed.add(Step("s2", "修复后的第二步", lambda c, x: x.__setitem__("s2", True)))
        res2 = self.engine.run(fixed, resume=True)
        self.assertTrue(res2.success)
        self.assertEqual(res2.resumed_from, 1)
        self.assertEqual(res2.ctx["s1"], 1)  # 第一步未被重复执行
        self.assertTrue(res2.ctx["s2"])


class TestTasksE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = fast_settings(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_price_coupon_closed_loop(self):
        dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=42)
        ctrl = Controller(dev, self.s, ocr=VirtualJsonOcr())
        res = price_coupon.run(ctrl, self.s, resume=False)
        self.assertTrue(res.success, res.summary_lines())
        rep = res.ctx["report"]
        self.assertEqual(rep["recommendation"]["price"], 179.0)
        self.assertGreaterEqual(len(res.ctx["juhai_prices"]), 3)

    def test_invoice_expense_closed_loop(self):
        dev = VirtualDevice(desktop_invoice_with_popup(), width=1920, height=1080, seed=7)
        ctrl = Controller(dev, self.s, ocr=VirtualJsonOcr())
        res = invoice_expense.run(ctrl, self.s, resume=False)
        self.assertTrue(res.success, res.summary_lines())
        rep = res.ctx["expense_report"]
        self.assertEqual(rep["total"], 1250.0)
        self.assertEqual(rep["total"], rep["mail_page_total"])
        self.assertEqual(rep["expense_no"], "BX-2026-1001")


if __name__ == "__main__":
    unittest.main()
