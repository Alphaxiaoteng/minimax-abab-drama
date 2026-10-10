"""export-openapi 导出文档的完整性与合法性测试.

钉住「Coze 上架可见」的契约: 完整 info/servers/tags、每个工具带 example payload、
response 引用可解析、且必须通过 validate_openapi 的 OpenAPI 3.0 严格结构校验;
同时校验仓库内提交版 docs/coze-plugin-openapi.json 与代码导出保持同步 (SSOT 不漂移).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from coze_skills.cli import main as cli_main
from coze_skills.core.registry import build_default_registry
from coze_skills.core.schema import DEFAULT_SERVER_URL, build_openapi, validate_openapi
from coze_skills.core.spec import JSON_TYPE_TO_PYTHON

EXPECTED_TOOLS = {"check_compliance", "batch_check", "analyze_reviews", "draft_reply"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DOC_PATH = PROJECT_ROOT / "docs" / "coze-plugin-openapi.json"


@pytest.fixture(scope="module")
def registry():
    return build_default_registry()


@pytest.fixture(scope="module")
def doc(registry) -> Dict[str, Any]:
    return build_openapi(
        registry,
        title="Coze电商智能体插件",
        version="1.0.0",
        description="电商垂类提效插件集: 合规审查 / 差评归因 / 英文回复, 全程离线可跑.",
    )


def _operations(document: Dict[str, Any]):
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            yield path, method, operation


# --------------------------------------------------------------- 顶层结构 ----
def test_document_top_level_is_valid_openapi_30(doc) -> None:
    assert doc["openapi"].startswith("3.0")
    assert validate_openapi(doc) == []
    assert set(doc) >= {"openapi", "info", "servers", "tags", "paths", "components"}


def test_no_json_schema_type_unions(doc) -> None:
    """OpenAPI 3.0 的 schema.type 只能是单字符串 (可空用 nullable), type 数组是 3.1 语法."""
    def _walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            t = node.get("type")
            assert not isinstance(t, list), f"{where}: type 不允许数组 (OpenAPI 3.0), 实际 {t!r}"
            for k, v in node.items():
                _walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{where}[{i}]")

    _walk(doc, "$")


def test_external_openapi_validator_accepts_export(tmp_path: Path) -> None:
    """用 openapi-spec-validator 做第三方严格校验; 该库不在运行时依赖里, 缺失则跳过."""
    pytest.importorskip("openapi_spec_validator")
    from openapi_spec_validator import validate as _strict_validate

    out = tmp_path / "openapi.json"
    assert cli_main(["export-openapi", "--out", str(out)]) == 0
    _strict_validate(json.loads(out.read_text(encoding="utf-8")))


def test_info_block_is_complete(doc) -> None:
    info = doc["info"]
    assert info["title"] == "Coze电商智能体插件"
    assert info["version"] == "1.0.0"
    assert len(info["description"].strip()) >= 20
    assert info["contact"]["url"].startswith(("http://", "https://"))


def test_servers_declares_reachable_gateway_url(doc) -> None:
    servers = doc["servers"]
    assert isinstance(servers, list) and len(servers) == 1
    assert servers[0]["url"] == DEFAULT_SERVER_URL
    assert servers[0]["url"].startswith(("http://", "https://"))
    assert servers[0]["description"]


def test_top_level_tags_unique_with_descriptions(doc) -> None:
    tags = doc["tags"]
    assert tags, "导出必须包含顶层 tags"
    names = [t["name"] for t in tags]
    assert len(names) == len(set(names))
    assert all(t["description"].strip() for t in tags)
    categories = {registry_spec.category for registry_spec in build_default_registry().all()}
    assert categories <= set(names)


# ------------------------------------------------------------ operation ----
def test_all_four_tools_present_with_expected_shape(doc) -> None:
    ops = {operation["operationId"] for _, _, operation in _operations(doc)}
    assert ops == EXPECTED_TOOLS
    for path, method, operation in _operations(doc):
        assert method == "post"
        assert path == f"/tools/{operation['operationId']}"
        assert operation["summary"].strip()
        assert operation["description"].strip()
        assert isinstance(operation["parameters"], list)
        assert operation["tags"], f"{operation['operationId']}: operation 必须带 tags"


def test_operation_tags_are_declared_at_top_level(doc) -> None:
    declared = {t["name"] for t in doc["tags"]}
    for _, _, operation in _operations(doc):
        assert set(operation["tags"]) <= declared


def test_response_refs_resolve_to_components(doc) -> None:
    schemas = doc["components"]["schemas"]
    for _, _, operation in _operations(doc):
        media = operation["responses"]["200"]["content"]["application/json"]
        ref = media["schema"]["$ref"]
        assert ref.startswith("#/components/schemas/")
        assert ref.rsplit("/", 1)[-1] in schemas


# --------------------------------------------------------------- example ----
def test_every_tool_carries_a_complete_example_payload(doc) -> None:
    registry = build_default_registry()
    for _, _, operation in _operations(doc):
        name = operation["operationId"]
        media = operation["requestBody"]["content"]["application/json"]
        schema, example = media["schema"], media.get("example")
        assert isinstance(example, dict), f"{name}: 必须带 example payload"
        assert set(example) <= set(schema["properties"])
        for req in schema.get("required", []):
            assert req in example, f"{name}: example 缺少必填参数 {req}"
        for pname, pvalue in example.items():
            pschema = schema["properties"][pname]
            expected = JSON_TYPE_TO_PYTHON[pschema["type"]]
            if pschema["type"] in ("integer", "number"):
                assert not isinstance(pvalue, bool)
            assert isinstance(pvalue, expected), f"{name}.{pname} 示例值类型不符"
            if pschema["type"] == "array" and pvalue:
                item_type = pschema["items"]["type"]
                assert all(isinstance(x, JSON_TYPE_TO_PYTHON[item_type]) for x in pvalue)


def test_example_payloads_are_invocable_business_inputs(doc) -> None:
    """example 不只是类型正确——必须能被 runner 真实调用成功 (评委零门槛照抄可用)."""
    from coze_skills.core.runner import ToolRunner

    runner = ToolRunner(build_default_registry())
    for _, _, operation in _operations(doc):
        example = operation["requestBody"]["content"]["application/json"]["example"]
        result = runner.invoke(operation["operationId"], example)
        assert result.ok, f"{operation['operationId']} example 调用失败: {result.error}"


# ------------------------------------------------------------------ CLI ----
def test_export_openapi_cli_writes_validated_json(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    code = cli_main(
        ["export-openapi", "--out", str(out), "--title", "Coze电商智能体插件", "--version", "1.0.0"]
    )
    assert code == 0
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert validate_openapi(exported) == []
    assert {op["operationId"] for _, _, op in _operations(exported)} == EXPECTED_TOOLS


def test_schema_and_export_openapi_subcommands_are_equivalent(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert cli_main(["schema", "--out", str(a)]) == 0
    assert cli_main(["export-openapi", "--out", str(b)]) == 0
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


# ------------------------------------------------------------ 提交版同步 ----
def test_committed_docs_json_matches_codegen_if_exists() -> None:
    if not COMMITTED_DOC_PATH.exists():
        pytest.skip("docs/coze-plugin-openapi.json 尚未生成")
    committed = json.loads(COMMITTED_DOC_PATH.read_text(encoding="utf-8"))
    fresh = build_openapi(
        build_default_registry(),
        title=committed["info"]["title"],
        version=committed["info"]["version"],
        description=committed["info"].get("description", ""),
        server_url=committed["servers"][0]["url"],
    )
    assert committed == fresh, "提交版 Schema 与代码导出漂移, 请重新运行 export-openapi"
