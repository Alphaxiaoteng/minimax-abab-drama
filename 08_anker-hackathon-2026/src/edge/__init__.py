"""edge — Layer-1 实时边缘运行时:硬保护、规则兜底、数字孪生、时序总线、状态持久化。

依赖方向:edge → core,core 永不 import edge。本包 re-export 公共名称供
serving/agent 切片与测试使用。
"""
from edge.safety import SafetyGuard, SafetyVerdict
from edge.reactor import RuleReactor, ReactorDecision
from edge.plant import PlantSimulator, SiteReading
from edge.telemetry import TelemetryBus
from edge.store import StateStore

__all__ = [
    "SafetyGuard",
    "SafetyVerdict",
    "RuleReactor",
    "ReactorDecision",
    "PlantSimulator",
    "SiteReading",
    "TelemetryBus",
    "StateStore",
]