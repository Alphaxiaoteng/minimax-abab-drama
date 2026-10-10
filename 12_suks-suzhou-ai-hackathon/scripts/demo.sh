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
echo -e "${CYAN}  12_suks-suzhou-ai-hackathon · 苏客松苏州工业 AI 质检参赛作品演示${NC}"
echo -e "${CYAN}  InspectAI 四场景工业金属件表面缺陷纯 CPU 亚秒级多通道检测${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/2] 运行离线样例图生成 (准备确定性测试集)...${NC}"
uv run --python 3.12 --with-requirements src/requirements.txt \
  python3 src/scripts/extract_samples.py --per-scene 1 --out src/service/static/samples

echo -e "\n${BLUE}[2/2] 运行工业缺陷检测引擎现场推演 (含OK/NG判决与缺陷分类)...${NC}"
uv run --python 3.12 --with-requirements src/requirements.txt \
  python3 scripts/demo_runner.py

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  12_suks-suzhou-ai-hackathon 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
