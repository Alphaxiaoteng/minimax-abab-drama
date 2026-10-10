"""core 包公共 re-export:域模型 + 优化链路。

边缘设备无 numpy,本包禁止 import numpy;全部纯 Python + 标准库。
"""
from __future__ import annotations

from .tariff import (
    TariffTier, TariffPlan, builtin_tariffs, load_tariff, save_tariff, TIER_NAMES,
)
from .battery import BatteryConfig, BatteryState, BatteryModel
from .solar import (
    WeatherForecast, SolarForecast, SolarModel, synthetic_weather,
)
from .hardware import (
    DeviceSpec, HomeLoad, HardwareCatalog, SiteConfig, demo_site,
)
from .lp import LPProblem, LPSolution, solve_lp
from .policy import (
    PolicyParams, GuardRails, clamp_params, validate_params, mode_presets, KNOWN_MODES,
)
from .optimizer import SchedulePoint, PlanResult, MPCOptimizer
from .explain import explain_plan, compare_plans

__all__ = [
    # tariff
    "TariffTier", "TariffPlan", "builtin_tariffs", "load_tariff", "save_tariff", "TIER_NAMES",
    # battery
    "BatteryConfig", "BatteryState", "BatteryModel",
    # solar
    "WeatherForecast", "SolarForecast", "SolarModel", "synthetic_weather",
    # hardware
    "DeviceSpec", "HomeLoad", "HardwareCatalog", "SiteConfig", "demo_site",
    # lp
    "LPProblem", "LPSolution", "solve_lp",
    # policy
    "PolicyParams", "GuardRails", "clamp_params", "validate_params", "mode_presets", "KNOWN_MODES",
    # optimizer
    "SchedulePoint", "PlanResult", "MPCOptimizer",
    # explain
    "explain_plan", "compare_plans",
]