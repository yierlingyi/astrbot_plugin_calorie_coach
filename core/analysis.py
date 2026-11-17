# -*- coding: utf-8 -*-
"""营养分析引擎：摄入汇总、达标判定、缺口清单、评分与建议。"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import body as bd
from . import nutrition as nu
from . import suggest as sg
from .util import MEALS, MEAL_ICON

STATUS_TEXT = {
    "none": "未记录",
    "vlow": "严重不足",
    "low": "不足",
    "ok": "达标",
    "high": "偏高",
    "over": "过量",
}
STATUS_ICON = {
    "none": "⬜",
    "vlow": "🔴",
    "low": "🟠",
    "ok": "🟢",
    "high": "🟡",
    "over": "🔴",
}

IDEAL_SHARE = {"早餐": 28, "午餐": 36, "晚餐": 31, "加餐": 5}

# 会参与评分与提醒的重点营养素（数据覆盖较好的那些）
ALERT_KEYS: tuple[str, ...] = (
    "protein", "fiber", "calcium", "iron", "zinc", "selenium",
    "va", "vc", "b1", "b2", "potassium", "magnesium",
)


# 需要按「供能目标」判断多与少的宏量营养素
MACRO_KEYS: frozenset[str] = frozenset({"protein", "fat", "carb"})


def _status(key: str, value: float, ref: float, ul: float | None) -> tuple[str, float]:
    """返回 (状态码, 达成百分比)。

    - 钠/饱和脂肪/胆固醇：只看是否逼近或超过上限；
    - 蛋白质/脂肪/碳水：按供能目标判断，超过目标 120% 才算偏高；
    - 维生素矿物质：只判断不足；只有存在 UL 且真的超了才算过量。
      没有 UL 的营养素（钾、镁、维 K、B1/B2/B12 等）吃多了不是问题，
      参考值本身只是「建议达到」，不是上限。
    """
    if ref <= 0:
        return "ok", 0.0
    pct = value / ref * 100

    if key in nu.UPPER_ONLY:
        if not ul:
            return "ok", pct
        upct = value / ul * 100
        if value > ul:
            return "over", upct
        if value > ul * 0.85:
            return "high", upct
        if key == "sodium" and value == 0:
            return "none", 0.0
        return "ok", upct

    if key in MACRO_KEYS:
        if value <= 0:
            return "none", 0.0
        if pct < 50:
            return "vlow", pct
        if pct < 80:
            return "low", pct
        if pct <= 120:
            return "ok", pct
        if pct <= 150:
            return "high", pct
        return "over", pct

    if value <= 0:
        return "none", 0.0
    if pct < 50:
        return "vlow", pct
    if pct < 80:
        return "low", pct
    if ul and value > ul:
        return "over", pct
    if ul and value > ul * 0.85:
        return "high", pct
    return "ok", pct


def totals_of(entries: list[dict[str, Any]]) -> list[float]:
    total = nu.zeros()
    for entry in entries:
        nu.accumulate(total, nu.as_vector(entry.get("nut")))
    return total


def meal_totals(entries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {m: {"kcal": 0.0, "count": 0} for m in MEALS}
    for entry in entries:
        meal = entry.get("meal") or "加餐"
        if meal not in out:
            meal = "加餐"
        out[meal]["kcal"] += nu.get(nu.as_vector(entry.get("nut")), "kcal")
        out[meal]["count"] += 1
    for meal in out:
        out[meal]["kcal"] = round(out[meal]["kcal"], 1)
    return out


def refs_of(targets: dict[str, Any], user: dict[str, Any], scale: float = 1.0) -> dict[str, float]:
    """按目标与性别生成每种营养素的当日参考值。

    scale < 1 表示「一天还没过完」，参考值按已记录比例折算成「到现在应该吃到多少」；
    只有钠/饱和脂肪/胆固醇这类上限值不折算 —— 它们看的是全天总量是否已经超限。
    """
    sex = bd.normalize_sex(user.get("sex"))
    refs: dict[str, float] = {}
    kcal = float(targets.get("kcal") or 0)
    if kcal:
        refs["kcal"] = kcal
    for key, fallback in (
        ("protein", targets.get("protein_g")),
        ("fat", targets.get("fat_g")),
        ("carb", targets.get("carb_g")),
        ("fiber", targets.get("fiber_g") or 25),
    ):
        if fallback:
            refs[key] = float(fallback) * scale
    for key in nu.MICRO_KEYS:
        if key in ("sfat", "chol"):
            continue
        meta = nu.NUTRIENTS[key]
        refs[key] = meta.rda(sex) * scale
    refs["sfat"] = nu.NUTRIENTS["sfat"].rda(sex)
    refs["chol"] = nu.NUTRIENTS["chol"].rda(sex)
    return refs


def analyze(
    day: dict[str, Any],
    targets: dict[str, Any],
    user: dict[str, Any],
    book: Any,
    scale: float = 1.0,
    today: date | None = None,
) -> dict[str, Any]:
    """对某一天的记录做完整营养分析。"""
    today = today or date.today()
    entries = list(day.get("entries") or [])
    total = totals_of(entries)
    refs = refs_of(targets, user, scale)
    kcal_in = nu.get(total, "kcal")
    target_kcal = float(targets.get("kcal") or 0)

    full_refs = refs_of(targets, user, 1.0)
    items: list[dict[str, Any]] = []
    for key in nu.KEYS:
        if key == "kcal":
            continue
        meta = nu.NUTRIENTS[key]
        ref = refs.get(key, 0)
        value = nu.get(total, key)
        status, pct = _status(key, value, ref, meta.ul)
        items.append(
            {
                "key": key,
                "name": meta.name,
                "unit": meta.unit,
                "group": meta.group,
                "value": round(value, 2),
                "ref": round(ref, 2),
                "ref_full": round(full_refs.get(key, ref), 2),
                "pct": round(pct, 1),
                "status": status,
                "status_text": STATUS_TEXT[status],
                "icon": STATUS_ICON[status],
                "ul": meta.ul,
            }
        )

    item_map = {item["key"]: item for item in items}
    gaps = [
        item for item in items
        if item["status"] in {"vlow", "low"} and item["key"] not in ("sfat", "chol")
    ]
    gaps.sort(key=lambda x: x["pct"])
    excess = [item for item in items if item["status"] in {"high", "over"}]
    excess.sort(key=lambda x: -x["pct"])

    # 热量判定
    kcal_pct = (kcal_in / target_kcal * 100) if target_kcal else 0.0
    kcal_status = "none"
    if target_kcal and kcal_in > 0:
        if kcal_pct < 60:
            kcal_status = "low"
        elif kcal_pct < 85:
            kcal_status = "slight_low"
        elif kcal_pct <= 105:
            kcal_status = "ok"
        elif kcal_pct <= 115:
            kcal_status = "slight_high"
        else:
            kcal_status = "high"

    # 多样性
    names = [e.get("name", "") for e in entries if e.get("name")]
    cats = {e.get("cat") or "其他" for e in entries if e.get("name")}
    diversity = {
        "count": len(set(names)),
        "cat_count": len(cats),
        "cats": sorted(cats),
    }

    # 餐次分布
    per_meal = meal_totals(entries)
    meals_logged = [m for m in MEALS if per_meal[m]["count"] > 0]
    shares: dict[str, float] = {}
    if kcal_in > 0:
        for meal in MEALS:
            shares[meal] = round(per_meal[meal]["kcal"] / kcal_in * 100, 1)

    alerts = _build_alerts(
        scale=scale,
        items=items,
        item_map=item_map,
        gaps=gaps,
        excess=excess,
        kcal_in=kcal_in,
        target_kcal=target_kcal,
        kcal_pct=kcal_pct,
        shares=shares,
        meals_logged=meals_logged,
        diversity=diversity,
        day=day,
        user=user,
        book=book,
        entries=entries,
    )

    score = _score(gaps, excess, kcal_pct, target_kcal, diversity, item_map)

    remaining_kcal = max(0.0, target_kcal - kcal_in)
    remaining_protein = max(
        0.0, float(targets.get("protein_g") or 0) - nu.get(total, "protein")
    )

    return {
        "date": day.get("date"),
        "entries": entries,
        "total": total,
        "kcal_in": round(kcal_in, 1),
        "target_kcal": target_kcal,
        "kcal_pct": round(kcal_pct, 1),
        "kcal_status": kcal_status,
        "remaining_kcal": round(remaining_kcal),
        "remaining_protein": round(remaining_protein, 1),
        "items": items,
        "item_map": item_map,
        "gaps": gaps,
        "excess": excess,
        "energy_ratio": nu.energy_ratio(total),
        "per_meal": per_meal,
        "meals_logged": meals_logged,
        "meal_shares": shares,
        "diversity": diversity,
        "alerts": alerts,
        "score": score,
        "scale": round(scale, 2),
        "water_ml": int(day.get("water_ml") or 0),
        "exercise": list(day.get("exercise") or []),
        "exercise_kcal": round(sum(float(e.get("kcal") or 0) for e in day.get("exercise") or []), 0),
        "_book": book,
    }


def _build_alerts(
    *,
    scale: float,
    items: list[dict[str, Any]],
    item_map: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
    excess: list[dict[str, Any]],
    kcal_in: float,
    target_kcal: float,
    kcal_pct: float,
    shares: dict[str, float],
    meals_logged: list[str],
    diversity: dict[str, Any],
    day: dict[str, Any],
    user: dict[str, Any],
    book: Any,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    user_foods = {}  # 由调用方补充时可用；这里只在补建议时查内置库
    dislikes = list(user.get("dislikes") or [])

    def add(level: str, text: str, kind: str = "") -> None:
        alerts.append({"level": level, "text": text, "kind": kind})

    if target_kcal:
        if kcal_in == 0:
            add("info", "今天还没有任何饮食记录。")
        elif kcal_pct > 115:
            add(
                "warn",
                f"热量已超目标 {kcal_in - target_kcal:.0f} 千卡（{kcal_pct:.0f}%），"
                "接下来只吃清淡蔬菜和蛋白，别再叠加油炸和甜饮。",
                "kcal",
            )
        elif kcal_pct < 60 and kcal_in > 0 and scale >= 0.95:
            add(
                "warn",
                f"热量只到目标的 {kcal_pct:.0f}%，长期吃太少会掉肌肉、代谢下降、还容易暴食。",
                "kcal",
            )

    # 关键缺口（最多提醒 3 条，按严重程度）
    picked = [g for k in ALERT_KEYS for g in gaps if g["key"] == k][:3]
    for gap in picked:
        level = "warn" if gap["status"] == "vlow" else "info"
        need = max(0.0, gap["ref"] - gap["value"])
        covers = sg.cover_gap(gap["key"], need, book, dislikes=dislikes, limit=2)
        hint = " + ".join(f"{c['name']} {c['text']}" for c in covers) if covers else ""
        if gap["ref"] < gap["ref_full"] - 0.01:
            text = (
                f"{gap['name']} {nu.fmt_num(gap['value'])}{gap['unit']}，"
                f"按当前进度应达 {nu.fmt_num(gap['ref'])}{gap['unit']}"
                f"（{gap['pct']:.0f}%，全天目标 {nu.fmt_num(gap['ref_full'])}{gap['unit']}）"
            )
        else:
            text = (
                f"{gap['name']}只有 {nu.fmt_num(gap['value'])}{gap['unit']}"
                f"（{gap['pct']:.0f}%，目标 {nu.fmt_num(gap['ref'])}{gap['unit']}）"
            )
        if hint:
            text += f"，补上可以吃 {hint}"
        add(level, text, gap["key"])

    # 超标项
    for over in excess[:2]:
        tip = sg.advice_for(over["key"], "high")
        if over["key"] in nu.UPPER_ONLY:
            ref_text = f"参考上限 {nu.fmt_num(over['ul'] or over['ref'])}{over['unit']}"
        else:
            ref_text = f"目标 {nu.fmt_num(over['ref'])}{over['unit']}"
        state = "超标" if over["status"] == "over" else "偏高"
        add(
            "warn" if over["status"] == "over" else "info",
            f"{over['name']}{state}（{nu.fmt_num(over['value'])}{over['unit']}，{ref_text}）。{tip}",
            over["key"],
        )

    # 蛋白质专项
    protein = item_map.get("protein")
    if protein and protein["pct"] >= 60 and kcal_in > 0:
        ratio = protein["value"] * 4 / kcal_in * 100
        if ratio > 35:
            add("info", f"蛋白质供能比 {ratio:.0f}%，偏高，注意多喝水、别长期高蛋白。", "protein")

    # 餐次分布
    if len(meals_logged) >= 3 and shares:
        dinner = shares.get("晚餐", 0)
        breakfast = shares.get("早餐", 0)
        if dinner >= 45:
            add("info", f"晚餐占了全天 {dinner:.0f}%，把一部分挪到早餐/午餐更利于控制体重。", "meal")
        if breakfast and breakfast < 12:
            add("info", f"早餐只占 {breakfast:.0f}%，早餐吃够蛋白和主食能减少晚上暴食。", "meal")

    # 深夜进食
    late = [e for e in entries if (e.get("time") or "00:00") >= "22:00"]
    if late:
        add("info", f"有 {len(late)} 条记录在 22:00 之后，夜宵尽量选蛋白+蔬菜。", "late")

    # 多样性
    if diversity["count"] and diversity["count"] < 8:
        add(
            "info",
            f"今天只吃了 {diversity['count']} 种食物，建议每天 12 种以上、每周 25 种以上，营养更全面。",
            "diversity",
        )

    # 饮水
    water = int(day.get("water_ml") or 0)
    water_target = 2000
    if water and water < water_target * 0.5:
        add("info", f"饮水 {water}ml，还不到 {water_target}ml 的一半。", "water")

    return alerts


def _score(
    gaps: list[dict[str, Any]],
    excess: list[dict[str, Any]],
    kcal_pct: float,
    target_kcal: float,
    diversity: dict[str, Any],
    item_map: dict[str, dict[str, Any]],
) -> int:
    """评分：缺口/超标只对重点营养素扣分，并设上限，避免一票否决。"""
    score = 100.0

    gap_penalty = 0.0
    for gap in gaps:
        if gap["key"] in ALERT_KEYS:
            gap_penalty += 6 if gap["status"] == "vlow" else 3
    score -= min(45.0, gap_penalty)

    over_penalty = 0.0
    for over in excess:
        if over["key"] in ("sodium", "fat", "carb", "protein", "sfat", "chol", "va", "iron", "selenium", "vd"):
            over_penalty += 6 if over["status"] == "over" else 2
    score -= min(20.0, over_penalty)

    if target_kcal and kcal_pct:
        if kcal_pct > 115 or kcal_pct < 60:
            score -= 10
        elif kcal_pct > 105 or kcal_pct < 80:
            score -= 4

    if diversity["count"] < 5:
        score -= 8
    elif diversity["count"] < 8:
        score -= 4
    if diversity["cat_count"] and diversity["cat_count"] < 3:
        score -= 4

    protein = item_map.get("protein")
    if protein and protein["status"] == "vlow":
        score -= 3
    return int(max(0, min(100, round(score))))


def suggest_meal(
    remaining_kcal: float,
    remaining_protein: float,
    book: Any,
    user: dict[str, Any] | None = None,
    limit_items: int = 3,
) -> dict[str, Any]:
    """按剩余额度配一顿饭：蛋白 + 蔬菜 + 主食，总量控制在额度内。"""
    user = user or {}
    dislikes = list(user.get("dislikes") or [])
    if remaining_kcal < 120:
        return {
            "items": [],
            "kcal": 0,
            "protein": 0,
            "note": "剩余额度太少，建议只补点蔬菜或一杯无糖酸奶。",
        }

    def pick(names: list[str]) -> dict[str, Any] | None:
        for name in names:
            if any(d and d in name for d in dislikes):
                continue
            item = book.find(name)
            if item:
                return item
        return None

    budget = remaining_kcal * 0.95
    protein_item = pick(["鸡胸肉（熟）", "虾仁", "鸡蛋", "豆腐（北）", "牛肉（瘦）", "三文鱼"])
    veg_item = pick(["西兰花", "菠菜", "生菜", "卷心菜", "青椒", "番茄"])
    carb_item = pick(["米饭", "红薯（蒸）", "玉米（煮）", "糙米饭", "面条（煮）"])

    items: list[dict[str, Any]] = []
    total_kcal = 0.0
    total_protein = 0.0

    def add_item(item: dict[str, Any], grams: float) -> None:
        nonlocal total_kcal, total_protein
        grams = round(grams)
        if grams <= 0:
            return
        gain = grams / 100
        k = nu.get(item["nut"], "kcal") * gain
        p = nu.get(item["nut"], "protein") * gain
        items.append(
            {"name": item["name"], "grams": grams, "kcal": round(k), "protein": round(p, 1)}
        )
        total_kcal += k
        total_protein += p

    # 1) 蛋白质：优先补足缺口，但不超过预算的一半
    if protein_item:
        per_p = max(nu.get(protein_item["nut"], "protein"), 0.5)
        per_k = max(nu.get(protein_item["nut"], "kcal"), 1)
        want = remaining_protein / per_p * 100 if remaining_protein > 5 else budget * 0.3 / per_k * 100
        cap_by_kcal = budget * 0.5 / per_k * 100
        grams = max(60.0, min(200.0, want, cap_by_kcal))
        add_item(protein_item, grams)

    # 2) 蔬菜：固定一大份
    if veg_item:
        veg_grams = 200.0 if budget - total_kcal > 120 else 120.0
        add_item(veg_item, veg_grams)

    # 3) 主食：填满剩余额度
    if carb_item:
        left = budget - total_kcal
        per_k = max(nu.get(carb_item["nut"], "kcal"), 1)
        grams = left / per_k * 100
        grams = min(250.0, max(0.0, round(grams / 10) * 10))
        if grams >= 30:
            add_item(carb_item, grams)

    return {
        "items": items[:limit_items],
        "kcal": round(total_kcal),
        "protein": round(total_protein, 1),
        "note": "",
    }


def summarize_period(
    days: list[tuple[str, dict[str, Any]]],
    targets: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    """多日汇总：平均摄入、达标天数、营养短板排行。"""
    target_kcal = float(targets.get("kcal") or 0)
    logged = [(d, day) for d, day in days if (day.get("entries") or [])]
    if not logged:
        return {
            "days": len(days),
            "logged_days": 0,
            "avg_kcal": 0,
            "on_target_days": 0,
            "avg_protein": 0,
            "weak": [],
            "kcal_series": [],
        }
    series = []
    on_target = 0
    protein_sum = 0.0
    nutrient_sum = nu.zeros()
    for day_str, day in logged:
        total = totals_of(day.get("entries") or [])
        kcal = nu.get(total, "kcal")
        series.append({"date": day_str, "kcal": round(kcal)})
        if target_kcal and abs(kcal - target_kcal) <= target_kcal * 0.1:
            on_target += 1
        protein_sum += nu.get(total, "protein")
        nu.accumulate(nutrient_sum, total)

    avg = nu.scale(nutrient_sum, 1 / len(logged))
    refs = refs_of(targets, user, 1.0)
    weak = []
    for key in ("protein", "fiber", "calcium", "iron", "vc", "b2", "potassium", "zinc"):
        ref = refs.get(key) or 0
        if ref <= 0:
            continue
        pct = nu.get(avg, key) / ref * 100
        if pct < 80:
            weak.append({"key": key, "name": nu.NUTRIENTS[key].name, "pct": round(pct, 1)})
    weak.sort(key=lambda x: x["pct"])

    return {
        "days": len(days),
        "logged_days": len(logged),
        "avg_kcal": round(nu.get(avg, "kcal")),
        "avg_protein": round(nu.get(avg, "protein"), 1),
        "on_target_days": on_target,
        "weak": weak,
        "kcal_series": series,
        "avg_total": avg,
    }
