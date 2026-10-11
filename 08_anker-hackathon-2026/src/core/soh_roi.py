"""电池健康度 (SOH) 退化模型与全生命周期 ROI 预测引擎。

核心功能：
1. 温度 +DoD(放电深度) 联合退化模型
2. 循环寿命衰减曲线预测
3. 全生命周期成本 (LCC) 分析
4. 投资回报期 (Payback Period) 计算
5. 碳减排与环保账单生成
6. PDF/HTML 报告导出支持
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel


@dataclass
class BatteryDegradationModel:
    """电池退化物理模型（温度×DoD 耦合）。
    
    基于 Arrhenius 方程 + Miner 累积损伤理论：
    - 高温加速化学老化
    - 深度放电增加机械应力
    - 循环计数累计容量衰减
    
    公式来源：
    1. NCA/LFP 电池退化文献 (J. Power Sources 2020)
    2. Tesla Megapack SOH 维护策略
    3. Anker SOLIX 实测数据拟合
    """
    
    # 基础参数
    initial_capacity_kwh: float = 10.0       # 初始容量
    rated_cycles: int = 6000                  # 标称循环次数 (80% SOH)
    pack_cost_cny: float = 25000.0           #  packs 成本
    calendar_life_years: int = 20             # 日历寿命
    
    # 退化系数
    temperature_coefficient: float = 0.025   # 每°C 退化率增量
    dod_coefficient: float = 0.0015          # DoD 每%的额外损耗
    c_rate_coefficient: float = 0.0005       # C-rate 快充损耗
    
    # 运行条件
    avg_temperature_c: float = 25.0          # 平均工作温度
    avg_do_pct: float = 60.0                 # 平均放电深度 (%)
    avg_c_rate: float = 0.5                  # 平均充放电速率
    
    def get_soh(self, cycles_used: int, days_calendar: int) -> float:
        """计算当前健康度 SOH(0-1)。
        
        Args:
            cycles_used: 已用循环次数
            days_calendar: 日历天数
            
        Returns:
            SOH 值 (1.0=新，0.8=寿命终点)
        """
        # 1. 循环退化分量
        cycle_degradation = cycles_used / self.rated_cycles
        cycle_degradation *= (1.0 + self.dod_coefficient * self.avg_do_pct / 100.0)
        cycle_degradation *= (1.0 + self.c_rate_coefficient * self.avg_c_rate * 2)
        
        # 2. 日历退化分量 (Arrhenius 方程)
        ref_temp = 25.0  # 参考温度
        activation_energy = 0.7  # eV (锂离子电池典型值)
        boltzman = 8.617e-5  # eV/K
        temp_factor = math.exp(
            (activation_energy / boltzman) * (1.0 / (ref_temp + 273.15) - 1.0 / (self.avg_temperature_c + 273.15))
        )
        calendar_degradation = (days_calendar / 365.0) / self.calendar_life_years * temp_factor
        
        # 3. 总退化 (并行叠加)
        total_degradation = cycle_degradation * 0.6 + calendar_degradation * 0.4
        soh = 1.0 - total_degradation
        
        return max(0.8, min(1.0, soh))  # 限制在 80%-100%
    
    def get_degradation_cost_per_cycle(self, current_soh: float) -> float:
        """计算当前 SOH 下的单次循环退化成本。
        
        Args:
            current_soh: 当前健康度
            
        Returns:
            每次完整循环的成本（元）
        """
        remaining_capacity = current_soh * self.initial_capacity_kwh
        cost_per_cycle = self.pack_cost_cny / (self.rated_cycles * current_soh)
        return cost_per_cycle
    
    def predict_remaining_life(self, current_soh: float, cycles_per_day: float) -> Dict:
        """预测剩余使用寿命。
        
        Args:
            current_soh: 当前健康度
            cycles_per_day: 日均循环次数
            
        Returns:
            {"cycles_remaining": int, "years_remaining": float, "doe_date": str}
        """
        if current_soh <= 0.8:
            return {
                "cycles_remaining": 0,
                "years_remaining": 0.0,
                "months_remaining": 0,
                "roe_date": "已达寿命终点",
            }
            
        remaining_degradation = current_soh - 0.8
        estimated_cycles_remaining = int(remaining_degradation * self.rated_cycles)
        estimated_days_remaining = estimated_cycles_remaining / max(cycles_per_day, 0.1)
        estimated_years = estimated_days_remaining / 365.0
        
        from datetime import timedelta
        doe = datetime.now() + timedelta(days=estimated_days_remaining)
        
        return {
            "cycles_remaining": estimated_cycles_remaining,
            "years_remaining": round(estimated_years, 2),
            "months_remaining": round(estimated_years * 12, 0),
            "expected_end_date": doe.strftime("%Y-%m-%d"),
        }


@dataclass
class ROIPredictor:
    """投资回报预测引擎。
    
    计算 LCOE(平准化度电成本)、NPV、IRR、Payback Period。
    """
    
    # 初始投资（所有参数必须有默认值）
    battery_cost_cny: float = 25000.0
    inverter_cost_cny: float = 8000.0
    installation_cost_cny: float = 5000.0
    monitoring_system_cost_cny: float = 2000.0
    
    annual_savings_cny: float = 1500.0      # 年节省电费
    annual_maintenance_cny: float = 500.0   # 年维护费
    battery_replacement_year: int = 12      # 电池更换年份
    
    discount_rate: float = 0.05              # 折现率 5%
    electricity_price_trend: float = 0.03   # 电价年涨 3%
    
    carbon_credit_value: float = 0.05       # 碳信用价格 (元/kg CO₂)
    annual_carbon_reduction_kg: float = 300 # 年减排量
    
    def calculate_payback_period(self) -> Dict:
        """计算静态/动态投资回收期。
        
        Returns:
            回收期分析结果
        """
        total_initial_investment = (
            self.battery_cost_cny + 
            self.inverter_cost_cny + 
            self.installation_cost_cny +
            self.monitoring_system_cost_cny
        )
        
        # 静态回收期
        annual_net_benefit = self.annual_savings_cny - self.annual_maintenance_cny
        payback_simple = total_initial_investment / annual_net_benefit
        
        # 动态回收期 (考虑电价上涨)
        cumulative_cash_flow = -total_initial_investment
        year = 0
        payback_discounted = 0.0
        
        for yr in range(1, 21):
            nominal_benefit = self.annual_savings_cny * ((1 + self.electricity_price_trend) ** yr)
            maintenance = self.annual_maintenance_cny * ((1 + 0.02) ** yr)  # 维护费年涨 2%
            net_cash_flow = nominal_benefit - maintenance
            
            # 碳收益
            carbon_income = self.annual_carbon_reduction_kg * self.carbon_credit_value
            net_cash_flow += carbon_income
            
            cumulative_cash_flow += net_cash_flow / ((1 + self.discount_rate) ** yr)
            
            if cumulative_cash_flow >= 0 and payback_discounted == 0.0:
                payback_discounted = yr - 1 + (abs(cumulative_cash_flow - net_cash_flow / ((1 + self.discount_rate) ** yr)) / net_cash_flow)
                break
                
            year = yr
        
        if payback_discounted == 0.0:
            payback_discounted = year + 1
            
        return {
            "total_initial_investment_cny": total_initial_investment,
            "payback_period_simple_years": round(payback_simple, 1),
            "payback_period_discounted_years": round(payback_discounted, 1),
            "annual_net_benefit_cny": annual_net_benefit,
        }
    
    def calculate_lcoe(self) -> float:
        """计算平准化度电成本 LCOE(元/kWh)。
        
        Returns:
            LCOE value
        """
        total_initial_investment = (
            self.battery_cost_cny + 
            self.inverter_cost_cny + 
            self.installation_cost_cny
        )
        
        # 假设每日循环 0.8 次，20 年生命周期
        daily_throughput_kwh = self.battery_cost_cny / 25000.0 * 10.0 * 0.8  # 容量折算
        annual_throughput_kwh = daily_throughput_kwh * 365
        
        # 资本回收因子 CRF
        crf = self.discount_rate * ((1 + self.discount_rate) ** 20) / (((1 + self.discount_rate) ** 20) - 1)
        
        # 年度化成本
        annualized_capital = total_initial_investment * crf
        annualized_maintenance = self.annual_maintenance_cny
        total_annual_cost = annualized_capital + annualized_maintenance
        
        lcoe = total_annual_cost / annual_throughput_kwh
        
        return round(lcoe, 3)
    
    def calculate_npv_irr(self) -> Dict:
        """计算净现值 NPV 和内部收益率 IRR。
        
        Returns:
            NPV, IRR analysis
        """
        total_initial_investment = (
            self.battery_cost_cny + 
            self.inverter_cost_cny + 
            self.installation_cost_cny +
            self.monitoring_system_cost_cny
        )
        
        # 现金流序列 (20 年)
        cash_flows = [-total_initial_investment]
        
        for yr in range(1, 21):
            nominal_savings = self.annual_savings_cny * ((1 + self.electricity_price_trend) ** yr)
            maintenance = self.annual_maintenance_cny * ((1 + 0.02) ** yr)
            carbon_income = self.annual_carbon_reduction_kg * self.carbon_credit_value
            
            # 第 12 年电池更换
            if yr == 12:
                battery_replacement = self.battery_cost_cny * 0.7  # 70% 第二组成本
                cash_flows.append(nominal_savings - maintenance + carbon_income - battery_replacement)
            else:
                cash_flows.append(nominal_savings - maintenance + carbon_income)
                
        # NPV @ 5%
        npv = sum(cf / ((1 + self.discount_rate) ** i) for i, cf in enumerate(cash_flows))
        
        # Simple IRR approximation
        irr = self._approximate_irr(cash_flows)
        
        return {
            "npv_cny": round(npv, 2),
            "irr_pct": round(irr * 100, 1),
            "cash_flow_profile": cash_flows[:10],  # 显示前 10 年
        }
    
    def _approximate_irr(self, cash_flows: List[float], max_iter: int = 100, tol: float = 1e-6) -> float:
        """简单 IRR 近似算法。"""
        irr = 0.1  # 初始猜测 10%
        
        for _ in range(max_iter):
            npv = sum(cf / ((1 + irr) ** i) for i, cf in enumerate(cash_flows))
            
            if abs(npv) < tol:
                break
                
            # 数值导数
            h = 0.001
            npv_h = sum(cf / ((1 + irr + h) ** i) for i, cf in enumerate(cash_flows))
            derivative = (npv_h - npv) / h
            
            if abs(derivative) < 1e-10:
                break
                
            new_irr = irr - npv / derivative
            
            if abs(new_irr - irr) < tol:
                irr = new_irr
                break
                
            irr = new_irr
            
        return irr


# Pydantic models
class SOHStatus(BaseModel):
    current_soh: float
    cycles_used: int
    days_calendar: int
    degradation_rate_per_year: float
    predicted_remaining_life: Dict


class ROIReportRequest(BaseModel):
    battery_cost_cny: float = 25000.0
    annual_savings_cny: float = 1500.0
    annual_maintenance_cny: float = 500.0
    carbon_reduction_kg: float = 300.0
    carbon_credit_value: float = 0.05


class ROIReport(BaseModel):
    investment_summary: Dict
    payback_analysis: Dict
    lcoe_analysis: Dict
    npv_irr_analysis: Dict
    environmental_impact: Dict
    lifecycle_projection: List[Dict]


def generate_html_report(soh_status: SOHStatus, roi_data: ROIReport, output_path: str):
    """生成 HTML 格式的 SOH/ROI 分析报告。"""
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Anker SOLIX 电池健康度与投资回报报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a73e8; border-bottom: 3px solid #1a73e8; padding-bottom: 12px; }}
        h2 {{ color: #34a853; margin-top: 32px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 24px 0; }}
        .metric-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 24px; border-radius: 8px; text-align: center; }}
        .metric-value {{ font-size: 36px; font-weight: bold; margin: 8px 0; }}
        .metric-label {{ font-size: 14px; opacity: 0.9; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .positive {{ color: #34a853; font-weight: bold; }}
        .negative {{ color: #ea4335; font-weight: bold; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔋 Anker SOLIX 电池健康度与投资回报报告</h1>
        <p>生成时间：<strong>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</strong></p>
        
        <h2>📊 电池健康度 (SOH)</h2>
        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-value">{soh_status.current_soh*100:.1f}%</div>
                <div class="metric-label">当前 SOH</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{soh_status.predicted_remaining_life.get("years_remaining", 0):.1f}</div>
                <div class="metric-label">预计剩余年限</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{soh_status.cycles_used:,}</div>
                <div class="metric-label">已用循环次数</div>
            </div>
        </div>
        
        <h2>💰 投资回报分析</h2>
        <table>
            <tr><th>指标</th><th>数值</th><th>说明</th></tr>
            <tr><td>总投资额</td><td>¥{roi_data.investment_summary['total_initial_investment_cny']:,.2f}</td><td>电池+ 逆变器 + 安装</td></tr>
            <tr><td>静态回收期</td><td>{roi_data.payback_analysis['payback_period_simple_years']:.1f}年</td><td>不考虑折现</td></tr>
            <tr><td>动态回收期</td><td>{roi_data.payback_analysis['payback_period_discounted_years']:.1f}年</td><td>考虑 5% 折现率</td></tr>
            <tr><td>LCOE</td><td>¥{roi_data.lcoe_analysis['lcoe_per_kwh']:.3f}/kWh</td><td>平准化度电成本</td></tr>
            <tr><td>NPV (@5%)</td><td class="{'positive' if roi_data.npv_irr_analysis['npv_cny'] > 0 else 'negative'}">¥{roi_data.npv_irr_analysis['npv_cny']:,.2f}</td><td>净现值</td></tr>
            <tr><td>IRR</td><td class="{'positive' if roi_data.npv_irr_analysis['irr_pct'] > 5 else 'negative'}">{roi_data.npv_irr_analysis['irr_pct']:.1f}%</td><td>内部收益率</td></tr>
        </table>
        
        <h2>🌱 环境影响</h2>
        <table>
            <tr><th>指标</th><th>年度贡献</th><th>20 年累计</th></tr>
            <tr><td>碳减排量</td><td>{roi_data.environmental_impact['annual_carbon_kg']:,.0f} kg CO₂</td><td>{roi_data.environmental_impact['lifecycle_carbon_kg']:,.0f} kg CO₂</td></tr>
            <tr><td>等效植树</td><td>{roi_data.environmental_impact['annual_trees_equiv']:.1f} 棵</td><td>{roi_data.environmental_impact['lifecycle_trees_equiv']:.1f} 棵</td></tr>
            <tr><td>碳收益</td><td>¥{roi_data.environmental_impact['annual_carbon_revenue']:,.2f}</td><td>¥{roi_data.environmental_impact['lifecycle_carbon_revenue']:,.2f}</td></tr>
        </table>
        
        <div class="footer">
            <p>本报告由 Anker SOLIX Energy Management System 生成 | 数据仅供决策参考</p>
        </div>
    </div>
</body>
</html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    return output_path


def generate_pdf_report(soh_status: SOHStatus, roi_data: ROIReport, output_path: str):
    """生成 PDF 格式报告（需要 reportlab 库）。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#1a73e8"))
        heading_style = ParagraphStyle("CustomHeading", parent=styles["Heading2"], fontSize=14, textColor=colors.HexColor("#34a853"))
        
        elements.append(Paragraph("Anker SOLIX 电池健康度与投资回报报告", title_style))
        elements.append(Spacer(1, 20))
        
        elements.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        
        elements.append(Paragraph("📊 电池健康度 (SOH)", heading_style))
        
        soh_data = [
            ["当前 SOH", f"{soh_status.current_soh*100:.1f}%"],
            ["预计剩余寿命", f"{soh_status.predicted_remaining_life.get('years_remaining', 0):.1f}年"],
            ["已用循环次数", f"{soh_status.cycles_used:,}次"],
        ]
        soh_table = Table(soh_data, colWidths=[150, 200])
        soh_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Heiti"),
            ("FONTSIZE", (0, 0), (-1, -1), 12),
            ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ("ROWHEIGHT", (0, 0), (-1, -1), 20),
        ]))
        elements.append(soh_table)
        
        doc.build(elements)
        return output_path
        
    except ImportError:
        raise RuntimeError("PDF generation requires reportlab: pip install reportlab")


# Export symbols
__all__ = [
    "BatteryDegradationModel",
    "ROIPredictor",
    "SOHStatus", 
    "ROIReport",
    "generate_html_report",
    "generate_pdf_report",
]
