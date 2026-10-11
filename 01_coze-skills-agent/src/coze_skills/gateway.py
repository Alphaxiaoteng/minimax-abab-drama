"""网关装配入口: 纯 API (core.server) + 交付演示形态 (Studio / Bot 演练场 / 容灾沙箱).

分层原则
--------
1. ``core/server.py`` 只提供扣子线上需要的 API; 本模块在其之上叠加**演示与运维面**.
2. 因此「给扣子回源的进程」(``core.server:create_app``) 与「给评委看的进程」
   (``gateway:create_app``) 可以按需选择, 但共享同一套 core —— 不存在两套配置漂移.
3. ``/sim/*`` 与 ``/bot/*`` 是**只增不改**的旁路: 不接管 ``/tools/{name}`` 的任何行为,
   容灾沙箱里的畸形入参依旧打到真实 ``/tools/{name}``, 由同一条校验链路拦截.

启动::

    PYTHONPATH=src python3 -m uvicorn coze_skills.gateway:create_app --factory --port 8000
    # 浏览器打开 http://127.0.0.1:8000/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core.audit import run_audit
from .core.bot import greet, run_turn
from .core.chaos import (
    DEFAULT_CLIENT_BUDGET_MS,
    SIM_TIMEOUT_MAX_MS,
    SIM_TIMEOUT_MIN_MS,
    THROTTLE_DEFAULT_REJECTIONS,
    THROTTLE_RETRY_AFTER_SECONDS,
    cases_payload,
)
from .core.schema import build_openapi
from .core.server import create_app as create_api_app
from .core.yamlout import sorted_document, to_yaml

#: 静态工作台目录 (随包分发, 与 gateway.py 相距一层)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STUDIO_MOUNT_PATH = "/studio"

#: 链路追踪响应头: 让 Studio 的延迟瀑布与扣子侧日志能对上同一次调用
REQUEST_ID_HEADER = "X-Coze-Request-Id"
PROCESS_MS_HEADER = "X-Process-Ms"


def studio_available() -> bool:
    """调试工作台资源是否齐备 (index.html 与 app.js 同时存在)."""
    return (STATIC_DIR / "index.html").is_file() and (STATIC_DIR / "app.js").is_file()


def mount_studio(app: FastAPI) -> bool:
    """把静态目录挂到 /studio, 并注册 GET / 根路由指向工作台.

    :param app: 已装配好 API 的 FastAPI 实例.
    :returns: 是否完成挂载 (资源缺失时返回 False, API 不受影响).
    """
    if not studio_available():
        return False

    app.mount(
        STUDIO_MOUNT_PATH,
        StaticFiles(directory=str(STATIC_DIR), html=True),
        name="plugin-debugger-studio",
    )

    @app.get("/", include_in_schema=False)
    def studio_index() -> FileResponse:
        """评委入口: 浏览器直开即进入 Plugin Debugger Studio."""
        return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")

    return True


def mount_trace(app: FastAPI) -> None:
    """给每个响应补上 ``X-Coze-Request-Id`` / ``X-Process-Ms`` 两个观测头.

    这两个头是 Studio「往返延迟瀑布」的服务端一手数据源: 客户端只能量到「发起到收到」,
    中间到底花了多少必须回过来告诉它, 否则瀑布图就是在猜.
    """

    @app.middleware("http")
    async def _trace(request: Request, call_next):
        started = time.perf_counter()
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        # 存进 state 供下游复用, 保证「卡片里的请求 id」与「响应头」永远是同一个
        request.state.coze_request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[PROCESS_MS_HEADER] = f"{(time.perf_counter() - started) * 1000.0:.2f}"
        return response


def mount_playground(app: FastAPI) -> None:
    """Coze Bot 演练场: 用本地确定性意图路由替身复现 Function Calling 链路."""

    @app.get("/bot/greet")
    def bot_greet() -> Dict[str, Any]:
        """开场白与快问快答 (前端首屏直接渲染, 不需要构造首轮消息)."""
        return {"ok": True, "error": None, "data": greet(app.state.registry)}

    @app.post("/bot/chat")
    async def bot_chat(request: Request) -> JSONResponse:
        """跑一整轮对话: 路由 -> 真实调用同一个 runner -> 返回结构化卡片.

        请求体 ``{"message": str, "context": {"tool","params"}}``; ``context`` 是客户端
        上一轮收到的载荷, 用于「换成淘宝再查一遍」这类只改参数的追问.
        """
        raw = await request.body()
        try:
            loaded = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        message = str(loaded.get("message") or "")
        context = loaded.get("context")
        if not isinstance(context, dict):
            context = None

        # 与 trace 中间件同源: 客户端带来的 id 一律沿用, 卡片里的请求头才和响应头对得上
        request_id = str(getattr(request.state, "coze_request_id", "") or "") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        card = run_turn(
            app.state.registry,
            app.state.runner,
            message,
            context,
            request_id=request_id,
            process_ms=(time.perf_counter() - started) * 1000.0,
        )
        return JSONResponse(
            {"ok": bool(card.get("ok")), "error": None, "data": card},
            headers={REQUEST_ID_HEADER: request_id},
        )


def mount_resilience(app: FastAPI) -> None:
    """容灾沙箱: 429 限流与 504 超时两个可注入端点 + 畸形入参用例清单.

    两个端点都**无隐藏状态**: 结果完全由查询参数决定, 因此评委反复点也能复现,
    pytest 也能脱离 HTTP 直接断言.
    """

    @app.get("/sim/cases")
    def sim_cases() -> Dict[str, Any]:
        """畸形入参用例清单 (由 core.chaos 单点声明, 前端不另抄一份)."""
        return {"ok": True, "error": None, "data": cases_payload()}

    @app.get("/sim/throttle")
    def sim_throttle(
        attempt: int = Query(0, ge=0, le=20, description="第几次尝试, 从 0 开始"),
        reject_times: int = Query(
            THROTTLE_DEFAULT_REJECTIONS, ge=0, le=10, description="前 N 次返回 429"
        ),
    ) -> JSONResponse:
        """429 限流仿真: 前 ``reject_times`` 次返回 429 + ``Retry-After``, 之后放行."""
        if attempt < reject_times:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"上游限流: 第 {attempt + 1} 次尝试被 429 拒绝",
                    "data": {
                        "attempt": attempt,
                        "reject_times": reject_times,
                        "retry_after_seconds": THROTTLE_RETRY_AFTER_SECONDS,
                    },
                },
                status_code=429,
                headers={
                    "Retry-After": str(THROTTLE_RETRY_AFTER_SECONDS),
                    "X-RateLimit-Remaining": "0",
                },
            )
        return JSONResponse(
            {
                "ok": True,
                "error": None,
                "data": {
                    "attempt": attempt,
                    "reject_times": reject_times,
                    "recovered_after": attempt + 1,
                    "note": "退避重试后恢复, 未产生重复扣量",
                },
            }
        )

    @app.get("/sim/timeout")
    async def sim_timeout(
        ms: int = Query(2500, ge=SIM_TIMEOUT_MIN_MS, le=SIM_TIMEOUT_MAX_MS),
        budget: int = Query(DEFAULT_CLIENT_BUDGET_MS, ge=0, le=SIM_TIMEOUT_MAX_MS * 2),
    ) -> JSONResponse:
        """504 超时仿真: 服务端按 ``ms`` 阻塞, 并回显客户端预算是否已被越过.

        真正的中断由前端 ``AbortController`` 完成 (它会先掐断连接), 本端点因此额外把
        ``budget`` 回显进响应, 用于在「客户端没来得及中断」时演示服务端降级封套.
        """
        await asyncio.sleep(ms / 1000.0)
        degraded = ms > budget
        return JSONResponse(
            {
                "ok": not degraded,
                "error": (
                    f"网关超时: 上游耗时 {ms}ms 超过客户端预算 {budget}ms, 已降级"
                    if degraded
                    else None
                ),
                "data": {
                    "slept_ms": ms,
                    "client_budget_ms": budget,
                    "degraded": degraded,
                    "fallback": "回退到最近一次成功结果 (本地缓存)" if degraded else "无需回退",
                },
            },
            status_code=504 if degraded else 200,
            headers={"X-Degrade": "cached-result" if degraded else "none"},
        )


def mount_delivery(app: FastAPI) -> None:
    """交付面: 兼容性自检清单 + OpenAPI JSON/YAML 导出 (可直接下载)."""

    @app.get("/audit")
    def audit() -> Dict[str, Any]:
        """Coze 上架兼容性一键自检 (带 runner, 因此连 example 能否跑通都查)."""
        return {
            "ok": True,
            "error": None,
            "data": run_audit(
                app.state.registry,
                title=app.state.title,
                version=app.state.version,
                description=app.state.description,
                runner=app.state.runner,
            ),
        }

    @app.get("/export/openapi")
    def export_openapi(
        format: str = Query("json", pattern="^(json|yaml)$", description="导出格式"),
        download: bool = Query(True, description="是否带 attachment 头 (浏览器直接存盘)"),
    ) -> Response:
        """导出与 ``/openapi.coze.json`` 同源的 OpenAPI 3.0 文档, 可选 YAML 形态."""
        doc = build_export_doc(app)
        if format == "yaml":
            text = to_yaml(doc)
            media, suffix = "application/yaml", "yaml"
        else:
            text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            media, suffix = "application/json", "json"
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="coze-plugin-openapi.{suffix}"'
        return Response(content=text, media_type=media, headers=headers)


def build_export_doc(app: FastAPI) -> Dict[str, Any]:
    """取导出用文档: 先按键名排序归一, 保证 JSON/YAML 两条路径同源同序."""
    return sorted_document(
        build_openapi(
            app.state.registry,
            title=app.state.title,
            version=app.state.version,
            description=app.state.description,
        )
    )


def create_app(
    registry: Optional[object] = None,
    *,
    runner: Optional[object] = None,
    title: str = "Coze 垂类提效插件网关",
    version: str = "0.1.0",
) -> FastAPI:
    """API 网关 + Studio 工作台 + Bot 演练场 + 容灾沙箱的装配产物 (uvicorn factory 入口)."""
    app = create_api_app(registry, runner=runner, title=title, version=version)  # type: ignore[arg-type]
    mount_trace(app)
    mount_playground(app)
    mount_resilience(app)
    mount_delivery(app)
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
