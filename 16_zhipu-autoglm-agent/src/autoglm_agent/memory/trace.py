from __future__ import annotations

"""执行轨迹留证：把“每一步为什么成功/失败、走的是哪个通道、自愈了几次”落成可提交材料。

评测方看到的录屏只是结果，轨迹文件才是**稳定性证据**：
它能让评审在不拉起设备的情况下复核“同一流程在多分辨率/多故障注入下依然收敛”。
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class TraceEvent:
    t: float
    step: str
    phase: str
    ok: bool
    detail: str = ""
    source: str = ""
    conf: float = 0.0
    recoveries: int = 0
    health_before: float = 1.0
    health_after: float = 1.0


class TraceRecorder:
    """内存优先、可落盘的轨迹记录器；未指定 path 时零 IO（测试/库用法）。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._events: List[TraceEvent] = []

    def add(self, **kw: Any) -> TraceEvent:
        kw.setdefault("t", time.time())
        known = {f for f in TraceEvent.__dataclass_fields__}
        unknown = set(kw) - known
        if unknown:
            raise TypeError(f"TraceEvent 不支持的字段: {sorted(unknown)}")
        event = TraceEvent(**kw)
        self._events.append(event)
        return event

    def events(self) -> List[TraceEvent]:
        return list(self._events)

    def to_json(self) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self._events]

    @staticmethod
    def _clock(t: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(t))

    def markdown(self, title: str = "") -> str:
        lines: List[str] = []
        head = title or "AutoGLM 执行轨迹"
        lines.append(f"# {head}")
        lines.append("")
        lines.append(f"事件数 {len(self._events)}；生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("| 时间 | 步骤 | 阶段 | 结果 | 通道 | 置信度 | 自愈 | 健康度(前→后) | 说明 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for e in self._events:
            lines.append(
                f"| {self._clock(e.t)} | {e.step} | {e.phase} | {'✓' if e.ok else '✗'} | "
                f"{e.source or '-'} | {e.conf:.2f} | {e.recoveries} | "
                f"{e.health_before:.2f}→{e.health_after:.2f} | {e.detail or ''} |")
        ok = sum(1 for e in self._events if e.ok)
        rec = sum(e.recoveries for e in self._events)
        avg = (sum(e.health_after for e in self._events) / len(self._events)) if self._events else 1.0
        lines.append("")
        lines.append(f"**汇总**：成功 {ok}/{len(self._events)}；自愈动作合计 {rec} 次；平均收尾健康度 {avg:.2f}")
        return "\n".join(lines) + "\n"

    def write(self, path: Optional[str] = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("未指定轨迹输出路径")
        parent = os.path.dirname(os.path.abspath(target))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if target.lower().endswith(".md"):
            with open(target, "w", encoding="utf-8") as f:
                f.write(self.markdown())
        else:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False, indent=2)
        return target
