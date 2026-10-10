from __future__ import annotations

"""自愈看门狗：把体检结论翻译成处置动作，并保证处置本身也有界（不无限重试）。

处置策略遵循“先保守、再升级”：
  - 弹窗拦截 → 交给 PopupGovernor 消化（它比动画/坐标猜测更可靠）
  - 画面冻结 → 先 `back()` 打破僵局；连续冻住且知道前台应用时重启该应用
  - 空白屏   → 先等一帧（渲染抖动很常见）；持续空白才返回/重启
每次处置都写 `device.world["log"]`（虚拟设备可断言；真机忽略），使自愈行为可被测试与录屏验证。
"""

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ..config import Settings
from ..device.base import Device
from ..guard.popup import PopupGovernor
from ..perception.health import HealthProbe, HealthReport, frame_signatures
from ..perception.screen import capture
from ..vision.base import OcrBackend

BLANK, FROZEN, POPUP = "blank", "frozen", "popup"

# 处置阈值：严重度低于阈值的故障不动作（避免对正常页面的偶发特征误操作）。
# frozen 的严重度固定为低值：单帧「画面未变」不足以定罪，改由 Watchdog 的
# _frozen_streak 决定升级节奏（首次 back 打破僵局，连续两次重启前台应用）。
SEVERITY = {BLANK: 0.55, FROZEN: 0.25, POPUP: 0.75}


@dataclass
class Issue:
    kind: str
    severity: float
    detail: str = ""
    title: str = ""
    action: str = ""


def classify(health: HealthReport) -> List[Tuple[str, float]]:
    """纯函数：健康报告 → 需要处置的 (故障类型, 严重度) 列表，按严重度降序。

    严重度反映「有多确定这是故障」而非「画面有多差」：
    弹窗有明确特征词，最确定；空白屏元素/文本双空，次之；
    画面冻结单帧不足以判定（静止的正常页面也会命中），因此给最低严重度，
    由 Watchdog 按连续帧数升级处置。
    """
    out: List[Tuple[str, float]] = []
    if health.popup_pending:
        out.append((POPUP, 0.90))
    if health.blank:
        out.append((BLANK, 0.60 + 0.1 * (len(health.reasons) > 1)))
    if health.frozen:
        out.append((FROZEN, 0.30))
    return sorted(out, key=lambda kv: -kv[1])


class Watchdog:
    """在每一步动作前后做体检与处置。持有跨步骤的故障计数，用于升级处置强度。"""

    def __init__(self, device: Device, settings: Settings, ocr: Optional[OcrBackend] = None,
                 popups: Optional[PopupGovernor] = None,
                 launch: Optional[Callable[[str], None]] = None):
        self.device = device
        self.s = settings
        self.ocr = ocr
        self.popups = popups or PopupGovernor(settings)
        self.launch = launch
        self.probe = HealthProbe(device, ocr, self.popups)
        self._frozen_streak = 0
        self._blank_streak = 0
        self._recent_faults = 0

    def reset(self) -> None:
        self.probe.clear_baseline()
        self._frozen_streak = 0
        self._blank_streak = 0
        self._recent_faults = 0

    def note_progress(self) -> None:
        """业务步骤取得实质进展时调用：重置“连续故障”计数，避免长期运行中误升级。"""
        self._recent_faults = 0

    def _count_fault(self) -> int:
        """统计自上次实质性进展以来的故障次数；单调递增，不受单次处置影响。"""
        self._recent_faults += 1
        return self._recent_faults

    # ---- 上下文 ----
    def _last_app(self) -> str:
        world = getattr(self.device, "world", None)
        if isinstance(world, dict):
            return str(world.get("vars", {}).get("app", ""))
        return ""

    def _log(self, payload: dict) -> None:
        world = getattr(self.device, "world", None)
        if isinstance(world, dict) and isinstance(world.get("log"), list):
            world["log"].append({"watchdog": payload})

    def _restart(self, reason: str) -> str:
        app = self._last_app()
        if self.launch and app:
            try:
                self.launch(app)
                self.probe.reset()
                return f"restart:{app}"
            except Exception:  # noqa: BLE001 —— 自愈动作本身失败不得中断业务
                return f"restart-failed:{app}"
        return f"wait:{reason}"

    # ---- 主入口 ----
    def check(self, screen=None) -> List[Issue]:
        """动作前的预防性体检：**不做冻结判定**，只处理弹窗与黑屏。

        冻结的语义是「动作之后画面毫无变化」，因此必须由动作前后配对取样判定
        （见 `Controller._assert_progress`）。在动作前无差别比较两次体检结果，
        会把静止的正常页面误判为冻结并触发破坏性的 back/重启。
        """
        screen = screen if screen is not None else capture(self.device, self.ocr)
        report = self.probe.evaluate(screen, freeze=False)
        if report.popup_pending:
            issue = Issue(kind=POPUP, severity=0.90, detail="；".join(report.reasons),
                          title=report.popup_title)
            self._handle(issue, self._count_fault())
            self._log({"kind": POPUP, "severity": issue.severity,
                       "detail": issue.detail, "action": issue.action})
            self.probe.clear_baseline()
            return [issue]
        if report.blank:
            issue = Issue(kind=BLANK, severity=0.60, detail="；".join(report.reasons))
            self._handle(issue, self._count_fault())
            self._log({"kind": BLANK, "severity": issue.severity,
                       "detail": issue.detail, "action": issue.action})
            self.probe.clear_baseline()
            return [issue]
        return []

    def assert_progress(self, before: Screen, after: Optional[Screen] = None) -> Optional[Issue]:
        """动作后校验：与动作前同签名则判定冻结并按 streak 升级处置。

        `before` 是动作执行前抓取的一帧（由 `Controller._act_with_watchdog` 提供）。
        """
        after = after if after is not None else capture(self.device, self.ocr)
        report = self.probe.evaluate(after, freeze=False)
        prev = frame_signatures(before)[0]
        same = report.screen_sig == prev
        self.probe.remember(report)
        if not same or report.blank:
            self._frozen_streak = 0
            return None
        issue = Issue(kind=FROZEN, severity=0.30,
                      detail="；".join(report.reasons) or "动作后画面未发生任何变化")
        self._handle(issue, self._count_fault())
        self._log({"kind": FROZEN, "severity": issue.severity,
                   "detail": issue.detail, "action": issue.action})
        self.probe.clear_baseline()
        return issue

    def _handle(self, issue: Issue, faults: int) -> None:
        """按故障类型处置；`faults` 为累计故障次数，用于决定是否升级到重启应用。"""
        if issue.kind == POPUP:
            handled = self.popups.handle(self.device, self.ocr)
            issue.action = f"dismissed:{len(handled)}"
            self._frozen_streak = 0
        elif issue.kind == FROZEN:
            self._frozen_streak += 1
            if faults >= 2:
                issue.action = self._restart("frozen")
            else:
                self.device.back()
                issue.action = "back"
        else:  # BLANK
            self._blank_streak += 1
            if faults >= 3:
                issue.action = self._restart("blank")
            elif self._blank_streak >= 2:
                self.device.back()
                issue.action = "back"
            else:
                time.sleep(self.s.blank_settle)
                issue.action = f"wait:{self.s.blank_settle}s"
