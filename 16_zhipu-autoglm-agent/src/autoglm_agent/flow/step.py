from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, List

from ..act.actions import Controller

Ctx = Dict[str, Any]
OnFail = str  # "retry" | "recover_back" | "skip" | "abort"


@dataclass
class Step:
    id: str
    name: str
    act: Callable[[Controller, Ctx], None]
    verify: Optional[Callable[[Controller, Ctx], bool]] = None
    verify_message: str = ""
    retries: int = 2
    on_fail: OnFail = "abort"
    fallback: Optional[Callable[[Controller, Ctx], None]] = None
    critical: bool = True

    def describe(self) -> str:
        return f"[{self.id}] {self.name}"


@dataclass
class StepOutcome:
    step_id: str
    status: str  # ok / skipped / failed
    attempts: int = 1
    error: str = ""
    handled_popups: List[str] = field(default_factory=list)


@dataclass
class Flow:
    flow_id: str
    title: str
    steps: List[Step] = field(default_factory=list)
    reset: Optional[Callable[[Controller], None]] = None

    def add(self, step: Step) -> "Flow":
        self.steps.append(step)
        return self
