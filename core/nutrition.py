# -*- coding: utf-8 -*-
"""营养素定义、参考摄入量与计算工具。

所有营养素统一用「每 100g 可食部」的 26 维向量表示，顺序与
``presets/foods.json`` 的 ``unit_order`` 完全一致，便于批量相加。
"""

from __future__ import annotations

from typing import Any, Iterable

# 26 维向量的键顺序（与 foods.json 的 unit_order 一致）
KEYS: tuple[str, ...] = (
    "kcal", "protein", "fat", "carb", "fiber",
    "sodium", "potassium", "calcium", "magnesium", "phosphorus",
    "iron", "zinc", "selenium",
    "va", "vd", "ve", "vk", "b1", "b2", "b3", "b6", "b12", "vc", "folate",
    "sfat", "chol",
)

INDEX: dict[str, int] = {k: i for i, k in enumerate(KEYS)}


class Nutrient:
    """一种营养素的元信息。"""

    __slots__ = ("key", "name", "unit", "group", "rda_m", "rda_f", "ul", "note")

    def __init__(
        self,
        key: str,
        name: str,
        unit: str,
        group: str,
        rda_m: float,
        rda_f: float | None = None,
        ul: float | None = None,
        note: str = "",
    ) -> None:
        self.key = key
        self.name = name
        self.unit = unit
        self.group = group
        self.rda_m = rda_m
        self.rda_f = rda_m if rda_f is None else rda_f
        self.ul = ul
        self.note = note

    def rda(self, sex: str) -> float:
        return self.rda_f if sex == "female" else self.rda_m


# 参考值取自《中国居民膳食营养素参考摄入量（2023 版）》与膳食指南的常用成人值
NUTRIENTS: dict[str, Nutrient] = {
    "kcal": Nutrient("kcal", "热量", "kcal", "能量", 2000),
    "protein": Nutrient("protein", "蛋白质", "g", "能量", 65, 55),
    "fat": Nutrient("fat", "脂肪", "g", "能量", 60, 50),
    "carb": Nutrient("carb", "碳水化合物", "g", "能量", 300, 250),
    "fiber": Nutrient("fiber", "膳食纤维", "g", "能量", 25, 25),
    "sodium": Nutrient("sodium", "钠", "mg", "矿物质", 1500, 1500, 2000, "上限相当于 5g 盐"),
    "potassium": Nutrient("potassium", "钾", "mg", "矿物质", 2000, 2000),
    "calcium": Nutrient("calcium", "钙", "mg", "矿物质", 800, 800, 2000),
    "magnesium": Nutrient("magnesium", "镁", "mg", "矿物质", 330, 330),
    "phosphorus": Nutrient("phosphorus", "磷", "mg", "矿物质", 720, 720, 3500),
    "iron": Nutrient("iron", "铁", "mg", "矿物质", 12, 18, 42),
    "zinc": Nutrient("zinc", "锌", "mg", "矿物质", 12, 8.5, 40),
    "selenium": Nutrient("selenium", "硒", "μg", "矿物质", 60, 60, 400),
    "va": Nutrient("va", "维生素A", "μgRAE", "维生素", 800, 700, 3000),
    "vd": Nutrient("vd", "维生素D", "μg", "维生素", 10, 10, 50),
    "ve": Nutrient("ve", "维生素E", "mg", "维生素", 14, 14, 700),
    "vk": Nutrient("vk", "维生素K", "μg", "维生素", 80, 80),
    "b1": Nutrient("b1", "维生素B1", "mg", "维生素", 1.4, 1.2),
    "b2": Nutrient("b2", "维生素B2", "mg", "维生素", 1.4, 1.2),
    "b3": Nutrient("b3", "烟酸", "mgNE", "维生素", 15, 12, 35),
    "b6": Nutrient("b6", "维生素B6", "mg", "维生素", 1.4, 1.4, 60),
    "b12": Nutrient("b12", "维生素B12", "μg", "维生素", 2.4, 2.4),
    "vc": Nutrient("vc", "维生素C", "mg", "维生素", 100, 100, 2000),
    "folate": Nutrient("folate", "叶酸", "μgDFE", "维生素", 400, 400, 1000),
    "sfat": Nutrient("sfat", "饱和脂肪", "g", "能量", 20, 20, 22),
    # 中国居民膳食指南 2023 不再设胆固醇硬上限，这里给一个宽松参考值，只做提示
    "chol": Nutrient("chol", "胆固醇", "mg", "能量", 300, 300, 500, "宽松参考值"),
}

