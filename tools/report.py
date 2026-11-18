# -*- coding: utf-8 -*-
"""报告类工具：营养报告、配餐建议、日历、周期趋势。"""

from __future__ import annotations

from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..core import report as rp
from .base import CoachTool, Field, dataclass, jdump, prop, schema, uid_of, guard_private


@dataclass
class NutritionReportTool(CoachTool):
    name: str = "nutrition_report"
    description: str = (
        "生成某一天完整的营养分析：热量完成度、三餐分布、蛋白质/脂肪/碳水、"
        "维生素矿物质达标情况、营养缺口与超标项、改进建议和营养评分。"
        "用户问『我今天营养怎么样』『缺什么』『分析一下』时调用。"
        "detail=true 时返回全部 26 项营养素明细。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "date": prop("日期，默认今天；也可填 昨天/本周"),
                "detail": prop("是否返回全部营养素明细，默认 false", "boolean"),
            }
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        blocked = guard_private(context)
        if blocked:
            return blocked
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        analysis = svc.analyze(uid, day)
        targets = analysis["targets"]
        text = rp.day_card(analysis, targets, day.isoformat())
        if kwargs.get("detail"):
            text += "\n\n" + rp.analysis_detail(analysis)
        return text


@dataclass
class MealPlanTool(CoachTool):
    name: str = "meal_plan"
    description: str = (
        "根据当天剩余热量和剩余蛋白质，给出下一餐或明天的具体搭配（食物+克数+热量）。"
        "用户问『我还能吃什么』『剩下这点热量能吃什么』『帮我配一餐』时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema({"date": prop("日期，默认今天")})
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        blocked = guard_private(context)
        if blocked:
            return blocked
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        result = svc.meal_plan(uid, day)
        analysis = result["analysis"]
        plan = result["plan"]
        if not plan["items"]:
            return jdump(
                {
                    "ok": False,
                    "remaining_kcal": analysis["remaining_kcal"],
                    "reason": plan.get("note") or "今天额度已经用完",
                }
            )
        return jdump(
            {
                "ok": True,
                "remaining_kcal": analysis["remaining_kcal"],
                "remaining_protein": analysis["remaining_protein"],
                "combination": [
                    {"name": i["name"], "grams": i["grams"], "kcal": i["kcal"]}
                    for i in plan["items"]
                ],
                "total_kcal": plan["kcal"],
                "total_protein": plan["protein"],
                "gaps": [
                    {"name": g["name"], "pct": g["pct"]} for g in analysis["gaps"][:4]
                ],
            }
        )


@dataclass
class FoodCalendarTool(CoachTool):
    name: str = "food_calendar"
    description: str = (
        "返回某个月的饮食日历：每天吃了多少热量、是否达标、当天体重，以及当月平均与体重变化。"
        "用户问『这个月记录得怎么样』『看看日历』『上周吃了多少』时调用。"
        "想要图片版日历时，告诉用户可以发送指令 /饮食日历。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "year": prop("年份，如 2026", "integer"),
                "month": prop("月份 1-12", "integer"),
            }
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        blocked = guard_private(context)
        if blocked:
            return blocked
        svc = self.service
        uid = uid_of(context)
        data = svc.calendar_data(uid, kwargs.get("year"), kwargs.get("month"))
        text = rp.calendar_text(
            svc.store.records.get(uid, {}),
            svc.store.get_weights(uid),
            data["target_kcal"],
            data["year"],
            data["month"],
        )
        return jdump(
            {
                "ok": True,
                "month": data["month_label"],
                "logged_days": data["logged_days"],
                "avg_kcal": data["avg_kcal"],
                "on_target_days": data["on_target_days"],
                "weight_delta": data["weight_delta"],
                "calendar_text": text,
                "image_hint": "需要图片版可发送指令 /饮食日历",
            }
        )


@dataclass
class TrendReportTool(CoachTool):
    name: str = "trend_report"
    description: str = (
        "最近一段时间（默认 7 天，可选 30 天）的汇总趋势：平均热量、达标天数、"
        "反复出现的营养短板、体重变化。用户问『最近怎么样』『这周有进步吗』时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {"days": prop("统计天数，默认 7", "integer")}
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        blocked = guard_private(context)
        if blocked:
            return blocked
        svc = self.service
        uid = uid_of(context)
        try:
            days = int(kwargs.get("days") or 7)
        except (TypeError, ValueError):
            days = 7
        days = max(2, min(90, days))
        from datetime import date, timedelta

        end = svc.today()
        start = end - timedelta(days=days - 1)
        pairs = []
        cursor = start
        while cursor <= end:
            pairs.append((cursor.isoformat(), svc.store.get_day(uid, cursor.isoformat())))
            cursor += timedelta(days=1)
        targets = svc.targets(uid)
        text = rp.week_report(pairs, targets, svc.user(uid), svc.store.get_weights(uid))
        return text


ALL_TOOLS: list[Any] = [NutritionReportTool, MealPlanTool, FoodCalendarTool, TrendReportTool]
