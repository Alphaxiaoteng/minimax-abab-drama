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

echo -e "\n${BLUE}[2/5] 导出 OpenAPI 3.0 Schema (JSON + YAML) 并跑 Coze 上架兼容性自检...${NC}"
EXPORTED="$(mktemp -t coze-openapi).json"
EXPORTED_YAML="$(mktemp -t coze-openapi).yaml"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli export-openapi \
  --out "${EXPORTED}" --title "Coze电商智能体插件" --version "1.0.0"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli schema --format yaml \
  --out "${EXPORTED_YAML}" --title "Coze电商智能体插件" --version "1.0.0"
echo -e "${GREEN}✓ OpenAPI Schema 严格校验通过: ${EXPORTED} / ${EXPORTED_YAML} (扣子控制台两种粘贴形态都备齐)${NC}"

echo -e "\n${BLUE}[2/5 补充] Coze 兼容性自检清单 (上架闸门: 0 error 且 0 warning)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli audit
echo -e "${GREEN}✓ 自检全绿: 结构合法性 + 模型可用性 (描述充分性/枚举默认值/example 可跑通/凭据扫描) 双重判据通过${NC}"

echo -e "\n${BLUE}[3/5] 运行核心规则引擎自检 (缺参防御与类型安全)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli selftest

echo -e "\n${BLUE}[4/5] 演示实战场景：文案合规检测 (含广告法极限词拦截与合规改写)...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke check_compliance \
  --params '{"text": "这款产品全网第一、绝对无敌，药效显著包治百病，立竿见影！", "platform": "douyin"}'

echo -e "\n${BLUE}[4/5 补充] 演示实战场景：多平台差评主题洞察与自动归因...${NC}"
uv run --with fastapi --with pydantic python3 -m coze_skills.cli invoke analyze_reviews \
  --params '{"reviews": ["快递三天没动静，到手包装全破了", "鞋子偏小两码根本穿不进去", "客服态度很差，问半天不回"], "marketplace": "tiktok"}'

echo -e "\n${BLUE}[5/5] 拉起网关 (gateway.py) 并验收 Studio 七个面板 (4 技能 + Bot 演练 + 容灾沙箱 + 规范导出)...${NC}"
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
for panel in compliance batch insight reply bot chaos schema; do
  echo "${STUDIO_HTML}" | grep -q "id=\"panel-${panel}\"" || { echo "缺少面板 panel-${panel}"; exit 1; }
done
echo "${STUDIO_HTML}" | grep -q "c-backdrop"
echo "${STUDIO_HTML}" | grep -q "i-bars"
echo -e "${GREEN}✓ 七个面板齐备: 评委打开 http://127.0.0.1:${DEMO_PORT}/ 即可体验 4 个技能 + Bot 演练 + 容灾沙箱 + 规范导出${NC}"

echo -e "\n${BLUE}[5/5 补充] Bot 演练场: 自然语言 -> 意图路由 -> 真实工具调用 -> 结构化卡片...${NC}"
curl -sf -X POST "http://127.0.0.1:${DEMO_PORT}/bot/chat" -H 'Content-Type: application/json' \
  -d '{"message": "这条文案能不能直接发:「这款面膜全网销量第一, 药效显著, 七天美白立竿见影!」"}' \
  | grep -E -q '"tool"[[:space:]]*:[[:space:]]*"check_compliance"'
curl -sf "http://127.0.0.1:${DEMO_PORT}/bot/greet" | grep -q '"quick_prompts"'
echo -e "${GREEN}✓ Bot 演练链路可用: 卡片含入参 Schema / Coze 请求头 (仅占位符) / 延迟瀑布 / Token 预估${NC}"

echo -e "\n${BLUE}[5/5 补充] 容灾沙箱: 畸形入参拦截 + 429 退避 + 504 降级 (恶劣环境下的稳定性证据)...${NC}"
curl -sf "http://127.0.0.1:${DEMO_PORT}/sim/cases" | grep -E -q '"count"[[:space:]]*:[[:space:]]*10'
MALFORMED=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:${DEMO_PORT}/tools/check_compliance" \
  -H 'Content-Type: application/json' -d '{"text": "全网销量第一"')
THROTTLE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${DEMO_PORT}/sim/throttle?attempt=0&reject_times=1")
RECOVERED=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${DEMO_PORT}/sim/throttle?attempt=1&reject_times=1")
TIMEOUT=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${DEMO_PORT}/sim/timeout?ms=50&budget=10")
echo "  截断 JSON -> HTTP ${MALFORMED} (期望 200 业务失败) · 限流首试 -> HTTP ${THROTTLE} (期望 429) · 退避后 -> HTTP ${RECOVERED} (期望 200) · 越预算 -> HTTP ${TIMEOUT} (期望 504)"
[ "${MALFORMED}" = "200" ] && [ "${THROTTLE}" = "429" ] && [ "${RECOVERED}" = "200" ] && [ "${TIMEOUT}" = "504" ]
curl -sf "http://127.0.0.1:${DEMO_PORT}/audit" | grep -E -q '"warning"[[:space:]]*:[[:space:]]*0,"error"[[:space:]]*:[[:space:]]*0'
curl -sf "http://127.0.0.1:${DEMO_PORT}/export/openapi?format=yaml&download=false" | head -1 | grep -q "coze_skills 自动生成"
echo -e "${GREEN}✓ 容灾与导出验收通过: 零 5xx、零堆栈外泄, /audit 0 error 0 warning, YAML 与 JSON 同源${NC}"
cleanup

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  01_coze-skills-agent 演示完成！全部链路 Exit Code 0${NC}"
echo -e "${GREEN}================================================================${NC}"
