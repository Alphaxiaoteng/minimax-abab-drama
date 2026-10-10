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
echo -e "${CYAN}  08_anker-hackathon-2026 · Anker 智能硬件 Agent 参赛作品演示${NC}"
echo -e "${CYAN}  Anker Solix 家庭光储系统动态时序优化与边缘 MPC 调度管家${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/2] 运行 24h 闭环 MPC 滚动优化求解与套利收益演示...${NC}"
uv run --with pytest --with pulp --with highspy --with fastapi --with httpx --with pydantic \
  python3 scripts/demo_cli.py

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  08_anker-hackathon-2026 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
