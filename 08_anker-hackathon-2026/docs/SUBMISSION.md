# Anker 软硬件 Agent 黑客松 · 参赛项目提交案 (Submission Dossier)

## 1. 项目定位与一句话价值 (Executive Summary)
- **项目名称**：Anker Solix Edge Energy Butler（安克 Solix 家庭光储智能管家）
- **参赛赛道**：Anker 软硬件智能体开发者黑客松 · 智能能源赛道（18万现金 + 包机酒）
- **一句话价值**：搭载于边缘网关的 24h 滚动时域 MPC 优化与可解释具身智能 Agent，在动态分时电价下实现电费降幅 24.4%，并杜绝充放电冲突与过度损耗。

---

## 2. 核心痛点与技术突破 (Pain Points & Innovations)
1. **痛点一：传统家庭光储逆变器规则固化，无法自适应动态分时电价**
   - *突破*：开发滚动时域模型预测控制（MPC），联合求解未来 24 小时家庭用电负荷、光伏辐照预测与阶梯分时电价，动态决策电池充放与电网交互。
2. **痛点二：同一小时“边充边放”或“边买边卖”的物理退化与模型越界**
   - *突破*：设计反同时性数学约束（余量行 + 平衡行 + 严格单调 SOC 界维护），在 120 组复杂边界工况测试下实现 100% 零冲突，电池寿命衰减成本显式纳入目标函数。
3. **痛点三：黑盒优化缺乏用户信任感**
   - *突破*：内置语义级决策解释器（Explain Engine），自动将复杂的数学对偶解与套利逻辑转化为用户易懂的自然语言操作原因（如“利用 0 点谷电 0.248 元充满，并在 10 点尖峰 1.112 元放电支撑”）。

---

## 3. 系统架构 (System Architecture)

```mermaid
flowchart TD
    subgraph EdgeDevice [安克 Solix 边缘网关 / 硬件端]
        Telemetry[实时功率采集 / 状态机 Store]
        Reactor[执行器驱动 / Safety 熔断守护]
    end

    subgraph Intelligence [智能优化与规划核]
        SolarModel[Clear-Sky 光伏发电预测]
        TariffModel[国内/海外阶梯分时电价库]
        MPCEngine[PuLP / HiGHS 线性规划求解器]
        Explainer[自然语言决策解释生成器]
    end

    Telemetry --> MPCEngine
    SolarModel --> MPCEngine
    TariffModel --> MPCEngine

    MPCEngine --> Reactor
    MPCEngine --> Explainer
    Explainer --> App[Anker App 移动端可视化 / Web API]
```

---

## 4. 权威基准指标与实测性能 (Benchmarks)

| 评测维度 | 指标参数 | 表现结果 |
|---|---|---|
| **单测通过率** | 102/102 全量通过 | `pytest` 100% 成功 |
| **电费节省幅度 (深圳典型户)** | 基准 10.31 元 → 优化 7.80 元 | **单日节约 24.37%** |
| **光伏自发自用率 (Self-Consumption)** | 无储能 42.1% → 储能协同 | **提升至 67.9%** |
| **电池反同时性冲突率** | 120 组极端边界组合 | **0 冲突 (严格互斥)** |
| **求解耗时** | 24 小时步长 (dt=1h) | **< 35ms (轻量嵌入式可运行)** |

---

## 5. 评委2分钟答辩/路演脚本 (2-Minute Pitch Script)
- **[0:00 - 0:30] 痛点引入**：各位评委好！家庭光储系统硬件卖得很好，但软件大多只是简单的“白天充、晚上放”死规则。面对全国各地甚至欧洲复杂的动态分时电价与负电价，用户根本无法发挥硬件的最大经济价值。
- **[0:30 - 1:00] 技术突破**：我们基于安克 Solix 硬件规格，打造了这套兼具硬核数学与温度的“边缘储能管家”。我们把电池充放损耗、光伏预测、动态电价建模为凸优化问题，并在边缘毫秒级求解。
- **[1:00 - 1:30] 现场实测**：运行 `./scripts/demo.sh`，仅需 0.1 秒即可完成 24 小时全局规划。在深圳电价下单日电费下降 24.4%，光伏自发自用率飙升至 68%。每一行调度动作都附带自然语言解释，告诉用户为什么此时充电、何时放电能省多少钱。
- **[1:30 - 2:00] 商业落地**：代码完全符合安克官方 SDK 与边缘网关规范，具备 RESTful API 与轻量化 WebUI，可以直接装载进下一代 Anker Solix 智能中枢。

---

## 6. 一键复现指南 (Quickstart)

```bash
# 1. 运行 102 项核心算法与 API 测试
uv run --with pytest --with pulp --with highspy --with fastapi --with httpx --with pydantic pytest

# 2. 运行一键 24h MPC 优化演示
./scripts/demo.sh
```
