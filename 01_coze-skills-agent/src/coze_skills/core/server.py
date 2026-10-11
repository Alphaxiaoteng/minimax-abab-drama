"""Coze 垂类提效插件网关: 把注册表 + 执行器暴露为 HTTP 接口 (纯 API 面).

设计约束:
1. 业务错误一律 HTTP 200 + ``ok=false`` —— 扣子插件侧只看 ``ok`` 字段,
   不依赖 HTTP 状态码判分支; 只有路由不存在才由框架返回 404.
2. 所有响应体都是 ``ToolResult.model_dump()`` 形状的纯 dict, 保证 JSON 安全.
3. ``/invoke/{tool}`` 与 ``/tools/{tool}`` 互为别名, 后者是
   ``tool_to_operation`` 生成的 OpenAPI path 的落地地址, 两条都必须可用.
4. 请求体按原始 JSON 解析, 而非强类型 ``Dict`` 注解 —— 否则数组体会被
   FastAPI 拦成 422, 无法收敛为「请求体必须是 JSON 对象」这条业务错误.
5. 本模块**只提供扣子线上需要的 API**, 不含 ``/`` 与 ``/studio/*``;
   演示形态 (Studio / Bot 演练场 / 容灾沙箱) 一律由 ``coze_skills.gateway`` 叠加,
   这样「给扣子回源的进程」和「给评委看的进程」可以按需选择, 而共享同一套 core.
"""

from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request

from .registry import ToolRegistry, build_default_registry
from .runner import ToolRunner
from .schema import DEFAULT_PLUGIN_DESCRIPTION, build_openapi
from .spec import ToolResult


def _tool_payload(registry: ToolRegistry) -> Dict[str, Any]:
    """序列化全部工具声明, 绝不包含 handler."""
    tools = []
    for spec in registry.all():
        params = [
            {
                "name": p.name,
                "type": p.type,
                "required": p.required,
                "description": p.description,
            }
            for p in spec.params
        ]
        tools.append(
            {
                "name": spec.name,
                "title": spec.title,
                "description": spec.description,
                "category": spec.category,
                "tags": list(spec.tags),
                "params": params,
            }
        )
    return {"count": len(tools), "tools": tools}


def create_app(
    registry: Optional[ToolRegistry] = None,
    *,
    runner: Optional[ToolRunner] = None,
    title: str = "Coze 垂类提效插件网关",
    version: str = "0.1.0",
    description: str = DEFAULT_PLUGIN_DESCRIPTION,
) -> FastAPI:
    """构建 FastAPI 网关应用.

    :param registry: 工具注册表; 缺省时自动发现全部垂类工具 (非严格模式).
    :param runner: 执行器; 缺省时用给定 registry 新建.
    :param title: OpenAPI 文档标题 (``info.title``), 同时是扣子插件详情页名称.
    :param version: OpenAPI 文档版本, 同时用于健康检查回显.
    :param description: OpenAPI ``info.description``; 留空会让插件详情页一片空白.
    """
    if registry is None:
        registry = build_default_registry(strict=False)
    if runner is None:
        runner = ToolRunner(registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        names = app.state.registry.names()
        print(f"[gateway] 已加载 {len(names)} 个工具: {', '.join(names)}")
        yield

    app = FastAPI(title=title, version=version, lifespan=lifespan)
    app.state.registry = registry
    app.state.runner = runner
    app.state.title = title
    app.state.version = version
    app.state.description = description

    @app.get("/healthz")
    def healthz() -> Dict[str, Any]:
        """存活探针: 回显工具数量与服务版本."""
        return ToolResult.success(
            status="ok",
            tools=len(app.state.registry.names()),
            version=app.state.version,
        ).model_dump()

    @app.get("/openapi.coze.json")
    def openapi_coze() -> Dict[str, Any]:
        """导出供扣子插件配置的 OpenAPI Schema (Starlette 保证中文不转义)."""
        return build_openapi(
            app.state.registry,
            title=app.state.title,
            version=app.state.version,
            description=app.state.description,
        )

    @app.get("/tools")
    def list_tools() -> Dict[str, Any]:
        """工具清单 (仅元数据, 不序列化 handler)."""
        return ToolResult.success(**_tool_payload(app.state.registry)).model_dump()

    async def _dispatch(request: Request, tool_name: str) -> Dict[str, Any]:
        """共享的执行逻辑: 解析请求体 -> 交给 runner -> 收敛为 ToolResult."""
        raw = await request.body()
        try:
            loaded = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            loaded = None
        if not isinstance(loaded, dict):
            return ToolResult.fail("请求体必须是 JSON 对象").model_dump()
        return app.state.runner.invoke(tool_name, loaded).model_dump()

    @app.post("/invoke/{tool_name}")
    async def invoke_alias(tool_name: str, request: Request) -> Dict[str, Any]:
        """主调用入口."""
        return await _dispatch(request, tool_name)

    @app.post("/tools/{tool_name}")
    async def invoke_primary(tool_name: str, request: Request) -> Dict[str, Any]:
        """别名入口 (对应 ``tool_to_operation`` 生成的 OpenAPI path)."""
        return await _dispatch(request, tool_name)

    @app.get("/metrics")
    def metrics() -> Dict[str, Any]:
        """执行器快照: tools / count / log."""
        return ToolResult.success(**app.state.runner.describe()).model_dump()

    return app


def main() -> None:
    """命令行启动网关 (uvicorn factory 模式)."""
    parser = argparse.ArgumentParser(description="Coze 垂类提效插件网关")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--log-level", default="info", help="日志级别")
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "coze_skills.core.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()