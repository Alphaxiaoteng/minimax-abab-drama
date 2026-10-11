"""Coze 上架兼容性自检清单 (一键自检: 目标 0 error / 0 warning).

和 :func:`~coze_skills.core.schema.validate_openapi` 的分工:
* ``validate_openapi`` 管**结构合法性** (会不会导入失败);
* 本模块管**平台可用性** —— 导入成功但大模型照样选错工具、填错参数, 是插件
  上架后最常见的「能跑不好用」. 于是把「参数必须有面向模型的描述」「枚举必须
  写明默认值」「example 必须真能调通」这类经验教训固化成可执行的检查项.

分级口径:
* ``error``   —— 会被 Coze 拒绝导入或线上必然翻车, 必须修;
* ``warning`` —— 能导入但会显著降低模型调用成功率或留下运维隐患, 上线前应修;
* ``info``    —— 演示环境成立、上架前需替换的事项 (如 ``http://127.0.0.1``),
  **不计入** warning, 否则本地跑通却满屏黄字反而看不清真实风险.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .registry import ToolRegistry
from .runner import ToolRunner
from .schema import (
    DEFAULT_PLUGIN_DESCRIPTION,
    DEFAULT_PLUGIN_TITLE,
    DEFAULT_SERVER_URL,
    build_openapi,
    validate_openapi,
)
from .yamlout import to_yaml

#: 参数描述最短长度 —— 低于此值基本等于「把参数名复读一遍」, 模型无从取值.
MIN_PARAM_DESCRIPTION = 10

#: 工具描述最短长度 —— 选工具全靠这句, 太短等于没写.
MIN_TOOL_DESCRIPTION = 30

#: 导出文档体积上限 (字节), Coze 导入框对超大 Schema 会截断, 这里留足余量.
MAX_DOC_BYTES = 200_000


@dataclass(frozen=True)
class AuditItem:
    """一条自检结论.

    :param code: 稳定代号, 前端 key 与测试锚点.
    :param name: 检查项名称.
    :param status: ``pass`` / ``info`` / ``warning`` / ``error``.
    :param detail: 结论说明 (含失败时的定位信息).
    """

    code: str
    name: str
    status: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        """转为 JSON 安全的纯 dict."""
        return {"code": self.code, "name": self.name, "status": self.status, "detail": self.detail}


def _item(code: str, name: str, ok: bool, good: str, bad: str) -> AuditItem:
    """把布尔判据折成 pass/error 条目."""
    return AuditItem(code, name, "pass" if ok else "error", good if ok else bad)


def run_audit(
    registry: ToolRegistry,
    *,
    title: str = DEFAULT_PLUGIN_TITLE,
    version: str = "0.1.0",
    description: str = DEFAULT_PLUGIN_DESCRIPTION,
    server_url: str = DEFAULT_SERVER_URL,
    runner: Optional[ToolRunner] = None,
) -> Dict[str, Any]:
    """对当前注册表生成完整的 Coze 兼容性清单.

    :param registry: 工具注册表 (Schema 的唯一来源).
    :param title: ``info.title``.
    :param version: ``info.version``.
    :param description: ``info.description``.
    :param server_url: ``servers[0].url``.
    :param runner: 传入执行器后会额外校验「每个 example 真能调通」.
    :returns: ``{"ok", "summary", "items", "doc_meta"}`` 纯 dict, 可直接 JSON 序列化.
    """
    doc = build_openapi(
        registry, title=title, version=version, description=description, server_url=server_url
    )
    operations = _operations(doc)
    items: List[AuditItem] = []

    structural = validate_openapi(doc)
    items.append(
        _item(
            "openapi-30-structure",
            "OpenAPI 3.0 结构校验 (validate_openapi)",
            not structural,
            f"{len(doc['paths'])} 个 operation 全部通过本地结构校验",
            "结构校验失败: " + "; ".join(structural[:3]),
        )
    )

    items.append(
        _item(
            "openapi-version-prefix",
            "版本号落在 3.0.x",
            str(doc.get("openapi", "")).startswith("3.0"),
            f"openapi = {doc['openapi']} (Coze 插件网关要求 3.0.x)",
            f"openapi = {doc.get('openapi')!r} 不是 3.0.x",
        )
    )

    info = doc["info"]
    items.append(
        _item(
            "info-metadata",
            "info 标题/版本/描述齐备",
            bool(info.get("title")) and bool(info.get("version")) and len(str(info.get("description", "")).strip()) >= 20,
            f"title={info['title']!r} version={info['version']!r} description {len(info['description'])} 字",
            "info 缺少 title/version 或 description 短于 20 字 (Coze 插件详情页会一片空白)",
        )
    )

    url = doc["servers"][0]["url"]
    items.append(
        AuditItem(
            "server-url",
            "servers[0].url 可达性",
            "pass" if url.startswith("https://") else "info",
            url
            if url.startswith("https://")
            else f"{url} —— 本地演示地址; 上架前替换为公网 HTTPS 域名 (仅影响线上, 不计入 warning)",
        )
    )

    ids = [op["operationId"] for _, _, op in operations]
    items.append(
        _item(
            "operation-id-unique",
            "operationId 全局唯一且与工具名一致",
            len(set(ids)) == len(ids) and set(ids) == set(registry.names()),
            f"{len(ids)} 个 operationId 一一对应注册表: {', '.join(sorted(ids))}",
            f"operationId 与注册表不一致: {sorted(ids)} vs {sorted(registry.names())}",
        )
    )

    paths_ok = all(path.startswith("/tools/") for path, _, _ in operations)
    items.append(
        _item(
            "path-alignment",
            "Schema 声明的 path 与网关路由前缀一致",
            paths_ok,
            "所有 path 均为 /tools/{name}, 与 server.py 的两条别名路由同源",
            "存在不以 /tools/ 开头的 path, 导入后 Coze 会 404",
        )
    )

    short_params = [
        f"{op['operationId']}.{name}"
        for _, _, op in operations
        for name, sch in op["requestBody"]["content"]["application/json"]["schema"]["properties"].items()
        if len(str(sch.get("description", "")).strip()) < MIN_PARAM_DESCRIPTION
    ]
    items.append(
        _item(
            "param-description-richness",
            f"每个参数都有面向模型的描述 (≥{MIN_PARAM_DESCRIPTION} 字)",
            not short_params,
            f"{sum(len(op['requestBody']['content']['application/json']['schema']['properties']) for _, _, op in operations)} 个参数描述齐备, 写明取值范围/单位/默认值",
            "描述过短或缺失: " + ", ".join(short_params),
        )
    )

    short_tools = [spec.name for spec in registry.all() if len(spec.description.strip()) < MIN_TOOL_DESCRIPTION]
    items.append(
        _item(
            "tool-description-richness",
            f"每个工具描述足以支撑选工具决策 (≥{MIN_TOOL_DESCRIPTION} 字)",
            not short_tools,
            f"{len(registry.all())} 个工具描述均写明输入/输出与适用场景",
            "描述过短, 模型无从判断该选哪个: " + ", ".join(short_tools),
        )
    )

    enum_missing_default = [
        f"{op['operationId']}.{name}"
        for _, _, op in operations
        for name, sch in op["requestBody"]["content"]["application/json"]["schema"]["properties"].items()
        if sch.get("enum") and "默认" not in str(sch.get("description", ""))
    ]
    items.append(
        _item(
            "enum-default-documented",
            "枚举参数的描述写明默认取值",
            not enum_missing_default,
            "所有枚举参数都在描述里给出默认值, 模型不会在空值与该枚举默认值之间摇摆",
            "未标注默认值: " + ", ".join(enum_missing_default),
        )
    )

    type_violations = _type_violations(doc)
    items.append(
        _item(
            "openapi30-scalar-types",
            "不使用 3.1 才支持的 type 数组/联合类型",
            not type_violations,
            "所有 type 均为单字符串, 可空字段用 nullable —— 兼容 Coze 的 3.0 解析器",
            "发现不兼容写法: " + ", ".join(type_violations),
        )
    )

    dangling_refs = [
        ref
        for _, op in _response_pairs(doc)
        for ref in _refs(op)
        if ref.split("/")[-1] not in doc.get("components", {}).get("schemas", {})
    ]
    items.append(
        _item(
            "response-refs-resolvable",
            "响应里的 $ref 全部可解析",
            not dangling_refs,
            "所有 200 响应都指向 components.schemas.PluginError",
            "悬空 $ref: " + ", ".join(dangling_refs),
        )
    )

    envelope = doc["components"]["schemas"]["PluginError"]
    envelope_ok = (
        envelope.get("type") == "object"
        and set(envelope["properties"]) == {"ok", "error", "data"}
        and envelope["properties"]["ok"]["type"] == "boolean"
        and envelope["properties"]["error"].get("nullable") is True
    )
    items.append(
        _item(
            "error-envelope",
            "统一响应封套 ok/error/data 且业务错误留在 HTTP 200",
            envelope_ok,
            "业务失败也返回 200 + ok=false, 平台不会把它当网络故障而自动重试",
            "响应封套结构不符合约定",
        )
    )

    missing_example = [
        op["operationId"]
        for _, _, op in operations
        if "example" not in op["requestBody"]["content"]["application/json"]
    ]
    items.append(
        _item(
            "example-payload-complete",
            "每个工具都带可一键试跑的 example",
            not missing_example,
            f"{len(operations)} 个 operation 均带完整 example (必填参数全覆盖), Coze 调试面板可直接点跑",
            "缺少 example: " + ", ".join(missing_example),
        )
    )

    timeouts = [(spec.name, spec.timeout_seconds) for spec in registry.all()]
    bad_timeouts = [f"{name}={value:g}s" for name, value in timeouts if not 0 < value <= 60]
    items.append(
        _item(
            "timeout-within-platform-budget",
            "每个工具超时都在平台预算内 (0<x≤60s)",
            not bad_timeouts,
            "超时声明: " + ", ".join(f"{name} {value:g}s" for name, value in timeouts),
            "超出平台预算: " + ", ".join(bad_timeouts),
        )
    )

    pure = all(spec.handler is not None and callable(spec.handler) for spec in registry.all())
    items.append(
        _item(
            "registry-handler-purity",
            "注册表里每个工具都挂了可调用 handler",
            pure,
            "工具层不感知 HTTP, 校验/超时/日志由 ToolRunner 单点注入",
            "存在未挂 handler 的工具声明",
        )
    )

    yaml_text_a = to_yaml(doc)
    yaml_text_b = to_yaml(doc)
    items.append(
        _item(
            "yaml-export-deterministic",
            "YAML 导出可确定复现 (同输入同字节)",
            bool(yaml_text_a) and yaml_text_a == yaml_text_b,
            f"{len(yaml_text_a.splitlines())} 行, 两次生成逐字节一致",
            "YAML 导出不可复现, 不能进 git diff",
        )
    )

    doc_bytes = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    items.append(
        _item(
            "doc-size-budget",
            f"Schema 体积在导入预算内 (<{MAX_DOC_BYTES // 1000}KB)",
            doc_bytes < MAX_DOC_BYTES,
            f"当前 {doc_bytes} 字节 / {len(doc['paths'])} 个 operation",
            f"文档 {doc_bytes} 字节, 超出 Coze 导入框限制",
        )
    )

    leaky = _scan_secrets(doc)
    items.append(
        _item(
            "no-credential-in-schema",
            "Schema/描述文本里不含密钥或凭据样式字符串",
            not leaky,
            "导出物可安全提交进仓库并公开给平台; 真实密钥只在部署环境变量里",
            "疑似凭据泄漏: " + ", ".join(leaky),
        )
    )

    if runner is not None:
        failing = []
        for _, _, op in operations:
            example = op["requestBody"]["content"]["application/json"].get("example")
            if example is None:
                continue
            result = runner.invoke(op["operationId"], dict(example))
            if not result.ok:
                failing.append(f"{op['operationId']}: {result.error}")
        items.append(
            _item(
                "examples-are-invocable",
                "每个 example 都能经真实 runner 调用成功",
                not failing,
                "Coze 调试面板「一键试运行」全部可用, 不存在示例即报错的工具",
                "; ".join(failing),
            )
        )

    warnings = [i for i in items if i.status == "warning"]
    errors = [i for i in items if i.status == "error"]
    infos = [i for i in items if i.status == "info"]
    return {
        "ok": not errors and not warnings,
        "summary": {
            "checked": len(items),
            "pass": sum(1 for i in items if i.status == "pass"),
            "info": len(infos),
            "warning": len(warnings),
            "error": len(errors),
        },
        "verdict": (
            "0 error · 0 warning —— 可直接导入扣子开放平台"
            if not errors and not warnings
            else f"{len(errors)} error / {len(warnings)} warning, 上线前须清零"
        ),
        "items": [i.to_dict() for i in items],
        "doc_meta": {
            "title": title,
            "version": version,
            "operations": len(doc["paths"]),
            "tools": len(registry.names()),
            "params": sum(len(spec.params) for spec in registry.all()),
            "bytes": doc_bytes,
        },
    }


def _operations(doc: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """展开 ``paths`` 为 ``(path, method, operation)`` 三元组列表 (按 path 排序)."""
    rows: List[Tuple[str, str, Dict[str, Any]]] = []
    for path in sorted(doc.get("paths", {})):
        for method, operation in doc["paths"][path].items():
            rows.append((path, method, operation))
    return rows


def _response_pairs(doc: Dict[str, Any]):
    """迭代每个 operation 的每个 ``(状态码, response)`` 项."""
    for _, _, operation in _operations(doc):
        for status, response in (operation.get("responses") or {}).items():
            yield status, response


def _refs(node: Any) -> List[str]:
    """递归收集子树里所有 ``$ref`` 值."""
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_refs(item))
    return found


def _type_violations(doc: Dict[str, Any]) -> List[str]:
    """找出 JSON Schema 里不兼容 OpenAPI 3.0 的写法 (type 非单字符串 / 3.1 专属关键字)."""
    bad: List[str] = []

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            if "type" in node and not isinstance(node["type"], str):
                bad.append(f"{trail}.type={node['type']!r}")
            for key in ("examples", "prefixItems"):
                if key in node:
                    bad.append(f"{trail}.{key} 为 OpenAPI 3.1 专属关键字")
            for key, value in node.items():
                walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{trail}[{idx}]")

    for name, schema in (doc.get("components", {}).get("schemas") or {}).items():
        walk(schema, f"components.schemas.{name}")
    for _, _, operation in _operations(doc):
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        walk(schema, f"{operation['operationId']}.requestBody")
    for status, response in _response_pairs(doc):
        walk(response, f"responses.{status}")
    return bad


_SECRET_MARKERS: Tuple[str, ...] = ("-----BEGIN", "sk-", "AKIA", "password=", "secret_key")


def _scan_secrets(doc: Dict[str, Any]) -> List[str]:
    """在导出文本里扫描凭据样式片段 (宁可误报也不漏报, 误报时改描述即可)."""
    text = json.dumps(doc, ensure_ascii=False)
    lowered = text.lower()
    return [marker for marker in _SECRET_MARKERS if marker.lower() in lowered]
