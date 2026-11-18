# -*- coding: utf-8 -*-
"""AstrBot 热量与营养管家：AI 边聊边记，自动算热量、查营养、记体重。

设计要点：
1. 全部能力以 LLM 工具形式提供，用户在聊天里说什么就记什么，不需要背指令；
2. 每轮对话前把「今天的进度 + 档案 + 规则」注入系统提示词，模型自然知道该记什么；
3. 记录后返回缺口与建议，模型顺口就说出来了 —— 提醒发生在对话里，不额外打扰；
4. 只在用户需要时用指令：/热量 /营养 /饮食日历 /体重 /目标 /食谱；
5. 只在私聊生效：群聊里不注入、不响应指令、所有工具统一拒绝；
6. 没有任何定时任务，永远不会主动发起对话或推送消息。
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools

from .core import body as bd
from .core import analysis as an
from .core import report as rp
from .core.foods import FoodBook
from .core.service import CoachService
from .core.store import Store
from .core.util import MEALS
from .tools import build_tools

PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_TZ = "Asia/Shanghai"
TEMPLATE_FILE = PLUGIN_DIR / "templates" / "calendar.html"

RULE_BLOCK = """【热量教练·内部状态｜仅供你判断，不要原样复述给用户】
{when}
{profile}
{target}
{today}
{extra}

