"""工具注册表: 工具实现的唯一挂载点.

注册表是「声明」与「调用」之间的接缝, 提供三件事:
1. 去重注册 —— 同名工具二次注册直接抛错, 防止上游覆盖线上工具;
2. 懒加载 —— ``discover()`` 用 ``importlib`` 扫描 ``coze_skills.tools.*``,
   约定模块级 ``TOOLS: Sequence[ToolSpec]`` 即可被自动发现;
3. 索引查询 —— 按分类/标签检索, 供 Agent 在工具数 >20 时做两级导航.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .spec import SpecError, ToolSpec

#: 默认工具包 —— 所有垂类工具实现放在 ``coze_skills/tools/`` 下
DEFAULT_TOOL_PACKAGE = "coze_skills.tools"


class ToolRegistry:
    """工具集合容器 (非单例, 允许测试各自持有独立实例)."""

    def __init__(self, namespace: str = "default") -> None:
        self.namespace = namespace
        self._tools: Dict[str, ToolSpec] = {}

    # ---- 注册 -----------------------------------------------------------
    def register(self, spec: ToolSpec) -> ToolSpec:
        """注册单个工具; 重名或替换已有工具时报错."""
        if spec.name in self._tools:
            raise SpecError(f"命名空间 {self.namespace!r} 已存在工具 {spec.name!r}, 拒绝覆盖")
        self._tools[spec.name] = spec
        return spec

    def register_all(self, specs: Iterable[ToolSpec]) -> "ToolRegistry":
        """批量注册, 返回 self 以支持链式调用."""
        for spec in specs:
            self.register(spec)
        return self

    def discover(self, package: str = DEFAULT_TOOL_PACKAGE, *, strict: bool = True) -> List[str]:
        """扫描包内所有子模块并注册其 ``TOOLS`` 常量.

        :param package: 待扫描包名.
        :param strict: ``True`` 时导入失败直接抛出 (开局暴露问题);
            ``False`` 时跳过坏模块, 用于灰度环境.
        :returns: 实际注册的模块全名列表.
        """
        loaded: List[str] = []
        try:
            root = importlib.import_module(package)
        except ImportError as exc:
            if strict:
                raise SpecError(f"工具包 {package!r} 不可导入: {exc}") from exc
            return loaded
        for info in pkgutil.iter_modules(root.__path__):
            if info.name.startswith("_"):
                continue
            module_name = f"{package}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                if strict:
                    raise SpecError(f"工具模块 {module_name!r} 导入失败: {exc}") from exc
                continue
            specs = getattr(module, "TOOLS", None)
            if not specs:
                continue
            self.register_all(specs)
            loaded.append(module_name)
        return loaded

    # ---- 查询 -----------------------------------------------------------
    def get(self, name: str) -> Optional[ToolSpec]:
        """按名取工具; 不存在返回 ``None``."""
        return self._tools.get(name)

    def require(self, name: str) -> ToolSpec:
        """按名取工具; 不存在抛 :class:`SpecError`."""
        spec = self._tools.get(name)
        if spec is None:
            raise SpecError(f"工具 {name!r} 未注册; 已注册: {sorted(self._tools)}")
        return spec

    def names(self) -> List[str]:
        """已注册工具名 (字典序, 保证 Schema 输出稳定可比对)."""
        return sorted(self._tools)

    def all(self) -> List[ToolSpec]:
        """全部工具声明 (按名排序, 便于 diff)."""
        return [self._tools[n] for n in self.names()]

    def by_category(self) -> Dict[str, List[ToolSpec]]:
        """按分类分组."""
        grouped: Dict[str, List[ToolSpec]] = {}
        for spec in self.all():
            grouped.setdefault(spec.category, []).append(spec)
        return grouped

    def search(self, keyword: str) -> List[ToolSpec]:
        """名称/描述/标签的朴素关键词检索 (供 Agent 二次筛选)."""
        kw = keyword.strip().lower()
        if not kw:
            return []
        hits: List[ToolSpec] = []
        for spec in self.all():
            haystack = " ".join((spec.name, spec.title, spec.description, *spec.tags)).lower()
            if kw in haystack:
                hits.append(spec)
        return hits

    def stats(self) -> Tuple[int, int]:
        """``(工具数, 参数总数)`` —— 用于输出规格自检报告."""
        return len(self._tools), sum(len(s.params) for s in self._tools.values())


def build_default_registry(*, strict: bool = True) -> ToolRegistry:
    """构建并自动发现全部垂类工具 (网关/CLI 的默认入口)."""
    registry = ToolRegistry()
    registry.discover(strict=strict)
    return registry
