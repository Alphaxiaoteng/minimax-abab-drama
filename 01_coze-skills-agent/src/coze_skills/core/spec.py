"""工具声明的零依赖数据契约.

设计约束:
1. 只用标准库 —— 扣子插件网关常以最小镜像部署, 不应被迫拖入 pydantic.
2. ``ToolSpec`` 同时是「OpenAPI Schema 源」「调用校验源」「MCP/Coze 清单源」,
   单一事实来源 (SSOT), 避免三处手写漂移.
3. 参数类型用 JSON Schema 原生类型字符串 (string/integer/number/boolean/array/object),
   与 Coze ``Plugin`` 参数定义一一对应.

.. note::
   ``ToolResult`` 的 ``model_dump`` 输出 **永远是 dict**, 绝不含非 JSON 可序列化对象;
   这是网关层 ``json.dumps`` 不抛异常的前提.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: JSON Schema 基础类型 -> Python 类型集合 (用于运行时校验)
JSON_TYPE_TO_PYTHON: Dict[str, Tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}

_PARAM_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class SpecError(ValueError):
    """工具声明阶段的静态错误 (启动即失败, 不拖到线上调用才炸)."""


@dataclass(frozen=True)
class Param:
    """单个入参声明.

    :param name: 参数名, 必须匹配 ``^[a-zA-Z_][a-zA-Z0-9_]{0,63}$``
        (Coze 参数名不支持中文/横线, 提前卡死避免上线后返工).
    :param type: JSON Schema 类型字符串.
    :param required: 是否必填.
    :param description: 给大模型看的语义描述 —— 这是 Agent 能否正确调用的关键,
        必须写明取值范围与单位, 而不是复述参数名.
    :param default: 默认值; 与 ``required=True`` 互斥.
    :param enum: 枚举白名单, 仅在 ``type == "string"`` 时生效.
    :param minimum / maximum: 数值区间 (含端点).
    :param min_length / max_length: 字符串长度区间.
    :param items_type: ``type == "array"`` 时元素类型.
    :param pattern: 字符串正则约束 (完整匹配由调用方 ``re.fullmatch`` 决定).
    :param example: 示例值; 仅用于 OpenAPI 导出 (Coze 调试面板/文档), 不参与运行时校验.
    """

    name: str
    type: str = "string"
    required: bool = False
    description: str = ""
    default: Any = None
    enum: Optional[Sequence[Any]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    items_type: Optional[str] = None
    pattern: Optional[str] = None
    example: Optional[Any] = None

    def __post_init__(self) -> None:
        if not _PARAM_NAME_RE.match(self.name):
            raise SpecError(f"非法参数名: {self.name!r} (需匹配 {_PARAM_NAME_RE.pattern})")
        if self.type not in JSON_TYPE_TO_PYTHON:
            raise SpecError(f"参数 {self.name}: 不支持的 type={self.type!r}")
        if self.required and self.default is not None:
            raise SpecError(f"参数 {self.name}: required=True 时不应提供 default")
        if self.enum is not None:
            if self.type != "string":
                raise SpecError(f"参数 {self.name}: enum 仅支持 string 类型")
            if not self.enum:
                raise SpecError(f"参数 {self.name}: enum 不能为空")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise SpecError(f"参数 {self.name}: minimum > maximum")
        if self.type == "array" and self.items_type is None:
            raise SpecError(f"参数 {self.name}: array 必须声明 items_type")
        if self.items_type is not None and self.items_type not in JSON_TYPE_TO_PYTHON:
            raise SpecError(f"参数 {self.name}: 不支持的 items_type={self.items_type!r}")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:  # pragma: no cover - 防御性
                raise SpecError(f"参数 {self.name}: pattern 非法: {exc}") from exc
        if self.example is not None:
            expected = JSON_TYPE_TO_PYTHON[self.type]
            if isinstance(self.example, bool) and self.type in ("integer", "number"):
                raise SpecError(f"参数 {self.name}: example 类型与 {self.type} 不符")
            if not isinstance(self.example, expected):
                raise SpecError(
                    f"参数 {self.name}: example 期望 {self.type}, 实际 {type(self.example).__name__}"
                )
            if self.type == "array":
                item_types = JSON_TYPE_TO_PYTHON[self.items_type]
                for idx, item in enumerate(self.example):
                    if not isinstance(item, item_types):
                        raise SpecError(
                            f"参数 {self.name}: example 第 {idx} 个元素期望 {self.items_type}"
                        )

    def coerce(self, raw: Any) -> Any:
        """把 LLM 常见「字符串化」入参收敛成声明类型.

        大模型调用插件时高频传出 ``"3"`` / ``"true"`` 这类字符串,
        在网关层统一纠偏, 避免每个工具重复 ``int(x or 1)``.
        收敛失败时原样返回, 交由 :func:`Param.validate` 报出可读错误.

        :returns: 收敛后的值; 无法收敛则返回原始值.
        """
        if raw is None:
            return None
        try:
            if self.type == "integer":
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, str):
                    return int(raw.strip())
                if isinstance(raw, float) and raw.is_integer():
                    return int(raw)
                return raw
            if self.type == "number":
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, str):
                    return float(raw.strip())
                return raw
            if self.type == "boolean":
                if isinstance(raw, str):
                    low = raw.strip().lower()
                    if low in ("true", "1", "yes", "y", "on"):
                        return True
                    if low in ("false", "0", "no", "n", "off"):
                        return False
                if isinstance(raw, int) and raw in (0, 1):
                    return bool(raw)
                return raw
            if self.type == "array":
                if isinstance(raw, str):
                    # 兼容 LLM 传入 "a,b,c" 的逗号分隔写法
                    return [p.strip() for p in raw.split(",") if p.strip()]
                return raw
        except (TypeError, ValueError):
            return raw
        return raw

    def validate(self, value: Any) -> Optional[str]:
        """校验已收敛的值; 合法返回 ``None``, 否则返回中文错误说明."""
        expected = JSON_TYPE_TO_PYTHON[self.type]
        if self.type == "boolean":
            if not isinstance(value, bool):
                return f"期望布尔值, 实际 {type(value).__name__}"
        elif self.type in ("integer", "number"):
            if isinstance(value, bool) or not isinstance(value, expected):
                return f"期望 {self.type}, 实际 {type(value).__name__}"
        elif not isinstance(value, expected):
            return f"期望 {self.type}, 实际 {type(value).__name__}"

        if self.enum is not None and value not in self.enum:
            return f"取值必须是 {list(self.enum)} 之一, 实际 {value!r}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                return f"取值不得小于 {self.minimum}, 实际 {value}"
            if self.maximum is not None and value > self.maximum:
                return f"取值不得大于 {self.maximum}, 实际 {value}"
        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                return f"长度不得小于 {self.min_length}, 实际 {len(value)}"
            if self.max_length is not None and len(value) > self.max_length:
                return f"长度不得大于 {self.max_length}, 实际 {len(value)}"
            if self.pattern is not None and not re.search(self.pattern, value):
                return f"格式不匹配 /{self.pattern}/, 实际 {value!r}"
        if isinstance(value, (list, tuple)) and self.items_type is not None:
            item_types = JSON_TYPE_TO_PYTHON[self.items_type]
            for idx, item in enumerate(value):
                if self.items_type == "boolean":
                    if not isinstance(item, bool):
                        return f"第 {idx} 个元素期望 boolean, 实际 {type(item).__name__}"
                elif not isinstance(item, item_types):
                    return f"第 {idx} 个元素期望 {self.items_type}, 实际 {type(item).__name__}"
        return None


@dataclass(frozen=True)
class ToolResult:
    """统一调用结果封装.

    ``data`` 必须可被 ``json.dumps(..., ensure_ascii=False)`` 序列化;
    ``error`` 非空即代表调用失败 (业务级失败, 非 HTTP 层异常).
    """

    ok: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ok and not self.error:
            raise SpecError("失败结果必须携带 error 说明")
        if not isinstance(self.data, dict):
            raise SpecError("data 必须是 dict")

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        """构造失败结果."""
        return cls(ok=False, data={}, error=error)

    @classmethod
    def success(cls, **data: Any) -> "ToolResult":
        """构造成功结果 (关键字参数即业务字段)."""
        return cls(ok=True, data=data)

    def model_dump(self) -> Dict[str, Any]:
        """序列化为纯 dict (JSON 安全)."""
        return {"ok": self.ok, "error": self.error, "data": dict(self.data)}


class ToolError(Exception):
    """工具执行期可预期的业务异常, 由 runner 统一转成 :class:`ToolResult.fail`."""


@dataclass(frozen=True)
class ToolSpec:
    """一个可被 Coze / MCP / CLI 共同调用的原子工具声明.

    约定: ``handler(**validated_params) -> ToolResult``,
    收到的参数已完成类型收敛与校验, 因此实现体内 **不再重复做类型判断**.
    """

    name: str
    title: str
    description: str
    params: Tuple[Param, ...] = ()
    category: str = "general"
    tags: Tuple[str, ...] = ()
    handler: Optional[Callable[..., ToolResult]] = None
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not _PARAM_NAME_RE.match(self.name):
            raise SpecError(f"非法工具名: {self.name!r}")
        if not self.description.strip():
            raise SpecError(f"工具 {self.name}: description 不能为空 (大模型靠它选工具)")
        seen = set()
        for p in self.params:
            if p.name in seen:
                raise SpecError(f"工具 {self.name}: 参数 {p.name} 重复声明")
            seen.add(p.name)
        if self.handler is None:
            raise SpecError(f"工具 {self.name}: handler 不能为空")
        if self.timeout_seconds <= 0:
            raise SpecError(f"工具 {self.name}: timeout_seconds 必须为正数")

    @property
    def required_params(self) -> Tuple[Param, ...]:
        """必填参数列表."""
        return tuple(p for p in self.params if p.required)

    def param(self, name: str) -> Optional[Param]:
        """按名取参数声明; 不存在返回 ``None``."""
        for p in self.params:
            if p.name == name:
                return p
        return None

    def coerce_and_validate(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """网关入口统一校验: 未知参数直接报错 (拒绝静默吞参数).

        :returns: ``(合法参数字典, 错误列表)``; 错误列表非空时参数字典不可信.
        """
        errors: List[str] = []
        for key in raw:
            if self.param(key) is None:
                errors.append(f"未知参数 {key!r}")
        cleaned: Dict[str, Any] = {}
        for p in self.params:
            if p.name not in raw or raw[p.name] is None:
                if p.required:
                    errors.append(f"缺少必填参数 {p.name!r}")
                continue
            value = p.coerce(raw[p.name])
            if value is None or (isinstance(value, str) and value == "" and p.type == "string"):
                if p.required:
                    errors.append(f"必填参数 {p.name!r} 不能为空")
                continue
            problem = p.validate(value)
            if problem:
                errors.append(f"参数 {p.name!r}: {problem}")
                continue
            cleaned[p.name] = value
        return cleaned, errors
