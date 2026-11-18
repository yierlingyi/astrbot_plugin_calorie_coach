# -*- coding: utf-8 -*-
"""端到端自测：用桩模块模拟 AstrBot 运行时，真实调用全部 16 个工具与指令。

跑法：python scripts/stub_e2e.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Generic, TypeVar

ROOT = Path(__file__).resolve().parent.parent
T = TypeVar("T")

# --------------------------------------------------------------------------- #
# 1. 构造 astrbot 桩模块（尽量贴近真实 API 形状）
# --------------------------------------------------------------------------- #
from pydantic import Field  # noqa: E402
from pydantic.dataclasses import dataclass  # noqa: E402


def _mod(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


class _Logger:
    def info(self, *a, **k):
        print("[info]", *a)

    def warning(self, *a, **k):
        print("[warn]", *a)

    def error(self, *a, **k):
        print("[error]", *a)

    def debug(self, *a, **k):
        pass

    def exception(self, *a, **k):
        print("[exc]", *a)


astrbot = _mod("astrbot")
api = _mod("astrbot.api")
api.logger = _Logger()
api.AstrBotConfig = dict
astrbot.api = api

event_mod = _mod("astrbot.api.event")


class AstrMessageEvent:
    def __init__(self, uid: str = "10001", umo: str = "aiocqhttp:FriendMessage:1", text: str = ""):
        self._uid = uid
        self.unified_msg_origin = umo
        self.message_str = text
        self.results: list[str] = []

    def get_sender_id(self):
        return self._uid

    def get_sender_name(self):
        return "小明"

    def get_platform_name(self):
        return "aiocqhttp"

    def plain_result(self, text):
        self.results.append(text)
        return text

    def image_result(self, url):
        self.results.append(f"[image]{url}")
        return url


class MessageChain:
    def __init__(self):
        self.text = ""

    def message(self, text):
        self.text = text
        return self


class _Filter:
    def command(self, *a, **k):
        def deco(fn):
            return fn

        return deco

    def on_llm_request(self, *a, **k):
        def deco(fn):
            return fn

        return deco

    def on_llm_response(self, *a, **k):
        def deco(fn):
            return fn

        return deco


event_mod.AstrMessageEvent = AstrMessageEvent
event_mod.MessageChain = MessageChain
event_mod.filter = _Filter()
astrbot.api.event = event_mod

provider_mod = _mod("astrbot.api.provider")


class ProviderRequest:
    def __init__(self):
        self.system_prompt = ""
        self.prompt = ""


class LLMResponse:
    def __init__(self, text: str):
        self.completion_text = text


provider_mod.ProviderRequest = ProviderRequest
provider_mod.LLMResponse = LLMResponse
astrbot.api.provider = provider_mod

star_mod = _mod("astrbot.api.star")


class Context:
    def __init__(self):
        self.tools: list[Any] = []
        self.sent: list[tuple[str, str]] = []

    def add_llm_tools(self, *tools):
        self.tools.extend(tools)

    def get_config(self):
        return {"timezone": "Asia/Shanghai"}

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain.text))
        return True


class Star:
    def __init__(self, context):
        self.context = context

    async def html_render(self, tmpl, data, return_url=False, options=None):
        return "file:///fake_calendar.png"


class StarTools:
    data_dir = Path(tempfile.mkdtemp(prefix="coach_"))

    @staticmethod
    def get_data_dir():
        return StarTools.data_dir


star_mod.Context = Context
star_mod.Star = Star
star_mod.StarTools = StarTools
astrbot.api.star = star_mod

# astrbot.core.agent.tool
core = _mod("astrbot.core")
agent = _mod("astrbot.core.agent")
agent_tool = _mod("astrbot.core.agent.tool")
run_context = _mod("astrbot.core.agent.run_context")
agent_ctx = _mod("astrbot.core.astr_agent_context")
core.agent = agent
astrbot.core = core


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict


@dataclass
class FunctionTool(ToolSchema, Generic[T]):
    handler: Any = None
    handler_module_path: str | None = None
    active: bool = True
    is_background_task: bool = False
    execution_timeout: float | None = None

    async def call(self, context, **kwargs):
        raise NotImplementedError


ToolExecResult = str
agent_tool.FunctionTool = FunctionTool
agent_tool.ToolExecResult = ToolExecResult
agent_tool.ToolSchema = ToolSchema
agent.tool = agent_tool


class ContextWrapper(Generic[T]):
    def __init__(self, context):
        self.context = context


run_context.ContextWrapper = ContextWrapper
agent.run_context = run_context


class AstrAgentContext:
    def __init__(self, event):
        self.event = event
        self.context = None


agent_ctx.AstrAgentContext = AstrAgentContext
core.astr_agent_context = agent_ctx

# --------------------------------------------------------------------------- #
# 2. 导入插件并初始化
# --------------------------------------------------------------------------- #
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(Path.home() / "Desktop"))

import importlib  # noqa: E402

pkg_name = ROOT.name
plugin_main = importlib.import_module(f"{pkg_name}.main")


def wrap(event, uid=None):
    agent_context = AstrAgentContext(event)
    return ContextWrapper(agent_context)


async def main() -> None:
    star_ctx = Context()
    config = {
        "enable": True,
        "timezone": "Asia/Shanghai",
        "passive_hint": True,
        "calendar_image": True,
    }
    plugin = plugin_main.CalorieCoachPlugin(star_ctx, config)
    await plugin.initialize()
    assert plugin.service is not None

    tools = {t.name: t for t in plugin._tools}
    print(f"\n已注册工具 {len(tools)} 个：{sorted(tools)}\n")

    event = AstrMessageEvent()
    ctx = wrap(event)

    # --- 1. 建档 ---
    print("=== update_profile ===")
    out = await tools["update_profile"].call(
        ctx,
        height_cm=175,
        weight_kg=82,
        age=28,
        sex="male",
        activity="light",
        goal="lose",
        target_weight_kg=72,
        target_days=120,
    )
    print(out[:400])
    assert '"ok": true' in out

    # --- 2. 记录早餐 ---
    print("\n=== log_food ===")
    out = await tools["log_food"].call(
        ctx,
        foods=[
            {"name": "包子（肉馅）", "amount": 2, "unit": "个"},
            {"name": "豆浆（无糖）", "amount": 1, "unit": "杯"},
            {"name": "茶叶蛋", "amount": 1, "unit": "个"},
        ],
        meal="早餐",
        time="07:40",
    )
    print(out[:600])
    assert '"added"' in out

    # --- 3. 未知食物 ---
    print("\n=== log_food（未知食物） ===")
    out = await tools["log_food"].call(ctx, foods=[{"name": "麦当劳巨无霸"}])
    print(out[:300])

    print("\n=== log_estimated_food ===")
    out = await tools["log_estimated_food"].call(
        ctx,
        name="麦当劳巨无霸",
        grams=215,
        kcal_per_100g=257,
        protein_per_100g=12.6,
        fat_per_100g=13.5,
        carb_per_100g=20.5,
        fiber_per_100g=1.4,
        sodium_per_100g=220,
        meal="午餐",
        time="12:30",
    )
    print(out[:400])
    assert '"ok": true' in out

    # --- 4. 午餐 + 奶茶 ---
    print("\n=== log_food 午餐 ===")
    out = await tools["log_food"].call(
        ctx,
        foods=[
            {"name": "米饭", "amount": 1, "unit": "碗"},
            {"name": "西红柿炒鸡蛋", "amount": 1, "unit": "份"},
            {"name": "奶茶（全糖）", "amount": 1, "unit": "杯"},
        ],
        meal="午餐",
    )
    print(out[:400])

    # --- 5. 查询 ---
    print("\n=== lookup_food ===")
    out = await tools["lookup_food"].call(ctx, query="土豆丝", amount=1, unit="份")
    print(out[:400])

    # --- 6. 状态 ---
    print("\n=== calorie_status ===")
    out = await tools["calorie_status"].call(ctx)
    print(out[:700])

    # --- 7. 营养报告 ---
    print("\n=== nutrition_report ===")
    out = await tools["nutrition_report"].call(ctx, detail=True)
    print(out[:1200])

    # --- 8. 配餐 ---
    print("\n=== meal_plan ===")
    print((await tools["meal_plan"].call(ctx))[:400])

    # --- 9. 体重 ---
    print("\n=== record_weight ===")
    print((await tools["record_weight"].call(ctx, weight_kg=81.6, note="早上空腹"))[:400])

    # --- 10. 食谱 ---
    print("\n=== save_recipe ===")
    print(
        (
            await tools["save_recipe"].call(
                ctx,
                name="减脂早餐",
                items=[
                    {"name": "鸡蛋", "amount": 2, "unit": "个"},
                    {"name": "纯牛奶", "amount": 1, "unit": "杯"},
                    {"name": "全麦面包", "amount": 2, "unit": "片"},
                ],
                servings=1,
            )
        )[:400]
    )
    print("\n=== log_recipe ===")
    print((await tools["log_recipe"].call(ctx, name="减脂早餐", meal="加餐"))[:400])

    # --- 11. 预设食物 ---
    print("\n=== save_food_preset ===")
    print(
        (
            await tools["save_food_preset"].call(
                ctx,
                name="妈妈的杂粮饭",
                kcal_per_100g=135,
                protein_per_100g=4.2,
                fat_per_100g=1.5,
                carb_per_100g=26,
                portions=[{"label": "一碗", "grams": 180}],
            )
        )[:300]
    )
    print("\n=== log_food 自定义食物 ===")
    print(
        (
            await tools["log_food"].call(
                ctx, foods=[{"name": "妈妈的杂粮饭", "amount": 1, "unit": "碗"}], meal="晚餐"
            )
        )[:300]
    )

    # --- 12. 饮水/运动/删除 ---
    print("\n=== log_water / log_exercise ===")
    print((await tools["log_water"].call(ctx, ml=500))[:200])
    print((await tools["log_exercise"].call(ctx, name="快走", minutes=40, intensity="中"))[:200])
    print("\n=== remove_food ===")
    print((await tools["remove_food"].call(ctx, name="奶茶（全糖）"))[:200])

    # --- 13. 日历/趋势 ---
    print("\n=== food_calendar ===")
    print((await tools["food_calendar"].call(ctx))[:600])
    print("\n=== trend_report ===")
    print((await tools["trend_report"].call(ctx, days=7))[:600])

    # --- 14. 钩子 ---
    print("\n=== on_llm_request（注入提示词） ===")
    req = ProviderRequest()
    await plugin.inject_status(event, req)
    print(req.system_prompt[:900])

    print("\n=== on_llm_response（顺口提醒） ===")
    resp = LLMResponse("这顿吃得不错。")
    await plugin.append_hint(event, resp)
    print(resp.completion_text)

    # --- 15. 指令 ---
    print("\n=== 指令 ===")
    for name, args in (
        ("cmd_today", ()),
        ("cmd_nutrition", ()),
        ("cmd_profile", ()),
        ("cmd_weight", ()),
        ("cmd_presets", ()),
        ("cmd_calendar", ()),
        ("cmd_help", ()),
    ):
        event2 = AstrMessageEvent()
        async for chunk in getattr(plugin, name)(event2, *args):
            print(f"[{name}] {str(chunk)[:120]}")

    event3 = AstrMessageEvent(text="/记录 米饭 2碗 晚餐")
    async for chunk in plugin.cmd_quick_log(event3):
        print(f"[cmd_quick_log] {chunk}")

    # --- 16. 私聊限制：群聊一律不参与 ---
    print("\n=== 群聊：注入与提醒都应静默 ===")

    # --- 16.5 新用户与群聊 ---
    print("\n=== 新用户首次对话（应引导建档） ===")
    new_event = AstrMessageEvent(uid="20002", umo="aiocqhttp:FriendMessage:2")
    req2 = ProviderRequest()
    await plugin.inject_status(new_event, req2)
    print(req2.system_prompt[-260:])
    status_new = await tools["calorie_status"].call(wrap(new_event))
    print("新用户状态：", status_new[:220])

    group_event = AstrMessageEvent(uid="10001", umo="aiocqhttp:GroupMessage:888")
    req3 = ProviderRequest()
    await plugin.inject_status(group_event, req3)
    print("群聊是否注入状态：", bool(req3.system_prompt))
    resp3 = LLMResponse("好的")
    await plugin.append_hint(group_event, resp3)
    print("群聊回复是否被追加：", "\n\n" in resp3.completion_text)
    blocked = await tools["log_food"].call(wrap(group_event), foods=[{"name": "米饭"}])
    print("群聊调用记录工具：", blocked)
    assert '"ignored": true' in blocked
    data = await tools["nutrition_report"].call(wrap(group_event))
    print("群聊调用报告工具：", data)
    assert '"ignored": true' in data
    group_cmd = AstrMessageEvent(uid="10001", umo="aiocqhttp:GroupMessage:888")
    chunks = [c async for c in plugin.cmd_today(group_cmd)]
    print("群聊里执行指令的输出条数：", len(chunks))
    assert len(chunks) == 0

    print("\n=== 暂停记录 ===")
    print((await tools["update_profile"].call(ctx, paused=True))[:160])
    req4 = ProviderRequest()
    await plugin.inject_status(event, req4)
    print("注入暂停提示：", "已暂停" in req4.system_prompt)
    resp4 = LLMResponse("嗯")
    await plugin.append_hint(event, resp4)
    print("暂停后是否追加提醒：", "\n\n" in resp4.completion_text)
    print("恢复：", (await tools["update_profile"].call(ctx, paused=False))[:90])

    # --- 17. 落盘校验 ---
    await plugin.terminate()
    data_dir = StarTools.data_dir
    print("\n=== 数据文件 ===")
    for f in sorted(data_dir.glob("*.json")):
        print(f"{f.name}: {f.stat().st_size} bytes")
    assert not (data_dir / "meta.json").exists(), "不应再生成订阅文件"

    ok = True
    import json

    records = json.loads((data_dir / "records.json").read_text(encoding="utf-8"))
    users = json.loads((data_dir / "users.json").read_text(encoding="utf-8"))
    presets = json.loads((data_dir / "presets.json").read_text(encoding="utf-8"))
    weights = json.loads((data_dir / "weights.json").read_text(encoding="utf-8"))
    today = list(records["records"][event._uid].values())[0]
    print(f"\n今日记录 {len(today['entries'])} 条，饮水 {today['water_ml']}ml，运动 {len(today['exercise'])} 条")
    print(f"用户 {len(users['users'])} 个，体重记录 {len(weights['weights'][event._uid])} 条")
    print(f"预设食物 {list(presets['foods'].get(event._uid, {}))}，食谱 {list(presets['recipes'].get(event._uid, {}))}")
    print("\nE2E 通过")

    shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
