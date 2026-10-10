"""CLI 入口: 生成 Coze 插件 OpenAPI Schema 并做静态自检.

用法::

    PYTHONPATH=src python3 -m coze_skills.cli schema --out docs/coze-plugin-openapi.json
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

from .core.registry import build_default_registry
from .core.runner import ToolRunner
from .core.schema import build_openapi, openapi_json, validate_openapi
from .core.spec import ToolResult


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
    """生成 OpenAPI 文档, 可选写入文件, 并做本地结构校验.

    :returns: 进程退出码 (校验不通过为 1, 便于 CI 拦截).
    """
    registry = _load_registry()
    doc = build_openapi(registry, title=args.title, version=args.version, description=args.description)
    problems: List[str] = validate_openapi(doc)
    payload = openapi_json(registry, title=args.title, version=args.version)
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
    print(f"Schema 校验通过: {len(doc.get('paths', {}))} 个 operation", file=sys.stderr)
    return 0


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
    """构造参数解析器 (子命令: list / schema / selftest / invoke)."""
    parser = argparse.ArgumentParser(prog="coze_skills", description="扣子插件 Schema 生成与本地自检")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出全部已注册工具")
    p_list.set_defaults(func=cmd_list)

    p_schema = sub.add_parser("schema", help="生成 Coze 插件 OpenAPI Schema")
    p_schema.add_argument("--out", default=None, help="输出文件路径; 省略则打印到 stdout")
    p_schema.add_argument("--title", default="Coze 垂类提效插件集", help="OpenAPI info.title")
    p_schema.add_argument("--version", default="0.1.0", help="OpenAPI info.version")
    p_schema.add_argument("--description", default="垂类提效小工具统一网关", help="OpenAPI info.description")
    p_schema.set_defaults(func=cmd_schema)

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
