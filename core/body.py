# -*- coding: utf-8 -*-
"""体成分与能量代谢计算：BMI、基础代谢、TDEE、目标热量、进度估算。"""

from __future__ import annotations

from datetime import date
from typing import Any

KCAL_PER_KG_FAT = 7700.0

ACTIVITY_LEVELS: dict[str, dict[str, Any]] = {
    "sedentary": {"factor": 1.2, "label": "久坐", "desc": "几乎不运动，办公室/居家为主"},
    "light": {"factor": 1.375, "label": "轻度活动", "desc": "每周 1-3 次轻运动或经常走动"},
    "moderate": {"factor": 1.55, "label": "中等活动", "desc": "每周 3-5 次运动"},
    "active": {"factor": 1.725, "label": "高强度", "desc": "每周 6-7 次运动或体力工作"},
    "very_active": {"factor": 1.9, "label": "极高强度", "desc": "运动员/重体力劳动"},
}
ACTIVITY_ALIASES: dict[str, str] = {
    "久坐": "sedentary", "不运动": "sedentary", "躺": "sedentary", "sedentary": "sedentary",
    "轻度": "light", "轻": "light", "偶尔运动": "light", "light": "light",
    "中等": "moderate", "中度": "moderate", "moderate": "moderate", "正常": "moderate",
    "高": "active", "较多": "active", "active": "active", "经常运动": "active",
    "极高": "very_active", "运动员": "very_active", "very_active": "very_active",
}
GOAL_LABELS = {"lose": "减脂", "maintain": "维持", "gain": "增重"}
SEX_LABELS = {"male": "男", "female": "女"}


def normalize_activity(text: str | None) -> str:
    if not text:
        return "light"
    key = str(text).strip().lower()
    if key in ACTIVITY_LEVELS:
        return key
    for alias, value in ACTIVITY_ALIASES.items():
        if alias in key:
            return value
    return "light"


def normalize_sex(text: str | None) -> str:
    key = str(text or "").strip().lower()
    if key in {"female", "f", "女", "女性", "女生", "woman", "girl"}:
        return "female"
    return "male"


def normalize_goal(text: str | None) -> str:
    key = str(text or "").strip().lower()
    if key in {"gain", "增重", "增肌", "长肉"}:
        return "gain"
    if key in {"maintain", "维持", "保持", "不变"}:
        return "maintain"
    return "lose"


def age_of(user: dict[str, Any], today: date | None = None) -> int | None:
    """优先用出生年份实时推算，其次用记录时的年龄做线性外推。"""
    today = today or date.today()
    birth_year = user.get("birth_year")
    if birth_year:
        try:
            age = today.year - int(birth_year)
            if 1 <= age <= 120:
                return age
        except (TypeError, ValueError):
            pass
    age = user.get("age")
    if age:
        recorded = user.get("age_recorded_year") or today.year
        try:
            return int(age) + (today.year - int(recorded))
        except (TypeError, ValueError):
            return None
    return None


def bmi_of(user: dict[str, Any]) -> float | None:
    h = user.get("height_cm")
    w = user.get("weight_kg")
    if not h or not w:
        return None
    h_m = float(h) / 100
    if h_m <= 0:
        return None
    return round(float(w) / (h_m * h_m), 1)


def bmi_label(bmi: float | None) -> str:
    if bmi is None:
        return "未知"
    if bmi < 18.5:
        return "偏瘦"
    if bmi < 24:
        return "正常"
    if bmi < 28:
        return "超重"
    return "肥胖"


def healthy_weight_range(height_cm: float | None) -> tuple[float, float] | None:
    if not height_cm:
        return None
    h_m = float(height_cm) / 100
    return round(18.5 * h_m * h_m, 1), round(23.9 * h_m * h_m, 1)


def bmr_of(user: dict[str, Any], today: date | None = None) -> float | None:
    """Mifflin-St Jeor 公式。"""
    h = user.get("height_cm")
    w = user.get("weight_kg")
    age = age_of(user, today)
    if not h or not w or not age:
        return None
    sex = normalize_sex(user.get("sex"))
    base = 10 * float(w) + 6.25 * float(h) - 5 * float(age)
    return round(base + (5 if sex == "male" else -161), 0)


