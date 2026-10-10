from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoglm_agent.config import Settings
from autoglm_agent.device.virtual import Effect, Scenario, ScreenDef, VElem, VirtualDevice
from autoglm_agent.guard.popup import PopupGovernor
from autoglm_agent.locate.locator import FaultTolerantLocator, LocateError
from autoglm_agent.locate.spec import ElementSpec
from autoglm_agent.perception.screen import normalize_text
from autoglm_agent.tasks.scenarios import mobile_price_coupon_with_popups
from autoglm_agent.vision.ocr import VirtualJsonOcr


def fast_settings() -> Settings:
    s = Settings()
    s.locate_poll_interval = 0.02
    s.locate_timeout = 1.5
    s.max_scroll_probe = 4
    s.retry_backoff_base = 0.01
    return s


def single_screen_scenario() -> Scenario:
    return Scenario(
        screens={
            "page": ScreenDef(elements=[
                VElem(key="buy", x=0.3, y=0.4, w=0.4, h=0.06, text="立即购买"),
                VElem(key="ghost", x=0.3, y=0.6, w=0.4, h=0.06, text="收藏到购物车"),
                VElem(key="amount", x=0.3, y=0.7, w=0.4, h=0.06, text="",
                      rid="form.amount", editable=True, cls="EditText"),
            ])
        },
        apps={"demo": "page"},
        initial="page",
    )


class TestNormalize(unittest.TestCase):
    def test_fullwidth_and_space(self):
        self.assertEqual(normalize_text("立 即购 买"), normalize_text("立即购买"))
        self.assertEqual(normalize_text("ＶＩＰ"), "vip")


class TestLocator(unittest.TestCase):
    def setUp(self):
        self.s = fast_settings()
        self.dev = VirtualDevice(single_screen_scenario())
        self.loc = FaultTolerantLocator(self.dev, self.s, ocr=VirtualJsonOcr())

    def test_exact_ui_text_wins(self):
        spec = ElementSpec(name="buy", texts=["立即购买"])
        cand = self.loc.locate(spec, timeout=0.5)
        self.assertEqual(cand.element_key, "buy")
        self.assertGreaterEqual(cand.conf, 0.93)

    def test_substring_not_confused_by_ghost(self):
        # “收藏到购物车” 不应抢走 “购物车” 查询？恰恰应当命中包含匹配
        spec = ElementSpec(name="cart", texts=["购物车"])
        cand = self.loc.locate(spec, timeout=0.5)
        self.assertEqual(cand.element_key, "ghost")

    def test_regex_and_rid_and_editable_filter(self):
        spec = ElementSpec(name="amount", patterns=["金额|amount"],
                           resource_ids=["form.amount"], editable=True)
        cand = self.loc.locate(spec, timeout=0.5)
        self.assertTrue(cand.editable)

    def test_prior_fallback_when_nothing_matches(self):
        spec = ElementSpec(name="nowhere", texts=["绝不存在"], prior=(0.5, 0.9))
        cand = self.loc.locate(spec, timeout=0.3)
        self.assertEqual(cand.source, "prior")
        self.assertLess(cand.conf, 0.6)

    def test_locate_error_when_no_prior(self):
        spec = ElementSpec(name="gone", texts=["绝不存在X"])
        with self.assertRaises(LocateError):
            self.loc.locate(spec, timeout=0.2, scroll_probe=False)

    def test_fuzzy_ocr_recovers_noisy_text(self):
        noisy = Scenario(screens={"p": ScreenDef(elements=[
            VElem(key="claim", x=0.5, y=0.5, w=0.4, h=0.06, text="立即领取", noisy=True),
        ])}, apps={"a": "p"}, initial="p")
        dev = VirtualDevice(noisy, seed=3)
        loc = FaultTolerantLocator(dev, self.s, ocr=VirtualJsonOcr())
        # 只允许 OCR 通道（无 UI 文本时用 patterns 模糊）
        spec = ElementSpec(name="claim", texts=["立即领取"])
        cand = loc.locate(spec, timeout=0.5)
        self.assertIsNotNone(cand)

    def test_resolution_drift_tolerance(self):
        for res, drift in [((720, 1536), 12), ((1080, 2400), 20), ((1440, 3200), 0)]:
            dev = VirtualDevice(mobile_price_coupon_with_popups(),
                                width=res[0], height=res[1], drift_px=drift, seed=res[0])
            gov = PopupGovernor(self.s)
            dev.launch("juhai")
            gov.handle(dev, VirtualJsonOcr())
            loc = FaultTolerantLocator(dev, self.s, ocr=VirtualJsonOcr())
            spec = ElementSpec(name="search_go", texts=["搜索"], require_clickable=True)
            cand = loc.locate(spec, timeout=1.0)
            self.assertIsNotNone(cand, f"分辨率 {res} 漂移 {drift}px 下定位失败")


class TestPopupGovernor(unittest.TestCase):
    def test_dismiss_ad_popup(self):
        s = fast_settings()
        dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=1)
        dev.launch("juhai")
        self.assertIsNotNone(dev.modal)
        gov = PopupGovernor(s)
        handled = gov.handle(dev, VirtualJsonOcr())
        self.assertTrue(any(h.startswith("dismiss") for h in handled))
        self.assertIsNone(dev.modal)

    def test_allow_only_with_signature(self):
        s = fast_settings()
        dev = VirtualDevice(mobile_price_coupon_with_popups(), seed=1)
        dev.launch("bilin")
        gov = PopupGovernor(s)
        handled = gov.handle(dev, VirtualJsonOcr())
        self.assertTrue(any(h.startswith("allow") for h in handled))
        self.assertIn("clipboard_allowed", [i.get("event") for i in dev.world["log"]])

    def test_no_false_positive_on_business_button(self):
        s = fast_settings()
        dev = VirtualDevice(single_screen_scenario())
        gov = PopupGovernor(s)
        screen = dev.screenshot()
        from autoglm_agent.perception.screen import capture
        pending = gov.find_pending(capture(dev, VirtualJsonOcr()))
        self.assertIsNone(pending)
        del screen


if __name__ == "__main__":
    unittest.main()
