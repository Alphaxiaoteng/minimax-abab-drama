"""设备规格库:Anker SOLIX 型号、家庭负荷画像与组合拓扑聚合。

规格数值与可控性结论均取自 research/anker-hardware.md(逐型号有官方页/HA README 引证)。
关键事实(驱动 controllable / comms 字段):
  - 并网家庭储能(Family C)的 XE / Solarbank Max AC / Solarbank 4 E5000 Pro:
    官方 Home Assistant 集成 anker-charging/ha-anker-solix-official + 确认本地 Modbus TCP
    → controllable=True。
  - X1: 有 Modbus 协议参考文档,但被官方 HA 集成明确排除,写入控制未端到端验证
    → controllable=False,comms 含 "modbus" 但加 control_note 说明。
  - 便携电站(C/S/F 系)、整户备电 E10、阳台储能 Solarbank 2: 仅 App 调度,
    无公开第三方写 API → controllable=False。
  - 全系列均不支持 Matter,任何 comms 元组都不得含 "matter"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .battery import BatteryConfig

# 归一化 24h 典型居民负荷系数 (均值≈1):夜间基荷 + 早晚双峰
_RESIDENTIAL_PROFILE = [
    0.55, 0.50, 0.48, 0.48, 0.50, 0.62,   # 0-5 深夜基荷
    0.95, 1.25, 1.15, 0.90, 0.85, 0.90,   # 6-11 早峰
    1.00, 0.90, 0.85, 0.90, 1.05, 1.30,   # 12-17 午后缓升
    1.60, 1.70, 1.45, 1.10, 0.85, 0.65,   # 18-23 晚峰回落
]


@dataclass(frozen=True)
class DeviceSpec:
    model: str
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    pv_input_kw: float
    ac_output_kw: float          # 连续
    surge_kw: float
    round_trip_eff: float
    grid_tie: bool               # 是否支持并网/余电上网
    controllable: bool           # 是否可第三方自动化写入控制
    comms: tuple                 # ("wifi","ble","modbus","cloud_api") —— 绝无 "matter"
    price_cny: float
    soc_start_default: float = 0.30
    family: str = ""
    control_note: str = ""


# 功率/容量 kW、kWh 由 research/anker-hardware.md 引用的官方 W/Wh 换算得到。
# 价格除标注外为 [ESTIMATE CNY](USD 官方价 + 约 30% 进口/税,人民币未公开定价)。
_SPECS: List[DeviceSpec] = [
    # ---- Family A: 便携电站 (App-only, 无第三方写控制, 无馈网) ----  源: research/anker-hardware.md
    DeviceSpec("SOLIX_C1000_GEN2", 1.024, 1.6, 2.0, 0.6, 2.0, 3.0, 0.90, False, False,
               ("wifi", "ble"), 7999.0, family="A",
               control_note="App-only TOU; 无公开写 API [ESTIMATE CNY]"),   # 源: research/anker-hardware.md
    DeviceSpec("SOLIX_C2000_GEN2", 2.048, 1.8, 2.4, 0.8, 2.4, 4.0, 0.90, False, False,
               ("wifi", "ble"), 12999.0, family="A",
               control_note="App-only TOU [ESTIMATE CNY]"),                 # 源: research/anker-hardware.md
    DeviceSpec("SOLIX_S2000", 2.010, 0.6, 1.5, 0.4, 1.5, 1.5, 0.90, False, False,
               ("wifi", "ble"), 6999.0, family="A",
               control_note="UPS/bypass only, 无 TOU 调度 [ESTIMATE CNY]"),  # 源: research/anker-hardware.md
    DeviceSpec("SOLIX_F2600", 2.560, 1.44, 2.4, 1.0, 2.4, 2.8, 0.90, False, False,
               ("wifi", "ble"), 9999.0, family="A",
               control_note="App-only TOU [ESTIMATE CNY]"),                 # 源: research/anker-hardware.md
    DeviceSpec("SOLIX_F3800", 3.840, 1.8, 6.0, 2.4, 6.0, 9.0, 0.90, True, False,
               ("wifi", "ble"), 13999.0, family="A",
               control_note="App-only TOU+PeakShaving, 无第三方写 API [ESTIMATE CNY]"),  # 源: research/anker-hardware.md
    DeviceSpec("SOLIX_F3800_PLUS", 3.840, 6.0, 6.0, 3.2, 6.0, 9.0, 0.91, True, False,
               ("wifi", "ble"), 17999.0, family="A",
               control_note="App-only; AC-couple [ESTIMATE CNY]"),           # 源: research/anker-hardware.md
    # ---- Family B: 整户备电 E10 (无馈网 FAQ 确认, App-only) ----  源: research/anker-hardware.md
    DeviceSpec("SOLIX_E10", 6.144, 7.6, 7.6, 9.0, 7.6, 37.2, 0.90, False, False,
               ("wifi", "ble"), 28999.0, family="B",
               control_note="无馈网(FAQ#2); AC 充电经 Power Dock ≈ 额定 [ESTIMATE CNY]"),  # 源: research/anker-hardware.md
    # ---- Family C: 并网家庭储能 (项目主目标) ----
    # 确认可本地控制 (官方 HA Modbus TCP) 的三个型号 = controllable=True:
    DeviceSpec("SOLARBANK_4_E5000", 5.024, 2.5, 2.5, 5.0, 5.0, 5.0, 0.92, True, True,
               ("wifi", "ble", "modbus", "cloud_api"), 12999.0, family="C",
               control_note="官方 HA 集成 + 确认本地 Modbus TCP; 5 kW 双向按每向 2.5 kW 保守拆分"),  # 源: research/anker-hardware.md
    DeviceSpec("XE", 7.0, 5.0, 5.0, 15.0, 5.0, 5.0, 0.92, True, True,
               ("wifi", "ble", "modbus", "cloud_api"), 25999.0, family="C",
               control_note="官方 HA 集成 + 确认本地 Modbus TCP; 5 kW 双向"),   # 源: research/anker-hardware.md
    DeviceSpec("SOLARBANK_MAX_AC", 7.0, 2.5, 2.5, 5.0, 5.0, 5.0, 0.92, True, True,
               ("wifi", "ble", "modbus", "cloud_api"), 16999.0, family="C",
               control_note="官方 HA 集成 + 确认本地 Modbus TCP; 5 kW 双向每向 2.5"),  # 源: research/anker-hardware.md
    # 有 Modbus 协议参考文档但被官方 HA 集成排除 → controllable=False:
    DeviceSpec("X1", 5.0, 5.0, 5.0, 10.0, 6.0, 6.6, 0.92, True, False,
               ("wifi", "modbus"), 39999.0, family="C",
               control_note="Modbus 协议参考文档存在，但未纳入官方 HA 集成，写入控制未经端到端验证"),  # 源: research/anker-hardware.md
    # ---- Family D: 阳台储能 (社区非官方云 API, 无本地 Modbus) ----  源: research/anker-hardware.md
    DeviceSpec("SOLARBANK_2_E1600", 1.6, 0.8, 0.8, 2.4, 0.8, 0.8, 0.90, True, False,
               ("wifi", "ble"), 4599.0, family="D",
               control_note="无本地 Modbus; 社区非官方云 API [ESTIMATE CNY]"),  # 源: research/anker-hardware.md
]


class HardwareCatalog:
    def __init__(self) -> None:
        self._specs: Dict[str, DeviceSpec] = {s.model: s for s in _SPECS}

    def get(self, model: str) -> DeviceSpec:
        if model not in self._specs:
            raise ValueError("unknown model %r; available: %s" % (model, sorted(self._specs)))
        return self._specs[model]

    def models(self) -> List[str]:
        return sorted(self._specs.keys())

    def battery_config(self, model: str, soc_start: Optional[float] = None) -> BatteryConfig:
        spec = self.get(model)
        return BatteryConfig(
            capacity_kwh=spec.capacity_kwh,
            max_charge_kw=spec.max_charge_kw,
            max_discharge_kw=spec.max_discharge_kw,
            round_trip_eff=spec.round_trip_eff,
            soc_min=0.05,
            soc_max=1.0,
            soc_start=soc_start if soc_start is not None else spec.soc_start_default,
            cycle_life=6000,
            pack_cost_cny=spec.price_cny,
            reserve_soc=0.10,
        )

    def aggregate(self, models: List[str]) -> BatteryConfig:
        """并联拓扑:容量与功率求和,效率取平均。"""
        if not models:
            raise ValueError("aggregate needs at least one model")
        specs = [self.get(m) for m in models]
        cap = sum(s.capacity_kwh for s in specs)
        return BatteryConfig(
            capacity_kwh=cap,
            max_charge_kw=sum(s.max_charge_kw for s in specs),
            max_discharge_kw=sum(s.max_discharge_kw for s in specs),
            round_trip_eff=sum(s.round_trip_eff for s in specs) / len(specs),
            soc_min=0.05,
            soc_max=1.0,
            soc_start=specs[0].soc_start_default,
            cycle_life=6000,
            pack_cost_cny=sum(s.price_cny for s in specs),
            reserve_soc=0.10,
        )


@dataclass
class HomeLoad:
    base_kw: float                       # 基础负荷
    hourly_profile: List[float] = field(default_factory=lambda: list(_RESIDENTIAL_PROFILE))  # 24 点归一化系数
    critical_kw: float = 0.4             # 断电容忍最小功率

    def series(self) -> List[float]:
        """逐时负荷 kW = base_kw × 归一化系数。"""
        return [self.base_kw * c for c in self.hourly_profile]


@dataclass
class SiteConfig:
    """站点配置:设备型号、电池容量、光伏、电价城市、负荷画像。"""
    site_id: str = "demo-home"
    model: str = "SOLARBANK_4_E5000"
    quantity: int = 1
    capacity_kwh: Optional[float] = None   # 覆盖聚合容量
    tariff_city: str = "shenzhen"
    load_kw: Optional[float] = None        # 平均负荷;None 则用 base 默认
    pv_kwp: float = 5.0
    load_profile: List[float] = field(default_factory=lambda: list(_RESIDENTIAL_PROFILE))


def demo_site() -> SiteConfig:
    # 选用已确认支持本地 Modbus 控制的型号作为默认站点,使演示与真实自动化能力一致。
    return SiteConfig(
        site_id="demo-home",
        model="SOLARBANK_4_E5000",     # 源: research/anker-hardware.md (官方 HA Modbus TCP)
        quantity=1,
        capacity_kwh=5.024,
        tariff_city="shenzhen",
        load_kw=1.2,
        pv_kwp=5.0,
    )