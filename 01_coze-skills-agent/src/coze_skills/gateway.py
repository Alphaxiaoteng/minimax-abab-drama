"""网关装配入口: API 路由 (core.server) + Plugin Debugger Studio 静态工作台.

与 ``core.server.create_app`` 的关系:
1. server.py 保持纯 API (扣子线上只需 API 面), 本模块只负责「演示形态」的装配;
2. 挂载 ``static/`` 目录到 ``/studio``, 并把 ``GET /`` 指向调试工作台,
   评委打开浏览器即可直观体验 4 个技能, 调用链路与扣子完全同源 (POST /tools/{name});
3. 静态目录缺失时 (如裁剪过的镜像) 自动跳过挂载, 不阻塞 API 启动.

启动::

    PYTHONPATH=src python3 -m uvicorn coze_skills.gateway:create_app --factory --port 8000
    # 浏览器打开 http://127.0.0.1:8000/
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.server import create_app as create_api_app

#: 静态工作台目录 (随包分发, 与 gateway.py 相距一层)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STUDIO_MOUNT_PATH = "/studio"


def studio_available() -> bool:
    """调试工作台资源是否齐备 (index.html 与 app.js 同时存在)."""
    return (STATIC_DIR / "index.html").is_file() and (STATIC_DIR / "app.js").is_file()


def mount_studio(app: FastAPI) -> bool:
    """把静态目录挂到 /studio, 并注册 GET / 根路由指向工作台.

    :returns: 是否完成挂载 (资源缺失时返回 False, API 不受影响).
    """
    if not studio_available():
        return False

    app.mount(STUDIO_MOUNT_PATH, StaticFiles(directory=str(STATIC_DIR)), name="plugin-debugger-studio")

    @app.get("/", include_in_schema=False)
    def studio_index() -> FileResponse:
        """评委入口: 浏览器直开即进入 Plugin Debugger Studio."""
        return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")

    return True


def create_app(
    registry: Optional[object] = None,
    *,
    runner: Optional[object] = None,
    title: str = "Coze 垂类提效插件网关",
    version: str = "0.1.0",
) -> FastAPI:
    """API 网关 + Studio 工作台的装配产物 (uvicorn factory 入口)."""
    app = create_api_app(registry, runner=runner, title=title, version=version)  # type: ignore[arg-type]
    mount_studio(app)
    return app


def main() -> None:
    """命令行启动 (含 Studio 工作台)."""
    parser = argparse.ArgumentParser(description="Coze 垂类提效插件网关 (含调试工作台)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--log-level", default="info", help="日志级别")
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "coze_skills.gateway:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