操作要求：
1. 用户提到吃了/喝了什么 → 立即调用 log_food 记录，多种食物一次传完；不要问「要不要帮你记」。
2. 用户提到自己的体重 → record_weight；提到身高/年龄/性别/目标体重/期限/活动量 → update_profile。
3. 食物库里没有的（外卖、品牌食品、地方菜）→ 先用联网搜索确认每 100g 热量与营养，再调用 log_estimated_food；绝不允许凭空编数字。
4. 记录完成后，用自己的话顺带说一句热量与关键营养（例如「这顿大概 520 大卡，蛋白 32 克，今天还剩 600 大卡」），不要贴 JSON、不要念清单、不要提「工具/插件/数据库/系统」这些词。
5. 只有真的出现缺口或超标才提醒，一次最多一句；用户只是闲聊时正常聊，不要每句都扯热量。
6. 绝不主动发起话题、不做每日问候、不催促记录、不主动关心「今天吃了没」。用户不开口，你就不要说话。
7. 只有在用户主动聊到体重、身材、饮食、减重时，才顺带了解身高体重年龄等信息，一次只问一个；用户只是打招呼或聊别的事，就正常回应，不要盘问档案。
8. 用户说「不想记了/别管我」时要立刻停止记录与提醒（调用 update_profile 设 paused=true），尊重用户。"""


class CalorieCoachPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir()
        self.store = Store(Path(self.data_dir))
        self.book = FoodBook(PLUGIN_DIR / "presets" / "foods.json")
        self.service = CoachService(self.store, self.book, self._tz(), self.config)
        self._hint_at: dict[str, datetime] = {}
        self._template: str | None = None
        self._tools: list[Any] = []

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def initialize(self) -> None:
        await self.store.load()
        self.service = CoachService(self.store, self.book, self._tz(), self.config)
        self._register_tools()
        logger.info(
            f"热量教练已加载：食物库 {self.book.count()} 条，数据目录 {self.data_dir}"
            "（仅私聊生效，不主动发消息）"
        )

    async def terminate(self) -> None:
        with contextlib.suppress(Exception):
            self.store.save()
        logger.info("热量教练已卸载，数据已保存")

    def _register_tools(self) -> None:
        try:
            tools = build_tools(self)
            self.context.add_llm_tools(*tools)
            owner = self.__class__.__module__
            for tool in tools:
                tool.handler_module_path = owner
            self._tools = tools
            logger.info(f"热量教练已注册 {len(tools)} 个 AI 工具")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"热量教练注册工具失败：{exc}", exc_info=True)

    # ------------------------------------------------------------------ #
    # 配置与时间
    # ------------------------------------------------------------------ #
    def _tz(self) -> ZoneInfo:
        name = str(self.config.get("timezone") or "").strip()
        if not name:
            try:
                name = str(self.context.get_config().get("timezone") or DEFAULT_TZ)
            except Exception:  # noqa: BLE001
                name = DEFAULT_TZ
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - Windows 精简环境可能没有 tzdata
            if name in {"Asia/Shanghai", "PRC", "Asia/Chongqing", "Asia/Harbin"}:
                return timezone(timedelta(hours=8), name)
            try:
                return ZoneInfo(DEFAULT_TZ)
            except Exception:  # noqa: BLE001
                return timezone(timedelta(hours=8), DEFAULT_TZ)

    def now(self) -> datetime:
        return datetime.now(self._tz())

    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            value = self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        return default if value is None else value

    # ------------------------------------------------------------------ #
    # 用户标识
    # ------------------------------------------------------------------ #
    @staticmethod
    def _uid(event: AstrMessageEvent) -> str:
        fn = getattr(event, "get_sender_id", None)
        if callable(fn):
            try:
                value = fn()
                if value:
                    return str(value)
            except Exception:  # noqa: BLE001
                pass
        obj = getattr(event, "message_obj", None)
        sender = getattr(obj, "sender", None)
        for value in (getattr(sender, "user_id", None), getattr(obj, "sender_id", None)):
            if value:
                return str(value)
        return str(getattr(event, "unified_msg_origin", "default") or "default")

    @staticmethod
    def is_private(event: AstrMessageEvent | None) -> bool:
        """只认私聊。拿不到会话类型时按私聊处理（语音/WebChat 等本就没有群概念）。"""
        if event is None:
            return True
        fn = getattr(event, "is_private_chat", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:  # noqa: BLE001
                pass
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if "GroupMessage" in umo or "Group" in umo:
            return False
        return True

    @staticmethod
    def _is_group(event: AstrMessageEvent) -> bool:
        return not CalorieCoachPlugin.is_private(event)

    # ------------------------------------------------------------------ #
    # 注入系统提示词：让 AI 自然知道现状
    # ------------------------------------------------------------------ #
    @filter.on_llm_request()
    async def inject_status(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self._cfg("enable", True):
            return
        if not self.is_private(event):
            return  # 群聊里完全不参与，不注入任何状态
        try:
            uid = self._uid(event)
            block = self._status_block(uid, event)
            if not block:
                return
            base = getattr(req, "system_prompt", "") or ""
            req.system_prompt = f"{base}\n\n{block}" if base else block
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"热量教练注入状态失败：{exc}")

    def _status_block(self, uid: str, event: AstrMessageEvent | None = None) -> str:
        store, svc = self.store, self.service
        if store.has_user(uid) and svc.is_paused(uid):
            return (
                "【热量教练·内部状态】用户已暂停饮食与体重记录，也关闭了提醒。"
                "除非用户主动说「继续记录」，否则不要再调用任何记录类工具，也不要提热量/营养。"
            )
        if not store.has_user(uid) and not store.get_weights(uid) and not store.records.get(uid):
            # 新用户：仍然给规则，引导自然建档
            user = store.get_user(uid)
            block = RULE_BLOCK.format(
                when=f"现在 {self.now():%Y年%m月%d日 %H:%M}",
                profile="档案：还没有任何信息（身高、体重、年龄、目标都缺）",
                target="目标：待建档",
                today="今日：暂无记录",
                extra="用户还没建档，但不要主动盘问。等他聊到体重/饮食/减重时，再像朋友一样顺带问一句身高体重年龄；只是打招呼就正常回，别查户口。",
            )
            return self._with_extra_prompt(block, event)

        user = svc.user(uid)
        targets = svc.targets(uid)
        analysis = svc.analyze(uid)
        progress = svc.progress(uid)
        today = svc.today()

        sex = bd.SEX_LABELS.get(bd.normalize_sex(user.get("sex")), "?")
        age = bd.age_of(user, today)
        bmi = bd.bmi_of(user)
        parts = [
            f"{sex}",
            f"{age}岁" if age else "年龄未知",
            f"{user.get('height_cm'):g}cm" if user.get("height_cm") else "身高未知",
            f"{user.get('weight_kg'):g}kg" if user.get("weight_kg") else "体重未知",
        ]
        if bmi:
            parts.append(f"BMI {bmi}({bd.bmi_label(bmi)})")
        act = bd.ACTIVITY_LEVELS.get(bd.normalize_activity(user.get("activity")), {})
        profile = f"档案：{' '.join(parts)}｜活动量 {act.get('label', '?')}"
        if user.get("allergies"):
            profile += f"｜过敏 {'、'.join(user['allergies'])}"
        if user.get("dislikes"):
            profile += f"｜不吃 {'、'.join(user['dislikes'])}"

        if targets.get("ready") and not user.get("goal_set"):
            target = (
                "目标：还没确定（暂按维持体重给参考值，"
                f"{targets['kcal']} kcal / 蛋白 {targets['protein_g']}g）；"
                "聊到减重/增重打算时再确认目标体重与期限"
            )
        elif targets.get("ready"):
            target = (
                f"目标：{targets['goal_label']}"
                + (f"→{user.get('target_weight_kg'):g}kg" if user.get("target_weight_kg") else "")
                + (f"/{user.get('target_days')}天" if user.get("target_days") else "")
                + f"｜每日 {targets['kcal']} kcal（蛋白 {targets['protein_g']}g 脂肪 {targets['fat_g']}g 碳水 {targets['carb_g']}g）"
                + f"｜BMR {targets['bmr']:.0f} TDEE {targets['tdee']:.0f}"
            )
        else:
            target = "目标：资料不全，缺 " + "、".join(targets.get("missing") or []) 

        if analysis["entries"]:
            meal_desc = " ".join(
                f"{m}{analysis['per_meal'][m]['kcal']:.0f}"
                for m in MEALS
                if analysis["per_meal"][m]["count"]
            )
            today_line = (
                f"今日：{analysis['kcal_in']:.0f} kcal（{analysis['kcal_pct']:.0f}%，剩 "
                f"{analysis['remaining_kcal']:.0f}）｜蛋白 "
                f"{analysis['item_map']['protein']['value']:.0f}/"
                f"{analysis['item_map']['protein'].get('ref_full', analysis['item_map']['protein']['ref']):.0f}g"
                f"｜{meal_desc}"
            )
        else:
            today_line = f"今日：{today:%m月%d日} 还没有任何饮食记录"

        extra_bits = []
        key_gaps = [g for g in analysis["gaps"] if g["key"] in an.ALERT_KEYS]
        if key_gaps:
            extra_bits.append(
                "缺口：" + "、".join(f"{g['name']}{g['pct']:.0f}%" for g in key_gaps[:3])
            )
        if analysis["excess"]:
            extra_bits.append(
                "超标：" + "、".join(f"{g['name']}{g['pct']:.0f}%" for g in analysis["excess"][:2])
            )
        latest = store.latest_weight(uid)
        if latest:
            extra_bits.append(f"最近体重 {latest['kg']}kg（{latest['date']}）")
        trend = (progress.get("trend") or {}).get("slope_per_week")
        if trend:
            extra_bits.append(f"趋势 {trend:+.2f}kg/周")
        if progress.get("remaining") is not None:
            extra_bits.append(f"距目标还 {progress['remaining']:.1f}kg")
        presets = svc.preset_overview(uid)
        if presets["recipes"]:
            extra_bits.append(
                "预设食谱：" + "、".join(r["name"] for r in presets["recipes"][:4])
            )
        if not analysis["entries"]:
            extra_bits.append(
                "今天还没记录：如果用户聊到吃饭，顺手把这一餐记下来，不用特意宣布。"
            )

        block = RULE_BLOCK.format(
            when=f"现在 {self.now():%Y年%m月%d日 %H:%M}（周{'一二三四五六日'[self.now().weekday()]}）",
            profile=profile,
            target=target,
            today=today_line,
            extra="｜".join(extra_bits),
        )
        return self._with_extra_prompt(block, event)

    def _with_extra_prompt(self, block: str, event: AstrMessageEvent | None = None) -> str:
        extra = str(self._cfg("extra_prompt", "") or "").strip()
        return f"{block}\n9. {extra}" if extra else block

    # ------------------------------------------------------------------ #
    # 对话后的顺口提醒（限频，避免打扰）
    # ------------------------------------------------------------------ #
    @filter.on_llm_response()
    async def append_hint(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
        if not self._cfg("passive_hint", True):
            return
        text = (getattr(resp, "completion_text", "") or "").strip()
        if not text:
            return
        if self._is_group(event):
            return  # 群聊里不做健康数据提醒，避免当众播报
        try:
            uid = self._uid(event)
            hint = self._hint_for(uid)
            if not hint:
                return
            resp.completion_text = f"{text}\n\n{hint}"
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"热量教练附加提醒失败：{exc}")

    def _hint_for(self, uid: str) -> str:
        now = self.now()
        if now.hour < 9 or now.hour >= 22:
            return ""
        last = self._hint_at.get(uid)
        if last and (now - last) < timedelta(hours=4):
            return ""
        if self.service.is_paused(uid):
            return ""
        analysis = self.service.analyze(uid)
        targets = analysis["targets"]
        if not targets.get("ready") or not analysis["entries"]:
            return ""
        hint = ""
        if analysis["kcal_status"] == "high":
            hint = (
                f"⚠️ 顺便提醒：今天已 {analysis['kcal_in']:.0f} kcal，"
                f"超过目标 {analysis['kcal_in'] - analysis['target_kcal']:.0f}，后面清淡点。"
            )
        elif [g for g in analysis["gaps"] if g["key"] in an.ALERT_KEYS]:
            gap = [g for g in analysis["gaps"] if g["key"] in an.ALERT_KEYS][0]
            hint = f"💡 顺口一提：今天{gap['name']}只到 {gap['pct']:.0f}%，可以补一点。"
        elif 18 <= now.hour < 21 and analysis["kcal_pct"] < 65:
            hint = f"💡 今天才 {analysis['kcal_in']:.0f} kcal，别吃太少，容易掉代谢。"
        if hint:
            self._hint_at[uid] = now
        return hint

    # ------------------------------------------------------------------ #
    # 指令
    # ------------------------------------------------------------------ #
    def _args(self, event: AstrMessageEvent, *names: str) -> str:
        """从原始消息里取出指令后面的参数（AstrBot 只按空格切第一个词）。"""
        text = (getattr(event, "message_str", "") or "").strip()
        if not text:
            return ""
        parts = text.split(maxsplit=1)
        head = parts[0].lstrip("/!！").strip()
        if head in names:
            return parts[1].strip() if len(parts) > 1 else ""
        return ""

    @filter.command("热量", alias={"今日热量", "cal", "kcal"})
    async def cmd_today(self, event: AstrMessageEvent, arg: str = ""):
        """查看当天热量与营养完成情况"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        day = self.service.resolve_day(arg or self._args(event, "热量", "今日热量", "cal", "kcal"))
        analysis = self.service.analyze(uid, day)
        if not self.service.profile_ready(uid):
            targets = analysis["targets"]
            yield event.plain_result(
                "先补一下基础信息我才能算准："
                + ("、".join(targets.get("missing") or []))
                + "\n直接告诉我「身高175 体重82 今年28」就行。"
            )
            return
        yield event.plain_result(rp.day_card(analysis, analysis["targets"], day.isoformat()))

    @filter.command("营养", alias={"营养分析"})
    async def cmd_nutrition(self, event: AstrMessageEvent, arg: str = ""):
        """查看 26 项营养素明细"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        day = self.service.resolve_day(arg or self._args(event, "营养", "营养分析"))
        analysis = self.service.analyze(uid, day)
        yield event.plain_result(rp.analysis_detail(analysis))

    @filter.command("目标", alias={"我的档案", "档案"})
    async def cmd_profile(self, event: AstrMessageEvent):
        """查看档案、代谢与目标进度"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        yield event.plain_result(
            rp.profile_card(self.service.user(uid), self.service.targets(uid), self.service.progress(uid))
        )

    @filter.command("体重")
    async def cmd_weight(self, event: AstrMessageEvent, arg: str = ""):
        """记录体重（/体重 68.5）或查看趋势（/体重）"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        raw = (arg or self._args(event, "体重")).strip()
        match = re.search(r"\d+(?:\.\d+)?", raw)
        if match:
            try:
                kg = float(match.group())
            except ValueError:
                kg = 0
            if 20 <= kg <= 400:
                result = self.service.add_weight(uid, kg, self.service.today())
                delta = result.get("total_delta")
                trend = result.get("trend_per_week")
                lines = [f"⚖️ 已记录 {kg}kg（{self.service.today():%m月%d日}）"]
                if result.get("bmi"):
                    lines.append(f"BMI {result['bmi']}（{result['bmi_label']}）")
                if delta is not None:
                    lines.append(f"累计变化 {delta:+.1f}kg")
                if trend:
                    lines.append(f"近期 {trend:+.2f}kg/周")
                targets = result["targets"]
                if targets.get("kcal"):
                    lines.append(f"新目标热量 {targets['kcal']} kcal / 蛋白 {targets['protein_g']}g")
                yield event.plain_result("\n".join(lines))
                return
            yield event.plain_result("体重数字看起来不对，用公斤，例如 /体重 68.5")
            return

        weights = self.store.get_weights(uid)
        if not weights:
            yield event.plain_result("还没有称重记录。发 `/体重 68.5` 或直接跟我说「今天68.5」都行。")
            return
        lines = ["⚖️ 体重记录（最近 10 次）"]
        base = weights[0]["kg"]
        for item in weights[-10:]:
            diff = item["kg"] - base
            bmi = bd.bmi_of({"height_cm": self.service.user(uid).get("height_cm"), "weight_kg": item["kg"]})
            lines.append(
                f"{item['date']}  {item['kg']}kg  {diff:+.1f}  BMI {bmi or '—'}"
            )
        trend = bd.weight_trend(weights)
        if trend.get("slope_per_week") is not None:
            lines.append(f"趋势 {trend['slope_per_week']:+.2f} kg/周")
        yield event.plain_result("\n".join(lines))

    @filter.command("食谱", alias={"预设"})
    async def cmd_presets(self, event: AstrMessageEvent):
        """查看预设食物与食谱"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        overview = self.service.preset_overview(uid)
        lines = ["🍱 我的预设"]
        if overview["foods"]:
            lines.append("食物：" + "、".join(overview["foods"][:12]))
        else:
            lines.append("食物：还没有自定义食物")
        if overview["recipes"]:
            lines.append("食谱：")
            for r in overview["recipes"][:10]:
                lines.append(
                    f" · {r['name']}（{r['kcal']} kcal / {r['servings']:g} 人份）"
                    f"：{'、'.join(r['items'])}"
                )
        else:
            lines.append("食谱：还没有，跟我说「把两个鸡蛋一杯牛奶一片全麦面包存成减脂早餐」就行")
        yield event.plain_result("\n".join(lines))

    @filter.command("饮食日历", alias={"日历", "热量日历"})
    async def cmd_calendar(self, event: AstrMessageEvent, arg: str = ""):
        """生成当月饮食日历图（/饮食日历 2026-11）"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        arg = arg or self._args(event, "饮食日历", "日历", "热量日历")
        year = month = None
        match = re.search(r"(\d{4})[-/年](\d{1,2})", arg)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
        elif arg.isdigit():
            month = int(arg)
        data = self.service.calendar_data(uid, year, month)

        if not self._cfg("calendar_image", True):
            yield event.plain_result(
                rp.calendar_text(
                    self.store.records.get(uid, {}),
                    self.store.get_weights(uid),
                    data["target_kcal"],
                    data["year"],
                    data["month"],
                )
            )
            return

        try:
            url = await self._render_calendar(data)
            yield event.image_result(url)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"热量教练渲染日历失败：{exc}", exc_info=True)
            yield event.plain_result(
                rp.calendar_text(
                    self.store.records.get(uid, {}),
                    self.store.get_weights(uid),
                    data["target_kcal"],
                    data["year"],
                    data["month"],
                )
            )

    @filter.command("记录")
    async def cmd_quick_log(self, event: AstrMessageEvent, arg: str = ""):
        """快速记录：/记录 米饭 1碗 午餐"""
        if not self.is_private(event):
            return
        uid = self._uid(event)
        raw = (arg or self._args(event, "记录")).strip()
        if not raw:
            yield event.plain_result("用法：/记录 米饭 1碗 午餐\n或者直接跟我说「中午吃了一碗米饭」。")
            return
        tokens = raw.replace("，", " ").split()
        meal = None
        if tokens and tokens[-1] in MEALS:
            meal = tokens.pop()
        amount, unit = 1.0, None
        if tokens:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)([^\d]*)", tokens[-1])
            if match and match.group(2):
                amount = float(match.group(1))
                unit = match.group(2)
                tokens.pop()
        name = " ".join(tokens) or raw
        result = self.service.add_food(uid, self.service.today(), name, amount, unit, meal)
        if not result.get("ok"):
            hits = result.get("suggestions") or []
            hint = f"\n是不是：{'、'.join(hits)}" if hits else ""
            yield event.plain_result(f"没找到「{name}」{hint}")
            return
        analysis = self.service.analyze(uid)
        yield event.plain_result(
            f"✅ {result['entry']['amount_text']} {result['entry']['name']} ≈ {result['kcal']} kcal\n"
            f"今日 {analysis['kcal_in']:.0f}/{analysis['target_kcal']:.0f} kcal，"
            f"还剩 {analysis['remaining_kcal']:.0f}"
        )

    @filter.command("热量帮助", alias={"怎么用"})
    async def cmd_help(self, event: AstrMessageEvent):
        """插件使用说明"""
        if not self.is_private(event):
            return
        yield event.plain_result(
            "🍽 热量管家\n"
            "不用记指令，正常聊天就行：\n"
            "· 「身高175 体重82 今年28，想三个月减到72」→ 自动建档\n"
            "· 「早饭两个包子一杯豆浆」→ 自动记录并算热量\n"
            "· 「今天68.5」→ 记体重\n"
            "· 「今天营养怎么样」→ 营养分析\n\n"
            "想手动看也可以用：\n"
            "/热量 今日热量　/营养 营养素明细\n"
            "/饮食日历 [2026-11] 日历图\n"
            "/体重 [68.5] 记录或查看\n"
            "/目标 档案与进度　/食谱 预设食物与食谱\n"
            "/记录 米饭 1碗 午餐 快速记录"
        )

    # ------------------------------------------------------------------ #
    # 日历出图
    # ------------------------------------------------------------------ #
    def _load_template(self) -> str:
        if self._template is None:
            self._template = TEMPLATE_FILE.read_text(encoding="utf-8")
        return self._template

    async def _render_calendar(self, data: dict[str, Any]) -> str:
        template = self._load_template()
        view = rp.calendar_view(data)
        return await self.html_render(
            template,
            view,
            return_url=True,
            options={"type": "png", "full_page": True},
        )
