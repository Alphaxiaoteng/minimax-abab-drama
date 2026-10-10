#!/usr/bin/env bash
# 一键演示：依赖检查 → 110 项单测 → 三情景端到端 LP 仿真 → 报告落盘。
# 用法：bash scripts/demo.sh   （任一环节失败即以非零退出码终止）
set -euo pipefail

cd "$(dirname "$0")/.."
echo "==> 工作目录: $(pwd)"

if command -v uv >/dev/null 2>&1; then
  echo "==> 运行器: uv (Python 3.12, requirements.txt 锁定依赖)"
else
  if [ ! -x .venv/bin/python ]; then
    echo "==> 未检测到 uv，创建 .venv 并安装依赖"
    python3 -m venv .venv
    ./.venv/bin/pip install -q -r requirements.txt
  fi
  export PATH="$PWD/.venv/bin:$PATH"
  echo "==> 运行器: .venv ($(python3 --version))"
fi

echo ""
echo "==> [1/3] 运行单元测试（预期 110 项全部通过）"
if command -v uv >/dev/null 2>&1; then
  uv run --python 3.12 --with-requirements requirements.txt pytest tests/
else
  pytest tests/
fi

echo ""
echo "==> [2/3] 端到端仿真：baseline_day / transient_spike / extreme_peak"
if command -v uv >/dev/null 2>&1; then
  uv run --python 3.12 --with-requirements requirements.txt python -m src.main --all
else
  python3 -m src.main --all
fi

echo ""
echo "==> [3/3] 产出物"
ls -1 reports/
echo ""
echo "✅ 演示完成：单测通过、三情景 Optimal、报告与图表见 reports/"
