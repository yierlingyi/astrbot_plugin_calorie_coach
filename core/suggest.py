# -*- coding: utf-8 -*-
"""营养缺口「吃什么补」的推荐：把缺口量换算成具体食物份量。"""

from __future__ import annotations

from typing import Any

from . import nutrition as nu

# 每个营养素的优先食物来源（名称必须能在内置库或用户食物里命中）
SOURCES: dict[str, list[str]] = {
    "protein": ["鸡胸肉（熟）", "鸡蛋", "虾仁", "豆腐（北）", "纯牛奶", "牛肉（瘦）", "无糖酸奶"],
    "fiber": ["即食燕麦", "黑木耳（干）", "奇亚籽", "红薯（蒸）", "西兰花", "毛豆", "苹果"],
    "calcium": ["纯牛奶", "无糖酸奶", "豆腐（北）", "豆干", "芝麻（黑）", "西兰花", "虾仁"],
    "iron": ["动物肝脏（猪肝）", "牛肉（瘦）", "鸭血", "菠菜", "黑木耳（干）", "羊肉（瘦）"],
    "zinc": ["牛肉（瘦）", "羊肉（瘦）", "南瓜子", "腰果", "鸡蛋", "虾仁"],
    "selenium": ["三文鱼", "虾仁", "鸡蛋", "腰果", "带鱼"],
    "potassium": ["香蕉", "土豆（蒸）", "菠菜", "毛豆", "橙子"],
    "magnesium": ["南瓜子", "杏仁", "巧克力（黑）", "菠菜", "即食燕麦"],
    "va": ["动物肝脏（猪肝）", "胡萝卜", "菠菜", "红薯（蒸）", "鸡蛋"],
    "vd": ["三文鱼", "鸡蛋黄", "纯牛奶", "带鱼"],
    "ve": ["杏仁", "瓜子（葵花籽）", "核桃", "菠菜", "橄榄油"],
    "vk": ["菠菜", "西兰花", "卷心菜", "韭菜"],
    "b1": ["猪肉（瘦）", "即食燕麦", "黄豆（干）", "花生"],
    "b2": ["纯牛奶", "鸡蛋", "动物肝脏（猪肝）", "菠菜", "香菇（鲜）"],
    "b3": ["鸡胸肉（熟）", "金枪鱼（水浸罐）", "花生", "牛肉（瘦）"],
    "b6": ["鸡胸肉（熟）", "香蕉", "土豆（蒸）", "三文鱼"],
    "b12": ["三文鱼", "牛肉（瘦）", "鸡蛋", "纯牛奶", "虾仁"],
    "vc": ["青椒", "猕猴桃", "草莓", "西兰花", "橙子"],
    "folate": ["菠菜", "动物肝脏（猪肝）", "毛豆", "西兰花", "黑木耳（干）"],
    "fat": ["核桃", "杏仁", "牛油果", "三文鱼", "橄榄油"],
    "carb": ["米饭", "红薯（蒸）", "即食燕麦", "香蕉", "糙米饭"],
    "kcal": ["米饭", "鸡蛋", "香蕉", "纯牛奶", "核桃"],
}

TIPS: dict[str, str] = {
    "protein": "蛋白质不足容易掉肌肉、饿得快，每餐安排一个手掌大小的优质蛋白。",
    "fiber": "纤维不足肠道和血糖都受影响，主食换一半粗粮、每天一斤蔬菜最省事。",
    "calcium": "钙长期不足影响骨密度，奶制品是最省事的来源。",
    "iron": "铁不足容易乏力、脸色差，动物性铁（红肉、肝脏、血制品）吸收率更高，配点维C更好。",
    "zinc": "锌和免疫、味觉相关，贝类、红肉、坚果都不错。",
    "selenium": "硒参与抗氧化，海鱼、蛋、坚果可以补。",
    "potassium": "钾有助于平衡钠、稳定血压，蔬菜水果豆类都要有。",
    "magnesium": "镁不足容易抽筋、睡不好，坚果和深绿色蔬菜是主力。",
    "va": "维生素A关系视力和黏膜免疫，动物肝脏含量极高但别过量，胡萝卜素更安全。",
    "vd": "维生素D主要靠晒太阳合成，食物来源有限，长期室内建议查一下血清水平。",
    "ve": "维生素E是脂溶性抗氧化剂，坚果和植物油足够。",
    "vk": "维生素K参与凝血和骨代谢，深绿色叶菜管够就行。",
    "b1": "B1 参与糖代谢，主食过于精细时容易不足，杂粮和瘦肉能补。",
    "b2": "B2 不足容易口角炎，奶蛋和动物内脏含量高。",
    "b3": "烟酸来自肉蛋和全谷物，一般不容易缺。",
    "b6": "B6 参与蛋白代谢，肉、鱼、香蕉都不错。",
    "b12": "B12 几乎只存在于动物性食物，长期素食要特别留意。",
    "vc": "维生素C来自新鲜蔬果，久煮会流失，能生吃就生吃。",
    "folate": "叶酸来自深绿叶菜和豆类，备孕人群尤其重要。",
    "fat": "脂肪太低会影响激素和脂溶性维生素吸收，别把油减到零。",
    "carb": "碳水太低容易乏力、训练表现下降，优先选粗杂粮。",
}

