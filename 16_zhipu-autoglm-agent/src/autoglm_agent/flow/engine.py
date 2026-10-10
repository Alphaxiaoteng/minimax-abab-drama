from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..act.actions import Controller
from ..config import Settings
from ..locate.locator import LocateError
from ..memory.checkpoint import CheckpointStore
from .step import Flow, Step, StepOutcome


@dataclass
class FlowResult:
    flow_id: str
    title: str
    success: bool
    outcomes: List[StepOutcome] = field(default_factory=list)
    ctx: Dict[str, Any] = field(default_factory=dict)
    resumed_from: Optional[int] = None

    def summary_lines(self) -> List[str]:
        icon = {"ok": "✓", "skipped": "-", "failed": "✗"}
        return [f"{icon[o.status]} {o.step_id} [{o.status}]"
                + (f" x{o.attempts}" if o.attempts > 1 else "")
                + (f"  {o.error}" if o.error else "") for o in self.outcomes]


class FlowEngine:
    """闭环执行器：步骤 = 动作 + 校验；失败按重试/回退/降级/放弃策略推进，
    每步成功后落检查点，进程中断可从断点续跑。"""

    def __init__(self, controller: Controller, settings: Settings,
                 checkpoints: Optional[CheckpointStore] = None):
        self.ctrl = controller
        self.s = settings
        self.store = checkpoints or CheckpointStore(settings.checkpoint_dir)

    def run(self, flow: Flow, resume: bool = True, ctx: Optional[Dict[str, Any]] = None) -> FlowResult:
        ctx = ctx if ctx is not None else {}
        start = 0
        if resume:
            saved = self.store.load(flow.flow_id)
            if saved:
                ctx.update(saved.get("ctx", {}))
                start = int(saved.get("next_step", 0))
        if flow.reset:
            flow.reset(self.ctrl)

        result = FlowResult(flow_id=flow.flow_id, title=flow.title, success=True,
                            resumed_from=start or None, ctx=ctx)
        for idx in range(start, len(flow.steps)):
            step = flow.steps[idx]
            outcome = self._run_step(step, ctx)
            result.outcomes.append(outcome)
            if outcome.status == "failed":
                if step.critical:
                    result.success = False
                    self.store.save(flow.flow_id, idx, ctx)
                    return result
                outcome.status = "skipped"
            self.store.save(flow.flow_id, idx + 1, ctx)

        self.store.clear(flow.flow_id)
        return result

    def _run_step(self, step: Step, ctx: Dict[str, Any]) -> StepOutcome:
        last_err = ""
        max_attempts = step.retries + self.s.max_step_retries
        for attempt in range(1, max_attempts + 1):
            try:
                step.act(self.ctrl, ctx)
                if step.verify is None or step.verify(self.ctrl, ctx):
                    return StepOutcome(step.id, "ok", attempt)
                last_err = step.verify_message or "校验未通过"
            except LocateError as e:
                last_err = str(e)
            except Exception as e:  # noqa: BLE001 —— 端侧脚本必须兜住一切异常
                last_err = f"{type(e).__name__}: {e}"

            if step.on_fail == "skip":
                return StepOutcome(step.id, "skipped", attempt, last_err)
            if attempt <= step.retries + self.s.max_step_retries - 1:
                self._recover(step)
                time.sleep(min(4.0, self.s.retry_backoff_base * (2 ** (attempt - 1))))
                continue
            if step.fallback is not None:
                try:
                    step.fallback(self.ctrl, ctx)
                    if step.verify is None or step.verify(self.ctrl, ctx):
                        return StepOutcome(step.id, "ok", attempt, error="via-fallback")
                    last_err += "；降级路径校验失败"
                except Exception as e:  # noqa: BLE001
                    last_err = f"降级失败 {type(e).__name__}: {e}"
            break
        return StepOutcome(step.id, "failed", max_attempts, last_err)

    def _recover(self, step: Step) -> None:
        self.ctrl.popups.handle(self.ctrl.device, self.ctrl.ocr)
        if step.on_fail == "recover_back":
            self.ctrl.back()
