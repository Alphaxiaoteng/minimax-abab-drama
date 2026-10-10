"""状态持久化 (StateStore):JSON 文件 + 原子写。

save 走 tmp 文件 + os.replace,进程崩溃不留半截文件;
load 在文件缺失/损坏时返回 default,永不抛异常。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional


class StateStore:
    """键值型 JSON 状态存储,单文件,线程内加锁。"""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()

    def _read_all(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, key: str, value: object) -> None:
        with self._lock:
            data = self._read_all()
            data[str(key)] = value
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = "%s.%d.tmp" % (self.path, os.getpid())
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, sort_keys=True)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    def load(self, key: str, default: Optional[object] = None) -> object:
        with self._lock:
            data = self._read_all()
            return data.get(str(key), default)