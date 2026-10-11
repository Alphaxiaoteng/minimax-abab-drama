"""交付面测试: 确定性 YAML 发射器 + OpenAPI 导出端点 + Coze 兼容性自检清单.

对标「大厂上线」的两道闸门:
1. **导出物可复现** —— 同一份注册表, 本地 CLI 与线上 ``GET /export/openapi`` 必须吐出
   逐字节相同的文档; YAML 还要能被标准解析器读回成同一个 dict, 否则「导入即用」是空话。
2. **自检必须清零** —— 目标 0 error / 0 warning; 同时用一个刻意写坏的注册表做反向对照,
   证明这套清单真的会红, 而不是一台永远亮绿灯的摆设。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from coze_skills.cli import main as cli_main
from coze_skills.core.audit import MAX_DOC_BYTES, MIN_PARAM_DESCRIPTION, run_audit
from coze_skills.core.registry import ToolRegistry, build_default_registry
from coze_skills.core.runner import ToolRunner
from coze_skills.core.schema import (
    DEFAULT_PLUGIN_DESCRIPTION,
    DEFAULT_PLUGIN_TITLE,
    build_openapi,
    validate_openapi,
)
from coze_skills.core.spec import Param, ToolResult, ToolSpec
from coze_skills.core.yamlout import DEFAULT_HEADER, sorted_document, to_yaml
from coze_skills.gateway import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_JSON_PATH = PROJECT_ROOT / "docs" / "coze-plugin-openapi.json"
COMMITTED_YAML_PATH = PROJECT_ROOT / "docs" / "coze-plugin-openapi.yaml"

#: 面板上「一键自检」的判据代号 —— 少一项就意味着某条上线经验被悄悄删掉
AUDIT_CODES = {
    "openapi-30-structure",
    "openapi-version-prefix",
    "info-metadata",
    "server-url",
    "operation-id-unique",
    "path-alignment",
    "param-description-richness",
    "tool-description-richness",
    "enum-default-documented",
    "openapi30-scalar-types",
    "response-refs-resolvable",
    "error-envelope",
    "example-payload-complete",
    "timeout-within-platform-budget",
    "registry-handler-purity",
    "yaml-export-deterministic",
    "doc-size-budget",
    "no-credential-in-schema",
    "examples-are-invocable",
}


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return build_default_registry()


@pytest.fixture(scope="module")
def doc(registry) -> Dict[str, Any]:
    return build_openapi(
        registry,
        title=DEFAULT_PLUGIN_TITLE,
        description=DEFAULT_PLUGIN_DESCRIPTION,
    )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ------------------------------------------------------- YAML 发射器口径 ----
def test_yaml_round_trips_through_a_standard_parser(doc) -> None:
    """扣子控制台粘贴的是 YAML: 必须能被 PyYAML 读回成与 JSON 导出完全相同的结构."""
    yaml = pytest.importorskip("yaml")
    loaded = yaml.safe_load(to_yaml(sorted_document(doc)))
    assert loaded == json.loads(json.dumps(doc, ensure_ascii=False))


def test_yaml_export_is_byte_stable(doc) -> None:
    """可进 git diff 的前提是同输入同字节 —— 否则每次导出都是满屏假改动."""
    first, second = to_yaml(sorted_document(doc)), to_yaml(sorted_document(doc))
    assert first == second
    assert first.startswith(DEFAULT_HEADER)
    assert len(first.splitlines()) > 200


def test_yaml_keys_stay_yaml_safe(doc) -> None:
    """状态码 200 与 path 这类键必须保持引号: 裸 ``200:`` 会被解析成整数而破坏往返."""
    text = to_yaml(sorted_document(doc))
    assert '"200":' in text
    assert '"/tools/check_compliance":' in text
    assert "\nopenapi: \"3.0.0\"" in text
    assert "\ncomponents:\n" in text  # 普通键保持可读, 不全员加引号
    assert "true" in text and "nullable: true" in text


def test_sorted_document_sorts_recursively(doc) -> None:
    """排序必须穿透嵌套 —— 只排顶层等于没排, 数组顺序则刻意保留 (YAML 序列有语义)."""
    sorted_doc = sorted_document(doc)
    keys = list(sorted_doc)
    assert keys == sorted(keys)
    for path_body in sorted_doc["paths"].values():
        assert list(path_body) == sorted(path_body)
    assert sorted_document(doc) == sorted_doc


# ------------------------------------------------------------ 导出端点 ----
def test_export_endpoints_are_cross_format_equivalent(client: TestClient) -> None:
    """JSON 与 YAML 两条导出路径必须指向同一份文档 —— 只允许序列化形态不同."""
    json_resp = client.get("/export/openapi?format=json")
    yaml_resp = client.get("/export/openapi?format=yaml")
    assert json_resp.status_code == yaml_resp.status_code == 200
    doc = json.loads(json_resp.content)
    assert validate_openapi(doc) == []
    assert {op["operationId"] for body in doc["paths"].values() for op in body.values()} == set(
        build_default_registry().names()
    )
    assert to_yaml(sorted_document(doc)) == yaml_resp.text
    assert "application/json" in json_resp.headers["content-type"]
    assert "application/yaml" in yaml_resp.headers["content-type"]
    for resp in (json_resp, yaml_resp):
        assert "attachment" in resp.headers["content-disposition"]


def test_export_is_byte_reproducible(client: TestClient) -> None:
    """同一进程内两次导出逐字节相同 —— 评委下载两次拿到的是同一个东西."""
    for fmt in ("json", "yaml"):
        first, second = client.get(f"/export/openapi?format={fmt}"), client.get(
            f"/export/openapi?format={fmt}"
        )
        assert first.content == second.content


def test_export_can_skip_attachment_for_in_page_preview(client: TestClient) -> None:
    """面板内预览靠这个开关: 带 attachment 的响应浏览器只会存盘, 渲染不出来."""
    resp = client.get("/export/openapi?format=yaml&download=false")
    assert "content-disposition" not in resp.headers
    assert resp.text.startswith(DEFAULT_HEADER)


def test_export_rejects_unknown_format(client: TestClient) -> None:
    resp = client.get("/export/openapi?format=xml")
    assert resp.status_code == 422


# ------------------------------------------------------------ 自检清零 ----
def test_audit_is_clean_on_the_shipped_registry(registry) -> None:
    """上架闸门: 0 error 且 0 warning 才算过, info 只提示不拦."""
    report = run_audit(registry, runner=ToolRunner(registry))
    assert report["ok"] is True, [i for i in report["items"] if i["status"] != "pass"]
    assert report["summary"]["error"] == 0
    assert report["summary"]["warning"] == 0
    assert report["summary"]["checked"] == len(report["items"]) == report["summary"]["pass"] + report["summary"]["info"]
    assert report["verdict"] == "0 error · 0 warning —— 可直接导入扣子开放平台"
    assert {item["code"] for item in report["items"]} == AUDIT_CODES


def test_audit_reports_the_local_demo_url_as_info_only(registry) -> None:
    """演示地址 http://127.0.0.1 是「上架前替换」而非「现在就有 bug」—— 不该染黄."""
    report = run_audit(registry)
    row = next(i for i in report["items"] if i["code"] == "server-url")
    assert row["status"] == "info"
    assert "上架前替换" in row["detail"]
    assert report["summary"]["warning"] == 0


