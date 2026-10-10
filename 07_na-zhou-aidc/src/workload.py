"""AIDC 数据中心 IT 负载与制冷功耗模拟 —— 全项目的物理驱动模块。

模型要点
--------
1. IT 基荷：it_base_kw × 平滑昼夜因子（峰值在 14:00，谷值在凌晨），
   范围 [DIURNAL_MIN, 1.0] × it_base_kw，恒 ≤ it_base_kw。
2. 瞬态算力峰值 (transient AI-training peaks)：Poisson 式到达的训练任务，
   每个任务有起始步、持续步数 (2~8 步)、功率幅度受 headroom = it_peak − base 约束。
   情景强度由 Scenario.spike_count / spike_scale / extreme_spike 决定：
     - baseline_day   : 1 次温和峰值
     - transient_spike: 6 次可重叠峰值
     - extreme_peak   : 单个满发 ~6 步(1.5h) 主导峰值 + 背景小幅峰值
3. 硬性钳制：叠加后 IT 功率 ≤ it_peak_kw。
4. 制冷：cooling_ratio_base × it × partload × ambient_factor；
   无储能时整机 PUE 落在 ~1.3-1.6。
5. 环境温度：正弦 24h，峰 34°C(15:00)、谷 20°C(03:00)，可叠加噪声。

确定性：所有随机量来自 numpy.random.default_rng(scenario.seed)。
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from src.config import N_STEPS, STEP_HOURS, Scenario

# --------------------------------------------------------------------------
# 物理/统计常数
# --------------------------------------------------------------------------
DIURNAL_MIN: float = 0.88
DIURNAL_PEAK_HOUR: float = 14.0

_AMBIENT_CENTER_C: float = 27.0
_AMBIENT_AMP_C: float = 7.0
_AMBIENT_PEAK_HOUR: float = 15.0
_AMBIENT_REF_C: float = 24.0
_AMBIENT_SLOPE: float = 0.012

_PARTLOAD_ALPHA: float = 0.15

_EXTREME_DUR_STEPS: int = 6
_EXTREME_REACH: float = 0.97
_EXTREME_BG_SCALE: float = 0.20

JOB_DUR_MIN: int = 2
JOB_DUR_MAX: int = 8


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _hours() -> np.ndarray:
    return np.arange(N_STEPS, dtype=np.float64) * STEP_HOURS


def _diurnal_factor() -> np.ndarray:
    """平滑昼夜因子 ∈ [DIURNAL_MIN, 1.0]，峰值 DIURNAL_PEAK_HOUR。"""
    h = _hours()
    shape = 0.5 + 0.5 * np.cos(2.0 * np.pi * (h - DIURNAL_PEAK_HOUR) / 24.0)
    return DIURNAL_MIN + (1.0 - DIURNAL_MIN) * shape


def _base_load_array(it_base_kw: float) -> np.ndarray:
    """逐点基荷 (kW)，恒 ≤ it_base_kw。"""
    return it_base_kw * _diurnal_factor()


def _ramp_shape(k: int, dur: int) -> float:
    """任务功率包络：首末半幅，次首末 0.8 幅，中间满幅。"""
    if k == 0 or k == dur - 1:
        return 0.5
    if k == 1 or k == dur - 2:
        return 0.8
    return 1.0


def _add_job(add: np.ndarray, headroom: np.ndarray, start: int, dur: int,
             amp_frac: float) -> None:
    """把一个训练任务叠加到 add（in-place）。"""
    for k in range(dur):
        idx = start + k
        if idx >= N_STEPS:
            break
        add[idx] += amp_frac * _ramp_shape(k, dur) * headroom[idx]


# --------------------------------------------------------------------------
# 环境温度剖面
# --------------------------------------------------------------------------
def ambient_profile(seed: Optional[int] = None) -> np.ndarray:
    """24h 环境温度 (°C)，正弦：峰 34°C@15:00，谷 20°C@03:00。

    seed 非 None 时叠加 σ=0.3°C 高斯扰动（典型夏季气象不确定性）。
    输出裁剪到 [15, 40]°C。
    """
    h = _hours()
    base = _AMBIENT_CENTER_C + _AMBIENT_AMP_C * np.cos(
        2.0 * np.pi * (h - _AMBIENT_PEAK_HOUR) / 24.0
    )
    if seed is not None:
        rng = np.random.default_rng(seed)
        base = base + rng.normal(0.0, 0.3, size=N_STEPS)
    return np.clip(base, 15.0, 40.0).astype(np.float64)


# --------------------------------------------------------------------------
# IT 功率生成
# --------------------------------------------------------------------------
def generate_it_power(scenario: Scenario) -> np.ndarray:
    """生成 IT 功率序列 (kW, float64, N_STEPS)。

    确定性：给定 scenario.seed 总产生相同序列。
    钳制：it_power[t] ≤ it_peak_kw。
    """
    dc = scenario.datacenter
    rng = np.random.default_rng(scenario.seed)
    base = _base_load_array(dc.it_base_kw)
    headroom = dc.it_peak_kw - base  # 每步可追加空间 > 0
    add = np.zeros(N_STEPS, dtype=np.float64)

    def _rand_start() -> int:
        lo = 16
        hi = max(lo, N_STEPS - JOB_DUR_MAX)
        return int(rng.integers(lo, hi + 1))

    if scenario.extreme_spike:
        start = _rand_start()
        _add_job(add, headroom, start, _EXTREME_DUR_STEPS, _EXTREME_REACH)
        for _ in range(int(scenario.spike_count)):
            s = _rand_start()
            d = int(rng.integers(JOB_DUR_MIN, 5))
            a = _EXTREME_BG_SCALE * float(rng.uniform(0.5, 1.0))
            _add_job(add, headroom, s, d, a)
    else:
        for _ in range(int(scenario.spike_count)):
            s = _rand_start()
            d = int(rng.integers(JOB_DUR_MIN, JOB_DUR_MAX + 1))
            a = scenario.spike_scale * float(rng.uniform(0.6, 1.0))
            _add_job(add, headroom, s, d, a)

    add = np.clip(add, 0.0, headroom)
    it = base + add
    it = np.minimum(it, dc.it_peak_kw)
    return it.astype(np.float64)


# --------------------------------------------------------------------------
# 制冷功耗
# --------------------------------------------------------------------------
def generate_cooling(
    it_power_kw: np.ndarray,
    scenario: Scenario,
    ambient_c: Optional[np.ndarray] = None,
) -> np.ndarray:
    """制冷功耗 (kW)。

    cooling = cooling_ratio_base × it × partload_factor × ambient_factor
    - partload: 低负载时 chiller 效率下降 (COP 退化)。
    - ambient: 环境温度高于基准 24°C 时制冷量上升。
    """
    it = np.asarray(it_power_kw, dtype=np.float64)
    dc = scenario.datacenter
    if ambient_c is None:
        ambient_c = ambient_profile()
    ambient_c = np.asarray(ambient_c, dtype=np.float64)

    load_fraction = np.clip(it / dc.it_peak_kw, 0.0, 1.0)
    partload = 1.0 + _PARTLOAD_ALPHA * (1.0 - load_fraction)
    amb_factor = 1.0 + _AMBIENT_SLOPE * (ambient_c - _AMBIENT_REF_C)

    cooling = dc.cooling_ratio_base * it * partload * amb_factor
    return np.maximum(cooling, 0.0).astype(np.float64)


# --------------------------------------------------------------------------
# 峰值统计（供 report 模块使用）
# --------------------------------------------------------------------------
def spike_stats(it_power_kw: np.ndarray, base_kw: float) -> Dict[str, float]:
    """瞬态峰值统计。

    Parameters
    ----------
    it_power_kw: 实际 IT 功率数组
    base_kw: Scenario.datacenter.it_base_kw (标量)

    Returns
    -------
    spike_events: 连续超标步合并后的事件数
    max_spike_kw: 峰值叠加幅度最大值 (kW)
    transient_energy_kwh: 超出基荷的总能量 (kWh)
    duty: it > 1.5 × base 的步占比
    """
    it = np.asarray(it_power_kw, dtype=np.float64)
    base_arr = _base_load_array(base_kw)
    excess = np.maximum(it - base_arr, 0.0)

    active = excess > 0.05 * base_arr
    events = 0
    prev = False
    for a in active:
        if a and not prev:
            events += 1
        prev = bool(a)

    duty = float(np.mean(it > 1.5 * base_arr))
    transient_energy = float(np.sum(excess) * STEP_HOURS)
    max_excess = float(np.max(excess)) if excess.size else 0.0

    return {
        "spike_events": float(events),
        "max_spike_kw": max_excess,
        "transient_energy_kwh": transient_energy,
        "duty": duty,
    }
