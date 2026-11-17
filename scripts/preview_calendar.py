# -*- coding: utf-8 -*-
"""生成本地日历预览 HTML（用于人工/截图检查模板效果）。"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import report as rp  # noqa: E402

TARGET = 1800


def build_data(year: int, month: int) -> dict:
    today = date(year, month, 17)
    start = date(year, month, 1)
    end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)

    random.seed(7)
    cells = []
    weights = []
    kg = 84.0
    cursor = start
    while cursor <= end:
        logged = cursor <= today and cursor.weekday() != 0 or (cursor <= today and random.random() > 0.4)
        kcal = random.choice([1680, 1750, 1810, 1920, 2050, 1620, 2380, 1790])
        count = random.randint(2, 5)
        if not logged:
            kcal, count = 0, 0
        status = "none"
        if count:
            pct = kcal / TARGET
            status = "low" if pct < 0.85 else "ok" if pct <= 1.05 else "high" if pct <= 1.2 else "over"
        weight = None
        if logged and cursor.day % 3 == 1 and cursor <= today:
            kg = round(kg - random.choice([0.2, 0.3, 0.1]), 1)
            weight = kg
            weights.append({"date": cursor.isoformat(), "kg": kg})
        cells.append(
            {
                "date": cursor.isoformat(),
                "day": cursor.day,
                "weekday": cursor.weekday(),
                "kcal": kcal,
                "count": count,
                "status": status,
                "weight": weight,
                "is_today": cursor == today,
                "future": cursor > today,
            }
        )
        cursor += timedelta(days=1)

    logged_days = sum(1 for c in cells if c["count"])
    avg = round(sum(c["kcal"] for c in cells if c["count"]) / logged_days) if logged_days else 0
    on_target = sum(1 for c in cells if c["count"] and abs(c["kcal"] - TARGET) <= TARGET * 0.1)
    return {
        "year": year,
        "month": month,
        "month_label": f"{year} 年 {month} 月",
        "cells": cells,
        "target_kcal": TARGET,
        "logged_days": logged_days,
        "avg_kcal": avg,
        "on_target_days": on_target,
        "weights": weights,
        "weight_delta": round(weights[-1]["kg"] - weights[0]["kg"], 1) if len(weights) >= 2 else None,
        "today": today.isoformat(),
        "user": {"name": "小明"},
        "targets": {"goal_label": "减脂"},
        "progress": {"pct": 42.0, "current": 82.6, "target": 72.0},
    }


def main() -> None:
    data = build_data(2026, 11)
    view = rp.calendar_view(data)
    template = jinja2.Template((ROOT / "templates" / "calendar.html").read_text(encoding="utf-8"))
    html = template.render(**view)
    out = ROOT / "_preview" / "calendar.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"已生成 {out}（{len(html)} 字符）")
    print(f"weeks={len(view['weeks'])} 格数={sum(len([c for c in w if c]) for w in view['weeks'])}")


if __name__ == "__main__":
    main()