# 只做「不超过」判定的营养素
UPPER_ONLY: frozenset[str] = frozenset({"sodium", "sfat", "chol"})

# 微量营养素（做摄入不足判定）
MICRO_KEYS: tuple[str, ...] = tuple(
    k for k in KEYS if k not in {"kcal", "protein", "fat", "carb", "sfat", "chol"}
)

# 精选展示顺序（报告与雷达图用）
RADAR_KEYS: tuple[str, ...] = (
    "protein", "fiber", "calcium", "iron", "zinc", "selenium",
    "va", "b1", "b2", "vc", "folate", "potassium",
)


def zeros() -> list[float]:
    """返回 26 维零向量。"""
    return [0.0] * len(KEYS)


def as_vector(values: dict[str, float] | Iterable[float] | None) -> list[float]:
    """把字典或序列归一化成 26 维向量。"""
    if values is None:
        return zeros()
    if isinstance(values, (list, tuple)):
        out = zeros()
        for i, v in enumerate(values[: len(KEYS)]):
            try:
                out[i] = float(v)
            except (TypeError, ValueError):
                out[i] = 0.0
        return out
    out = zeros()
    for key, val in values.items():
        idx = INDEX.get(key)
        if idx is None:
            continue
        try:
            out[idx] = float(val)
        except (TypeError, ValueError):
            out[idx] = 0.0
    return out


def add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def accumulate(a: list[float], b: list[float]) -> None:
    """原地累加，用于批量统计。"""
    for i in range(len(a)):
        a[i] += b[i]


def scale(a: list[float], factor: float) -> list[float]:
    return [x * factor for x in a]


def get(a: list[float], key: str) -> float:
    return a[INDEX[key]] if key in INDEX else 0.0


def to_dict(a: list[float]) -> dict[str, float]:
    """只输出非零值，减少落盘体积。"""
    return {k: round(a[i], 3) for i, k in enumerate(KEYS) if a[i]}


def energy_ratio(a: list[float]) -> dict[str, float]:
    """三大宏量营养素的供能比（%）。"""
    p = get(a, "protein") * 4
    f = get(a, "fat") * 9
    c = get(a, "carb") * 4
    total = p + f + c
    if total <= 0:
        return {"protein": 0.0, "fat": 0.0, "carb": 0.0}
    return {
        "protein": round(p / total * 100, 1),
        "fat": round(f / total * 100, 1),
        "carb": round(c / total * 100, 1),
    }


def fmt_num(value: float, unit: str = "") -> str:
    """按量级选择小数位，避免 0.7000000001 之类的输出。"""
    if value is None:
        return "—"
    if abs(value) >= 100:
        text = f"{value:.0f}"
    elif abs(value) >= 10:
        text = f"{value:.1f}"
    elif abs(value) >= 1:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return f"{text}{unit}" if unit else text


def bar(pct: float, width: int = 10) -> str:
    """文本进度条，pct 为 0~1+ 的比例。"""
    filled = max(0, min(width, int(round(pct * width))))
    return "▓" * filled + "░" * (width - filled)


def coverage_of(intake_kcal: float, target_kcal: float) -> float:
    """当日已记录比例，用于把参考值折算到「到现在为止」。"""
    if target_kcal <= 0:
        return 1.0
    return max(0.1, min(1.0, intake_kcal / target_kcal))


def pct_of(value: float, ref: float) -> float:
    if ref <= 0:
        return 0.0
    return value / ref * 100.0