EXCESS_TIPS: dict[str, str] = {
    "sodium": "钠超了，水肿和血压都会受影响；少放盐、酱油、蚝油，多喝水多吃含钾蔬果。",
    "sfat": "饱和脂肪偏高，减少肥肉、黄油、油炸食品。",
    "chol": "胆固醇偏高，动物内脏和蛋黄适量即可。",
    "fat": "脂肪占比过高，注意烹调油和油炸食物。",
    "carb": "碳水占比偏高，留意含糖饮料和精制主食。",
    "protein": "蛋白质偏多会增加肾脏负担，同时注意多喝水。",
    "va": "维生素A是脂溶性的，长期超量会在体内蓄积，暂停肝脏类食物。",
    "vd": "维生素D超量可能引起高钙血症，别再额外补剂。",
    "ve": "维生素E超量会影响凝血，停掉相关补充剂。",
    "vc": "维生素C超量可能腹泻、增加结石风险。",
    "folate": "叶酸超量可能掩盖B12缺乏，注意补充来源。",
    "b3": "烟酸超量会潮红、伤肝，注意强化食品和补剂。",
    "b6": "B6 长期大剂量会神经损伤。",
    "iron": "铁超量会伤肝、影响吸收平衡，别盲目补铁。",
    "zinc": "锌超量会干扰铜吸收、影响免疫。",
    "selenium": "硒超量会掉发、指甲变形。",
    "phosphorus": "磷超量（尤其来自加工食品）不利于骨骼和肾脏。",
    "potassium": "钾过高对肾功能不全者危险，需就医评估。",
}


def _portion_text(item: dict[str, Any], grams: float) -> tuple[str, float]:
    """把克数尽量表达成「1杯（250g）」这种人类说法。"""
    best: tuple[str, float] | None = None
    for label, g in (item.get("portions") or []):
        try:
            g = float(g)
        except (TypeError, ValueError):
            continue
        if g <= 0:
            continue
        count = grams / g
        if 0.5 <= count <= 4 and (best is None or abs(count - round(count)) < 0.35):
            best = (label, g)
    if best:
        label, g = best
        count = grams / g
        ctext = f"{int(round(count))}" if abs(count - round(count)) < 0.15 else f"{count:.1f}"
        base = label[1:] if label.startswith("一") else label
        base = base.replace("（", "(").replace("）", ")")
        return f"{grams:g}g（约{ctext}{base}）", grams
    return f"{grams:g}g", grams


def cover_gap(
    key: str,
    gap: float,
    book: Any,
    user_foods: dict[str, Any] | None = None,
    dislikes: list[str] | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """给出「组合起来刚好补上缺口」的食物与份量。

    第一步先用最实用的食物补掉大部分缺口，剩下的用第二种食物补，
    单个食物最多 400g，避免出现「吃 600g 鸡蛋」这种离谱建议。
    """
    if gap <= 0:
        return []
    dislikes = [d.strip() for d in (dislikes or []) if d and d.strip()]
    extra = []
    for name, raw in (user_foods or {}).items():
        extra.append(
            {
                "name": name,
                "cat": raw.get("cat") or "我的食物",
                "alias": raw.get("alias") or [],
                "nut": nu.as_vector(raw.get("nut")),
                "portions": [tuple(p) for p in (raw.get("portions") or [["100克", 100]])],
                "source": "自定义",
            }
        )

    def find(name: str) -> dict[str, Any] | None:
        item = book.find(name)
        if item:
            return item
        for cand in extra:
            if cand["name"] == name:
                return cand
        return None

    remaining = gap
    items: list[dict[str, Any]] = []
    for name in SOURCES.get(key, []):
        if len(items) >= limit:
            break
        if any(d in name for d in dislikes):
            continue
        item = find(name)
        if item is None:
            continue
        per100 = nu.get(item["nut"], key)
        if per100 <= 0:
            continue
        # 已有第一项时，第二项只补剩余部分；剩余太少就不再凑
        if items and remaining < gap * 0.2:
            break
        grams = remaining / per100 * 100
        grams = max(80.0 if items else 30.0, min(400.0, round(grams / 10) * 10))
        gain = per100 * grams / 100
        text, _ = _portion_text(item, grams)
        items.append(
            {
                "name": item["name"],
                "grams": round(grams),
                "text": text,
                "gain": round(gain, 1),
                "cat": item.get("cat"),
            }
        )
        remaining -= gain
        if remaining <= gap * 0.12:
            break

    return items


def advice_for(key: str, direction: str) -> str:
    if direction == "low":
        return TIPS.get(key, "")
    return EXCESS_TIPS.get(key, "")
