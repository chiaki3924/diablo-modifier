"""中文名称表与分类（物品/职业/法术/稀有度）。

物品名以运行时 idx（0..168）为键，因为 d1items.ITEM_NAMES 里存在重名
（Club 出现在 3 和 140，Buckler 在 2 和 71，戒指/护身符各 3 个）。
"""
from __future__ import annotations

from d1env import MODULES

# 运行时 idx -> 中文名
ITEM_CN: dict[int, str] = {
    0: "金币",
    1: "短剑", 2: "小圆盾", 3: "棍棒", 4: "短弓", 5: "法力短杖", 6: "剁斧",
    7: "亡灵王冠", 8: "苍穹之戒", 9: "魔法石", 10: "视觉护身符", 11: "真实之戒",
    12: "酒馆招牌", 13: "丑角头冠", 14: "钢铁面纱", 15: "黄金灵药", 16: "愤怒铁砧",
    17: "黑蘑菇", 18: "大脑", 19: "真菌典籍", 20: "幽灵灵药", 21: "血石",
    22: "教堂地图", 23: "心脏",
    24: "治疗药水", 25: "法力药水", 26: "鉴定卷轴", 27: "回城卷轴",
    28: "阿凯恩的勇气", 29: "全治疗药水", 30: "全法力药水", 31: "格里斯瓦德的边缘",
    32: "牛甲", 33: "拉撒路法杖", 34: "复活卷轴", 35: "铁匠油",
    36: "短杖", 37: "剑", 38: "匕首", 39: "符文炸弹", 40: "西奥多",
    41: "金色护身符", 42: "残破笔记一", 43: "残破笔记二", 44: "残破笔记三",
    45: "重组的笔记", 46: "棕色套装", 47: "灰色套装",
    48: "帽子", 49: "骷髅帽", 50: "头盔", 51: "全盔", 52: "王冠", 53: "大头盔",
    54: "斗篷", 55: "破布衣", 56: "披风", 57: "长袍",
    58: "绗缝甲", 59: "皮甲", 60: "硬皮甲", 61: "镶钉皮甲", 62: "环甲",
    63: "锁子甲", 64: "鳞甲", 65: "胸甲", 66: "板条甲", 67: "板甲",
    68: "野战板甲", 69: "哥特式板甲", 70: "全身板甲",
    71: "小圆盾", 72: "小盾", 73: "大盾", 74: "鸢盾", 75: "塔盾", 76: "哥特盾",
    77: "治疗药水", 78: "全治疗药水", 79: "法力药水", 80: "全法力药水",
    81: "恢复药水", 82: "全恢复药水", 83: "铁匠油", 84: "精准之油",
    85: "锋利之油", 86: "油", 87: "力量灵药", 88: "魔法灵药",
    89: "敏捷灵药", 90: "体质灵药",
    91: "治疗卷轴", 92: "搜寻卷轴", 93: "闪电卷轴", 94: "鉴定卷轴",
    95: "复活卷轴", 96: "火墙卷轴", 97: "地狱火卷轴", 98: "回城卷轴",
    99: "闪光卷轴", 100: "夜视卷轴", 101: "相位卷轴", 102: "法力护盾卷轴",
    103: "烈焰波卷轴", 104: "火球卷轴", 105: "石化卷轴", 106: "连锁闪电卷轴",
    107: "守护者卷轴", 109: "新星卷轴", 110: "魔像卷轴", 112: "传送卷轴",
    113: "末日卷轴",
    118: "匕首", 119: "短剑", 120: "半月弯刀", 121: "弯刀", 122: "双刃大剑",
    123: "刀刃", 124: "马刀", 125: "长剑", 126: "阔剑", 127: "混种剑",
    128: "双手剑", 129: "巨剑",
    130: "小斧", 131: "斧", 132: "大斧", 133: "阔斧", 134: "战斧", 135: "巨斧",
    136: "钉头锤", 137: "晨星", 138: "战锤", 139: "尖刺棍棒", 140: "棍棒",
    141: "连枷", 142: "大槌",
    143: "短弓", 144: "猎弓", 145: "长弓", 146: "复合弓", 147: "短战弓",
    148: "长战弓", 149: "短战争弓", 150: "长战争弓",
    151: "短杖", 152: "长杖", 153: "复合杖", 154: "棍杖", 155: "战杖",
    156: "戒指", 157: "戒指", 158: "戒指", 159: "护身符", 160: "护身符",
    161: "火之符文", 162: "闪电符文", 163: "强效火之符文",
    164: "强效闪电符文", 165: "石之符文", 166: "充能弹短杖",
    167: "竞技场药水",
}

