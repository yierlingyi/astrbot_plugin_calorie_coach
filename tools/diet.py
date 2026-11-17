# -*- coding: utf-8 -*-
"""饮食记录、查询、饮水与运动工具。"""

from __future__ import annotations

from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..core import nutrition as nu
from ..core.report import brief
from .base import CoachTool, Field, dataclass, jdump, prop, schema, uid_of

FOOD_ITEM = {
    "type": "object",
    "properties": {
        "name": prop("食物名称，用常见叫法，如 米饭/鸡胸肉/西红柿炒鸡蛋"),
        "amount": prop("数量，默认 1", "number"),
        "unit": prop("单位：克/碗/个/份/杯/两/片…；不确定就填 克 并给克数"),
        "meal": prop("这条属于哪一餐：早餐/午餐/晚餐/加餐"),
        "kcal_per_100g": prop("可选：每 100 克热量，仅在食物库没有且你已确认时填写", "number"),
        "time": prop("时间 HH:MM"),
    },
    "required": ["name"],
}


@dataclass
class LogFoodTool(CoachTool):
    name: str = "log_food"
    description: str = (
        "记录用户吃/喝的东西，可以一次记录多种食物。只要用户提到吃了什么、喝了什么，"
        "就立即静默调用本工具记录，不要先问『要记录吗』。"
        "份量按用户说法换算（一碗米饭=1 碗、两个鸡蛋=2 个、一杯牛奶=1 杯）。"
        "若返回 unknown 列表，说明食物库里没有，需要先联网确认营养再调用 log_estimated_food。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "foods": {
                    "type": "array",
                    "description": "要记录的食物列表",
                    "items": FOOD_ITEM,
                },
                "date": prop("日期，如 今天/昨天/2026-11-16，默认今天"),
                "meal": prop("默认餐次，食物项里没写时用它"),
                "time": prop("默认时间 HH:MM"),
                "note": prop("备注"),
            },
            ["foods"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        foods = kwargs.get("foods") or []
        if not isinstance(foods, list) or not foods:
            return jdump({"ok": False, "reason": "foods 不能为空"})

        day = svc.resolve_day(kwargs.get("date"))
        default_meal = kwargs.get("meal")
        default_time = kwargs.get("time")
        added: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []

        for raw in foods:
            if isinstance(raw, str):
                raw = {"name": raw}
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            amount = raw.get("amount", 1)
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = 1.0
            unit = raw.get("unit")
            nut_override = None
            if raw.get("kcal_per_100g"):
                nut_override = {
                    "kcal": float(raw.get("kcal_per_100g") or 0),
                    "protein": float(raw.get("protein") or 0),
                    "fat": float(raw.get("fat") or 0),
                    "carb": float(raw.get("carb") or 0),
                    "fiber": float(raw.get("fiber") or 0),
                }
            res = svc.add_food(
                uid,
                day,
                name,
                amount,
                unit,
                raw.get("meal") or default_meal,
                raw.get("time") or default_time,
                nut_override=nut_override,
                save_preset=bool(nut_override),
                note=str(kwargs.get("note") or ""),
            )
            if res.get("ok"):
                entry = res["entry"]
                added.append(
                    {
                        "name": entry["name"],
                        "amount_text": entry["amount_text"],
                        "meal": entry["meal"],
                        "kcal": res["kcal"],
                        "grams": res["grams"],
                    }
                )
            else:
                unknown.append(
                    {
                        "input": name,
                        "reason": res.get("reason"),
                        "suggestions": res.get("suggestions") or [],
                    }
                )

        analysis = svc.analyze(uid, day)
        return jdump(
            {
                "ok": bool(added),
                "date": day.isoformat(),
                "added": added,
                "unknown": unknown,
                "today": {
                    "kcal_in": analysis["kcal_in"],
                    "kcal_target": analysis["target_kcal"],
                    "remaining_kcal": analysis["remaining_kcal"],
                    "remaining_protein": analysis["remaining_protein"],
                    "kcal_pct": analysis["kcal_pct"],
                },
                "summary": brief(analysis),
                "alerts": [a["text"] for a in analysis["alerts"][:3]],
                "next": (
                    "食物库没有的条目：请联网确认每 100g 热量与营养，再调用 log_estimated_food 记录。"
                    if unknown else ""
                ),
            }
        )


@dataclass
class LogEstimatedFoodTool(CoachTool):
    name: str = "log_estimated_food"
    description: str = (
        "记录食物库里没有的食物（通常是联网查到营养数据的外卖、品牌食品、地方菜）。"
        "按每 100 克营养填写，工具会换算成实际份量并自动存入用户的个人食物库，下次可直接用名字记录。"
        "数据必须来自联网查询或包装标示，不要凭感觉编造。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("食物名称"),
                "grams": prop("实际吃了多少克", "number"),
                "kcal_per_100g": prop("每 100 克热量", "number"),
                "protein_per_100g": prop("每 100 克蛋白质 g", "number"),
                "fat_per_100g": prop("每 100 克脂肪 g", "number"),
                "carb_per_100g": prop("每 100 克碳水 g", "number"),
                "fiber_per_100g": prop("每 100 克膳食纤维 g", "number"),
                "sodium_per_100g": prop("每 100 克钠 mg", "number"),
                "calcium_per_100g": prop("每 100 克钙 mg", "number"),
                "iron_per_100g": prop("每 100 克铁 mg", "number"),
                "vc_per_100g": prop("每 100 克维生素C mg", "number"),
                "meal": prop("早餐/午餐/晚餐/加餐"),
                "date": prop("日期，默认今天"),
                "time": prop("时间 HH:MM"),
                "save": prop("是否存入个人食物库，默认 true", "boolean"),
            },
            ["name", "grams", "kcal_per_100g"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        name = str(kwargs.get("name") or "").strip()
        try:
            grams = float(kwargs.get("grams"))
            kcal100 = float(kwargs.get("kcal_per_100g"))
        except (TypeError, ValueError):
            return jdump({"ok": False, "reason": "grams 与 kcal_per_100g 必须是数字"})
        if grams <= 0 or kcal100 <= 0:
            return jdump({"ok": False, "reason": "克数或热量必须大于 0"})

        nut = {
            "kcal": kcal100,
            "protein": float(kwargs.get("protein_per_100g") or 0),
            "fat": float(kwargs.get("fat_per_100g") or 0),
            "carb": float(kwargs.get("carb_per_100g") or 0),
            "fiber": float(kwargs.get("fiber_per_100g") or 0),
            "sodium": float(kwargs.get("sodium_per_100g") or 0),
            "calcium": float(kwargs.get("calcium_per_100g") or 0),
            "iron": float(kwargs.get("iron_per_100g") or 0),
            "vc": float(kwargs.get("vc_per_100g") or 0),
        }
        save = kwargs.get("save")
        save = True if save is None else bool(save)
        res = svc.add_food(
            uid,
            day,
            name,
            grams,
            "克",
            kwargs.get("meal"),
            kwargs.get("time"),
            nut_override=nut,
            cat="联网查询",
            save_preset=save,
            grams_override=grams,
        )
        analysis = svc.analyze(uid, day)
        return jdump(
            {
                "ok": res.get("ok"),
                "entry": {
                    "name": name,
                    "grams": grams,
                    "kcal": res.get("kcal"),
                }
                if res.get("ok") else None,
                "saved_to_library": save,
                "today": {
                    "kcal_in": analysis["kcal_in"],
                    "kcal_target": analysis["target_kcal"],
                    "remaining_kcal": analysis["remaining_kcal"],
                },
                "summary": brief(analysis),
                "alerts": [a["text"] for a in analysis["alerts"][:3]],
            }
        )


@dataclass
class LookupFoodTool(CoachTool):
    name: str = "lookup_food"
    description: str = (
        "查询某个食物的热量与营养（不记录）。用户问『XX 多少卡』『一碗面条热量高吗』，"
        "或者你不确定份量对应多少克时调用。会返回每 100 克营养、常见份量换算和相似食物。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "query": prop("食物名称或关键词"),
                "amount": prop("数量，可选", "number"),
                "unit": prop("单位，可选：碗/个/份/克"),
            },
            ["query"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return jdump({"ok": False, "reason": "query 不能为空"})
        amount = kwargs.get("amount") or 0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0
        result = svc.lookup(uid, query, amount, kwargs.get("unit"))
        return jdump(result)


@dataclass
class RemoveFoodTool(CoachTool):
    name: str = "remove_food"
    description: str = (
        "删除一条饮食记录。用户说『记错了』『不算那杯奶茶』『删掉早饭』时调用。"
        "不传 name 时删除该餐最后一条记录。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("要删除的食物名或记录 id，不填则删最后一条"),
                "meal": prop("限定餐次"),
                "date": prop("日期，默认今天"),
            }
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        name = kwargs.get("name")
        meal = kwargs.get("meal")
        entries = svc.store.day_entries(uid, day.isoformat())
        if meal and not name:
            meal_entries = [e for e in entries if e.get("meal") == meal]
            if not meal_entries:
                return jdump({"ok": False, "reason": f"{meal}没有记录"})
            name = meal_entries[-1].get("id")
        result = svc.remove_food(uid, day, str(name) if name else None)
        if not result.get("ok"):
            return jdump({"ok": False, "reason": result.get("reason")})
        analysis = svc.analyze(uid, day)
        return jdump(
            {
                "ok": True,
                "removed": {
                    "name": result["entry"].get("name"),
                    "kcal": round(nu.get(nu.as_vector(result["entry"].get("nut")), "kcal")),
                },
                "today": {
                    "kcal_in": analysis["kcal_in"],
                    "remaining_kcal": analysis["remaining_kcal"],
                },
            }
        )


@dataclass
class LogWaterTool(CoachTool):
    name: str = "log_water"
    description: str = "记录喝水量。用户说『喝了500ml水』『今天喝了两瓶水』时调用。"
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "ml": prop("毫升数", "number"),
                "date": prop("日期，默认今天"),
            },
            ["ml"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        try:
            ml = int(float(kwargs.get("ml")))
        except (TypeError, ValueError):
            return jdump({"ok": False, "reason": "ml 必须是数字"})
        day = svc.resolve_day(kwargs.get("date"))
        result = svc.log_water(uid, ml, day)
        return jdump({"ok": True, "date": day.isoformat(), **result})


@dataclass
class LogExerciseTool(CoachTool):
    name: str = "log_exercise"
    description: str = (
        "记录运动并估算消耗的热量（基于 MET 与体重）。用户说『跑步半小时』『游泳40分钟』时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("运动名称，如 跑步/快走/游泳/力量训练"),
                "minutes": prop("时长（分钟）", "number"),
                "intensity": prop("强度：低/中/高"),
                "date": prop("日期，默认今天"),
            },
            ["name", "minutes"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        try:
            minutes = float(kwargs.get("minutes"))
        except (TypeError, ValueError):
            return jdump({"ok": False, "reason": "minutes 必须是数字"})
        day = svc.resolve_day(kwargs.get("date"))
        result = svc.log_exercise(
            uid, str(kwargs.get("name") or "运动"), minutes, str(kwargs.get("intensity") or ""), day
        )
        return jdump({"ok": True, "date": day.isoformat(), **result})


ALL_TOOLS: list[Any] = [
    LogFoodTool,
    LogEstimatedFoodTool,
    LookupFoodTool,
    RemoveFoodTool,
    LogWaterTool,
    LogExerciseTool,
]
