from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


class CheckpointStore:
    """步骤级断点：流程中断（设备掉线/脚本崩溃）后可从最后一个成功步骤续跑。"""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, flow_id: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in flow_id)
        return os.path.join(self.base_dir, safe + ".json")

    def save(self, flow_id: str, next_step: int, ctx: Dict[str, Any]) -> None:
        tmp = self._path(flow_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"flow_id": flow_id, "next_step": next_step, "ctx": ctx},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path(flow_id))

    def load(self, flow_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(flow_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def clear(self, flow_id: str) -> None:
        path = self._path(flow_id)
        if os.path.exists(path):
            os.remove(path)
