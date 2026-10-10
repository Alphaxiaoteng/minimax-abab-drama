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

echo -e "\n${BLUE}[1/5] 列出已注册的智能体工具清单...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli list

echo -e "\n${BLUE}[2/5] 导出完整 OpenAPI 3.0 Schema (info/servers/tags + 每个工具 example payload)...${NC}"
EXPORTED="$(mktemp -t coze-openapi).json"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli export-openapi \
  --out "${EXPORTED}" --title "Coze电商智能体插件" --version "1.0.0"
echo -e "${GREEN}✓ OpenAPI Schema 严格校验通过, 已导出 ${EXPORTED} (扣子导入即用, 见 docs/COZE_BOT_SETUP.md)${NC}"

echo -e "\n${BLUE}[3/5] 运行核心规则引擎自检 (缺参防御与类型安全)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli selftest

echo -e "\n${BLUE}[4/5] 演示实战场景：文案合规检测 (含广告法极限词拦截与合规改写)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke check_compliance \
  --params '{"text": "这款产品全网第一、绝对无敌，药效显著包治百病，立竿见影！", "platform": "douyin"}'

echo -e "\n${BLUE}[4/5 补充] 演示实战场景：多平台差评主题洞察与自动归因...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke analyze_reviews \
  --params '{"reviews": ["快递三天没动静，到手包装全破了", "鞋子偏小两码根本穿不进去", "客服态度很差，问半天不回"], "marketplace": "tiktok"}'

echo -e "\n${BLUE}[5/5] 拉起网关 (gateway.py) 并验收 Plugin Debugger Studio 工作台...${NC}"
DEMO_PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
GATEWAY_PID=""
cleanup() { [ -n "${GATEWAY_PID}" ] && kill "${GATEWAY_PID}" 2>/dev/null || true; }
trap cleanup EXIT
uv run --with fastapi --with uvicorn --with pydantic python3 -m uvicorn coze_skills.gateway:create_app --factory --host 127.0.0.1 --port "${DEMO_PORT}" >/tmp/coze-gateway-demo.log 2>&1 &
GATEWAY_PID=$!
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${DEMO_PORT}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.25
done
STUDIO_HTML="$(curl -sf "http://127.0.0.1:${DEMO_PORT}/")"
echo "${STUDIO_HTML}" | grep -q "Plugin Debugger Studio"
curl -sf -o /dev/null -w "GET /studio/app.js -> HTTP %{http_code}\n" "http://127.0.0.1:${DEMO_PORT}/studio/app.js"
curl -sf -X POST "http://127.0.0.1:${DEMO_PORT}/tools/check_compliance" -H 'Content-Type: application/json' \
  -d '{"text": "全网销量第一，包治百病"}' | grep -E -q '"risk_level"[[:space:]]*:[[:space:]]*"high"'
echo -e "${GREEN}✓ Studio 工作台就绪: 评委打开 http://127.0.0.1:${DEMO_PORT}/ 即可体验 4 个技能 (与扣子同源 /tools 链路)${NC}"
cleanup

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  01_coze-skills-agent 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
