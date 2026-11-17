# -*- coding: utf-8 -*-
"""预设食物与食谱工具。"""

from __future__ import annotations

from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..core import nutrition as nu
from .base import CoachTool, Field, dataclass, jdump, prop, schema, uid_of


@dataclass
class SaveFoodPresetTool(CoachTool):
    name: str = "save_food_preset"
    description: str = (
        "把一种食物存进用户的个人食物库（预设食物），以后说名字就能直接记录。"
        "用户说『以后就按这个算』『把这个加进我的食物库』，或某种自制菜/品牌食品会经常吃时调用。"
        "营养按每 100 克填写，可同时定义常用份量。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("食物名称"),
                "kcal_per_100g": prop("每 100 克热量", "number"),
                "protein_per_100g": prop("蛋白质 g", "number"),
                "fat_per_100g": prop("脂肪 g", "number"),
                "carb_per_100g": prop("碳水 g", "number"),
                "fiber_per_100g": prop("膳食纤维 g", "number"),
                "sodium_per_100g": prop("钠 mg", "number"),
                "alias": prop("别名，数组", "array", items={"type": "string"}),
                "portions": {
                    "type": "array",
                    "description": "常用份量，如 [{\"label\":\"一碗\",\"grams\":200}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": prop("份量说法，如 一碗/一个"),
                            "grams": prop("对应克数", "number"),
                        },
                        "required": ["label", "grams"],
                    },
                },
            },
            ["name", "kcal_per_100g"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        name = str(kwargs.get("name") or "").strip()
        try:
            kcal = float(kwargs.get("kcal_per_100g"))
        except (TypeError, ValueError):
            return jdump({"ok": False, "reason": "kcal_per_100g 必须是数字"})
        if not name:
            return jdump({"ok": False, "reason": "name 不能为空"})

        nut = {
            "kcal": kcal,
            "protein": float(kwargs.get("protein_per_100g") or 0),
            "fat": float(kwargs.get("fat_per_100g") or 0),
            "carb": float(kwargs.get("carb_per_100g") or 0),
            "fiber": float(kwargs.get("fiber_per_100g") or 0),
            "sodium": float(kwargs.get("sodium_per_100g") or 0),
        }
        portions = []
        for raw in kwargs.get("portions") or []:
            try:
                portions.append([str(raw.get("label")), float(raw.get("grams"))])
            except (TypeError, ValueError, AttributeError):
                continue
        if not portions:
            portions = [["100克", 100]]

        svc.store.add_user_food(
            uid,
            name,
            {
                "nut": nu.to_dict(nu.as_vector(nut)),
                "cat": "我的食物",
                "alias": list(kwargs.get("alias") or []),
                "portions": portions,
                "note": "AI 录入",
                "updated_at": svc.now().isoformat(timespec="seconds"),
            },
        )
        svc.store.save("presets")
        return jdump(
            {
                "ok": True,
                "saved": name,
                "kcal_per_100g": kcal,
                "portions": portions,
                "total_foods": len(svc.store.user_foods(uid)),
            }
        )


@dataclass
class SaveRecipeTool(CoachTool):
    name: str = "save_recipe"
    description: str = (
        "保存一个预设食谱（一顿饭的固定搭配），例如『我的减脂早餐：两个鸡蛋+一杯牛奶+一片全麦面包』。"
        "食谱里的食物可以是内置食物，也可以是之前用 save_food_preset 存过的自定义食物。"
        "保存后可用 log_recipe 一句话记录整餐。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("食谱名称，如 减脂早餐"),
                "items": {
                    "type": "array",
                    "description": "食谱包含的食物",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": prop("食物名称"),
                            "amount": prop("数量", "number"),
                            "unit": prop("单位，如 个/碗/克"),
                        },
                        "required": ["name"],
                    },
                },
                "servings": prop("这份食谱是几人份，默认 1", "number"),
                "note": prop("备注"),
            },
            ["name", "items"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        name = str(kwargs.get("name") or "").strip()
        items = kwargs.get("items") or []
        if not name or not items:
            return jdump({"ok": False, "reason": "需要 name 与 items"})
        result = svc.save_recipe(
            uid, name, items, float(kwargs.get("servings") or 1), str(kwargs.get("note") or "")
        )
        if not result.get("ok"):
            return jdump({"ok": False, "reason": result.get("reason")})
        recipe = result["recipe"]
        return jdump(
            {
                "ok": True,
                "name": recipe["name"],
                "items": recipe["items"],
                "total_kcal": recipe["kcal"],
                "per_serving_kcal": result["per_serving_kcal"],
                "servings": recipe["servings"],
            }
        )


@dataclass
class LogRecipeTool(CoachTool):
    name: str = "log_recipe"
    description: str = (
        "按预设食谱记录一整餐。用户说『吃了减脂早餐』『晚餐照食谱来』时调用，"
        "不用再一样一样报食物。份数默认 1。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "name": prop("食谱名称"),
                "servings": prop("吃了几人份，默认 1", "number"),
                "meal": prop("早餐/午餐/晚餐/加餐"),
                "date": prop("日期，默认今天"),
                "time": prop("时间 HH:MM"),
            },
            ["name"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        result = svc.log_recipe(
            uid,
            str(kwargs.get("name") or ""),
            float(kwargs.get("servings") or 1),
            kwargs.get("meal"),
            day,
            kwargs.get("time"),
        )
        if not result.get("ok"):
            recipes = list(svc.store.user_recipes(uid).keys())
            return jdump({"ok": False, "reason": result.get("reason"), "available": recipes})
        analysis = svc.analyze(uid, day)
        return jdump(
            {
                "ok": True,
                "name": result["entry"]["name"],
                "kcal": result["kcal"],
                "items": result["recipe_items"],
                "today": {
                    "kcal_in": analysis["kcal_in"],
                    "kcal_target": analysis["target_kcal"],
                    "remaining_kcal": analysis["remaining_kcal"],
                },
                "alerts": [a["text"] for a in analysis["alerts"][:2]],
            }
        )


ALL_TOOLS: list[Any] = [SaveFoodPresetTool, SaveRecipeTool, LogRecipeTool]