def tdee_of(user: dict[str, Any], today: date | None = None) -> float | None:
    bmr = bmr_of(user, today)
    if not bmr:
        return None
    factor = ACTIVITY_LEVELS[normalize_activity(user.get("activity"))]["factor"]
    return round(bmr * factor, 0)


def _calorie_floor(user: dict[str, Any], bmr: float) -> float:
    base = 1200 if normalize_sex(user.get("sex")) == "female" else 1500
    return max(base, round(bmr * 0.85, -1))


def build_targets(user: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """计算每日热量与营养素目标，并给出可行性评估。"""
    today = today or date.today()
    sex = normalize_sex(user.get("sex"))
    goal = normalize_goal(user.get("goal"))
    weight = float(user.get("weight_kg") or 0)
    height = float(user.get("height_cm") or 0)
    age = age_of(user, today)

    result: dict[str, Any] = {
        "ready": False,
        "goal": goal,
        "goal_label": GOAL_LABELS[goal],
        "bmr": None,
        "tdee": None,
        "kcal": None,
        "deficit": None,
        "protein_g": None,
        "fat_g": None,
        "carb_g": None,
        "fiber_g": 25,
        "water_ml": None,
        "target_weight": user.get("target_weight_kg"),
        "target_days": user.get("target_days"),
        "eta_days": None,
        "capped": False,
        "warnings": [],
        "missing": [],
    }

    for field, label in (
        ("height_cm", "身高"),
        ("weight_kg", "体重"),
    ):
        if not user.get(field):
            result["missing"].append(label)
    if not age:
        result["missing"].append("年龄")
    if result["missing"]:
        result["warnings"].append(
            "还缺" + "、".join(result["missing"]) + "，补齐后才能算准基础代谢。"
        )
        return result

    bmr = bmr_of(user, today)
    tdee = tdee_of(user, today)
    result["bmr"] = bmr
    result["tdee"] = tdee
    result["ready"] = True

    target_weight = user.get("target_weight_kg")
    target_days = user.get("target_days")
    deficit = 0.0
    eta_days = None

    if goal == "lose":
        deficit = 400.0
        if target_weight and weight:
            diff = weight - float(target_weight)
            if diff <= 0:
                result["warnings"].append("目标体重不低于当前体重，已按「维持体重」处理。")
                deficit = 0.0
            elif target_days:
                deficit = diff * KCAL_PER_KG_FAT / float(target_days)
                if deficit > 1000:
                    result["warnings"].append(
                        f"按 {int(target_days)} 天减 {diff:.1f}kg 需要每天少 {deficit:.0f} 千卡，"
                        "超出安全范围，已按每天 1000 千卡缺口规划，实际需要更长时间。"
                    )
                    deficit = 1000.0
    elif goal == "gain":
        deficit = -300.0
        if target_weight and weight:
            diff = float(target_weight) - weight
            if diff > 0 and target_days:
                surplus = diff * KCAL_PER_KG_FAT / float(target_days)
                deficit = -min(max(surplus, 150), 600)

    kcal = tdee - deficit
    floor = _calorie_floor(user, bmr)
    if kcal < floor:
        kcal = floor
        result["capped"] = True
        result["warnings"].append(
            f"目标热量低于安全下限，已提升到 {floor:.0f} 千卡（不建议长期低于基础代谢）。"
        )
        deficit = tdee - kcal

    if deficit > 0:
        result["deficit"] = round(deficit)
        if target_weight and weight and goal == "lose":
            eta_days = (weight - float(target_weight)) * KCAL_PER_KG_FAT / deficit
    elif deficit < 0:
        result["deficit"] = round(deficit)
        if target_weight and weight and goal == "gain":
            eta_days = (float(target_weight) - weight) * KCAL_PER_KG_FAT / abs(deficit)

    result["kcal"] = int(round(kcal, -1))
    result["eta_days"] = int(round(eta_days)) if eta_days and eta_days > 0 else None
    if target_days and result["eta_days"] and goal == "lose":
        result["target_days"] = int(target_days)

    # 蛋白质：肥胖者按理想体重折算，避免高估
    bmi = bmi_of(user)
    protein_base = weight
    if bmi and bmi >= 28 and height:
        rng = healthy_weight_range(height)
        if rng:
            protein_base = (rng[0] + rng[1]) / 2
    per_kg = {"lose": 1.6, "gain": 1.8, "maintain": 1.2}[goal]
    protein_g = min(protein_base * per_kg, weight * 2.2)
    fat_g = max(kcal * 0.25 / 9, weight * 0.6)
    carb_g = max((kcal - protein_g * 4 - fat_g * 9) / 4, 60)
    result["protein_g"] = int(round(protein_g))
    result["fat_g"] = int(round(fat_g))
    result["carb_g"] = int(round(carb_g))
    result["water_ml"] = int(round(weight * 35, -1))

    # 目标体重合理性
    if goal == "lose" and target_weight and height:
        rng = healthy_weight_range(height)
        if rng and float(target_weight) < rng[0]:
            result["warnings"].append(
                f"目标 {target_weight}kg 低于健康体重下限 {rng[0]}kg，建议不要低于这个值。"
            )
        if bmi and bmi < 18.5:
            result["warnings"].append("当前 BMI 已偏瘦，继续减重可能影响健康，建议改为增肌或维持。")

    return result


def weight_trend(weights: list[dict[str, Any]], window: int = 14) -> dict[str, Any]:
    """用最近若干条记录做线性拟合，得到每周变化速度。"""
    points: list[tuple[int, float]] = []
    if not weights:
        return {"slope_per_week": None, "points": 0, "span_days": 0}
    try:
        base = date.fromisoformat(weights[0]["date"])
    except (ValueError, KeyError):
        return {"slope_per_week": None, "points": 0, "span_days": 0}
    for item in weights[-window:]:
        try:
            d = date.fromisoformat(item["date"])
        except (ValueError, KeyError):
            continue
        points.append(((d - base).days, float(item["kg"])))
    if len(points) < 2:
        return {"slope_per_week": None, "points": len(points), "span_days": 0}
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if denom == 0:
        return {"slope_per_week": None, "points": n, "span_days": 0}
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denom
    return {
        "slope_per_week": round(slope * 7, 2),
        "points": n,
        "span_days": points[-1][0] - points[0][0],
    }


def goal_progress(
    user: dict[str, Any],
    weights: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    # 优先用最近一次称重，其次用档案里的体重
    current = float(weights[-1]["kg"]) if weights else 0.0
    if not current:
        current = float(user.get("weight_kg") or 0)
    target = user.get("target_weight_kg")
    start = user.get("goal_start_weight") or (
        float(weights[0]["kg"]) if weights else current
    )
    out: dict[str, Any] = {
        "current": current or None,
        "start": start or None,
        "target": target,
        "lost": None,
        "remaining": None,
        "pct": None,
        "eta_days": None,
        "trend": weight_trend(weights),
        "on_track": None,
    }
    if not current or not target:
        return out
    target = float(target)
    out["lost"] = round(start - current, 1) if start else None
    remaining = current - target
    out["remaining"] = round(remaining, 1)
    total = (start - target) if start else 0
    if total and abs(total) > 0.01:
        out["pct"] = max(0.0, min(100.0, round((start - current) / total * 100, 1)))
    slope = out["trend"].get("slope_per_week")
    if slope and slope < -0.05 and remaining > 0:
        out["eta_days"] = int(round(remaining / abs(slope) * 7))
    start_date = user.get("goal_start_date")
    if start_date and user.get("target_days"):
        try:
            elapsed = (today - date.fromisoformat(start_date)).days
            planned = float(user["target_days"])
            if planned > 0:
                expected = total * (elapsed / planned)
                actual = (start - current) if start else 0
                out["on_track"] = actual >= expected - 0.5
        except (ValueError, TypeError):
            pass
    return out
