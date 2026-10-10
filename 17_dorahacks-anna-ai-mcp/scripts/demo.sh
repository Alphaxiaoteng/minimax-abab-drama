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
echo -e "${CYAN}  17_dorahacks-anna-ai-mcp · DoraHacks Anna AI MCP 参赛作品演示${NC}"
echo -e "${CYAN}  NetIntel MCP Server (零依赖手写 JSON-RPC 2.0 + 协议合规与开源情报聚合)${NC}"
echo -e "${CYAN}================================================================${NC}"

echo -e "\n${BLUE}[1/2] 编译 TypeScript 项目...${NC}"
npm run build

echo -e "\n${BLUE}[2/2] 运行 MCP 协议合规端到端冒烟验证 (17 步全覆盖)...${NC}"
npm run smoke

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  17_dorahacks-anna-ai-mcp 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
