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
echo -e "${CYAN}  16_zhipu-autoglm-agent · 智谱 AutoGLM 智能体参赛作品演示${NC}"
echo -e "${CYAN}  端侧设备跨平台自动化操作与自愈容错智能体 (手机 + 桌面 + 政务)${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/2] 运行虚拟设备三场景端侧闭环演示 (比价领券 / 发票报销 / 政务取证)...${NC}"
uv run python src/run_demo.py

echo -e "\n${BLUE}[2/2] 验证故障注入自愈模式 (UI 漂移与看门狗容错)...${NC}"
uv run python src/run_demo.py --chaos

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  16_zhipu-autoglm-agent 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
