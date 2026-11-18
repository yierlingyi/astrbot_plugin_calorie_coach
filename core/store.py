# -*- coding: utf-8 -*-
"""JSON 持久化层：用户档案、每日饮食记录、体重历史、预设食物与食谱。"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger

SCHEMA_VERSION = 1


def _atomic_write(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Store:
    """一个插件实例对应一个 Store，内部按文件分片落盘。"""

    def __init__(self, data_dir: Path) -> None:
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._files = {
            "users": self.dir / "users.json",
            "records": self.dir / "records.json",
            "weights": self.dir / "weights.json",
            "presets": self.dir / "presets.json",
        }
        self.users: dict[str, dict[str, Any]] = {}
        self.records: dict[str, dict[str, dict[str, Any]]] = {}
        self.weights: dict[str, list[dict[str, Any]]] = {}
        self.preset_foods: dict[str, dict[str, dict[str, Any]]] = {}
        self.preset_recipes: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------ #
    async def load(self) -> None:
        self.users = await self._read("users", "users", {})
        self.records = await self._read("records", "records", {})
        self.weights = await self._read("weights", "weights", {})
        presets = await self._read("presets", None, {})
        self.preset_foods = presets.get("foods", {})
        self.preset_recipes = presets.get("recipes", {})

    async def _read(self, name: str, key: str | None, default: Any) -> Any:
        path = self._files[name]
        if not path.exists():
            return default
        try:
            raw = await asyncio.to_thread(path.read_text, "utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"[热量教练] 读取 {path.name} 失败：{exc}")
            return default
        if key is None:
            return data if isinstance(data, dict) else default
        value = data.get(key, default)
        return value if isinstance(value, dict) else default

    def save(self, *names: str) -> None:
        """按需落盘，names 为 users/records/weights/presets。

        单用户数据量在几百 KB 级，同步写足够快，也避免 async 调用方漏掉 await。
        """
        for name in names or self._files.keys():
            payload: Any
            if name == "users":
                payload = {"version": SCHEMA_VERSION, "users": self.users}
            elif name == "records":
                payload = {"version": SCHEMA_VERSION, "records": self.records}
            elif name == "weights":
                payload = {"version": SCHEMA_VERSION, "weights": self.weights}
            elif name == "presets":
                payload = {
                    "version": SCHEMA_VERSION,
                    "foods": self.preset_foods,
                    "recipes": self.preset_recipes,
                }
            else:
                continue
            try:
                _atomic_write(self._files[name], payload)
            except OSError as exc:
                logger.error(f"[热量教练] 写入 {name}.json 失败：{exc}")

    # ------------------------------------------------------------------ #
    # 用户档案
    # ------------------------------------------------------------------ #
    def get_user(self, uid: str) -> dict[str, Any]:
        user = self.users.get(uid)
        if user is None:
            user = {
                "uid": uid,
                "name": "",
                "sex": "male",
                "birth_year": None,
                "age": None,
                "age_recorded_year": None,
                "height_cm": None,
                "weight_kg": None,
                "body_fat": None,
                "activity": "light",
                "goal": "maintain",
                "goal_set": False,
                "paused": False,
                "target_weight_kg": None,
                "target_days": None,
                "goal_start_date": None,
                "goal_start_weight": None,
                "diet_prefs": [],
                "allergies": [],
                "dislikes": [],
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.users[uid] = user
        return user

    def has_user(self, uid: str) -> bool:
        return uid in self.users

    # ------------------------------------------------------------------ #
    # 每日记录
    # ------------------------------------------------------------------ #
    def get_day(self, uid: str, day: str, create: bool = False) -> dict[str, Any]:
        bucket = self.records.setdefault(uid, {})
        record = bucket.get(day)
        if record is None:
            record = {"date": day, "entries": [], "water_ml": 0, "exercise": [], "note": ""}
            if create:
                bucket[day] = record
        return record

    def add_entry(self, uid: str, day: str, entry: dict[str, Any]) -> dict[str, Any]:
        record = self.get_day(uid, day, create=True)
        entry.setdefault("id", uuid.uuid4().hex[:8])
        record["entries"].append(entry)
        record["entries"].sort(key=lambda e: (e.get("time", ""), e.get("id", "")))
        return entry

    def remove_entry(self, uid: str, day: str, index_or_id: str | int | None = None) -> dict[str, Any] | None:
        record = self.get_day(uid, day)
        entries = record.get("entries") or []
        if not entries:
            return None
        if index_or_id is None:
            return entries.pop()
        for i, entry in enumerate(entries):
            if str(entry.get("id")) == str(index_or_id) or entry.get("name") == index_or_id:
                return entries.pop(i)
        try:
            idx = int(index_or_id)
            if 0 <= idx < len(entries):
                return entries.pop(idx)
        except (TypeError, ValueError):
            pass
        return None

    def day_entries(self, uid: str, day: str) -> list[dict[str, Any]]:
        return list(self.get_day(uid, day).get("entries") or [])

    def days_with_records(self, uid: str) -> list[str]:
        return sorted(self.records.get(uid, {}).keys())

    # ------------------------------------------------------------------ #
    # 体重
    # ------------------------------------------------------------------ #
    def get_weights(self, uid: str) -> list[dict[str, Any]]:
        return list(self.weights.get(uid, []))

    def add_weight(self, uid: str, day: str, kg: float, **extra: Any) -> dict[str, Any]:
        bucket = self.weights.setdefault(uid, [])
        record = {
            "date": day,
            "kg": round(float(kg), 1),
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        record.update({k: v for k, v in extra.items() if v not in (None, "")})
        for i, old in enumerate(bucket):
            if old.get("date") == day:
                bucket[i] = record
                bucket.sort(key=lambda x: x["date"])
                return record
        bucket.append(record)
        bucket.sort(key=lambda x: x["date"])
        return record

    def latest_weight(self, uid: str) -> dict[str, Any] | None:
        bucket = self.weights.get(uid) or []
        return bucket[-1] if bucket else None

    def weight_on(self, uid: str, day: str) -> float | None:
        for item in reversed(self.weights.get(uid) or []):
            if item.get("date") == day:
                return item.get("kg")
        return None

    # ------------------------------------------------------------------ #
    # 预设食物 / 食谱
    # ------------------------------------------------------------------ #
    def user_foods(self, uid: str) -> dict[str, dict[str, Any]]:
        return self.preset_foods.setdefault(uid, {})

    def add_user_food(self, uid: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        book = self.user_foods(uid)
        book[name] = payload
        return payload

    def del_user_food(self, uid: str, name: str) -> bool:
        return self.user_foods(uid).pop(name, None) is not None

    def user_recipes(self, uid: str) -> dict[str, dict[str, Any]]:
        return self.preset_recipes.setdefault(uid, {})

    def add_recipe(self, uid: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        book = self.user_recipes(uid)
        book[name] = payload
        return payload

    def del_recipe(self, uid: str, name: str) -> bool:
        return self.user_recipes(uid).pop(name, None) is not None

    # ------------------------------------------------------------------ #
    def all_uids(self) -> list[str]:
        return list(self.users.keys())


def today_str() -> str:
    return date.today().isoformat()
