# -*- coding: utf-8 -*-
"""业务服务层：工具、指令都只调这里，保证同一套记录与计算逻辑。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import analysis as an
from . import body as bd
from . import nutrition as nu
from . import suggest as sg
from .foods import FoodBook, merge_user_foods
from .store import Store
from .util import MEAL_TIME, guess_meal_by_hour, normalize_meal, parse_date, parse_time

MET_TABLE: dict[str, float] = {
    "走路": 3.5, "散步": 3.0, "快走": 4.3, "跑步": 8.0, "慢跑": 7.0, "骑行": 6.0,
    "自行车": 6.0, "游泳": 6.0, "跳绳": 10.0, "瑜伽": 2.5, "力量训练": 5.0,
    "健身": 5.0, "撸铁": 5.0, "篮球": 6.5, "羽毛球": 5.5, "足球": 7.0,
    "乒乓球": 4.0, "网球": 7.3, "爬山": 6.0, "徒步": 6.0, "椭圆机": 5.0,
    "划船": 7.0, "爬楼": 8.0, "家务": 3.0, "跳舞": 4.5, "HIIT": 8.0,
}
INTENSITY_FACTOR = {"低": 0.8, "轻松": 0.8, "中": 1.0, "中等": 1.0, "正常": 1.0, "高": 1.3, "剧烈": 1.3}


class CoachService:
    def __init__(self, store: Store, book: FoodBook, tz: ZoneInfo, config: Any = None) -> None:
        self.store = store
        self.book = book
        self.tz = tz
        self.config = config

    # ------------------------------------------------------------------ #
    # 时间
    # ------------------------------------------------------------------ #
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def today_str(self) -> str:
        return self.today().isoformat()

    def resolve_day(self, text: str | None) -> date:
        return parse_date(text, self.today())

    # ------------------------------------------------------------------ #
    # 用户与目标
    # ------------------------------------------------------------------ #
    def user(self, uid: str) -> dict[str, Any]:
        user = self.store.get_user(uid)
        if not user.get("activity_set"):
            if self.config is not None:
                try:
                    default = self.config.get("default_activity")
                except Exception:  # noqa: BLE001
                    default = None
                if default:
                    user["activity"] = bd.normalize_activity(default)
            user["activity_set"] = True
        return user

    def is_paused(self, uid: str) -> bool:
        return bool(self.user(uid).get("paused"))

    def profile_ready(self, uid: str) -> bool:
        u = self.user(uid)
        return bool(u.get("height_cm") and u.get("weight_kg") and bd.age_of(u, self.today()))

    def targets(self, uid: str) -> dict[str, Any]:
        return bd.build_targets(self.user(uid), self.today())

    def progress(self, uid: str) -> dict[str, Any]:
        return bd.goal_progress(self.user(uid), self.store.get_weights(uid), self.today())

    def update_profile(self, uid: str, fields: dict[str, Any]) -> dict[str, Any]:
        user = self.user(uid)
        today = self.today()
        touched_weight = None
        for key, value in fields.items():
            if value is None or value == "":
                continue
            if key == "sex":
                user["sex"] = bd.normalize_sex(value)
            elif key == "activity":
                user["activity"] = bd.normalize_activity(value)
                user["activity_set"] = True
            elif key == "goal":
                user["goal"] = bd.normalize_goal(value)
                user["goal_set"] = True
            elif key in ("height_cm", "weight_kg", "target_weight_kg", "body_fat"):
                try:
                    user[key] = round(float(value), 1)
                except (TypeError, ValueError):
                    continue
                if key == "weight_kg":
                    touched_weight = user[key]
            elif key in ("age", "target_days", "birth_year"):
                try:
                    user[key] = int(float(value))
                except (TypeError, ValueError):
                    continue
                if key == "age":
                    user["age_recorded_year"] = today.year
                    user.pop("birth_year", None)
            elif key in ("diet_prefs", "allergies", "dislikes"):
                if isinstance(value, str):
                    value = [v.strip() for v in value.replace("，", ",").split(",") if v.strip()]
                user[key] = list(value)
            elif key == "paused":
                user["paused"] = bool(value)
            elif key == "name":
                user["name"] = str(value)
        user["updated_at"] = datetime.now().isoformat(timespec="seconds")

        # 首次设定目标时记录起点
        if user.get("target_weight_kg") and not user.get("goal_start_weight") and user.get("weight_kg"):
            user["goal_start_weight"] = user["weight_kg"]
            user["goal_start_date"] = today.isoformat()

        if touched_weight:
            self.store.add_weight(uid, today.isoformat(), touched_weight, source="档案")
            self.store.save("weights")
        self.store.save("users")
        return user

    # ------------------------------------------------------------------ #
    # 食物解析
    # ------------------------------------------------------------------ #
    def user_food_items(self, uid: str) -> list[dict[str, Any]]:
        return merge_user_foods(self.book, self.store.user_foods(uid))

    def find_food(self, uid: str, name: str) -> dict[str, Any] | None:
        item = self.book.find(name)
        if item:
            return item
        for cand in self.user_food_items(uid):
            if cand["name"] == name or name in (cand.get("alias") or []):
                return cand
        hits = self.book.search(name, limit=1, extra=self.user_food_items(uid))
        return hits[0] if hits else None

    def search_food(self, uid: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.book.search(query, limit=limit, extra=self.user_food_items(uid))

    def lookup(self, uid: str, query: str, amount: float = 0, unit: str | None = None) -> dict[str, Any]:
        hits = self.search_food(uid, query, limit=4)
        if not hits:
            return {"ok": False, "query": query, "hits": []}
        main = hits[0]
        out: dict[str, Any] = {
            "ok": True,
            "query": query,
            "name": main["name"],
            "cat": main["cat"],
            "per100": {k: nu.get(main["nut"], k) for k in nu.KEYS if nu.get(main["nut"], k)},
            "portions": [f"{label}≈{grams:g}g" for label, grams in main["portions"]],
            "alternatives": [h["name"] for h in hits[1:]],
        }
        if amount > 0:
            grams, text = self.book.resolve_grams(main, amount, unit)
            nut = nu.scale(main["nut"], grams / 100)
            out["amount_text"] = text
            out["grams"] = round(grams, 1)
            out["nut"] = {k: round(v, 2) for k, v in nu.to_dict(nut).items()}
        return out

    # ------------------------------------------------------------------ #
    # 记录饮食
    # ------------------------------------------------------------------ #
    def add_food(
        self,
        uid: str,
        day: date,
        name: str,
        amount: float = 1.0,
        unit: str | None = None,
        meal: str | None = None,
        time_text: str | None = None,
        *,
        nut_override: dict[str, float] | None = None,
        cat: str = "",
        save_preset: bool = False,
        note: str = "",
        grams_override: float | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "reason": "食物名称为空"}

        item = self.find_food(uid, name)
        virtual = False
        if item is None and nut_override:
            item = {
                "name": name,
                "cat": cat or "联网查询",
                "alias": [],
                "nut": nu.as_vector(nut_override),
                "portions": [["100克", 100]],
                "source": "估算",
            }
            virtual = True
        if item is None:
            return {
                "ok": False,
                "reason": f"食物库里没有「{name}」",
                "suggestions": [h["name"] for h in self.search_food(uid, name, limit=3)],
                "hint": "请先确认这是什么食物，或提供每 100g 的热量与营养后用估算方式记录。",
            }

        if grams_override:
            grams = float(grams_override)
            amount_text = f"{grams:g}g"
        else:
            grams, amount_text = self.book.resolve_grams(item, amount or 1, unit)

        nut = nu.scale(item["nut"], grams / 100)
        meal_name = normalize_meal(meal, guess_meal_by_hour(self.now().hour))
        time_str = parse_time(time_text, MEAL_TIME.get(meal_name, "12:00"))
        entry = {
            "name": item["name"],
            "cat": item.get("cat") or cat or "其他",
            "meal": meal_name,
            "grams": round(grams, 1),
            "amount": amount,
            "unit": unit or "克",
            "amount_text": amount_text,
            "time": time_str,
            "nut": nu.to_dict(nut),
            "source": item.get("source") or "内置",
            "day": day.isoformat(),
        }
        if note:
            entry["note"] = note
        self.store.add_entry(uid, day.isoformat(), entry)

        if save_preset and nut_override:
            self.store.add_user_food(
                uid,
                name,
                {
                    "nut": nu.to_dict(nu.as_vector(nut_override)),
                    "cat": cat or "我的食物",
                    "portions": [["100克", 100]],
                    "alias": [],
                    "note": note or "AI 查询录入",
                },
            )
        self.store.save("records", "presets")
        return {"ok": True, "entry": entry, "kcal": round(nu.get(nut, "kcal")), "grams": round(grams, 1)}

    def add_food_batch(
        self,
        uid: str,
        day: date,
        items: list[dict[str, Any]],
        meal: str | None = None,
        time_text: str | None = None,
    ) -> dict[str, Any]:
        results = []
        for raw in items:
            name = raw.get("name") or raw.get("食物") or ""
            amount = raw.get("amount", raw.get("数量", 1)) or 1
            unit = raw.get("unit") or raw.get("单位")
            meal_i = raw.get("meal") or meal
            nut = None
            if raw.get("kcal_per_100g"):
                nut = {
                    "kcal": float(raw.get("kcal_per_100g") or 0),
                    "protein": float(raw.get("protein") or 0),
                    "fat": float(raw.get("fat") or 0),
                    "carb": float(raw.get("carb") or 0),
                    "fiber": float(raw.get("fiber") or 0),
                }
            res = self.add_food(
                uid,
                day,
                name,
                float(amount),
                unit,
                meal_i,
                raw.get("time") or time_text,
                nut_override=nut,
                save_preset=bool(raw.get("save_preset")),
                note=raw.get("note") or "",
            )
            results.append(res)
        ok_items = [r for r in results if r.get("ok")]
        failed = [r for r in results if not r.get("ok")]
        total = sum(r.get("kcal", 0) for r in ok_items)
        return {
            "ok": bool(ok_items),
            "added": len(ok_items),
            "failed": failed,
            "kcal": total,
            "items": ok_items,
        }

    def remove_food(self, uid: str, day: date, target: str | None = None) -> dict[str, Any]:
        entry = self.store.remove_entry(uid, day.isoformat(), target)
        if not entry:
            return {"ok": False, "reason": "没有找到要删除的记录"}
        self.store.save("records")
        return {"ok": True, "entry": entry}

    def log_water(self, uid: str, ml: int, day: date | None = None) -> dict[str, Any]:
        day = day or self.today()
        record = self.store.get_day(uid, day.isoformat(), create=True)
        record["water_ml"] = int(record.get("water_ml") or 0) + int(ml)
        self.store.save("records")
        target = self.targets(uid).get("water_ml") or 2000
        return {"ok": True, "water_ml": record["water_ml"], "target_ml": target}

    def log_exercise(
        self, uid: str, name: str, minutes: float, intensity: str = "", day: date | None = None
    ) -> dict[str, Any]:
        day = day or self.today()
        met = 0.0
        for key, value in MET_TABLE.items():
            if key in name or name in key:
                met = value
                break
        if not met:
            met = 5.0
        factor = INTENSITY_FACTOR.get(str(intensity).strip(), 1.0)
        weight = float(self.user(uid).get("weight_kg") or 65)
        kcal = met * factor * weight * (float(minutes) / 60)
        record = self.store.get_day(uid, day.isoformat(), create=True)
        record.setdefault("exercise", []).append(
            {
                "name": name,
                "minutes": float(minutes),
                "met": met,
                "kcal": round(kcal),
                "at": self.now().isoformat(timespec="minutes"),
            }
        )
        self.store.save("records")
        return {"ok": True, "name": name, "minutes": minutes, "kcal": round(kcal), "met": met}

    # ------------------------------------------------------------------ #
    # 体重
    # ------------------------------------------------------------------ #
    def add_weight(
        self, uid: str, kg: float, day: date | None = None, note: str = "", body_fat: float | None = None
    ) -> dict[str, Any]:
        day = day or self.today()
        record = self.store.add_weight(
            uid, day.isoformat(), kg, note=note, body_fat=body_fat
        )
        user = self.user(uid)
        user["weight_kg"] = round(float(kg), 1)
        user["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if not user.get("goal_start_weight"):
            user["goal_start_weight"] = round(float(kg), 1)
            user["goal_start_date"] = day.isoformat()
        self.store.save("weights", "users")

        weights = self.store.get_weights(uid)
        trend = bd.weight_trend(weights)
        delta = 0.0
        if len(weights) >= 2:
            delta = round(weights[-1]["kg"] - weights[0]["kg"], 1)
        return {
            "ok": True,
            "record": record,
            "bmi": bd.bmi_of(user),
            "bmi_label": bd.bmi_label(bd.bmi_of(user)),
            "trend_per_week": trend.get("slope_per_week"),
            "total_delta": delta,
            "targets": self.targets(uid),
        }

    # ------------------------------------------------------------------ #
    # 食谱
    # ------------------------------------------------------------------ #
    def compute_recipe(self, uid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        total = nu.zeros()
        detail = []
        for raw in items:
            name = raw.get("name") or ""
            amount = raw.get("amount", 1) or 1
            unit = raw.get("unit")
            item = self.find_food(uid, name)
            if item is None:
                continue
            try:
                grams, text = self.book.resolve_grams(item, float(amount), unit)
            except (TypeError, ValueError):
                continue
            nut = nu.scale(item["nut"], grams / 100)
            nu.accumulate(total, nut)
            detail.append(
                {
                    "name": item["name"],
                    "grams": round(grams, 1),
                    "amount_text": text,
                    "kcal": round(nu.get(nut, "kcal")),
                }
            )
        return {
            "items": detail,
            "total": nu.to_dict(total),
            "kcal": round(nu.get(total, "kcal")),
        }

    def save_recipe(
        self, uid: str, name: str, items: list[dict[str, Any]], servings: float = 1, note: str = ""
    ) -> dict[str, Any]:
        computed = self.compute_recipe(uid, items)
        if not computed["items"]:
            return {"ok": False, "reason": "食谱里的食物都没能识别"}
        payload = {
            "name": name.strip(),
            "items": items,
            "servings": max(1.0, float(servings or 1)),
            "note": note,
            "kcal": computed["kcal"],
            "total_nut": computed["total"],
            "updated_at": self.now().isoformat(timespec="seconds"),
        }
        self.store.add_recipe(uid, name.strip(), payload)
        self.store.save("presets")
        return {"ok": True, "recipe": payload, "per_serving_kcal": round(computed["kcal"] / payload["servings"])}

    def log_recipe(
        self,
        uid: str,
        name: str,
        servings: float = 1.0,
        meal: str | None = None,
        day: date | None = None,
        time_text: str | None = None,
    ) -> dict[str, Any]:
        recipes = self.store.user_recipes(uid)
        recipe = recipes.get(name)
        if not recipe:
            for key, value in recipes.items():
                if name in key or key in name:
                    recipe = value
                    break
        if not recipe:
            return {"ok": False, "reason": f"没有找到食谱「{name}」"}

        total = nu.as_vector(recipe.get("total_nut"))
        base_servings = max(1.0, float(recipe.get("servings") or 1))
        factor = float(servings or 1) / base_servings
        nut = nu.scale(total, factor)
        day = day or self.today()
        meal_name = normalize_meal(meal, guess_meal_by_hour(self.now().hour))
        entry = {
            "name": f"{recipe['name']}（{servings:g}人份）",
            "cat": "食谱",
            "meal": meal_name,
            "grams": 0,
            "amount": servings,
            "unit": "人份",
            "amount_text": f"{servings:g}人份",
            "time": parse_time(time_text, MEAL_TIME.get(meal_name, "12:00")),
            "nut": nu.to_dict(nut),
            "source": "食谱",
        }
        self.store.add_entry(uid, day.isoformat(), entry)
        self.store.save("records")
        return {
            "ok": True,
            "entry": entry,
            "kcal": round(nu.get(nut, "kcal")),
            "recipe_items": recipe.get("items"),
        }

    # ------------------------------------------------------------------ #
    # 分析
    # ------------------------------------------------------------------ #
    def coverage(self, uid: str, intake_kcal: float, targets: dict[str, Any], day: date) -> float:
        """今天的参考值按已记录比例折算；过去的日期用全天标准。"""
        if day != self.today():
            return 1.0
        if self.now().hour >= 21:
            return 1.0
        return nu.coverage_of(intake_kcal, float(targets.get("kcal") or 0))

    def analyze(self, uid: str, day: date | None = None) -> dict[str, Any]:
        day = day or self.today()
        targets = self.targets(uid)
        record = self.store.get_day(uid, day.isoformat())
        intake = an.totals_of(record.get("entries") or [])
        scale = self.coverage(uid, nu.get(intake, "kcal"), targets, day)
        result = an.analyze(record, targets, self.user(uid), self.book, scale=scale, today=day)
        result["targets"] = targets
        return result

    def weekly(self, uid: str, days: int = 7, end: date | None = None) -> dict[str, Any]:
        end = end or self.today()
        start = end - timedelta(days=days - 1)
        pairs = []
        cursor = start
        while cursor <= end:
            pairs.append((cursor.isoformat(), self.store.get_day(uid, cursor.isoformat())))
            cursor += timedelta(days=1)
        targets = self.targets(uid)
        summary = an.summarize_period(pairs, targets, self.user(uid))
        summary["start"] = start.isoformat()
        summary["end"] = end.isoformat()
        summary["targets"] = targets
        summary["weights"] = [
            w for w in self.store.get_weights(uid) if start.isoformat() <= w["date"] <= end.isoformat()
        ]
        return summary

    def meal_plan(self, uid: str, day: date | None = None) -> dict[str, Any]:
        result = self.analyze(uid, day)
        plan = an.suggest_meal(
            result["remaining_kcal"], result["remaining_protein"], self.book, self.user(uid)
        )
        return {"analysis": result, "plan": plan}

    def deficiency_plan(self, uid: str, key: str, need: float) -> list[dict[str, Any]]:
        user = self.user(uid)
        return sg.cover_gap(
            key,
            need,
            self.book,
            user_foods=self.store.user_foods(uid),
            dislikes=list(user.get("dislikes") or []),
        )

    # ------------------------------------------------------------------ #
    # 日历
    # ------------------------------------------------------------------ #
    def calendar_data(self, uid: str, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        today = self.today()
        year = year or today.year
        month = month or today.month
        from .util import month_range

        start, end = month_range(year, month)
        targets = self.targets(uid)
        records = self.store.records.get(uid, {})
        weights = {w["date"]: w for w in self.store.get_weights(uid)}

        cells = []
        cursor = start
        target_kcal = float(targets.get("kcal") or 0)
        while cursor <= end:
            key = cursor.isoformat()
            record = records.get(key) or {}
            entries = record.get("entries") or []
            kcal = round(sum(nu.get(nu.as_vector(e.get("nut")), "kcal") for e in entries))
            status = "none"
            if entries and target_kcal:
                pct = kcal / target_kcal
                if pct < 0.85:
                    status = "low"
                elif pct <= 1.05:
                    status = "ok"
                elif pct <= 1.2:
                    status = "high"
                else:
                    status = "over"
            elif entries:
                status = "ok"
            weight = weights.get(key, {}).get("kg")
            cells.append(
                {
                    "date": key,
                    "day": cursor.day,
                    "weekday": cursor.weekday(),
                    "kcal": kcal,
                    "count": len(entries),
                    "status": status,
                    "weight": weight,
                    "is_today": key == today.isoformat(),
                    "future": cursor > today,
                }
            )
            cursor += timedelta(days=1)

        logged = [c for c in cells if c["count"]]
        avg = round(sum(c["kcal"] for c in logged) / len(logged)) if logged else 0
        on_target = (
            sum(1 for c in logged if target_kcal and abs(c["kcal"] - target_kcal) <= target_kcal * 0.1)
            if target_kcal else 0
        )
        month_weights = sorted(
            [w for w in self.store.get_weights(uid) if w["date"].startswith(f"{year:04d}-{month:02d}")],
            key=lambda w: w["date"],
        )
        return {
            "year": year,
            "month": month,
            "month_label": f"{year} 年 {month} 月",
            "cells": cells,
            "target_kcal": target_kcal,
            "logged_days": len(logged),
            "avg_kcal": avg,
            "on_target_days": on_target,
            "weights": month_weights,
            "weight_delta": (
                round(month_weights[-1]["kg"] - month_weights[0]["kg"], 1)
                if len(month_weights) >= 2 else None
            ),
            "today": today.isoformat(),
            "user": self.user(uid),
            "targets": targets,
            "progress": self.progress(uid),
        }

    # ------------------------------------------------------------------ #
    # 预设总览
    # ------------------------------------------------------------------ #
    def preset_overview(self, uid: str) -> dict[str, Any]:
        foods = self.store.user_foods(uid)
        recipes = self.store.user_recipes(uid)
        return {
            "foods": list(foods.keys()),
            "recipes": [
                {
                    "name": name,
                    "items": [i.get("name") for i in (data.get("items") or [])],
                    "kcal": data.get("kcal"),
                    "servings": data.get("servings", 1),
                }
                for name, data in recipes.items()
            ],
        }
