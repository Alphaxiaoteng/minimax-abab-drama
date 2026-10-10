"""时序总线 (TelemetryBus):环形缓冲 + CSV 落盘 + 运行统计。

纯标准库。能量按相邻读数的 ts 差 (小时) 积分,兼容 1h 与 15min 混合步进。
"""
from __future__ import annotations

import csv
from collections import deque
from typing import Dict, List, Optional

from edge.plant import SiteReading


class TelemetryBus:
    """内存环形时序缓冲;recent(n) 返回 oldest→newest 行列表。"""

    FIELDS = ("ts", "hour", "soc", "pv_kw", "load_kw", "battery_kw",
              "grid_kw", "price", "tier", "temp_c")

    def __init__(self, keep: int = 5000) -> None:
        self._buf: deque = deque(maxlen=max(1, int(keep)))

    def push(self, r: SiteReading) -> None:
        self._buf.append(r)

    def __len__(self) -> int:
        return len(self._buf)

    def recent(self, n: int = 200) -> List[Dict[str, object]]:
        n = max(0, min(int(n), len(self._buf)))
        rows: List[Dict[str, object]] = []
        for r in list(self._buf)[-n:]:
            rows.append(r.to_row())
        return rows

    def to_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(list(self.FIELDS))
            for r in self._buf:
                row = r.to_row()
                w.writerow([row[k] for k in self.FIELDS])

    def stats(self) -> Dict[str, object]:
        count = len(self._buf)
        if count == 0:
            return {"count": 0, "soc_last": 0.0, "soc_min": 0.0, "soc_max": 0.0,
                    "cost_total": 0.0, "pv_kwh": 0.0,
                    "grid_import_kwh": 0.0, "grid_export_kwh": 0.0}
        rows = [r.to_row() for r in self._buf]
        socs = [float(x["soc"]) for x in rows]
        pv_kwh = 0.0
        imp = 0.0
        exp = 0.0
        cost = 0.0
        prev_ts: Optional[float] = None
        for x in rows:
            ts = float(x["ts"])
            dt = (ts - prev_ts) if prev_ts is not None and ts > prev_ts else 0.0
            prev_ts = ts
            pv_kwh += float(x["pv_kw"]) * dt
            grid = float(x["grid_kw"])
            if grid >= 0.0:
                imp += grid * dt
            else:
                exp += -grid * dt
            cost += grid * float(x["price"]) * dt
        return {"count": count, "soc_last": socs[-1], "soc_min": min(socs),
                "soc_max": max(socs), "cost_total": cost, "pv_kwh": pv_kwh,
                "grid_import_kwh": imp, "grid_export_kwh": exp}