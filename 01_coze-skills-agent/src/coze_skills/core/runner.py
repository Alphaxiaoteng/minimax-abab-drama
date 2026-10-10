"""工具调用统一执行层: 全项目唯一允许触碰 handler 的模块.

设计约束:
1. 超时、异常、日志三件事只在这一处实现, 工具实现体保持纯粹 (只做业务).
2. ``invoke`` **永不抛异常** —— 任何路径都收敛为 :class:`ToolResult`,
   让网关/CLI/Agent 调用方只需判断 ``ok`` 字段, 不必写 try/except.
3. 硬超时用单工作线程 ``ThreadPoolExecutor`` 实现, 不使用 ``signal`` ——
   插件网关可能跑在非主线程, signal 定时器只在主线程可用.
4. 调用日志只记录参数名与耗时, **绝不记录参数值** (用户文本/密钥可能流经参数).
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .registry import ToolRegistry
from .spec import ToolError, ToolResult

#: 工具未声明有效超时时的兜底超时 (秒)
DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class CallRecord:
    """单次工具调用的审计记录 (只含元信息, 不含任何参数值).

    :param tool: 工具名.
    :param ok: 调用是否成功.
    :param latency_ms: 端到端耗时 (毫秒, 已保留 2 位小数).
    :param error: 失败原因; 成功时为 ``None``.
    :param params_keys: 本次调用实际传入的参数名 (排序后), 供排查「传了哪些字段」.
    """

    tool: str
    ok: bool
    latency_ms: float
    error: Optional[str] = None
    params_keys: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转为 JSON 安全的纯 dict (元组展开为列表).

        :returns: 可直接 ``json.dumps`` 的记录字典.
        """
        return {
            "tool": self.tool,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "params_keys": list(self.params_keys),
        }


class CallLog:
    """进程内定长环形调用日志: 满容量后丢弃最旧记录.

    仅用于观测 (``describe``/运维面板), 不落盘、不含参数值, 因此可安全放进
    任何进程的常驻内存结构; 非线程安全保证只依赖单写者场景下的原子追加.
    """

    def __init__(self, capacity: int = 200) -> None:
        """初始化环形日志.

        :param capacity: 最多保留的记录条数, 必须为正整数.
        :raises ValueError: ``capacity <= 0`` 时抛出.
        """
        if capacity <= 0:
            raise ValueError(f"capacity 必须为正整数, 实际 {capacity}")
        self._capacity = capacity
        self._records: deque = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        """日志容量."""
        return self._capacity

    def append(self, record: CallRecord) -> None:
        """追加一条记录; 超出容量时自动丢弃最旧记录.

        :param record: 待追加的调用记录.
        """
        self._records.append(record)

    def records(self) -> List[CallRecord]:
        """按时间正序返回当前保留的全部记录.

        :returns: 记录列表副本, 外部修改不影响内部状态.
        """
        return list(self._records)

    def summary(self) -> Dict[str, Any]:
        """聚合统计, 供 ``ToolRunner.describe`` 与运维端点消费.

        :returns: 含 ``total`` / ``ok`` / ``failed`` / ``success_rate`` (4 位小数,
            空日志为 0.0) / ``avg_latency_ms`` (2 位小数, 空日志为 0.0) /
            ``by_tool`` (每个工具 ``{calls, failed, avg_latency_ms}``) /
            ``recent_errors`` (最近 5 条失败, 每条 ``{tool, error}``).
        """
        recs = list(self._records)
        total = len(recs)
        ok_count = sum(1 for r in recs if r.ok)
        failed = total - ok_count
        success_rate = round(ok_count / total, 4) if total else 0.0
        avg_latency_ms = round(sum(r.latency_ms for r in recs) / total, 2) if total else 0.0
        by_tool: Dict[str, Dict[str, Any]] = {}
        for r in recs:
            bucket = by_tool.setdefault(r.tool, {"calls": 0, "failed": 0, "_latency_sum": 0.0})
            bucket["calls"] += 1
            if not r.ok:
                bucket["failed"] += 1
            bucket["_latency_sum"] += r.latency_ms
        for bucket in by_tool.values():
            bucket["avg_latency_ms"] = round(bucket.pop("_latency_sum") / bucket["calls"], 2)
        recent_errors = [
            {"tool": r.tool, "error": r.error} for r in recs if not r.ok
        ][-5:]
        return {
            "total": total,
            "ok": ok_count,
            "failed": failed,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency_ms,
            "by_tool": by_tool,
            "recent_errors": recent_errors,
        }

    def clear(self) -> None:
        """清空全部记录 (容量不变)."""
        self._records.clear()


