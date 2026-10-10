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
echo -e "${CYAN}  09_watcha-wechat-miniapp · 观猹微信小程序参赛作品演示${NC}"
echo -e "${CYAN}  AI 一页纸快读 + 日程断舍离 (双场景秒开型 原生小程序 + 云开发 AI)${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/2] 运行小程序代码静态体积与分包合规检查...${NC}"
npm run size

echo -e "\n${BLUE}[2/2] 运行双场景离线确定性与流式秒开演示...${NC}"
npm run demo

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  09_watcha-wechat-miniapp 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