def test_audit_flags_a_deliberately_thin_registry() -> None:
    """反向对照: 描述敷衍 + 枚举不写默认值 + 超时越界, 清单必须变红并给出定位."""
    bad = ToolRegistry("audit-negative")

    def _handler(**kwargs: Any) -> ToolResult:
        return ToolResult.success(**kwargs)

    bad.register(
        ToolSpec(
            name="thin_tool",
            title="敷衍",
            description="太短",
            params=(
                Param(name="mode", type="string", description="模式", enum=("a", "b")),
                Param(
                    name="text",
                    type="string",
                    required=True,
                    description="x" * (MIN_PARAM_DESCRIPTION - 1),
                ),
            ),
            handler=_handler,
            timeout_seconds=600,
        )
    )
    report = run_audit(bad, runner=ToolRunner(bad))
    assert report["ok"] is False
    failing = {i["code"] for i in report["items"] if i["status"] == "error"}
    assert {"tool-description-richness", "param-description-richness"} <= failing
    assert "enum-default-documented" in failing
    assert "timeout-within-platform-budget" in failing
    assert validate_openapi(
        build_openapi(bad, title="负面对照", description="用于验证自检清单真的会红")
    ) == []  # 结构合法但不好用 —— 正是本清单的存在理由


def test_audit_scans_exported_text_for_credential_shapes(registry) -> None:
    """导出物要提交进仓库并交给平台: 凭据样式片段必须被扫出来, 且出厂文档是干净的."""
    report = run_audit(registry)
    row = next(i for i in report["items"] if i["code"] == "no-credential-in-schema")
    assert row["status"] == "pass"
    assert report["doc_meta"]["bytes"] < MAX_DOC_BYTES
    assert "AKIA" not in json.dumps(build_openapi(registry, title=DEFAULT_PLUGIN_TITLE), default=str)


