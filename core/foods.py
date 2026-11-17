# -*- coding: utf-8 -*-
"""食物库：加载内置营养库、模糊检索、份量换算。"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from . import nutrition as nu

# 常见「量词 -> 克」的兜底换算（当食物没有自定义份量时使用）
GENERIC_UNITS: dict[str, float] = {
    "克": 1, "g": 1, "grams": 1, "gram": 1, "公克": 1,
    "千克": 1000, "kg": 1000, "公斤": 1000,
    "两": 50, "斤": 500, "市斤": 500,
    "毫升": 1, "ml": 1, "毫升数": 1,  # 近似按水密度
    "碗": 200, "小碗": 130, "大碗": 300,
    "盘": 250, "份": 150, "个": 100, "只": 100, "块": 80,
    "杯": 250, "盒": 200, "包": 80, "袋": 60, "片": 30,
    "勺": 10, "小勺": 5, "大勺": 15, "把": 25,
    "根": 100, "条": 100, "张": 50, "串": 80, "颗": 12, "粒": 5,
}

_PUNCT = re.compile(r"[\s\u3000()（）\[\]【】,，.。、!！?？:：;；\-—_/]")
_CN_NUM = "一二两三四五六七八九十半"


def _amount_text(amount: float, label: str) -> str:
    """「1 碗」+ 自带的「一碗」不要拼成「1一小碗」。"""
    label = str(label).strip()
    if label.startswith("一") and len(label) > 1:
        rest = label[1:]
        if amount == 1:
            return label
        if float(amount).is_integer():
            return f"{int(amount)}{rest}"
        return f"{amount:g}{rest}"
    if amount == 1 and label.startswith(("两", "半")):
        return label
    if float(amount).is_integer():
        return f"{int(amount)}{label}"
    return f"{amount:g}{label}"


def normalize(text: str) -> str:
    """去掉空白与标点，统一全角括号，便于匹配。"""
    return _PUNCT.sub("", str(text or "").lower())


class FoodBook:
    """内置食物库 + 用户自定义食物的统一检索入口。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict[str, Any]] = []
        self.by_name: dict[str, dict[str, Any]] = {}
        self._norm_index: dict[str, dict[str, Any]] = {}
        self.load()

    # ---------------------------------------------------------------- #
    def load(self) -> None:
        self.items = []
        self.by_name = {}
        self._norm_index = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            foods = raw.get("foods", [])
        except (OSError, json.JSONDecodeError):
            foods = []
        for entry in foods:
            item = {
                "name": entry.get("name", ""),
                "cat": entry.get("cat", "其他"),
                "alias": list(entry.get("alias") or []),
                "nut": nu.as_vector(entry.get("nut")),
                "portions": [tuple(p) for p in (entry.get("portions") or [["100克", 100]])],
                "source": "内置",
            }
            if not item["name"]:
                continue
            self._register(item)

    def _register(self, item: dict[str, Any]) -> None:
        self.items.append(item)
        self.by_name[item["name"]] = item
        for key in {normalize(item["name"]), *[normalize(a) for a in item["alias"]]}:
            if key:
                self._norm_index.setdefault(key, item)

    # ---------------------------------------------------------------- #
    def count(self) -> int:
        return len(self.items)

    def find(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        if name in self.by_name:
            return self.by_name[name]
        return self._norm_index.get(normalize(name))

    def search(
        self,
        query: str,
        limit: int = 5,
        extra: Iterable[dict[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        """带评分的模糊检索，extra 为用户自定义食物（优先命中）。"""
        q = normalize(query)
        if not q:
            return []

        pool: list[dict[str, Any]] = list(extra) + self.items
        scored: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()

        for item in pool:
            score = self._score(q, item)
            if score <= 0:
                continue
            name = item["name"]
            if name in seen:
                continue
            seen.add(name)
            scored.append((score, item))

        scored.sort(key=lambda x: (-x[0], len(x[1]["name"])))
        return [item for _, item in scored[:limit]]

    def _score(self, q: str, item: dict[str, Any]) -> float:
        name = normalize(item["name"])
        if name == q:
            return 1000 - len(name) * 0.01
        aliases = [normalize(a) for a in item["alias"]]
        if q in aliases:
            return 950 - len(q) * 0.01
        if name.startswith(q):
            return 800 - len(name) * 0.1
        if any(a.startswith(q) for a in aliases):
            return 760 - len(name) * 0.1
        if q in name:
            return 700 - len(name) * 0.1
        if any(q in a for a in aliases):
            return 660 - len(name) * 0.1
        if name and name in q:
            return 600 - len(name) * 0.2
        for a in aliases:
            if a and a in q:
                return 560 - len(a) * 0.2
        # 字面相似度兜底（错别字 / 简写）
        ratio = difflib.SequenceMatcher(None, q, name).ratio()
        if ratio >= 0.62:
            return 500 * ratio
        for a in aliases:
            r = difflib.SequenceMatcher(None, q, a).ratio()
            if r >= 0.68:
                return 460 * r
        return 0.0

    # ---------------------------------------------------------------- #
    def resolve_grams(
        self,
        item: dict[str, Any],
        amount: float,
        unit: str | None = None,
    ) -> tuple[float, str]:
        """把「1 碗」「150 克」换算成克数，返回 (克数, 说明)。"""
        amount = float(amount or 0)
        if amount <= 0:
            raise ValueError("份量必须大于 0")

        unit_raw = (unit or "").strip()
        unit_norm = normalize(unit_raw)
        portions = item.get("portions") or []

        # 1) 纯重量
        if not unit_norm or unit_norm in {"克", "g", "公克"}:
            return amount, f"{amount:g}克"
        if unit_norm in {"千克", "kg", "公斤"}:
            return amount * 1000, f"{amount * 1000:g}克"

        # 2) 食物自带份量：先找完全一致的，再找「碗」→「一碗」这种量词包含的
        for label, grams in portions:
            lab = normalize(label)
            if not lab:
                continue
            if unit_norm == lab or unit_norm == lab.rstrip("克g"):
                return amount * float(grams), _amount_text(amount, label)

        candidates: list[tuple[int, str, float]] = []
        for label, grams in portions:
            lab = normalize(label)
            if not lab:
                continue
            if lab.endswith(unit_norm) and len(lab) - len(unit_norm) <= 2:
                candidates.append((len(lab), label, float(grams)))
            elif unit_norm.endswith(lab) and len(unit_norm) - len(lab) <= 2:
                candidates.append((len(lab), label, float(grams)))
        if candidates:
            # 越短的标签越接近用户说法（「碗」优先命中「一碗」而不是「一小碗」）
            candidates.sort(key=lambda c: (c[0], c[1]))
            _, label, grams = candidates[0]
            return amount * grams, _amount_text(amount, label)

        # 3) 通用量词
        for key, grams in GENERIC_UNITS.items():
            if unit_norm == normalize(key):
                return amount * grams, f"{amount:g}{key}"
        for key, grams in GENERIC_UNITS.items():
            if normalize(key) in unit_norm or unit_norm in normalize(key):
                return amount * grams, f"{amount:g}{key}"

        # 4) 实在不认识：按 100 克理解，并在说明里标注
        return amount * 100, f"{amount:g}{unit_raw or '份'}（按100克估）"

    def portion_hint(self, item: dict[str, Any]) -> str:
        parts = []
        for label, grams in (item.get("portions") or [])[:3]:
            parts.append(f"{label}≈{grams:g}g")
        return "、".join(parts) if parts else "按克计"

    # ---------------------------------------------------------------- #
    def entry_from_values(
        self,
        name: str,
        values: dict[str, float],
        *,
        cat: str = "其他",
        alias: list[str] | None = None,
        portions: list[list[Any]] | None = None,
        source: str = "自定义",
    ) -> dict[str, Any]:
        return {
            "name": name.strip(),
            "cat": cat,
            "alias": alias or [],
            "nut": nu.as_vector(values),
            "portions": [tuple(p) for p in (portions or [["100克", 100]])],
            "source": source,
        }


def merge_user_foods(book: FoodBook, foods: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """把用户自定义/预设食物转成与内置食物同构的结构。"""
    out: list[dict[str, Any]] = []
    for name, raw in (foods or {}).items():
        out.append(
            {
                "name": name,
                "cat": raw.get("cat") or "我的食物",
                "alias": list(raw.get("alias") or []),
                "nut": nu.as_vector(raw.get("nut")),
                "portions": [tuple(p) for p in (raw.get("portions") or [["100克", 100]])],
                "source": "自定义",
            }
        )
    return out
