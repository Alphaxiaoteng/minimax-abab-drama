#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  07_na-zhou-aidc · 初焰钠电 × AIDC 瞬态算力削峰填谷仿真演示${NC}"
echo -e "${CYAN}  基于线性规划 (PuLP) 的智算中心钠电储能充放电协同优化与 PUE 分析${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/3] 验证可用仿真情景清单...${NC}"
uv run --python 3.12 --with-requirements requirements.txt python -m src.main --list

echo -e "\n${BLUE}[2/3] 执行 24 小时瞬态大模型训练负荷仿真与 LP 优化求解...${NC}"
uv run --python 3.12 --with-requirements requirements.txt python -m src.main --all --no-charts

echo -e "\n${BLUE}[3/3] 检查生成的分析报告与量化指标...${NC}"
if [ -f "reports/pue_report.md" ]; then
  head -n 25 reports/pue_report.md
  echo -e "${GREEN}✓ 评测报告 reports/pue_report.md 已成功生成${NC}"
fi

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  07_na-zhou-aidc 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
