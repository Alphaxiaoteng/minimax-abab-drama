# Anker 智能用电管家 — 环境与集成约定 (Integration Contract)

本次并行构建的公共约束。所有切片必须遵守。

## 运行环境
- **Python 3.9.6**（系统 `/usr/bin/python3`）。禁止 3.10+ 语法（无 `match`、无 `X | Y` 运行时联合类型）。需要联合类型时 `from __future__ import annotations`。
- 已安装可直接 import：`fastapi`、`uvicorn`、`pydantic`(v2)、`pytest` 8.4、`numpy` 2.0、`pandas` 2.3。
- **未安装**：`scipy`、`ortools`、`pulp`、`requests`（requests 未验证，禁止依赖）。
- HTTP：只用标准库 `urllib.request`。
- `src/core/**` 优化链路 **禁止 import numpy**（边缘设备无 numpy）。numpy 仅允许在 `src/tests/**` 与分析脚本中。

## 代码规范
- 类型注解用 `typing.List/Dict/Tuple/Optional/Union`（`from typing import ...`），不要用 `list[...]` 下标泛型（3.9 支持但为一致性统一用 typing）。
- `@dataclass` 优先；不用 pydantic 做内部领域模型。serving 层可用 pydantic。
- 每个模块文件头加 3-5 行 docstring 说明职责。
- 中文注释/字符串可以，标识符一律英文。
- 不打印调试噪音；库代码不 `print`（CLI/server 入口除外）。
- 任何失败必须显式返回错误状态（`status="infeasible"` / `source="rule_fallback"`），**不许静默假成功、不许 stub/TODO/NotImplemented 占位**——唯一例外是 `SolixCloudAdapter` 写操作，未验证的真实云 API 必须显式 `raise NotImplementedError`。

## 目录归属（严格，不得越界写文件）
- `src/core/{tariff,solar,battery,hardware,lp,policy,optimizer,explain}.py` + `src/core/__init__.py` → 切片 A
- `src/edge/{safety,reactor,plant,telemetry,store}.py` + `src/edge/__init__.py` → 切片 B
- `src/agent/{llm,planner,fleet,hardware_adapter}.py` + `src/agent/__init__.py` → 切片 C
- `src/serving/{app,api}.py` + `src/serving/__init__.py` + `src/web/**` → 切片 D
- `src/tests/test_<你的模块>.py` → 各自切片
- **公共契约文件 `docs/01-architecture.md` 只读**，不得修改。

## 冒烟验证要求（必须真实执行）
每个切片结束前必须运行：
```bash
cd <repo root> && python3 -m pytest src/tests -q
python3 -c "<真实 import 并调用你负责的公开 API 的脚本>"
```
并在报告中贴出真实命令与真实输出（不许编造）。

## 已知可用 LLM
- `DASHSCOPE_API_KEY` 环境变量有效；`https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 可用模型：`qwen3.8-flash`（推荐，快）、`qwen3.8-max`、`qwen3.8-27b`。
- **不可用**：`qwen-plus`、`qwen-turbo`（配额耗尽）、`qwen3.8-flash-latest`（不存在）。
- 所有 LLM 调用必须有 `available == False` 时的确定性回退路径，且测试不得依赖网络。
