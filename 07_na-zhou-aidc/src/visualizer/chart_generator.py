# -*- coding: utf-8 -*-
"""
chart_generator.py
==================
纯 Python 高清矢量 SVG 图表生成器。
渲染 AIDC 负荷削峰对比图、钠电 24H SOC 充放电轨迹图与综合经济效益瀑布图。
无需第三方绘图库依赖，开箱即用，生成可在网页、论文与 PPT 中直接嵌入的矢量图。
"""

import numpy as np
import os
from typing import Dict, Any

class SVGChartGenerator:
    @staticmethod
    def render_load_shaving_svg(
        hours: np.ndarray,
        original_kw: np.ndarray,
        grid_kw: np.ndarray,
        battery_kw: np.ndarray,
        output_path: str
    ):
        """
        生成 24 小时负载对比与电池充放电曲线 SVG。
        """
        width = 960
        height = 420
        pad_left = 70
        pad_right = 40
        pad_top = 50
        pad_bottom = 50

        plot_w = width - pad_left - pad_right
        plot_h = height - pad_top - pad_bottom

        max_kw = max(np.max(original_kw), np.max(grid_kw)) * 1.15
        min_kw = 0.0

        def x_map(h):
            return pad_left + (h / 24.0) * plot_w

        def y_map(kw):
            return pad_top + plot_h - ((kw - min_kw) / (max_kw - min_kw)) * plot_h

        # 构造多段折线路径
        orig_pts = " ".join([f"{x_map(h):.1f},{y_map(kw):.1f}" for h, kw in zip(hours, original_kw)])
        grid_pts = " ".join([f"{x_map(h):.1f},{y_map(kw):.1f}" for h, kw in zip(hours, grid_kw)])

        # 电池充放电填充条
        bars_svg = []
        bar_w = plot_w / len(hours) * 0.8
        for h, b_kw in zip(hours, battery_kw):
            cx = x_map(h)
            zero_y = y_map(0)
            if b_kw > 0:
                # 放电 (橙红色，顶峰削减)
                bh = (b_kw / max_kw) * plot_h
                bars_svg.append(f'<rect x="{cx - bar_w/2:.1f}" y="{zero_y - bh:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="#ef4444" opacity="0.45"/>')
            elif b_kw < 0:
                # 充电 (翠绿色，低谷储能)
                bh = (abs(b_kw) / max_kw) * plot_h
                bars_svg.append(f'<rect x="{cx - bar_w/2:.1f}" y="{zero_y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="#10b981" opacity="0.45"/>')

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background:#0f172a; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
  <defs>
    <linearGradient id="gridGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
    </linearGradient>
  </defs>

  <!-- Title -->
  <text x="{width/2}" y="30" fill="#f8fafc" font-size="16" font-weight="600" text-anchor="middle">
    AIDC 智算中心 24H 动态负载与钠电储能削峰填谷功率轨迹 (MW)
  </text>

  <!-- Grid lines -->
  {"".join([f'<line x1="{pad_left}" y1="{pad_top + i*plot_h/4:.1f}" x2="{width-pad_right}" y2="{pad_top + i*plot_h/4:.1f}" stroke="#334155" stroke-dasharray="4,4"/>' for i in range(5)])}
  {"".join([f'<text x="{pad_left - 12}" y="{pad_top + i*plot_h/4 + 4:.1f}" fill="#94a3b8" font-size="11" text-anchor="end">{(max_kw - i*(max_kw-min_kw)/4)/1000:.1f} MW</text>' for i in range(5)])}

  <!-- Time Labels -->
  {"".join([f'<text x="{x_map(h):.1f}" y="{height - pad_bottom + 20}" fill="#94a3b8" font-size="11" text-anchor="middle">{int(h):02d}:00</text>' for h in [0, 4, 8, 12, 16, 20, 24]])}

  <!-- Battery Bars -->
  {"".join(bars_svg)}

  <!-- Curves -->
  <polyline points="{orig_pts}" fill="none" stroke="#f43f5e" stroke-width="2.5" stroke-dasharray="6,4" opacity="0.8"/>
  <polyline points="{grid_pts}" fill="none" stroke="#38bdf8" stroke-width="3"/>

  <!-- Legend -->
  <g transform="translate({width - 340}, 20)">
    <line x1="0" y1="0" x2="25" y2="0" stroke="#f43f5e" stroke-width="2.5" stroke-dasharray="4,3"/>
    <text x="32" y="4" fill="#f43f5e" font-size="12">原始 AIDC 设施负荷</text>
    
    <line x1="160" y1="0" x2="185" y2="0" stroke="#38bdf8" stroke-width="3"/>
    <text x="192" y="4" fill="#38bdf8" font-size="12">电网受电功率 (削峰后)</text>
  </g>
</svg>"""

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(svg)
