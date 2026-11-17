# -*- coding: utf-8 -*-
"""工具注册入口：一次性构建全部 LLM 工具。"""

from __future__ import annotations

from typing import Any

from .diet import ALL_TOOLS as DIET_TOOLS
from .plan import ALL_TOOLS as PLAN_TOOLS
from .profile import ALL_TOOLS as PROFILE_TOOLS
from .report import ALL_TOOLS as REPORT_TOOLS

TOOL_CLASSES: list[Any] = [*PROFILE_TOOLS, *DIET_TOOLS, *PLAN_TOOLS, *REPORT_TOOLS]

EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "calorie_status",
        "update_profile",
        "record_weight",
        "log_food",
        "log_estimated_food",
        "lookup_food",
        "remove_food",
        "log_water",
        "log_exercise",
        "save_food_preset",
        "save_recipe",
        "log_recipe",
        "nutrition_report",
        "meal_plan",
        "food_calendar",
        "trend_report",
    }
)


def build_tools(plugin: Any) -> list[Any]:
    """每次调用都返回全新实例，避免热重载时复用旧对象。"""
    tools = []
    for cls in TOOL_CLASSES:
        tool = cls()
        tool.plugin_ref = plugin
        tools.append(tool)
    names = [tool.name for tool in tools]
    if len(set(names)) != len(names):
        raise RuntimeError(f"LLM 工具名称重复：{names}")
    missing = EXPECTED_TOOL_NAMES - set(names)
    if missing:
        raise RuntimeError(f"LLM 工具缺失：{sorted(missing)}")
    return tools


__all__ = ["build_tools", "TOOL_CLASSES", "EXPECTED_TOOL_NAMES"]