# 分类（按 idx 区间 + 覆盖）
_CATEGORY_OVERRIDES = {
    0: "杂项", 5: "法杖", 6: "斧", 7: "暗金/任务", 15: "药剂", 24: "药剂",
    25: "药剂", 26: "卷轴", 27: "卷轴", 28: "暗金/任务", 29: "药剂",
    30: "药剂", 31: "暗金/任务", 32: "暗金/任务", 33: "法杖", 34: "卷轴",
    35: "杂项", 39: "杂项", 40: "暗金/任务", 41: "暗金/任务", 42: "杂项",
    43: "杂项", 44: "杂项", 45: "杂项", 46: "暗金/任务", 47: "暗金/任务",
    48: "头盔", 49: "头盔", 50: "头盔", 51: "头盔", 52: "头盔", 53: "头盔",
    54: "护甲", 55: "护甲", 56: "护甲", 57: "护甲", 58: "护甲", 59: "护甲",
    60: "护甲", 61: "护甲", 62: "护甲", 63: "护甲", 64: "护甲", 65: "护甲",
    66: "护甲", 67: "护甲", 68: "护甲", 69: "护甲", 70: "护甲",
    71: "盾牌", 72: "盾牌", 73: "盾牌", 74: "盾牌", 75: "盾牌", 76: "盾牌",
    156: "戒指/项链", 157: "戒指/项链", 158: "戒指/项链",
    159: "戒指/项链", 160: "戒指/项链",
    161: "杂项", 162: "杂项", 163: "杂项", 164: "杂项", 165: "杂项",
    166: "法杖", 167: "药剂", 168: "杂项",
}

_CATEGORY_RANGES = [
    (77, 90, "药剂"),
    (91, 117, "卷轴"),
    (118, 129, "剑"),
    (130, 135, "斧"),
    (136, 142, "锤/棍"),
    (143, 150, "弓"),
    (151, 155, "法杖"),
]

CATEGORY_ORDER = ["剑", "斧", "锤/棍", "弓", "法杖", "盾牌", "头盔", "护甲",
                  "戒指/项链", "药剂", "卷轴", "暗金/任务", "杂项"]


def item_category(idx: int) -> str:
    if idx in _CATEGORY_OVERRIDES:
        return _CATEGORY_OVERRIDES[idx]
    for lo, hi, cat in _CATEGORY_RANGES:
        if lo <= idx <= hi:
            return cat
    return "杂项"


def item_en(idx: int) -> str:
    try:
        return MODULES.d1items.ITEM_NAMES.get(idx, "") or ""
    except Exception:
        return ""


def item_cn(idx: int) -> str:
    return ITEM_CN.get(idx) or item_en(idx) or f"物品{idx}"


def item_label(idx: int) -> str:
    """『中文名（English）』，用于列表/下拉。"""
    cn = ITEM_CN.get(idx)
    en = item_en(idx)
    if cn and en:
        return f"{cn}（{en}）"
    return cn or en or f"物品{idx}"


def item_size(idx: int) -> tuple[int, int]:
    try:
        return tuple(MODULES.d1items.ITEM_SIZE.get(idx, (1, 1)))
    except Exception:
        return (1, 1)


def class_name(hero_class: int) -> str:
    try:
        return MODULES.d1save.CLASS_NAMES_CN[hero_class]
    except Exception:
        return f"职业{hero_class}"


def spell_name(idx: int) -> str:
    try:
        names = MODULES.d1save.SPELL_NAMES_CN
        return names[idx] if 0 <= idx < len(names) else f"法术{idx}"
    except Exception:
        return f"法术{idx}"


def _spell_tables():
    """``d1tables``（法术白名单/中文名）；缺失时抛异常由调用方兜底。"""
    import sys

    mod = sys.modules.get("d1tables")
    if mod is not None:
        return mod
    try:
        import d1tables as mod  # work/lib 通常已在 sys.path
        return mod
    except Exception:  # noqa: BLE001
        from d1env import lib_module

        mod, err = lib_module("d1tables")
        if mod is None:
            raise RuntimeError(err)
        return mod


def learnable_spell_name(idx: int) -> str:
    """1.5.5 原版**可学习**法术的中文名。

    只查 ``d1tables.learnable_spells()`` 白名单，所以地狱火/职业自带/不可学习
    法术不会显示出来；不在白名单时退回「法术N」（不暴露 Hellfire 名称）。
    """
    sid = int(idx)
    try:
        tables = _spell_tables()
        for row in tables.learnable_spells():
            if int(row["index"]) == sid:
                return str(row.get("cn") or row.get("name") or f"法术{sid}")
    except Exception:  # noqa: BLE001
        pass
    return f"法术{sid}"


def spell_names() -> list[str]:
    try:
        return list(MODULES.d1save.SPELL_NAMES_CN)
    except Exception:
        return [f"法术{i}" for i in range(37)]


RARITY_CN = {"normal": "普通", "magic": "魔法", "unique": "暗金"}
RARITY_KEYS = ["normal", "magic", "unique"]


def rarity_cn(key: str) -> str:
    return RARITY_CN.get(str(key).lower(), str(key))
