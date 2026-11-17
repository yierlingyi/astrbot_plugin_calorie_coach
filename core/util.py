# -*- coding: utf-8 -*-
"""通用小工具：日期解析、餐次归一化、文本渲染。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MEALS: tuple[str, ...] = ("早餐", "午餐", "晚餐", "加餐")
MEAL_ALIASES: dict[str, str] = {
    "早餐": "早餐", "早饭": "早餐", "早点": "早餐", "早上": "早餐", "breakfast": "早餐",
    "午餐": "午餐", "午饭": "午餐", "中饭": "午餐", "中午": "午餐", "lunch": "午餐",
    "晚餐": "晚餐", "晚饭": "晚餐", "晚上": "晚餐", "dinner": "晚餐",
    "加餐": "加餐", "零食": "加餐", "夜宵": "加餐", "宵夜": "加餐", "下午茶": "加餐",
    "snack": "加餐", "其他": "加餐",
}
MEAL_TIME: dict[str, str] = {"早餐": "08:00", "午餐": "12:00", "晚餐": "18:30", "加餐": "15:30"}
MEAL_ICON: dict[str, str] = {"早餐": "🌅", "午餐": "☀️", "晚餐": "🌙", "加餐": "🍪"}


def normalize_meal(text: str | None, default: str = "加餐") -> str:
    """把用户/模型传来的餐次说法归一化。"""
    if not text:
        return default
    key = str(text).strip().lower()
    if key in MEAL_ALIASES:
        return MEAL_ALIASES[key]
    for alias, meal in MEAL_ALIASES.items():
        if alias in key:
            return meal
    for meal in MEALS:
        if meal in key:
            return meal
    return default


def guess_meal_by_hour(hour: int) -> str:
    if 5 <= hour < 10:
        return "早餐"
    if 10 <= hour < 14:
        return "午餐"
    if 17 <= hour < 21:
        return "晚餐"
    return "加餐"


def parse_date(text: str | None, today: date | None = None) -> date:
    """解析「今天/昨天/前天/11-16/11月16日/2026-11-16/三天前」等说法。"""
    today = today or date.today()
    if not text:
        return today
    raw = str(text).strip()
    if not raw:
        return today

    table = {
        "今天": 0, "今日": 0, "today": 0,
        "昨天": 1, "昨日": 1, "yesterday": 1,
        "前天": 2, "前日": 2,
        "大前天": 3,
    }
    for word, delta in table.items():
        if raw == word or raw.startswith(word):
            return today - timedelta(days=delta)

    m = re.fullmatch(r"(\d{1,2})\s*天前", raw)
    if m:
        return today - timedelta(days=int(m.group(1)))

    m = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return today

    m = re.fullmatch(r"(\d{1,2})[-/.月](\d{1,2})日?", raw)
    if m:
        try:
            cand = date(today.year, int(m.group(1)), int(m.group(2)))
            # 明显在未来的月份，视为去年
            if cand > today + timedelta(days=30):
                cand = cand.replace(year=today.year - 1)
            return cand
        except ValueError:
            return today

    return today


def parse_time(text: str | None, fallback: str = "12:00") -> str:
    """把「12:30」「中午12点半」之类粗解析成 HH:MM。"""
    if not text:
        return fallback
    m = re.search(r"(\d{1,2})\s*[:：时点]\s*(\d{1,2})?", str(text))
    if not m:
        return fallback
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return fallback


def human_date(d: date, today: date | None = None) -> str:
    """返回「今天/昨天/11-16 周日」这种人类友好的日期。"""
    today = today or date.today()
    delta = (today - d).days
    week = "一二三四五六日"[d.weekday()]
    if delta == 0:
        return f"今天（{d.month}月{d.day}日 周{week}）"
    if delta == 1:
        return f"昨天（{d.month}月{d.day}日 周{week}）"
    if delta == 2:
        return f"前天（{d.month}月{d.day}日 周{week}）"
    if 0 < delta < 7:
        return f"{d.month}月{d.day}日 周{week}（{delta}天前）"
    return f"{d.month}月{d.day}日 周{week}"


def short_date(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def week_range(d: date) -> tuple[date, date]:
    """返回 d 所在周的周一与周日。"""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def now_str(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default


def truncate(text: str, limit: int = 60) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
