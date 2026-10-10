# -*- coding: utf-8 -*-
"""
aidc_workload.py
================
AIDC (人工智能算力中心) 24小时动态负载与 PUE (电源使用效率) 模型。
模拟 GPU 集群分布式训练、在线推理峰谷冲击，以及环境气温驱动的冷却机房功耗。
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class AIDCProfileConfig:
    baseline_it_kw: float = 3500.0        # 基础 IT 负荷 (3.5 MW)
    peak_training_kw: float = 3000.0      # 突发大模型训练突增负荷 (3.0 MW)
    inference_burst_kw: float = 1200.0    # 白天高并发推理潮汐波动 (1.2 MW)
    steps_per_day: int = 96               # 15 分钟分辨率 (24 * 4 = 96)
    base_pue: float = 1.15                # 理想设计工况 PUE
    temp_coef_pue: float = 0.005          # 气温每上升 1°C 对 PUE 的增益惩罚
    load_coef_pue: float = 0.04           # 低负载或满载工况下冷冻水系统的非线性 PUE 损耗

class AIDCWorkloadGenerator:
    def __init__(self, config: AIDCProfileConfig = None):
        self.config = config or AIDCProfileConfig()

    def generate_24h_profile(self, seed: int = 42) -> Dict[str, np.ndarray]:
        """
        生成 24 小时真实 AIDC 算力负载序列 (96 个时间片)。
        返回各时段的 IT 功率、气温、动态 PUE 与设施总功耗。
        """
        np.random.seed(seed)
        t = np.linspace(0, 24, self.config.steps_per_day, endpoint=False)

        # 1. 气温曲线 (典型长三角春秋过渡季，昼夜温差 16°C ~ 28°C)
        # 最低温在凌晨 5:00，最高温在午后 14:00
        ambient_temp = 22.0 + 6.0 * np.sin((t - 9.0) * np.pi / 12.0) + np.random.normal(0, 0.3, len(t))

        # 2. 推理负荷 (潮汐特征：上午 9:30-11:30、下午 14:00-17:30、晚间 20:00-22:00 高峰)
        morning_peak = np.exp(-((t - 10.5) ** 2) / 2.0)
        afternoon_peak = np.exp(-((t - 15.5) ** 2) / 3.0)
        evening_peak = 0.7 * np.exp(-((t - 21.0) ** 2) / 2.0)
        inference_load = self.config.inference_burst_kw * (morning_peak + afternoon_peak + evening_peak)

        # 3. 训练任务突发冲击 (夜间低谷期批量提交大规模分布式 Checkpoint 训练，午后突发训练)
        # 01:00 - 06:00 集中跑训练，14:00 突发一次 2 小时训练
        training_load = np.zeros_like(t)
        for i, hour in enumerate(t):
            if 1.0 <= hour <= 6.5:
                training_load[i] = self.config.peak_training_kw * 0.95 + np.random.normal(0, 50)
            elif 13.5 <= hour <= 16.0:
                training_load[i] = self.config.peak_training_kw * 0.85 + np.random.normal(0, 40)
            else:
                training_load[i] = self.config.peak_training_kw * 0.20 + np.random.normal(0, 30)

        training_load = np.maximum(0.0, training_load)

        # 4. 汇总 IT 功率
        it_power_kw = self.config.baseline_it_kw + inference_load + training_load + np.random.normal(0, 25, len(t))
        it_power_kw = np.maximum(self.config.baseline_it_kw * 0.8, it_power_kw)

        # 5. 动态 PUE 计算
        # 随着气温上升，冷水机组能耗上升；随着 IT 负载增大，PUE 展现先降后升的 U 型曲线
        normalized_load = (it_power_kw - np.min(it_power_kw)) / (np.max(it_power_kw) - np.min(it_power_kw) + 1e-5)
        pue = (
            self.config.base_pue
            + self.config.temp_coef_pue * (ambient_temp - 20.0)
            + self.config.load_coef_pue * (normalized_load - 0.7) ** 2
        )
        pue = np.clip(pue, 1.10, 1.35)

        # 6. 数据中心总功耗 (Facility Power)
        facility_total_kw = it_power_kw * pue

        return {
            "hours": t,
            "ambient_temp": ambient_temp,
            "it_power_kw": it_power_kw,
            "dynamic_pue": pue,
            "facility_total_kw": facility_total_kw
        }

    @staticmethod
    def get_tou_tariff(hours: np.ndarray) -> np.ndarray:
        """
        获取工业分时电价 (元/kWh) - 以华东/长三角典型工商业储能电价为例。
        - 尖峰 (10:00-12:00, 14:00-19:00): 1.48 元
        - 高峰 (08:00-10:00, 12:00-14:00, 19:00-22:00): 1.18 元
        - 平段 (07:00-08:00, 22:00-23:00): 0.72 元
        - 低谷 (23:00-07:00): 0.36 元
        """
        tariff = np.zeros_like(hours)
        for i, h in enumerate(hours):
            if (10.0 <= h < 12.0) or (14.0 <= h < 19.0):
                tariff[i] = 1.48
            elif (8.0 <= h < 10.0) or (12.0 <= h < 14.0) or (19.0 <= h < 22.0):
                tariff[i] = 1.18
            elif (7.0 <= h < 8.0) or (22.0 <= h < 23.0):
                tariff[i] = 0.72
            else:
                tariff[i] = 0.36
        return tariff
