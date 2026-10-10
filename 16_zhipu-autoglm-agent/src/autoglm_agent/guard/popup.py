from __future__ import annotations

"""弹窗治理：广告弹窗、权限申请、协议确认可能在任意步骤后弹出。
统一在此消化，业务流不感知临时 UI；同时避免误点业务页的正常按钮
（允许类按钮仅在页面含权限/提示特征词时消费）。"""

import time
from typing import List, Optional, Tuple

from ..config import Settings
from ..device.base import Device
from ..locate.spec import ElementSpec
from ..locate.strategy import Candidate, ocr_strategy, ui_tree_strategy
from ..perception.screen import Screen, capture, normalize_text

DISMISS_SPEC = ElementSpec(
    name="popup-dismiss",
    texts=["关闭", "跳过", "以后再说", "稍后再说", "取消", "我知道了", "知道了",
           "不再提示", "残忍离开", "close", "skip"],
    patterns=["^跳过\\s*\\d*$", "^×$"],
)
ALLOW_SPEC = ElementSpec(
    name="popup-allow",
    texts=["允许", "同意并继续", "始终允许", "allow", "only this time"],
)
POPUP_SIGNATURES = ["想要", "请求", "权限", "温馨提示", "系统通知", "推广", "广告",
                    "permission", "allow", "notice"]


class PopupGovernor:
    def __init__(self, settings: Optional[Settings] = None):
        self.s = settings or Settings()
        self.max_sweeps = 4

    def find_pending(self, screen: Screen) -> Optional[Tuple[str, Candidate]]:
        has_signature = any(normalize_text(sig) in "".join(screen.all_texts())
                            for sig in POPUP_SIGNATURES)
        dismiss = self._best(screen, DISMISS_SPEC)
        if dismiss and dismiss.conf >= 0.8:
            return "dismiss", dismiss
        if has_signature:
            allow = self._best(screen, ALLOW_SPEC)
            if allow and allow.conf >= 0.8:
                return "allow", allow
        return None

    def _best(self, screen: Screen, spec: ElementSpec) -> Optional[Candidate]:
        cands = ui_tree_strategy(screen, spec) + ocr_strategy(screen, spec)
        if not cands:
            return None
        return max(cands, key=lambda c: c.conf)

    def handle(self, device: Device, ocr=None) -> List[str]:
        """循环治理直到屏幕干净（或达到上限）。返回治理记录。"""
        handled: List[str] = []
        for _ in range(self.max_sweeps):
            pending = self.find_pending(capture(device, ocr))
            if pending is None:
                break
            kind, cand = pending
            x, y = cand.center
            device.tap(x, y)
            handled.append(f"{kind}:{cand.text}")
            time.sleep(0.3)
        return handled
