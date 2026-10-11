"""serving.api — HTTP 边界模型。

pydantic v2 请求/响应模型,仅服务层使用(领域模型用 @dataclass)。
`city`/`model` 的取值在 core 模块导入时动态解析,因此校验函数在运行时查询
`core.tariff.builtin_tariffs()` 与 `core.hardware.HardwareCatalog().models()`。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict


def _valid_cities() -> List[str]:
    from core.tariff import builtin_tariffs
    return list(builtin_tariffs().keys())


def _valid_models() -> List[str]:
    from core.hardware import HardwareCatalog
    return HardwareCatalog().models()


class PlanRequest(BaseModel):
    """POST /api/plan 请求体;GET /api/plan 以查询参镜像同名字段。"""

    model_config = ConfigDict(protected_namespaces=())

    city: str = Field(default="shenzhen")
    model: str = Field(default="SOLIX_F3800")
    mode: str = Field(default="arbitrage")
    weather: str = Field(default="clear")
    risk_aversion: float = Field(default=0.5, ge=0.0, le=1.0)
    reserve_soc: float = Field(default=0.10, ge=0.0, le=1.0)
    use_llm: bool = Field(default=False)
    load_kw: Optional[List[float]] = Field(default=None)
    pv_kw: Optional[List[float]] = Field(default=None)
    capacity_kwh: Optional[float] = Field(default=None, gt=0.0)

    @field_validator("city")
    @classmethod
    def _check_city(cls, v: str) -> str:
        cities = _valid_cities()
        if v not in cities:
            raise ValueError(
                "未知城市 %r;可选: %s" % (v, ", ".join(sorted(cities)))
            )
        return v

    @field_validator("model")
    @classmethod
    def _check_model(cls, v: str) -> str:
        models = _valid_models()
        if v not in models:
            raise ValueError(
                "未知设备型号 %r;可选: %s" % (v, ", ".join(sorted(models)))
            )
        return v

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        modes = {"arbitrage", "self_consumption", "resilience", "balanced"}
        if v not in modes:
            raise ValueError("未知模式 %r;可选: %s" % (v, ", ".join(sorted(modes))))
        return v

    @field_validator("weather")
    @classmethod
    def _check_weather(cls, v: str) -> str:
        days = {"clear", "cloudy", "overcast", "rain", "heatwave"}
        if v not in days:
            raise ValueError("未知天象 %r;可选: %s" % (v, ", ".join(sorted(days))))
        return v


class PlanResponse(BaseModel):
    """计划响应:PlanResult.to_dict() 展平 + 契约 §3.11 额外字段。"""

    model_config = ConfigDict(extra="allow")

    site_id: str = ""
    model: str = ""
    city: str = ""
    solver_status: str = ""
    baseline_cost_cny: float = 0.0
    optimized_cost_cny: float = 0.0
    savings_cny: float = 0.0
    savings_pct: float = 0.0
    export_revenue_cny: float = 0.0
    pv_self_consumption: float = 0.0
    cycles_used: float = 0.0
    degradation_cost_cny: float = 0.0
    points: List[dict] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    rationale: List[str] = Field(default_factory=list)
    explain: List[str] = Field(default_factory=list)
    soc_now: float = 0.0
    tier_now: str = ""
    price_now: float = 0.0
    llm_available: bool = False
    llm_note: Optional[str] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    llm_available: bool = False
    models: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    version: str = "1.0"


# New Phase 2 API Models
class ApplianceConfig(BaseModel):
    type: str
    max_power_kw: float
    min_power_kw: float = 0.0
    efficiency: float = 1.0
    soc_min: float = 0.0
    soc_max: float = 1.0
    priority: int = 5
    can_defer: bool = True


class ApplianceState(BaseModel):
    soc: float = 0.5
    power_kw: float = 0.0
    energy_kwh: float = 0.0
    status: str = "off"
    runtime_hours: float = 0.0
    temperature_c: float = 25.0
    degradation_factor: float = 1.0


class ScenarioConfig(BaseModel):
    scenario_type: str = "sunny_high_pv"


class ROIReportRequest(BaseModel):
    battery_cost_cny: float = 25000.0
    annual_savings_cny: float = 1500.0
    annual_maintenance_cny: float = 500.0
    carbon_reduction_kg: float = 300.0
    carbon_credit_value: float = 0.05