def test_audit_catches_a_key_pasted_into_a_tool_description() -> None:
    """正向对照: 有人把长期密钥写进工具描述当「示例」, 清单必须当场报红而不是放行."""
    leaky = ToolRegistry("audit-secret")

    def _handler(**kwargs: Any) -> ToolResult:
        return ToolResult.success(**kwargs)

    leaky.register(
        ToolSpec(
            name="leaky_tool",
            title="带密钥的描述",
            description=(
                "这个工具的描述里被人误贴了上游服务的访问密钥 AKIAIOSFODNN7EXAMPLE, "
                "用于验证导出前的凭据扫描真的会拦下它。"
            ),
            params=(Param(name="text", type="string", required=True, description="待处理文本内容"),),
            handler=_handler,
        )
    )
    failing = {i["code"] for i in run_audit(leaky)["items"] if i["status"] == "error"}
    assert "no-credential-in-schema" in failing


def test_audit_endpoint_and_cli_share_one_verdict(client: TestClient) -> None:
    """HTTP 面板、CLI 闸门与网关内嵌 runner 三处结论必须一致, 否则「本地绿线上红」."""
    payload = client.get("/audit").json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["summary"]["error"] == 0 and data["summary"]["warning"] == 0
    assert {i["code"] for i in data["items"]} == AUDIT_CODES


# ---------------------------------------------------------------- CLI ----
def test_cli_audit_exits_zero_and_prints_checkmarks(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "[ok  ]" in out and "[info]" in out
    assert "0 warning / 0 error" in out
    assert "[FAIL]" not in out and "[WARN]" not in out


def test_cli_audit_json_format_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["audit", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["error"] == 0
    assert report["summary"]["warning"] == 0


def test_cli_schema_yaml_export_equals_json_export(tmp_path: Path) -> None:
    """两条导出路径必须指向同一份文档 —— 只允许序列化形态不同."""
    yaml = pytest.importorskip("yaml")
    json_out, yaml_out = tmp_path / "doc.json", tmp_path / "doc.yaml"
    assert cli_main(["schema", "--format", "json", "--out", str(json_out)]) == 0
    assert cli_main(["schema", "--format", "yaml", "--out", str(yaml_out)]) == 0
    assert yaml.safe_load(yaml_out.read_text(encoding="utf-8")) == json.loads(
        json_out.read_text(encoding="utf-8")
    )


def test_committed_docs_yaml_matches_codegen_if_exists() -> None:
    """提交版 YAML 必须等于提交版 JSON 的确定性序列化.

    另一条测试已钉住「提交版 JSON == 代码导出」, 因此这里传递性地把 YAML 也钉在代码上,
    同时保证仓库里这两份文件永远不会各说各话。
    """
    if not COMMITTED_YAML_PATH.exists():
        pytest.skip("docs/coze-plugin-openapi.yaml 尚未生成")
    yaml = pytest.importorskip("yaml")
    committed_json = json.loads(COMMITTED_JSON_PATH.read_text(encoding="utf-8"))
    committed_yaml = COMMITTED_YAML_PATH.read_text(encoding="utf-8")
    assert yaml.safe_load(committed_yaml) == committed_json
    assert committed_yaml == to_yaml(sorted_document(committed_json)), (
        "提交版 YAML 与 JSON 漂移, 请重跑 cli schema --format yaml --out docs/coze-plugin-openapi.yaml"
    )
