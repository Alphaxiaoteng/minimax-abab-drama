"""从 ``ToolSpec`` 生成 Coze 插件 OpenAPI 3.0 Schema, 并提供本地结构校验.

设计动机:
1. ``ToolSpec`` 是单一事实来源 (SSOT), OpenAPI 文档由它机械生成, 杜绝手写漂移;
2. 插件网关跑在最小镜像里, 不引入 jsonschema 等第三方依赖 ——
   以 :func:`validate_openapi` 做定向结构校验, 专防 Coze 侧最易踩的坑
   (必填参数名拼错 -> 整条工具在平台上不可调用);
3. 所有接口统一 POST + JSON body: Coze 对这种形态支持最稳, 且避免 query 编码歧义;
   业务错误也返回 HTTP 200 + ``ok=false``, 避免平台把非 2xx 当网络故障而自动重试.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .registry import ToolRegistry
from .spec import JSON_TYPE_TO_PYTHON, Param, ToolSpec

#: 本模块生成的 OpenAPI 版本 (Coze 插件网关要求 3.0.x)
COZE_OPENAPI_VERSION = "3.0.0"


def param_to_schema(param: Param) -> Dict[str, Any]:
    """把单个 :class:`~coze_skills.core.spec.Param` 转成 JSON Schema 片段.

    :param param: 参数声明.
    :returns: JSON Schema 片段 dict; 遵循 Coze 约定 ——
        不在参数级写 ``required`` (必填信息统一放 object schema 的 ``required`` 列表),
        也不写 ``default: null`` (空默认值会误导大模型).
    :raises TypeError: ``param`` 不是 :class:`Param` 实例时由属性访问自然抛出.
    """
    schema: Dict[str, Any] = {"type": param.type}
    if param.description:
        schema["description"] = param.description
    if param.enum is not None:
        schema["enum"] = list(param.enum)
    if param.type == "string":
        if param.min_length is not None:
            schema["minLength"] = param.min_length
        if param.max_length is not None:
            schema["maxLength"] = param.max_length
        if param.pattern is not None:
            schema["pattern"] = param.pattern
    elif param.type in ("integer", "number"):
        if param.minimum is not None:
            schema["minimum"] = param.minimum
        if param.maximum is not None:
            schema["maximum"] = param.maximum
    elif param.type == "array":
        schema["items"] = {"type": param.items_type}
    if not param.required and param.default is not None:
        schema["default"] = param.default
    if param.example is not None:
        schema["example"] = param.example
    return schema


def tool_to_operation(spec: ToolSpec, *, path_prefix: str = "/tools") -> Dict[str, Any]:
    """把 :class:`~coze_skills.core.spec.ToolSpec` 转成单条 OpenAPI operation.

    返回的是「扁平描述」(含 ``path``/``method`` 两个元信息键),
    由 :func:`build_openapi` 负责嵌入 ``paths`` 结构并补上 ``responses``.

    :param spec: 工具声明.
    :param path_prefix: 工具路由前缀, 生成 ``{path_prefix}/{spec.name}``.
    :returns: 含 ``path/method/operationId/summary/description/parameters/requestBody`` 的 dict.
    """
    properties: Dict[str, Any] = {p.name: param_to_schema(p) for p in spec.params}
    required: List[str] = [p.name for p in spec.params if p.required]

    description = spec.description
    if spec.tags:
        description += "\n\n标签: " + ", ".join(spec.tags)
    description += "\n分类: " + spec.category

    body_schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        body_schema["required"] = required

    example_payload: Optional[Dict[str, Any]] = None
    declared = {p.name for p in spec.params if p.example is not None}
    if declared:
        example_payload = {p.name: p.example for p in spec.params if p.name in declared}
    json_media: Dict[str, Any] = {"schema": body_schema}
    if example_payload is not None:
        json_media["example"] = example_payload

    return {
        "path": "{}/{}".format(path_prefix, spec.name),
        "method": "POST",
        "operationId": spec.name,
        "summary": spec.title,
        "description": description,
        "tags": [spec.category] + list(spec.tags),
        # 本设计明确走 body, 不混用 query/path 参数, 因此永远是空 list
        "parameters": [],
        "requestBody": {
            "required": True,
            "content": {"application/json": json_media},
        },
    }


def _plugin_error_schema() -> Dict[str, Any]:
    """``PluginError`` 公共响应模型, 对应 :class:`~coze_skills.core.spec.ToolResult.model_dump`."""
    return {
        "type": "object",
        "description": (
            "所有接口统一返回该结构, 调用方先看 ok; "
            "业务错误同样以 HTTP 200 + ok=false 返回, 避免平台把非 2xx 当网络故障重试."
        ),
        "properties": {
            "ok": {"type": "boolean"},
            # OpenAPI 3.0 的 type 只能是单字符串, 可空用 nullable (3.1 才允许 type 数组)
            "error": {"type": "string", "nullable": True},
            "data": {"type": "object"},
        },
    }


#: 默认网关地址: Coze 插件导入后 servers 需指向公网可达的 HTTP 服务地址
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"

#: 默认插件标题: 出现在 Coze 插件详情页与导入框, 与 CLI 默认值同源
DEFAULT_PLUGIN_TITLE = "Coze 垂类提效插件集"

#: 默认插件描述: 必须一句话说清「给谁、解决什么、是否离线」, 否则详情页一片空白
DEFAULT_PLUGIN_DESCRIPTION = (
    "垂类提效小工具统一网关: 文案合规审查 / 批量体检 / 差评主题归因 / 英文客服回复, "
    "全程本地规则引擎计算, 不依赖任何外部接口, 断网也能稳定出结果。"
)


def build_openapi(
    registry: ToolRegistry,
    *,
    title: str,
    version: str = "0.1.0",
    description: str = "",
    server_url: str = DEFAULT_SERVER_URL,
) -> Dict[str, Any]:
    """把注册表内全部工具编译成完整 OpenAPI 3.0 文档.

    :param registry: 工具注册表 (paths 按 ``registry.names()`` 字典序生成, 稳定可 diff).
    :param title: 插件标题, 写入 ``info.title``.
    :param version: 插件版本号, 写入 ``info.version``.
    :param description: 插件描述, 写入 ``info.description``.
    :param server_url: 网关公网地址, 写入 ``servers`` (Coze 导入后按此地址发起调用).
    :returns: 可直接 ``json.dumps`` 的 OpenAPI 文档 dict, 含 ``info/servers/tags/paths/components``,
        每个 operation 带 ``tags`` 与请求体 ``example``.
    """
    paths: Dict[str, Any] = {}
    tag_names: List[str] = []

    def _remember_tag(name: str) -> None:
        if name and name not in tag_names:
            tag_names.append(name)

    for name in registry.names():
        spec = registry.require(name)
        operation = tool_to_operation(spec)
        body = {k: v for k, v in operation.items() if k not in ("path", "method")}
        body["responses"] = {
            "200": {
                "description": "工具 {} 的统一响应, 先看 ok 字段".format(name),
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PluginError"}
                    }
                },
            }
        }
        paths[operation["path"]] = {operation["method"].lower(): body}
        for tag in operation["tags"]:
            _remember_tag(tag)

    return {
        "openapi": COZE_OPENAPI_VERSION,
        "info": {
            "title": title,
            "version": version,
            "description": description,
            "contact": {"name": "Coze 垂类提效插件集", "url": server_url.rstrip("/")},
        },
        "servers": [
            {"url": server_url, "description": "扣子插件网关 (生产环境请替换为公网可达 HTTPS 域名)"}
        ],
        "tags": [{"name": t, "description": "工具分组/能力标签: {}".format(t)} for t in tag_names],
        "paths": paths,
        "components": {"schemas": {"PluginError": _plugin_error_schema()}},
    }


def validate_openapi(doc: Dict[str, Any]) -> List[str]:
    """本地结构校验 (不依赖 jsonschema 库), 专防 Coze 侧高频翻车点.

    校验项:
    1. 顶层 ``openapi`` 以 ``3.0`` 开头, ``info.title`` / ``info.version`` 非空;
    2. 每个 path 以 ``/`` 开头, operation 是 dict;
    3. ``operationId`` 全局唯一且非空;
    4. ``parameters`` 必须是 list;
    5. ``requestBody`` (若存在) 的 JSON schema 必须 ``type=object`` 且 ``properties`` 是 dict;
    6. 每个参数的 ``type`` 必须落在 :data:`~coze_skills.core.spec.JSON_TYPE_TO_PYTHON` 键集合;
    7. ``array`` 参数必须有 ``items.type``;
    8. ``required`` 列表里的每个名字必须存在于 ``properties`` (必填名拼错会整条工具不可调用);
    9. ``servers`` 必须是非空 list, 每项含非空字符串 ``url`` (Coze 按此地址发起调用);
    10. 顶层 ``tags`` 须为 ``{name, description}`` 列表且 name 唯一;
        operation 级 ``tags`` 必须是 list 且每项已在顶层 ``tags`` 声明;
    11. 请求体 ``example`` (若存在) 必须是 dict: 键须落在 ``properties``,
        必填参数须出现在 example 中, 各示例值类型须与参数 schema 一致.

    :param doc: :func:`build_openapi` 生成的文档.
    :returns: 中文错误列表; 空列表表示通过. 本函数不抛异常.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["OpenAPI 文档顶层必须是 dict"]

    openapi = doc.get("openapi")
    if not isinstance(openapi, str) or not openapi.startswith("3.0"):
        errors.append("openapi 版本必须以 3.0 开头, 实际 {!r}".format(openapi))
    info = doc.get("info")
    if not isinstance(info, dict) or not info.get("title"):
        errors.append("缺少 info.title")
    if not isinstance(info, dict) or not info.get("version"):
        errors.append("缺少 info.version")

    servers = doc.get("servers")
    if not isinstance(servers, list) or not servers:
        errors.append("servers 必须是非空 list (Coze 按 servers[0].url 发起调用)")
    else:
        for idx, item in enumerate(servers):
            url = item.get("url") if isinstance(item, dict) else None
            if not isinstance(url, str) or not url.strip():
                errors.append("servers[{}] 缺少非空字符串 url".format(idx))

    top_tags: Dict[str, int] = {}
    tags = doc.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            errors.append("顶层 tags 必须是 list")
            tags = []
        else:
            for idx, item in enumerate(tags):
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not name:
                    errors.append("tags[{}] 缺少非空字符串 name".format(idx))
                    continue
                if name in top_tags:
                    errors.append("tags name {!r} 重复".format(name))
                top_tags[name] = idx
                desc = item.get("description")
                if not isinstance(desc, str) or not desc:
                    errors.append("tags[{}] ({!r}) 缺少非空 description".format(idx, name))

    paths = doc.get("paths")
    if not isinstance(paths, dict):
        errors.append("缺少 paths (必须为 dict)")
        return errors

    seen: Dict[str, str] = {}
    for path, methods in paths.items():
        if not path.startswith("/"):
            errors.append("path {!r} 必须以 / 开头".format(path))
        if not isinstance(methods, dict):
            errors.append("path {!r} 的值必须是 method -> operation 映射".format(path))
            continue
        for method, operation in methods.items():
            where = "{} {}".format(str(method).upper(), path)
            if not isinstance(operation, dict):
                errors.append("{}: operation 必须是 dict".format(where))
                continue

            op_id = operation.get("operationId")
            if not op_id:
                errors.append("{}: 缺少 operationId".format(where))
            elif not isinstance(op_id, str):
                errors.append("{}: operationId 必须是字符串, 实际 {!r}".format(where, op_id))
            elif op_id in seen:
                errors.append(
                    "operationId {!r} 重复: {} 与 {}".format(op_id, seen[op_id], where)
                )
            else:
                seen[op_id] = where
            label = op_id if isinstance(op_id, str) and op_id else where

            parameters = operation.get("parameters")
            if not isinstance(parameters, list):
                errors.append("{}: parameters 必须是 list".format(label))

            op_tags = operation.get("tags")
            if op_tags is not None:
                if not isinstance(op_tags, list):
                    errors.append("{}: operation tags 必须是 list".format(label))
                else:
                    for t in op_tags:
                        if not isinstance(t, str) or not t:
                            errors.append("{}: operation tag 必须是非空字符串, 实际 {!r}".format(label, t))
                        elif top_tags and t not in top_tags:
                            errors.append(
                                "{}: operation tag {!r} 未在顶层 tags 声明".format(label, t)
                            )

            request_body = operation.get("requestBody")
            if request_body is None:
                continue
            if not isinstance(request_body, dict):
                errors.append("{}: requestBody 必须是 dict".format(label))
                continue
            content = request_body.get("content")
            json_media = content.get("application/json") if isinstance(content, dict) else None
            schema = json_media.get("schema") if isinstance(json_media, dict) else None
            if not isinstance(schema, dict) or schema.get("type") != "object":
                errors.append("{}: requestBody 的 JSON schema 必须是 type=object".format(label))
                continue
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                errors.append("{}: requestBody schema.properties 必须是 dict".format(label))
                continue

            for pname, pschema in properties.items():
                ptype = pschema.get("type") if isinstance(pschema, dict) else None
                if ptype not in JSON_TYPE_TO_PYTHON:
                    errors.append(
                        "{}: 参数 {!r} 的 type {!r} 不受支持".format(label, pname, ptype)
                    )
                    continue
                if ptype == "array":
                    items = pschema.get("items")
                    if not isinstance(items, dict) or not items.get("type"):
                        errors.append("{}: 数组参数 {!r} 缺少 items.type".format(label, pname))

            required = schema.get("required")
            if required is not None:
                if not isinstance(required, list):
                    errors.append("{}: required 必须是 list".format(label))
                else:
                    for rname in required:
                        if rname not in properties:
                            errors.append(
                                "{}: required 中的 {!r} 不存在于 properties, "
                                "Coze 端会导致整条工具不可调用".format(label, rname)
                            )

            example = json_media.get("example")
            if example is not None:
                if not isinstance(example, dict):
                    errors.append("{}: 请求体 example 必须是 dict".format(label))
                else:
                    for ename, eval_ in example.items():
                        pschema = properties.get(ename)
                        if pschema is None:
                            errors.append(
                                "{}: example 键 {!r} 不存在于 properties".format(label, ename)
                            )
                            continue
                        etype = pschema.get("type")
                        expected_types = JSON_TYPE_TO_PYTHON.get(etype)
                        if expected_types is None:
                            continue
                        if etype in ("integer", "number") and isinstance(eval_, bool):
                            errors.append(
                                "{}: example {!r} 类型与 {} 不符 (bool)".format(label, ename, etype)
                            )
                        elif not isinstance(eval_, expected_types):
                            errors.append(
                                "{}: example {!r} 期望 {}, 实际 {}".format(
                                    label, ename, etype, type(eval_).__name__
                                )
                            )
                    if isinstance(required, list):
                        for rname in required:
                            if rname in properties and rname not in example:
                                errors.append(
                                    "{}: example 缺少必填参数 {!r} 的示例值".format(label, rname)
                                )
    return errors


def openapi_json(
    registry: ToolRegistry,
    *,
    title: str,
    version: str = "0.1.0",
    description: str = "",
    server_url: str = DEFAULT_SERVER_URL,
) -> str:
    """便捷函数: 生成完整文档并序列化为稳定 JSON 文本.

    :param registry: 工具注册表.
    :param title: 插件标题.
    :param version: 插件版本号.
    :param description: 插件描述.
    :param server_url: 网关地址 (servers).
    :returns: ``json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True)`` 的结果.
    """
    doc = build_openapi(
        registry, title=title, version=version, description=description, server_url=server_url
    )
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)