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
echo -e "${CYAN}  01_coze-skills-agent · 扣子智能体参赛作品演示${NC}"
echo -e "${CYAN}  电商垂类提效插件集 (合规审查 / 差评归因 / 英文回复)${NC}"
echo -e "${CYAN}================================================================${NC}"

export PYTHONPATH=src

echo -e "\n${BLUE}[1/4] 列出已注册的智能体工具清单...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli list

echo -e "\n${BLUE}[2/4] 导出完整 OpenAPI 3.0 Schema (info/servers/tags + 每个工具 example payload)...${NC}"
EXPORTED="$(mktemp -t coze-openapi).json"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli export-openapi \
  --out "${EXPORTED}" --title "Coze电商智能体插件" --version "1.0.0"
echo -e "${GREEN}✓ OpenAPI Schema 严格校验通过, 已导出 ${EXPORTED} (扣子导入即用, 见 docs/COZE_BOT_SETUP.md)${NC}"

echo -e "\n${BLUE}[3/4] 运行核心规则引擎自检 (缺参防御与类型安全)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli selftest

echo -e "\n${BLUE}[4/4] 演示实战场景：文案合规检测 (含广告法极限词拦截与合规改写)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke check_compliance \
  --params '{"text": "这款产品全网第一、绝对无敌，药效显著包治百病，立竿见影！", "platform": "douyin"}'

echo -e "\n${BLUE}[4/4 补充] 演示实战场景：多平台差评主题洞察与自动归因...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke analyze_reviews \
  --params '{"reviews": ["快递三天没动静，到手包装全破了", "鞋子偏小两码根本穿不进去", "客服态度很差，问半天不回"], "marketplace": "tiktok"}'

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  01_coze-skills-agent 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
