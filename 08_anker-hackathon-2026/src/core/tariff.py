"""分时电价 (TOU) 域模型。

TariffTier/TariffPlan 数据结构、跨零点时段解析、内置 8 城市 2025-2026
阶梯分时电价表(来源:发改委/电网公开价目表,一档居民口径),
以及 JSON 读写。价格单位: 元/kWh, 含税, 不含政府性基金及附加。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple

# 尖峰/峰/平/谷/深谷 五档语义名 (用于 tier_order 同价并列排序)
TIER_NAMES = ("deep_valley", "valley", "flat", "peak", "sharp_peak")


@dataclass(frozen=True)
class TariffTier:
    name: str            # "sharp_peak" | "peak" | "flat" | "valley" | "deep_valley"
    start_hour: float    # 含,0-24,支持 22.5 表示 22:30
    end_hour: float      # 不含;可 >24 表示跨零点(如 22.0 -> 30.0)
    price: float         # 元/kWh


@dataclass(frozen=True)
class TariffPlan:
    city: str
    currency: str                     # "CNY"
    tiers: Tuple[TariffTier, ...]
    export_price: float               # 上网电价 元/kWh
    tier_order: Tuple[str, ...]       # 由便宜到贵,用于策略比较

    @staticmethod
    def _contains(start: float, end: float, h: float) -> bool:
        if end > 24.0:
            return h >= start or h < (end - 24.0)
        return start <= h < end

    def _tier_for(self, hour: float) -> TariffTier:
        h = hour % 24.0
        for t in self.tiers:
            if self._contains(t.start_hour, t.end_hour, h):
                return t
        raise ValueError(
            "hour %.3f 未被任何电价时段覆盖 (city=%s)" % (hour, self.city)
        )

    def price_at(self, hour: float) -> float:
        return self._tier_for(hour).price

    def tier_at(self, hour: float) -> str:
        return self._tier_for(hour).name

    def daily_curve(self, step_hours: float = 0.25) -> List[Tuple[float, float, str]]:
        out: List[Tuple[float, float, str]] = []
        n = int(round(24.0 / step_hours))
        for i in range(n):
            hh = i * step_hours
            out.append((round(hh, 4), self.price_at(hh), self.tier_at(hh)))
        return out

    def spread(self) -> float:
        prices = [t.price for t in self.tiers]
        return max(prices) - min(prices)

    def windows(self, tier: str) -> List[Tuple[float, float]]:
        return [(t.start_hour, t.end_hour) for t in self.tiers if t.name == tier]

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "currency": self.currency,
            "export_price": self.export_price,
            "tier_order": list(self.tier_order),
            "tiers": [
                {"name": t.name, "start_hour": t.start_hour,
                 "end_hour": t.end_hour, "price": t.price}
                for t in self.tiers
            ],
        }


def _make_plan(city: str, export_price: float,
               raw: List[Tuple[str, float, float, float]]) -> TariffPlan:
    """raw: [(name, start, end, price)]. tier_order = cheapest->most expensive."""
    tiers = tuple(TariffTier(n, s, e, p) for (n, s, e, p) in raw)
    cheapest: Dict[str, float] = {}
    for t in tiers:
        if t.name not in cheapest or t.price < cheapest[t.name]:
            cheapest[t.name] = t.price
    order = sorted(
        cheapest.keys(),
        key=lambda k: (cheapest[k], TIER_NAMES.index(k) if k in TIER_NAMES else 99),
    )
    return TariffPlan(city, "CNY", tiers, export_price, tuple(order))


# 上网电价统一取江苏存量机制电价(煤电基准) 0.391 元/kWh
# 来源: 发改委燃煤发电上网基准, 适用于所有城市的余电上网。
_EXPORT_PRICE = 0.391


def builtin_tariffs() -> Dict[str, TariffPlan]:
    """返回 8 个真实中国城市的分时电价表 (2025-2026 一档居民口径)。

    来源: 各省市发改委/电网公开价目表, 部分为推算 [ESTIMATE], 逐城市注释。
    深圳 spread = 0.8635 元/kWh 是全项目最核心的套利空间。
    北京居民无峰谷分时(仅阶梯平段), 作为对照城市: 优化器应报告接近 0 的节省。

    上海/山东/浙江/江苏的居民分时仅 2 档(峰谷), 无第三档官方定义;
    如实保留 2-tier, 不人为拆造 flat。
    """
    plans: Dict[str, TariffPlan] = {}

    # --- shenzhen (深圳/广东) 一档 ---
    # SOURCE: 深圳市居民生活电价价目表
    # https://fgw.sz.gov.cn/attachment/1/1460/1460239/11394935.pdf
    # valley 00-08=0.2486, flat 08-10/12-14/19-24=0.6542, peak 10-12/14-19=1.1121
    # 居民无尖峰(尖峰仅工商业 Jul-Sep), spread=0.8635
    plans["shenzhen"] = _make_plan("shenzhen", _EXPORT_PRICE, [
        ("valley", 0.0, 8.0, 0.2486),
        ("flat", 8.0, 10.0, 0.6542),
        ("peak", 10.0, 12.0, 1.1121),
        ("flat", 12.0, 14.0, 0.6542),
        ("peak", 14.0, 19.0, 1.1121),
        ("flat", 19.0, 24.0, 0.6542),
    ])

    # --- shanghai 一档 ---
    # SOURCE: 上海市发改委 https://scjgj.sh.gov.cn/1072/20210303/...
    # 仅 2 档: valley 22-06 = 0.307, peak 06-22 = 0.617
    plans["shanghai"] = _make_plan("shanghai", _EXPORT_PRICE, [
        ("valley", 22.0, 30.0, 0.307),  # 跨零点 22:00-06:00
        ("peak", 6.0, 22.0, 0.617),
    ])

    # --- shandong (山东) 一档, 非采暖季默认 ---
    # SOURCE: 烟台市发改委(转发) https://fgw.yantai.gov.cn/art/2025/4/21/art_52219_2909514.html
    # valley 22-08 = 0.3769, peak 08-22 = 0.5769
    plans["shandong"] = _make_plan("shandong", _EXPORT_PRICE, [
        ("valley", 22.0, 32.0, 0.3769),  # 跨零点 22:00-08:00 (end_hour=32 → 22-24 + 0-8)
        ("peak", 8.0, 22.0, 0.5769),
    ])

    # --- zhejiang 一档 ---
    # SOURCE: 浙价资[2012]169号 (link: research/tou-tariff-cn.md §2.4)
    # valley 22-08 = 0.288, peak 08-22 = 0.568
    plans["zhejiang"] = _make_plan("zhejiang", _EXPORT_PRICE, [
        ("valley", 22.0, 32.0, 0.288),  # 跨零点 22:00-08:00
        ("peak", 8.0, 22.0, 0.568),
    ])

    # --- jiangsu 一档 ---
    # SOURCE: 国网南通 居民电价提示, 苏州销售电价表
    # 峰谷: peak 08-21 = 0.6783 [ESTIMATE: 一档基础+0.15],
    #       valley 21-08 = 0.3583 [ESTIMATE: 一档基础-0.17]
    # 一档基础 flat = 0.5283 (不满1千伏); 仅用于 flat 子区间 21-08/08-21 无重叠。
    # 因居民峰段覆盖 08-21 全部, 谷段 21-08, 无官方中间 flat → 如实 2-tier。
    plans["jiangsu"] = _make_plan("jiangsu", _EXPORT_PRICE, [
        ("valley", 21.0, 32.0, 0.3583),  # 跨零点 21:00-08:00
        ("peak", 8.0, 21.0, 0.6783),
    ])

    # --- beijing 居民 (对照城市) ---
    # SOURCE: 北京市居民阶梯电价表
    # https://fgw.beijing.gov.cn/bmcx/djcx/jzldj/202110/t20211025_2520169.htm
    # 北京居民无峰谷分时(仅阶梯平段 一档 0.4883 不满1千伏).
    # 作为控制组: 优化器在此城市应报告接近 0 的节省。spread = 0.0。
    plans["beijing"] = _make_plan("beijing", _EXPORT_PRICE, [
        ("flat", 0.0, 24.0, 0.4883),
    ])

    # --- sichuan 一档 ---
    # SOURCE: 川发改价格〔2025〕185号, 一档 flat 0.5224
    # valley 23:00-07:00 (官方时段, 价格 推算 flat-0.12 [ESTIMATE])
    # peak = flat + 0.12 = 0.6424 [ESTIMATE]
    plans["sichuan"] = _make_plan("sichuan", _EXPORT_PRICE, [
        ("valley", 23.0, 31.0, 0.4024),  # 跨零点 23:00-07:00
        ("flat", 7.0, 12.0, 0.5224),
        ("peak", 12.0, 14.0, 0.6424),  # 午间峰 [ESTIMATE]
        ("flat", 14.0, 23.0, 0.5224),
    ])

    # --- hunan 一档 ---
    # SOURCE: 湘发改价调规〔2024〕14号, 一档 flat 0.588
    # 居民 TOU yuan unconfirmed; peak = 0.688, valley = 0.418 [ESTIMATE]
    # windows: valley 23-07, peak 10-12/18-22, flat otherwise [ESTIMATE]
    plans["hunan"] = _make_plan("hunan", _EXPORT_PRICE, [
        ("valley", 23.0, 31.0, 0.418),  # 跨零点 23:00-07:00 [ESTIMATE]
        ("flat", 7.0, 10.0, 0.588),
        ("peak", 10.0, 12.0, 0.688),  # [ESTIMATE]
        ("flat", 12.0, 18.0, 0.588),
        ("peak", 18.0, 22.0, 0.688),  # [ESTIMATE]
        ("flat", 22.0, 23.0, 0.588),
    ])

    return plans


def _tiers_from_raw(raw, city: str) -> Tuple[TariffTier, ...]:
    if not isinstance(raw, list) or len(raw) == 0:
        raise ValueError("tariff for city=%r must contain a non-empty 'tiers' list" % city)
    tiers: List[TariffTier] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("tier #%d for city=%r is not an object" % (i, city))
        for key in ("name", "start_hour", "end_hour", "price"):
            if key not in item:
                raise ValueError("tier #%d for city=%r missing field %r" % (i, city, key))
        try:
            t = TariffTier(
                name=str(item["name"]),
                start_hour=float(item["start_hour"]),
                end_hour=float(item["end_hour"]),
                price=float(item["price"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("tier #%d for city=%r has a non-numeric field: %s" % (i, city, exc))
        if t.end_hour <= t.start_hour:
            raise ValueError(
                "tier #%d (%s) for city=%r: end_hour (%.3f) must exceed start_hour (%.3f)"
                % (i, t.name, city, t.end_hour, t.start_hour)
            )
        if t.price < 0:
            raise ValueError("tier #%d for city=%r has negative price" % (i, city))
        tiers.append(t)
    return tuple(tiers)


def load_tariff(path: str) -> TariffPlan:
    """读取与 TariffPlan.to_dict() 同形的 JSON。畸形输入抛 ValueError。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise ValueError("tariff file not found: %s" % path)
    except json.JSONDecodeError as exc:
        raise ValueError("tariff file %s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ValueError("tariff JSON at %s must be an object" % path)
    for key in ("city", "tiers", "export_price"):
        if key not in data:
            raise ValueError("tariff JSON at %s missing required field %r" % (path, key))
    city = str(data["city"])
    tiers = _tiers_from_raw(data["tiers"], city)
    try:
        export_price = float(data["export_price"])
    except (TypeError, ValueError):
        raise ValueError("tariff export_price for city=%r must be numeric" % city)
    currency = str(data.get("currency", "CNY"))
    cheapest: Dict[str, float] = {}
    for t in tiers:
        if t.name not in cheapest or t.price < cheapest[t.name]:
            cheapest[t.name] = t.price
    order = sorted(
        cheapest.keys(),
        key=lambda k: (cheapest[k], TIER_NAMES.index(k) if k in TIER_NAMES else 99),
    )
    return TariffPlan(city=city, currency=currency, tiers=tiers,
                      export_price=export_price, tier_order=tuple(order))


def save_tariff(plan: TariffPlan, path: str) -> None:
    """将 TariffPlan 序列化为 JSON。"""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan.to_dict(), fh, ensure_ascii=False, indent=2)