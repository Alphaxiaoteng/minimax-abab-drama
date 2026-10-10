#!/usr/bin/env bash
# 启动 S3 在线质检服务（FastAPI/uvicorn）。
# 端口经 PORT 环境变量覆盖，默认 8000；工作目录固定为 src/（脚本上一级），
# 保证 service.api 模块路径与 static/ 相对定位都正确。
set -euo pipefail
cd "$(dirname "$0")/.." && exec python3 -m uvicorn service.api:app --host 0.0.0.0 --port "${PORT:-8000}"