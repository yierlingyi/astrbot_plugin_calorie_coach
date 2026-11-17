# -*- coding: utf-8 -*-
"""LLM 工具基类与公共辅助。"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


def event_of(context: Any) -> Any:
    """取出 AstrMessageEvent。"""
    try:
        return context.context.event
    except AttributeError:
        return None


def uid_of(context: Any) -> str:
    """稳定用户标识：优先平台用户 ID，退化为会话来源。"""
    event = event_of(context)
    if event is None:
        return "default"
    fn = getattr(event, "get_sender_id", None)
    if callable(fn):
        try:
            value = fn()
            if value:
                return str(value)
        except Exception:  # noqa: BLE001 - 各适配器实现差异较大
            pass
    obj = getattr(event, "message_obj", None)
    sender = getattr(obj, "sender", None)
    for value in (getattr(sender, "user_id", None), getattr(obj, "sender_id", None)):
        if value:
            return str(value)
    return str(getattr(event, "unified_msg_origin", "default") or "default")


def umo_of(context: Any) -> str:
    event = event_of(context)
    return str(getattr(event, "unified_msg_origin", "") or "")


def platform_of(context: Any) -> str:
    event = event_of(context)
    fn = getattr(event, "get_platform_name", None)
    if callable(fn):
        try:
            return str(fn() or "")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def sender_name_of(context: Any) -> str:
    event = event_of(context)
    fn = getattr(event, "get_sender_name", None)
    if callable(fn):
        try:
            return str(fn() or "")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def jdump(payload: Any) -> str:
    """把结果序列化成紧凑 JSON，模型解析更准确。"""
    return json.dumps(payload, ensure_ascii=False, default=str)


def schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def prop(desc: str, type_: str = "string", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": type_, "description": desc}
    out.update(extra)
    return out


class CoachTool(FunctionTool[AstrAgentContext]):
    """所有工具的共同基类。

    插件实例通过 ``plugin_ref`` 注入（不声明成 dataclass 字段，避免 pydantic
    把插件对象当成需要校验/序列化的数据）。这种写法与 AstrBot 官方示例和
    主流插件的做法一致。
    """

    plugin_ref: ClassVar[Any] = None

    @property
    def service(self) -> Any:
        return getattr(self.plugin_ref, "service", None)


__all__ = [
    "CoachTool",
    "ContextWrapper",
    "FunctionTool",
    "ToolExecResult",
    "AstrAgentContext",
    "Field",
    "dataclass",
    "event_of",
    "uid_of",
    "umo_of",
    "platform_of",
    "sender_name_of",
    "jdump",
    "schema",
    "prop",
]
