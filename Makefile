# ==============================================================================
# 纯现金大赛交付工程统一控制台 (Master Makefile for Top 10 Pure-Cash Competitions)
# ==============================================================================

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.PHONY: help test-all demo-all verify-all \
        test-01 test-07 test-08 test-09 test-11 test-12 test-15 test-16 test-17 test-18 \
        demo-01 demo-07 demo-08 demo-09 demo-11 demo-12 demo-15 demo-16 demo-17 demo-18

# 颜色定义
CYAN   := \033[0;36m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
BLUE   := \033[0;34m
NC     := \033[0m

help:
	@echo -e "$(CYAN)==============================================================================$(NC)"
	@echo -e "$(CYAN)  10 个纯现金赛事交付工程统一控制台 (Master Makefile)$(NC)"
	@echo -e "$(CYAN)==============================================================================$(NC)"
	@echo -e "$(GREEN)全量命令:$(NC)"
	@echo -e "  make test-all    - 顺序执行全部 10 个赛事的单元与回归测试套件并输出综合矩阵"
	@echo -e "  make demo-all    - 顺序执行全部 10 个赛事的一键独立 Demo (Exit Code 0)"
	@echo -e "  make verify-all  - 全量回归：先 test-all 再 demo-all"
	@echo -e ""
	@echo -e "$(GREEN)单项目测试 (make test-XX):$(NC)"
	@echo -e "  test-01: 扣子智能体 (Coze)         test-12: 苏客松苏州 (InspectAI)"
	@echo -e "  test-07: 初焰钠电 (AIDC LP)        test-15: MiniMax ABAB (推理剧)"
	@echo -e "  test-08: Anker 光储 (Solix MPC)    test-16: 智谱 AutoGLM (端侧 Agent)"
	@echo -e "  test-09: 观猹微信 (小程序秒开)     test-17: DoraHacks Anna (NetIntel MCP)"
	@echo -e "  test-11: Open Agent (Squad)        test-18: 雾客松重庆 (3D 空间计算)"
	@echo -e ""
	@echo -e "$(GREEN)单项目演示 (make demo-XX):$(NC)"
	@echo -e "  demo-01 | demo-07 | demo-08 | demo-09 | demo-11"
	@echo -e "  demo-12 | demo-15 | demo-16 | demo-17 | demo-18"
	@echo -e "$(CYAN)==============================================================================$(NC)"

# ------------------------------------------------------------------------------
# 单项目测试目标
# ------------------------------------------------------------------------------
test-01:
	@echo -e "\n$(BLUE)>>> [01_coze-skills-agent] 运行单元测试...$(NC)"
	cd 01_coze-skills-agent && uv run --with pytest --with fastapi --with httpx --with pyyaml --with openapi-spec-validator pytest tests/

test-07:
	@echo -e "\n$(BLUE)>>> [07_na-zhou-aidc] 运行 110 项物理与优化测试...$(NC)"
	cd 07_na-zhou-aidc && uv run --python 3.12 --with-requirements requirements.txt pytest tests/

test-08:
	@echo -e "\n$(BLUE)>>> [08_anker-hackathon-2026] 运行 102 项 MPC 优化测试...$(NC)"
	cd 08_anker-hackathon-2026 && uv run --with pytest --with pulp --with highspy --with fastapi --with httpx --with pydantic pytest

test-09:
	@echo -e "\n$(BLUE)>>> [09_watcha-wechat-miniapp] 运行 41 项静态规范与单元测试...$(NC)"
	cd 09_watcha-wechat-miniapp && npm run verify

test-11:
	@echo -e "\n$(BLUE)>>> [11_genai-open-agent] 运行 66 项多智能体编排测试...$(NC)"
	cd 11_genai-open-agent && uv run --with pytest pytest

test-12:
	@echo -e "\n$(BLUE)>>> [12_suks-suzhou-ai-hackathon] 运行 56 项工业质检测试...$(NC)"
	cd 12_suks-suzhou-ai-hackathon && uv run --python 3.12 --with-requirements src/requirements.txt pytest src/tests

test-15:
	@echo -e "\n$(BLUE)>>> [15_minimax-abab-agent] 运行 116 项推理剧状态机测试...$(NC)"
	cd 15_minimax-abab-agent/src && npm test

test-16:
	@echo -e "\n$(BLUE)>>> [16_zhipu-autoglm-agent] 运行 30 项端侧鲁棒性测试...$(NC)"
	cd 16_zhipu-autoglm-agent && uv run --with pytest pytest src/tests/ -q

test-17:
	@echo -e "\n$(BLUE)>>> [17_dorahacks-anna-ai-mcp] 运行 35 项 MCP 单元测试与类型检查...$(NC)"
	cd 17_dorahacks-anna-ai-mcp && npm run verify

test-18:
	@echo -e "\n$(BLUE)>>> [18_wakeathon-chongqing-2027] 运行生产构建与类型检查...$(NC)"
	cd 18_wakeathon-chongqing-2027/src && npm run build

# ------------------------------------------------------------------------------
# 单项目演示目标
# ------------------------------------------------------------------------------
demo-01:
	@./01_coze-skills-agent/scripts/demo.sh

demo-07:
	@./07_na-zhou-aidc/scripts/demo.sh

demo-08:
	@./08_anker-hackathon-2026/scripts/demo.sh

demo-09:
	@./09_watcha-wechat-miniapp/scripts/demo.sh

demo-11:
	@./11_genai-open-agent/scripts/demo.sh

demo-12:
	@./12_suks-suzhou-ai-hackathon/scripts/demo.sh

demo-15:
	@./15_minimax-abab-agent/scripts/demo.sh

demo-16:
	@./16_zhipu-autoglm-agent/scripts/demo.sh

demo-17:
	@./17_dorahacks-anna-ai-mcp/scripts/demo.sh

demo-18:
	@./18_wakeathon-chongqing-2027/scripts/demo.sh

# ------------------------------------------------------------------------------
# 复合回归目标
# ------------------------------------------------------------------------------
test-all: test-01 test-07 test-08 test-09 test-11 test-12 test-15 test-16 test-17 test-18
	@echo -e "\n$(GREEN)==============================================================================$(NC)"
	@echo -e "$(GREEN)  🏆 全部 10 个赛事的单元与回归测试 100% 通过 (Exit Code 0)$(NC)"
	@echo -e "$(GREEN)==============================================================================$(NC)"

demo-all: demo-01 demo-07 demo-08 demo-09 demo-11 demo-12 demo-15 demo-16 demo-17 demo-18
	@echo -e "\n$(GREEN)==============================================================================$(NC)"
	@echo -e "$(GREEN)  🏆 全部 10 个赛事的一键 Demo 演练 100% 成功 (Exit Code 0)$(NC)"
	@echo -e "$(GREEN)==============================================================================$(NC)"

verify-all: test-all demo-all
	@echo -e "\n$(GREEN)==============================================================================$(NC)"
	@echo -e "$(GREEN)  🎉 全量极速交付验证已完全达标！(ALL SYSTEMS READY FOR JUDGES)$(NC)"
	@echo -e "$(GREEN)==============================================================================$(NC)"
