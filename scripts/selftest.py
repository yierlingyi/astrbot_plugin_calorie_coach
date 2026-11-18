# -*- coding: utf-8 -*-
"""离线自测：不依赖 AstrBot 运行环境，验证核心计算链路。"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---- stub astrbot（仅 store.py 需要 logger） ----
if "astrbot" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")

    class _Logger:
        def info(self, *a, **k):
            print("[info]", *a)

        def warning(self, *a, **k):
            print("[warn]", *a)

        def error(self, *a, **k):
            print("[error]", *a)

        def exception(self, *a, **k):
            print("[exc]", *a)

    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

sys.path.insert(0, str(ROOT))

from core import analysis as an  # noqa: E402
from core import body as bd  # noqa: E402
from core import nutrition as nu  # noqa: E402
from core import report as rp  # noqa: E402
from core.foods import FoodBook, merge_user_foods  # noqa: E402
from core.store import Store  # noqa: E402


def build_entry(book, name, amount, unit, meal, time_str):
    item = book.find(name)
    assert item, f"食物未找到: {name}"
    grams, text = book.resolve_grams(item, amount, unit)
    nut = nu.scale(item["nut"], grams / 100)
    return {
        "id": name[:4] + meal,
        "name": item["name"],
        "cat": item["cat"],
        "meal": meal,
        "grams": round(grams, 1),
        "amount_text": f"{text}",
        "time": time_str,
        "nut": nu.to_dict(nut),
    }, nu.get(nut, "kcal")


def main() -> None:
    book = FoodBook(ROOT / "presets" / "foods.json")
    print(f"食物库：{book.count()} 条")

    # 检索能力
    for q in ["米饭", "饭", "西红柿炒蛋", "可乐", "牛奶", "鸡胸", "土豆丝", "麦当劳"]:
        hits = book.search(q, limit=3)
        print(f"  搜索 {q!r} -> {[h['name'] for h in hits]}")

    user = {
        "sex": "male",
        "age": 28,
        "birth_year": 1998,
        "height_cm": 175,
        "weight_kg": 82,
        "activity": "light",
        "goal": "lose",
        "target_weight_kg": 72,
        "target_days": 120,
        "dislikes": ["香菜"],
    }
    targets = bd.build_targets(user)
    print("\n目标：", {k: targets[k] for k in ("bmr", "tdee", "kcal", "protein_g", "fat_g", "carb_g", "deficit", "eta_days")})
    print("警告：", targets["warnings"])

    today = date.today().isoformat()
    entries = []
    plan = [
        ("白粥", 1, "碗", "早餐", "07:40"),
        ("鸡蛋", 2, "个", "早餐", "07:45"),
        ("包子（肉馅）", 1, "个", "早餐", "07:50"),
        ("米饭", 1, "碗", "午餐", "12:10"),
        ("西红柿炒鸡蛋", 1, "份", "午餐", "12:15"),
        ("青椒炒肉", 0.5, "份", "午餐", "12:20"),
        ("奶茶（全糖）", 1, "杯", "加餐", "15:30"),
    ]
    for name, amount, unit, meal, t in plan:
        entry, kcal = build_entry(book, name, amount, unit, meal, t)
        entries.append(entry)
        print(f"  + {entry['name']} {entry['amount_text']} = {kcal:.0f} kcal")

    day = {"date": today, "entries": entries, "water_ml": 800, "exercise": []}
    result = an.analyze(day, targets, user, book)
    print("\n" + "=" * 50)
    print(rp.day_card(result, targets, today))
    print("=" * 50)
    print(rp.analysis_detail(result))

    # 缺口建议
    print("\n建议补餐：", an.suggest_meal(result["remaining_kcal"], result["remaining_protein"], book, user))

    # 日历
    records = {today: day}
    for i in range(1, 6):
        d = (date.today() - timedelta(days=i)).isoformat()
        records[d] = {
            "date": d,
            "entries": [build_entry(book, "米饭", 2, "碗", "午餐", "12:00")[0]],
        }
    weights = [
        {"date": (date.today() - timedelta(days=10)).isoformat(), "kg": 84.0},
        {"date": (date.today() - timedelta(days=5)).isoformat(), "kg": 83.2},
        {"date": today, "kg": 82.6},
    ]
    print("\n" + rp.calendar_text(records, weights, targets["kcal"], date.today().year, date.today().month))
    print("\n" + rp.profile_card(user, targets, bd.goal_progress(user, weights)))

    days = [(k, v) for k, v in sorted(records.items())]
    print("\n" + rp.week_report(days, targets, user, weights))

    # 持久化
    store = Store(ROOT / "_selftest_data")
    import asyncio

    asyncio.run(store.load())
    store.get_user("u1")
    store.add_entry("u1", today, entries[0])
    store.add_weight("u1", today, 82.6)
    store.add_user_food("u1", "自制鸡胸沙拉", {"nut": nu.to_dict(nu.zeros()), "portions": [["一份", 250]]})
    store.save()

    store2 = Store(ROOT / "_selftest_data")
    asyncio.run(store2.load())
    print("\n持久化回读：", len(store2.users), len(store2.records.get("u1", {})), store2.latest_weight("u1"), list(store2.user_foods("u1")))
    print("OK")


if __name__ == "__main__":
    main()
