"""CLI 入口: 生成 Coze 插件 OpenAPI Schema 并做静态自检.

用法::

    PYTHONPATH=src python3 -m coze_skills.cli schema --out docs/coze-plugin-openapi.json
    PYTHONPATH=src python3 -m coze_skills.cli schema --format yaml --out docs/coze-plugin-openapi.yaml
    PYTHONPATH=src python3 -m coze_skills.cli audit
    PYTHONPATH=src python3 -m coze_skills.cli list
    PYTHONPATH=src python3 -m coze_skills.cli selftest

设计说明: CLI 与 HTTP 网关共用同一份 :class:`~coze_skills.core.registry.ToolRegistry`,
因此「本地生成的 Schema」与「线上网关行为」永远同源, 不存在两套配置漂移.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from .core.audit import run_audit
from .core.registry import build_default_registry
from .core.runner import ToolRunner
from .core.schema import (
    DEFAULT_PLUGIN_DESCRIPTION,
    DEFAULT_PLUGIN_TITLE,
    DEFAULT_SERVER_URL,
    build_openapi,
    validate_openapi,
)
from .core.spec import ToolResult
from .core.yamlout import sorted_document, to_yaml


def _load_registry(strict: bool = True):
    """构建并发现全部工具的注册表."""
    return build_default_registry(strict=strict)


def cmd_list(args: argparse.Namespace) -> int:
    """打印已注册工具及其参数签名."""
    registry = _load_registry()
    for spec in registry.all():
        required = "".join(f"<{p.name}>" for p in spec.required_params)
        optional = ",".join(f"{p.name}?" for p in spec.params if not p.required)
        signature = ",".join(x for x in (required, optional) if x)
        print(f"[{spec.category}] {spec.name}({signature})")
        print(f"    {spec.title}: {spec.description.splitlines()[0]}")
    count, param_count = registry.stats()
    print(f"\n共 {count} 个工具 / {param_count} 个参数")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    """生成 OpenAPI 文档 (含 info/servers/tags/example), 可选写入文件, 并做结构校验.

    ``--format yaml`` 走的是网关同一套确定性序列化 (键名字典序 + 标准库 YAML 发射器),
    因此本地导出的 YAML 与线上 ``GET /export/openapi?format=yaml`` 逐字节一致.

    :param args: 需含 ``format`` / ``out`` / ``title`` / ``version`` / ``description`` / ``server_url``.
    :returns: 进程退出码 (校验不通过为 1, 便于 CI 拦截).
    """
    registry = _load_registry()
    doc = build_openapi(
        registry,
        title=args.title,
        version=args.version,
        description=args.description,
        server_url=args.server_url,
    )
    problems: List[str] = validate_openapi(doc)
    if args.format == "yaml":
        payload = to_yaml(sorted_document(doc))
    else:
        payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fp:
            fp.write(payload)
        print(f"已写入 {args.out} ({len(payload)} 字节)")
    else:
        print(payload)
    if problems:
        print(f"Schema 校验失败 ({len(problems)} 项):", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1
    n_examples = sum(
        1
        for methods in doc["paths"].values()
        for op in methods.values()
        if "example" in op["requestBody"]["content"]["application/json"]
    )
    print(
        f"Schema 校验通过 (OpenAPI {doc['openapi']}): {len(doc['paths'])} 个 operation / "
        f"{len(doc['tags'])} 个 tags / servers={doc['servers'][0]['url']} / "
        f"{n_examples} 个 example payload",
        file=sys.stderr,
    )
    return 0


#: 自检清单三档状态对应的行首标记 (info 是「不影响导入、但上架前值得看一眼」的提示项)
_AUDIT_MARK = {"pass": "ok  ", "info": "info", "warning": "WARN", "error": "FAIL"}


def cmd_audit(args: argparse.Namespace) -> int:
    """跑一遍 Coze 平台兼容性自检清单 (与网关 ``GET /audit`` 同一套判据).

    ``--format json`` 直接输出机器可解析的清单, 便于 CI 与提交材料归档;
    退出码只由 warning/error 决定 —— info 是提示, 拦下 CI 只会逼人把检查关掉.

    :param args: 需含 ``format`` / ``out`` / ``title`` / ``version`` / ``description`` / ``server_url``.
    :returns: 存在 warning 或 error 时为 1, 否则 0.
    """
    registry = _load_registry()
    report = run_audit(
        registry,
        title=args.title,
        version=args.version,
        description=args.description,
        server_url=args.server_url,
        runner=ToolRunner(registry),
    )
    summary = report["summary"]
    if args.format == "json":
        payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fp:
                fp.write(payload)
            print(f"已写入 {args.out} ({len(payload)} 字节)")
        else:
            print(payload)
    else:
        print(f"=== Coze 兼容性自检 · {summary['checked']} 项 ===")
        for item in report["items"]:
            mark = _AUDIT_MARK.get(item["status"], "?   ")
            print(f"  [{mark}] {item['name']}: {item['detail']}")
        print(
            f"→ {summary['pass']} pass / {summary['info']} info / "
            f"{summary['warning']} warning / {summary['error']} error :: {report['verdict']}"
        )
    return 0 if report["ok"] else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    """对每个工具跑一次「必填参数缺失」调用, 验证校验链路与日志可用."""
    registry = _load_registry()
    runner = ToolRunner(registry)
    failures = 0
    for spec in registry.all():
        result: ToolResult = runner.invoke(spec.name, {})
        if not spec.required_params:
            print(f"  ~ {spec.name}: 无必填参数, 跳过")
            continue
        if result.ok or not (result.error or "").startswith("参数校验失败"):
            print(f"  ! {spec.name}: 缺参调用未按预期被拦截 -> {result.model_dump()}")
            failures += 1
        else:
            print(f"  ok {spec.name}: 缺参调用被正确拦截")
    summary: Dict[str, Any] = runner.describe()
    print(f"自检完成, 失败 {failures} 项; 日志: {json.dumps(summary['log'], ensure_ascii=False)}")
    if not failures:
        print("  (说明: 日志中的 failed 即缺参拦截次数, success_rate 0.0 为预期结果)")
    return 1 if failures else 0


def cmd_invoke(args: argparse.Namespace) -> int:
    """本地直调单个工具, 便于不启网关时做冒烟验证."""
    registry = _load_registry()
    runner = ToolRunner(registry)
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        print(f"--params 不是合法 JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print("--params 必须是 JSON 对象", file=sys.stderr)
        return 2
    result = runner.invoke(args.tool, params)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器 (子命令: list / schema / export-openapi / audit / selftest / invoke)."""
    parser = argparse.ArgumentParser(prog="coze_skills", description="扣子插件 Schema 生成与本地自检")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出全部已注册工具")
    p_list.set_defaults(func=cmd_list)

    def _add_schema_args(
        p: argparse.ArgumentParser,
        help_text: str,
        *,
        format_choices: Sequence[str] = ("json", "yaml"),
        format_default: str = "json",
        format_help: str = "导出形态: json 便于程序消费, yaml 是扣子控制台「导入 OpenAPI」直接粘贴的形态",
    ) -> None:
        p.description = help_text
        p.add_argument("--out", default=None, help="输出文件路径; 省略则打印到 stdout")
        p.add_argument("--format", choices=format_choices, default=format_default, help=format_help)
        p.add_argument("--title", default=DEFAULT_PLUGIN_TITLE, help="OpenAPI info.title")
        p.add_argument("--version", default="0.1.0", help="OpenAPI info.version")
        p.add_argument("--description", default=DEFAULT_PLUGIN_DESCRIPTION, help="OpenAPI info.description")
        p.add_argument(
            "--server-url",
            default=DEFAULT_SERVER_URL,
            help="网关 servers[0].url (扣子导入后按此地址发起调用, 上架前替换为公网 HTTPS 域名)",
        )
        p.set_defaults(func=cmd_schema)

    _add_schema_args(
        sub.add_parser("schema", help="生成 Coze 插件 OpenAPI Schema (别名: export-openapi)"),
        "生成 Coze 插件 OpenAPI Schema (等价于 export-openapi)",
    )
    _add_schema_args(
        sub.add_parser(
            "export-openapi",
            help="导出完整 openapi.json|yaml: info/servers/tags + 每个工具的 example payload",
        ),
        "导出完整 OpenAPI 文档: info/servers/tags + 每个工具的 example payload, 严格通过 OpenAPI 3.0 结构校验",
    )
    p_audit = sub.add_parser(
        "audit",
        help="Coze 平台兼容性自检清单 (与网关 GET /audit 同源; 有 warning/error 时退出码 1)",
    )
    _add_schema_args(
        p_audit,
        "对当前注册表生成的 Schema 跑满兼容性清单, 只导不发布, 适合提交前闸门",
        format_choices=("text", "json"),
        format_default="text",
        format_help="text 给人看 (逐项打勾), json 给 CI 解析",
    )
    p_audit.set_defaults(func=cmd_audit)

    p_self = sub.add_parser("selftest", help="逐工具执行缺参调用, 验证校验链路")
    p_self.set_defaults(func=cmd_selftest)

    p_invoke = sub.add_parser("invoke", help="本地直调工具")
    p_invoke.add_argument("tool", help="工具名")
    p_invoke.add_argument("--params", default="{}", help="JSON 对象形式的参数")
    p_invoke.set_defaults(func=cmd_invoke)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 主入口, 返回进程退出码."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
