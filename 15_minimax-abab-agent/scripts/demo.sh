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
echo -e "${CYAN}  15_minimax-abab-agent · MiniMax 商业应用参赛作品演示${NC}"
echo -e "${CYAN}  原生富媒体沉浸式互动推理剧 Agent (abab 文本 + 拟真情绪 TTS)${NC}"
echo -e "${CYAN}================================================================${NC}"

cd src

echo -e "\n${BLUE}[1/2] 运行互动推理剧角色会话演示 (强制离线确定性 Mock 降级)...${NC}"
AGENT_FORCE_OFFLINE=1 npm run demo -- he-jinglan

echo -e "\n${BLUE}[2/2] 运行全维度商业量化评测体系 (人格一致性 / 情绪准确 / 表现力 / 延迟)...${NC}"
npm run eval

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  15_minimax-abab-agent 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