class ToolRunner:
    """工具执行器: 校验 -> 超时执行 -> 异常收敛 -> 记账, 永不抛异常."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        log: Optional[CallLog] = None,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """构建执行器.

        :param registry: 已注册好工具的注册表.
        :param log: 复用已有调用日志; 缺省时新建容量 200 的 :class:`CallLog`.
        :param default_timeout: 工具未声明有效超时时使用的兜底超时 (秒).
        """
        self._registry = registry
        self._log = log if log is not None else CallLog()
        self._default_timeout = default_timeout

    @property
    def log(self) -> CallLog:
        """本次执行器使用的调用日志."""
        return self._log

    @property
    def registry(self) -> ToolRegistry:
        """本次执行器挂载的注册表."""
        return self._registry

    def invoke(self, name: str, raw_params: Optional[Dict[str, Any]] = None) -> ToolResult:
        """执行一次工具调用; 任何失败都收敛为失败的 :class:`ToolResult`.

        流程: 查注册表 -> 参数收敛与校验 -> 线程池硬超时执行 handler ->
        按异常类型转成对应错误文案; 成功/失败 (含校验失败) 均记入调用日志.

        :param name: 工具名.
        :param raw_params: 原始入参字典 (通常来自 LLM/HTTP), 允许为 ``None``.
        :returns: 永远返回 :class:`ToolResult`, 不抛异常.
        """
        params: Dict[str, Any] = dict(raw_params or {})
        timeout = self._default_timeout
        started = time.perf_counter()

        def finish(result: ToolResult, params_keys: Tuple[str, ...] = ()) -> ToolResult:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            self._log.append(
                CallRecord(
                    tool=name,
                    ok=result.ok,
                    latency_ms=latency_ms,
                    error=result.error,
                    params_keys=params_keys,
                )
            )
            return result

        spec = self._registry.get(name)
        if spec is None:
            return finish(ToolResult.fail(f"工具 {name!r} 未注册"))
        if spec.timeout_seconds > 0:
            timeout = spec.timeout_seconds

        cleaned, errors = spec.coerce_and_validate(params)
        if errors:
            return finish(ToolResult.fail("参数校验失败: " + "; ".join(errors)))

        keys = tuple(sorted(cleaned))
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(spec.handler, **cleaned)
            try:
                outcome = future.result(timeout=timeout)
            except FuturesTimeoutError:
                # cancel 对已开始运行的任务无效, 但保证排队中的后续任务不再执行;
                # wait=False 避免超时路径阻塞等待跑不完的工作线程.
                future.cancel()
                return finish(ToolResult.fail(f"工具 {name!r} 执行超时 ({timeout:g}s)"), keys)
            except ToolError as exc:
                return finish(ToolResult.fail(str(exc)), keys)
            except Exception as exc:
                return finish(
                    ToolResult.fail(f"工具 {name!r} 内部错误: {type(exc).__name__}: {exc}"),
                    keys,
                )
        finally:
            executor.shutdown(wait=False)

        if not isinstance(outcome, ToolResult):
            return finish(
                ToolResult.fail(
                    f"工具 {name!r} 实现错误: handler 必须返回 ToolResult, "
                    f"实际返回 {type(outcome).__name__}"
                ),
                keys,
            )
        return finish(outcome, keys)

    def invoke_many(self, calls: Sequence[Tuple[str, Dict[str, Any]]]) -> List[ToolResult]:
        """顺序执行多次调用; 不做并发, 避免瞬时打爆下游接口配额.

        :param calls: ``(工具名, 入参)`` 序列.
        :returns: 与输入等长、顺序一致的结果列表 (逐个复用 :meth:`invoke`).
        """
        return [self.invoke(name, raw) for name, raw in calls]

    def describe(self) -> Dict[str, Any]:
        """输出执行器快照: 已注册工具名、数量与调用日志统计.

        :returns: ``{"tools": [...], "count": n, "log": {...}}`` 纯 dict.
        """
        return {
            "tools": self._registry.names(),
            "count": len(self._registry.names()),
            "log": self._log.summary(),
        }