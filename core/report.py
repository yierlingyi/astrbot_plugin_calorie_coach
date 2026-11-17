# -*- coding: utf-8 -*-
"""文本报告渲染：日卡、营养详情、日历、周报。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import body as bd
from . import nutrition as nu
from .analysis import ALERT_KEYS, STATUS_ICON, STATUS_TEXT, analyze, suggest_meal, summarize_period
from .util import MEAL_ICON, MEALS, human_date, month_range, short_date

LINE = "─" * 22


def kcal_header(analysis: dict[str, Any]) -> str:
    target = analysis.get("target_kcal") or 0
    intake = analysis.get("kcal_in") or 0
    pct = analysis.get("kcal_pct") or 0
    if not target:
        return f"🔥 已记录 {intake:.0f} kcal"
    protein = analysis["item_map"].get("protein")
    tail = ""
    if protein:
        tail = (
            f"\n   剩余 {analysis.get('remaining_kcal', 0):.0f} kcal · "
            f"蛋白 {protein['value']:.0f}/{protein.get('ref_full', protein['ref']):.0f}g"
        )
    return f"🔥 {intake:.0f} / {target:.0f} kcal  {nu.bar(pct / 100)} {pct:.0f}%{tail}"


def brief(analysis: dict[str, Any]) -> str:
    """一句话摘要，供工具返回与提醒使用。"""
    parts = []
    target = analysis.get("target_kcal") or 0
    if target:
        parts.append(
            f"热量 {analysis['kcal_in']:.0f}/{target:.0f} kcal（{analysis['kcal_pct']:.0f}%）"
        )
    else:
        parts.append(f"热量 {analysis['kcal_in']:.0f} kcal")
    protein = analysis["item_map"].get("protein")
    if protein:
        parts.append(
            f"蛋白 {protein['value']:.0f}/{protein.get('ref_full', protein['ref']):.0f}g"
        )
    if analysis["gaps"]:
        names = "、".join(f"{g['name']}{g['pct']:.0f}%" for g in analysis["gaps"][:3])
        parts.append(f"缺口 {names}")
    if analysis["excess"]:
        names = "、".join(f"{g['name']}{g['pct']:.0f}%" for g in analysis["excess"][:2])
        parts.append(f"超标 {names}")
    return "；".join(parts)


def day_card(analysis: dict[str, Any], targets: dict[str, Any], day_str: str) -> str:
    """完整日卡（用于 /热量 指令与报告）。"""
    lines: list[str] = []
    d = date.fromisoformat(day_str) if day_str else date.today()
    lines.append(f"📅 {human_date(d)}")
    lines.append(kcal_header(analysis))

    entries = analysis["entries"]
    if entries:
        lines.append("")
        for meal in MEALS:
            meal_entries = [e for e in entries if (e.get("meal") or "加餐") == meal]
            if not meal_entries:
                continue
            kcal = analysis["per_meal"][meal]["kcal"]
            share = analysis["meal_shares"].get(meal, 0)
            lines.append(f"{MEAL_ICON[meal]} {meal} · {kcal:.0f} kcal（{share:.0f}%）")
            for e in meal_entries:
                nut = nu.as_vector(e.get("nut"))
                lines.append(
                    f"   {e.get('amount_text') or str(e.get('grams', '')) + 'g'} "
                    f"{e.get('name')} · {nu.get(nut, 'kcal'):.0f} kcal"
                    f"（蛋白 {nu.get(nut, 'protein'):.1f}g）"
                )
    else:
        lines.append("")
        lines.append("今天还没有饮食记录，跟我说「早饭吃了两个包子一杯豆浆」就行。")

    # 营养达标概览
    lines.append("")
    lines.append("🧪 营养状态")
    overview = []
    for key in ("protein", "fat", "carb", "fiber", "sodium"):
        item = analysis["item_map"].get(key)
        if not item:
            continue
        if key in nu.UPPER_ONLY:
            overview.append(
                f"{item['icon']} {item['name']} {nu.fmt_num(item['value'])}{item['unit']}"
                f"（上限 {nu.fmt_num(item['ul'] or item['ref'])}{item['unit']}，{item['pct']:.0f}%）"
            )
        elif item.get("ref_full", item["ref"]) > item["ref"] + 0.01:
            overview.append(
                f"{item['icon']} {item['name']} {nu.fmt_num(item['value'])}{item['unit']}"
                f" / {nu.fmt_num(item['ref_full'])}{item['unit']}（按进度 {item['pct']:.0f}%）"
            )
        else:
            overview.append(
                f"{item['icon']} {item['name']} {nu.fmt_num(item['value'])}{item['unit']}"
                f" / {nu.fmt_num(item['ref'])}{item['unit']}（{item['pct']:.0f}%）"
            )
    lines.extend(overview)

    # 维矿短板
    micro = [
        i for i in analysis["items"]
        if i["group"] in ("维生素", "矿物质") and i["key"] in ALERT_KEYS
    ]
    bad_micro = [i for i in micro if i["status"] in ("vlow", "low")]
    bad_micro.sort(key=lambda x: x["pct"])
    if bad_micro:
        lines.append(
            "短板：" + "、".join(f"{i['name']} {i['pct']:.0f}%" for i in bad_micro[:5])
        )
    good_micro = [i for i in micro if i["status"] == "ok"]
    if good_micro:
        lines.append(
            "达标：" + "、".join(i["name"] for i in good_micro[:6])
        )

    if analysis["water_ml"] or analysis["exercise"]:
        extra = []
        if analysis["water_ml"]:
            extra.append(f"饮水 {analysis['water_ml']}ml")
        if analysis["exercise"]:
            extra.append(f"运动消耗 {analysis['exercise_kcal']:.0f} kcal")
        lines.append(" · ".join(extra))

    if analysis["alerts"]:
        lines.append("")
        lines.append("⚠️ 提醒")
        for alert in analysis["alerts"][:4]:
            lines.append(f"· {alert['text']}")

    # 下一餐建议
    remain = analysis.get("remaining_kcal") or 0
    if remain >= 150:
        meal_plan = suggest_meal(remain, analysis.get("remaining_protein") or 0, _book_of(analysis))
        if meal_plan["items"]:
            combo = " + ".join(
                f"{i['name']} {i['grams']:.0f}g" for i in meal_plan["items"]
            )
            lines.append("")
            lines.append(f"💡 剩余 {remain:.0f} kcal 可以这样吃")
            lines.append(f"{combo} ≈ {meal_plan['kcal']} kcal，蛋白 {meal_plan['protein']}g")

    lines.append("")
    lines.append(f"营养评分 {analysis['score']}/100")
    return "\n".join(lines)


def _book_of(analysis: dict[str, Any]) -> Any:
    return analysis.get("_book")


def analysis_detail(analysis: dict[str, Any]) -> str:
    """全部 25 项营养素的明细表。"""
    lines = ["🧪 营养素明细（对照当日目标）", ""]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in analysis["items"]:
        groups.setdefault(item["group"], []).append(item)
    for group, items in groups.items():
        lines.append(f"【{group}】")
        for item in items:
            val = nu.fmt_num(item["value"])
            if item["key"] in nu.UPPER_ONLY:
                ref_text = f"上限{nu.fmt_num(item['ul'] or item['ref'])}{item['unit']}"
            else:
                ref_text = f"{nu.fmt_num(item.get('ref_full', item['ref']))}{item['unit']}"
            lines.append(
                f" {item['icon']} {item['name']} {val}{item['unit']} / {ref_text}"
                f"  {item['pct']:.0f}%  {item['status_text']}"
            )
        lines.append("")
    if analysis["energy_ratio"]:
        e = analysis["energy_ratio"]
        lines.append(
            f"供能比：蛋白 {e['protein']}% · 脂肪 {e['fat']}% · 碳水 {e['carb']}%"
            "（建议 15-20 / 20-30 / 50-65）"
        )
    lines.append(
        f"食物种类：{analysis['diversity']['count']} 种 / {analysis['diversity']['cat_count']} 类"
    )
    lines.append("注：维矿数值来自常见食物成分表，未收录的食物按 0 计，实际摄入通常略高。")
    return "\n".join(lines)


def profile_card(user: dict[str, Any], targets: dict[str, Any], progress: dict[str, Any] | None = None) -> str:
    bmi = bd.bmi_of(user)
    age = bd.age_of(user)
    lines = ["👤 我的档案"]
    lines.append(
        f"性别 {bd.SEX_LABELS.get(bd.normalize_sex(user.get('sex')))} · "
        f"年龄 {age or '?'} · 身高 {user.get('height_cm') or '?'}cm · "
        f"体重 {user.get('weight_kg') or '?'}kg"
    )
    if bmi:
        lines.append(f"BMI {bmi}（{bd.bmi_label(bmi)}）")
    rng = bd.healthy_weight_range(user.get("height_cm"))
    if rng:
        lines.append(f"健康体重区间 {rng[0]}–{rng[1]}kg")

    if targets.get("ready"):
        lines.append("")
        lines.append(
            f"🔥 基础代谢 {targets['bmr']:.0f} kcal · 每日消耗 {targets['tdee']:.0f} kcal"
        )
        lines.append(
            f"🎯 目标：{targets['goal_label']}"
            + (f" → {user.get('target_weight_kg')}kg" if user.get("target_weight_kg") else "")
            + (f"，计划 {user.get('target_days')} 天" if user.get("target_days") else "")
        )
        lines.append(
            f"🍽 建议摄入 {targets['kcal']} kcal · 蛋白 {targets['protein_g']}g · "
            f"脂肪 {targets['fat_g']}g · 碳水 {targets['carb_g']}g"
        )
        if targets.get("deficit"):
            lines.append(f"📉 每日热量缺口 {targets['deficit']} kcal")
        if targets.get("eta_days"):
            lines.append(f"⏳ 按此节奏预计 {targets['eta_days']} 天达到目标")
    else:
        lines.append("")
        lines.append("资料还不完整：" + "、".join(targets.get("missing") or []))

    if progress and progress.get("current") and progress.get("target"):
        lines.append("")
        lost = progress.get("lost")
        delta_text = ""
        if lost is not None:
            if lost > 0:
                delta_text = f"，已减 {lost:.1f}kg"
            elif lost < 0:
                delta_text = f"，已增 {abs(lost):.1f}kg"
        lines.append(
            f"⚖️ 当前 {progress['current']}kg / 目标 {progress['target']}kg"
            + delta_text
            + (f"，还剩 {progress['remaining']:.1f}kg" if progress.get("remaining") is not None else "")
        )
        if progress.get("pct") is not None:
            lines.append(f"进度 {nu.bar(progress['pct'] / 100)} {progress['pct']:.0f}%")
        trend = (progress.get("trend") or {}).get("slope_per_week")
        if trend:
            lines.append(f"近期趋势 {trend:+.2f} kg/周")
        if progress.get("eta_days"):
            lines.append(f"按趋势预计还需 {progress['eta_days']} 天")

    for warning in targets.get("warnings") or []:
        lines.append(f"⚠️ {warning}")
    return "\n".join(lines)


def calendar_text(
    records: dict[str, dict[str, Any]],
    weights: list[dict[str, Any]],
    target_kcal: float,
    year: int,
    month: int,
) -> str:
    """纯文本日历：逐日列出热量与体重。"""
    start, end = month_range(year, month)
    weight_map = {w["date"]: w["kg"] for w in weights}
    lines = [f"📅 {year} 年 {month} 月 · 饮食日历", ""]
    logged = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        day = records.get(key)
        entries = (day or {}).get("entries") or []
        if entries:
            kcal = sum(nu.get(nu.as_vector(e.get("nut")), "kcal") for e in entries)
            logged.append(kcal)
            pct = kcal / target_kcal if target_kcal else 0
            if not target_kcal:
                icon = "⬜"
            elif pct < 0.85:
                icon = "🟦"
            elif pct <= 1.05:
                icon = "🟩"
            elif pct <= 1.2:
                icon = "🟨"
            else:
                icon = "🟥"
            w = weight_map.get(key)
            line = f"{short_date(cursor)} 周{'一二三四五六日'[cursor.weekday()]}  {icon} {kcal:.0f} kcal"
            if w:
                line += f"  ⚖️ {w}kg"
            lines.append(line)
        elif weight_map.get(key):
            lines.append(
                f"{short_date(cursor)} 周{'一二三四五六日'[cursor.weekday()]}  ·        ⚖️ {weight_map[key]}kg"
            )
        cursor += timedelta(days=1)

    if not logged:
        lines.append("这个月还没有记录。")
    else:
        avg = sum(logged) / len(logged)
        lines.append("")
        lines.append(
            f"记录 {len(logged)} 天 · 平均 {avg:.0f} kcal"
            + (f" · 达标 {sum(1 for k in logged if abs(k - target_kcal) <= target_kcal * 0.1)} 天" if target_kcal else "")
        )
        if weights:
            month_weights = [w for w in weights if w["date"].startswith(f"{year:04d}-{month:02d}")]
            if len(month_weights) >= 2:
                delta = month_weights[-1]["kg"] - month_weights[0]["kg"]
                lines.append(
                    f"体重 {month_weights[0]['kg']}kg → {month_weights[-1]['kg']}kg"
                    f"（{delta:+.1f}kg）"
                )
    return "\n".join(lines)


def week_report(
    days: list[tuple[str, dict[str, Any]]],
    targets: dict[str, Any],
    user: dict[str, Any],
    weights: list[dict[str, Any]],
) -> str:
    summary = summarize_period(days, targets, user)
    lines = ["📈 本周小结", ""]
    if not summary["logged_days"]:
        lines.append("本周还没有任何记录。")
        return "\n".join(lines)
    lines.append(f"记录 {summary['logged_days']}/{summary['days']} 天")
    lines.append(f"平均热量 {summary['avg_kcal']} kcal（目标 {targets.get('kcal') or '—'}）")
    lines.append(f"达标天数 {summary['on_target_days']} 天 · 平均蛋白 {summary['avg_protein']}g")

    if summary["weak"]:
        lines.append(
            "薄弱环节：" + "、".join(f"{w['name']} {w['pct']:.0f}%" for w in summary["weak"][:4])
        )

    week_weights = [w for w in weights if days and w["date"] >= days[0][0] and w["date"] <= days[-1][0]]
    if len(week_weights) >= 2:
        delta = week_weights[-1]["kg"] - week_weights[0]["kg"]
        lines.append(
            f"体重 {week_weights[0]['kg']}kg → {week_weights[-1]['kg']}kg（{delta:+.1f}kg）"
        )

    # 简易柱状图
    series = summary["kcal_series"]
    if series:
        peak = max(s["kcal"] for s in series) or 1
        lines.append("")
        for point in series:
            h = int(round(point["kcal"] / peak * 10))
            lines.append(
                f"{point['date'][5:]} {'█' * h} {point['kcal']}"
            )
    return "\n".join(lines)


def calendar_view(data: dict[str, Any]) -> dict[str, Any]:
    cells = data["cells"]
    weeks: list[list[dict[str, Any] | None]] = []
    week: list[dict[str, Any] | None] = [None] * cells[0]["weekday"]
    for cell in cells:
        if len(week) == 7:
            weeks.append(week)
            week = []
        week.append(cell)
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)

    weights = data["weights"]
    points: list[dict[str, Any]] = []
    if len(weights) >= 2:
        values = [w["kg"] for w in weights]
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1
        width, height = 520, 130
        for i, w in enumerate(weights):
            x = 20 + i * (width - 40) / max(1, len(weights) - 1)
            y = 20 + (hi - w["kg"]) / span * (height - 40)
            points.append({"x": round(x, 1), "y": round(y, 1), "kg": w["kg"], "date": w["date"]})

    polyline = " ".join(f"{p['x']},{p['y']}" for p in points)
    progress = data.get("progress") or {}
    return {
        "month_label": data["month_label"],
        "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
        "weeks": weeks,
        "target_kcal": data["target_kcal"],
        "logged_days": data["logged_days"],
        "avg_kcal": data["avg_kcal"],
        "on_target_days": data["on_target_days"],
        "weight_delta": data["weight_delta"],
        "weight_start": weights[0]["kg"] if weights else None,
        "weight_end": weights[-1]["kg"] if weights else None,
        "chart_points": points,
        "polyline": polyline,
        "has_chart": len(points) >= 2,
        "progress_pct": progress.get("pct"),
        "progress_current": progress.get("current"),
        "progress_target": progress.get("target"),
        "goal_label": (data.get("targets") or {}).get("goal_label"),
        "user_name": (data.get("user") or {}).get("name") or "",
        "today": data["today"],
    }
