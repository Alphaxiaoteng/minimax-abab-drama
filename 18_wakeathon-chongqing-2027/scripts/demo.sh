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
echo -e "${CYAN}  18_wakeathon-chongqing-2027 · 雾客松重庆跨年 AI 参赛作品演示${NC}"
echo -e "${CYAN}  雾醒山城 · 3D 空间计算与现场互动评测架构 (WAKE UP WITH AI)${NC}"
echo -e "${CYAN}================================================================${NC}"

cd src

echo -e "\n${BLUE}[1/2] 编译生产包与 TypeScript 类型检查...${NC}"
npm run build

echo -e "\n${BLUE}[2/2] 运行 24 场景全量视觉原型与帧率评测矩阵...${NC}"
npm run eval

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  18_wakeathon-chongqing-2027 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
