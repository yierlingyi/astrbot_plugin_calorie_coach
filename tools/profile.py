# -*- coding: utf-8 -*-
"""档案与体重相关工具。"""

from __future__ import annotations

from typing import Any

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..core import body as bd
from .base import CoachTool, Field, dataclass, jdump, prop, schema, uid_of


@dataclass
class GetStatusTool(CoachTool):
    name: str = "calorie_status"
    description: str = (
        "查询当前用户的减重档案与今日进度：身高体重年龄、基础代谢、每日热量目标、"
        "今天已吃多少/还剩多少、缺哪些营养、有哪些预设食物和食谱。"
        "在对话开始、用户问『我还能吃多少』『今天怎么样』『我的目标是多少』时必须先调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {"date": prop("要查询的日期，如 2026-11-17 或 昨天；不填默认今天")}
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        day = svc.resolve_day(kwargs.get("date"))
        targets = svc.targets(uid)
        analysis = svc.analyze(uid, day)
        user = svc.user(uid)
        progress = svc.progress(uid)
        return jdump(
            {
                "date": day.isoformat(),
                "profile": {
                    "name": user.get("name") or "",
                    "sex": user.get("sex"),
                    "age": bd.age_of(user, day),
                    "height_cm": user.get("height_cm"),
                    "weight_kg": user.get("weight_kg"),
                    "activity": user.get("activity"),
                    "goal": user.get("goal"),
                    "target_weight_kg": user.get("target_weight_kg"),
                    "target_days": user.get("target_days"),
                    "dislikes": user.get("dislikes") or [],
                    "allergies": user.get("allergies") or [],
                    "complete": svc.profile_ready(uid),
                    "missing": targets.get("missing") or [],
                },
                "targets": {
                    "bmr": targets.get("bmr"),
                    "tdee": targets.get("tdee"),
                    "kcal": targets.get("kcal"),
                    "protein_g": targets.get("protein_g"),
                    "fat_g": targets.get("fat_g"),
                    "carb_g": targets.get("carb_g"),
                    "deficit": targets.get("deficit"),
                    "eta_days": targets.get("eta_days"),
                    "warnings": targets.get("warnings") or [],
                },
                "today": {
                    "kcal_in": analysis["kcal_in"],
                    "kcal_target": analysis["target_kcal"],
                    "kcal_pct": analysis["kcal_pct"],
                    "remaining_kcal": analysis["remaining_kcal"],
                    "remaining_protein": analysis["remaining_protein"],
                    "protein_g": analysis["item_map"]["protein"]["value"],
                    "meals_logged": analysis["meals_logged"],
                    "entry_count": len(analysis["entries"]),
                    "gaps": [
                        {"name": g["name"], "pct": g["pct"], "value": g["value"], "unit": g["unit"]}
                        for g in analysis["gaps"][:5]
                    ],
                    "excess": [
                        {"name": g["name"], "pct": g["pct"], "value": g["value"], "unit": g["unit"]}
                        for g in analysis["excess"][:3]
                    ],
                    "score": analysis["score"],
                    "reference_scaled_to": analysis["scale"],
                },
                "progress": {
                    "current": progress.get("current"),
                    "target": progress.get("target"),
                    "lost": progress.get("lost"),
                    "remaining": progress.get("remaining"),
                    "pct": progress.get("pct"),
                    "trend_per_week": (progress.get("trend") or {}).get("slope_per_week"),
                },
                "presets": svc.preset_overview(uid),
            }
        )


@dataclass
class UpdateProfileTool(CoachTool):
    name: str = "update_profile"
    description: str = (
        "创建或更新用户的减重档案：身高、体重、年龄/出生年、性别、活动量、目标类型、"
        "目标体重、计划天数、忌口与过敏。用户在聊天中提到这些信息时立即调用，不要追问无关细节。"
        "更新后会返回新的基础代谢、每日热量目标与可行性提醒。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "height_cm": prop("身高，厘米", "number"),
                "weight_kg": prop("体重，公斤", "number"),
                "age": prop("年龄，岁", "integer"),
                "birth_year": prop("出生年份，如 1998（比年龄更准，优先用这个）", "integer"),
                "sex": prop("性别", "string", enum=["male", "female"]),
                "activity": prop(
                    "活动量", "string",
                    enum=["sedentary", "light", "moderate", "active", "very_active"],
                ),
                "goal": prop("目标", "string", enum=["lose", "maintain", "gain"]),
                "target_weight_kg": prop("期望减到/增到多少公斤", "number"),
                "target_days": prop("希望用多少天达成", "integer"),
                "dislikes": prop("不吃/讨厌的食物，数组", "array", items={"type": "string"}),
                "allergies": prop("过敏食物，数组", "array", items={"type": "string"}),
                "diet_prefs": prop("饮食偏好，如 素食/低碳/清真，数组", "array", items={"type": "string"}),
                "paused": prop(
                    "是否暂停记录与提醒：用户说「不想记了/别管我」时设为 true，"
                    "用户说「继续记录」时设为 false",
                    "boolean",
                ),
                "name": prop("称呼"),
            }
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        fields = {k: v for k, v in kwargs.items() if v not in (None, "", [])}
        if not fields:
            return jdump({"ok": False, "reason": "没有提供任何可更新的字段"})
        if "paused" in fields and len(fields) == 1:
            user = svc.update_profile(uid, fields)
            return jdump(
                {
                    "ok": True,
                    "paused": bool(user.get("paused")),
                    "message": "已暂停记录与提醒，用户主动要求前不要再记录"
                    if user.get("paused")
                    else "已恢复记录与提醒",
                }
            )
        user = svc.update_profile(uid, fields)
        targets = svc.targets(uid)
        return jdump(
            {
                "ok": True,
                "saved": fields,
                "profile": {
                    "height_cm": user.get("height_cm"),
                    "weight_kg": user.get("weight_kg"),
                    "birth_year": user.get("birth_year"),
                    "age": user.get("age"),
                    "sex": user.get("sex"),
                    "activity": user.get("activity"),
                    "goal": user.get("goal"),
                    "target_weight_kg": user.get("target_weight_kg"),
                    "target_days": user.get("target_days"),
                },
                "targets": {
                    "bmr": targets.get("bmr"),
                    "tdee": targets.get("tdee"),
                    "kcal": targets.get("kcal"),
                    "protein_g": targets.get("protein_g"),
                    "fat_g": targets.get("fat_g"),
                    "carb_g": targets.get("carb_g"),
                    "deficit": targets.get("deficit"),
                    "eta_days": targets.get("eta_days"),
                    "complete": targets.get("ready"),
                    "missing": targets.get("missing") or [],
                    "warnings": targets.get("warnings") or [],
                },
            }
        )


@dataclass
class RecordWeightTool(CoachTool):
    name: str = "record_weight"
    description: str = (
        "记录一次体重（只在用户真的称了体重时调用）。返回 BMI、与上次相比的变化、"
        "近期趋势和新的热量目标。用户说『今天68.5』『早上称了体重』时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: schema(
            {
                "weight_kg": prop("体重，公斤", "number"),
                "date": prop("称重日期，如 今天/昨天/2026-11-16，默认今天"),
                "body_fat": prop("体脂率百分比，有就填", "number"),
                "note": prop("备注，如 早上空腹"),
            },
            ["weight_kg"],
        )
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        svc = self.service
        uid = uid_of(context)
        try:
            kg = float(kwargs.get("weight_kg"))
        except (TypeError, ValueError):
            return jdump({"ok": False, "reason": "体重数值不合法"})
        if not 20 <= kg <= 400:
            return jdump({"ok": False, "reason": "体重看起来不合理，请确认一下单位是不是公斤"})

        day = svc.resolve_day(kwargs.get("date"))
        body_fat = kwargs.get("body_fat")
        result = svc.add_weight(
            uid,
            kg,
            day,
            note=str(kwargs.get("note") or ""),
            body_fat=float(body_fat) if body_fat else None,
        )
        return jdump(
            {
                "ok": True,
                "date": day.isoformat(),
                "weight_kg": kg,
                "bmi": result["bmi"],
                "bmi_label": result["bmi_label"],
                "total_delta": result["total_delta"],
                "trend_per_week": result["trend_per_week"],
                "targets": {
                    "kcal": result["targets"].get("kcal"),
                    "protein_g": result["targets"].get("protein_g"),
                    "eta_days": result["targets"].get("eta_days"),
                },
            }
        )


ALL_TOOLS: list[Any] = [GetStatusTool, UpdateProfileTool, RecordWeightTool]
