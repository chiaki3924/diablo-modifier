"""中文（简体）名称与属性说明（Round 2）。

数据来源，按优先级：
  1. ``work/lib/d1i18n.py``（i18n 代理交付：tr / item_name_cn / affix_name_cn /
     unique_name_cn / affix_desc）；
  2. 本目录的 ``zh_fallback.json``（由 ``work/build/gen_zh_fallback.py`` 从
     ``DevilutionX-1.5.5/Translations/zh_CN.po`` 抽取，去掉 U+200B）；
  3. 内置少量常用映射（Brutal=残忍、Sharp=锋利、of the Fox=狐狸 …）。

属性说明由本模块生成（不依赖 d1i18n）：中文标签 + 数值范围（param1~param2，
和游戏 tooltip 一致）+ 需求等级 + 适用装备。数值语义直接对应
``SaveItemPower()`` 里的 ``r = RndPL(param1, param2)``，也就是「指定数值」时
传给 itemgen 的目标值。
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from d1env import bundle_dir, lib_module

ZWSP = "\u200b"

# ---------------------------------------------------------------- 基础
def clean(s) -> str:
    if s is None:
        return ""
    return str(s).replace(ZWSP, "").replace("\ufeff", "").strip()


def _fmt_signed(v: int, unit: str = "") -> str:
    v = int(v)
    sign = "+" if v > 0 else ""
    return f"{sign}{v}{unit}"


#: 兜底：常用词缀（i18n 与 PO 表都不可用时至少这些是中文）
BUILTIN_AFFIX = {
    "prefix": {
        "Brutal": "残忍", "Sharp": "锋利", "Fine": "精良", "Strong": "强壮",
        "Grand": "宏大", "Valiant": "英勇", "Glorious": "荣耀", "Blessed": "祝福",
        "Saintly": "圣洁", "Holy": "神圣", "Godly": "神之", "King's": "王者",
        "Vicious": "恶毒", "Deadly": "致命", "Massive": "厚重", "Savage": "野蛮",
        "Ruthless": "无情", "Merciless": "残忍无情", "Bronze": "青铜", "Iron": "铁",
        "Steel": "钢", "Silver": "银", "Gold": "金", "Platinum": "白金",
        "Tin": "锡", "Brass": "黄铜", "Copper": "铜", "Crimson": "赤红",
        "Red": "红色", "Blue": "蓝色", "Gold": "金色", "Emerald": "翠绿",
        "Obsidian": "黑曜石", "Ivory": "象牙", "Crystal": "水晶",
        "Diamond": "钻石", "Topaz": "黄玉", "Sapphire": "蓝宝石",
        "Ruby": "红宝石", "Amber": "琥珀", "Jade": "翡翠",
    },
    "suffix": {
        "the Fox": "狐狸", "the Wolf": "野狼", "the Eagle": "雄鹰",
        "the Tiger": "猛虎", "the Lion": "雄狮", "the Bear": "巨熊",
        "the Giant": "巨人", "of Health": "生命", "of Protection": "保护",
        "of Absorption": "吸收", "of Life": "生命", "of Vitality": "活力",
        "of Strength": "力量", "of Dexterity": "敏捷", "of Magic": "魔法",
        "of the Mind": "心灵", "of Brilliance": "才华", "of Sorcery": "巫术",
        "of Wizardry": "法师", "of the Stars": "星辰", "of the Moon": "月亮",
        "of the Sun": "太阳", "of Fire": "火焰", "of Burning": "燃烧",
        "of Flame": "烈焰", "of Lightning": "闪电", "of Thunder": "雷鸣",
        "of Shock": "电击", "of the Lion": "雄狮", "of Craftsmanship": "工艺",
        "quality": "品质", "maiming": "伤残", "slaying": "屠杀", "gore": "血腥",
        "carnage": "杀戮", "slaughter": "屠宰",
    },
}

#: 兜底：词缀 -> 效果名（Round 3）。只在 d1i18n 没有 ``affix_effect_label``
#: **且** 词缀的 power 信息缺失时才用到；主力来源是 d1i18n 与 ``power_value``。
#: 例：``红宝石（Ruby） 火焰抗性 +51~+60``、``翼龙的（Dragon's） 法力``。
#: 只收“确定无误”的几条 —— 其余全部靠 ``power_name`` 推导，避免猜错属性名。
BUILTIN_EFFECT = {
    ("prefix", "Brutal"): "伤害",
    ("prefix", "Sharp"): "伤害",
    ("prefix", "Fine"): "伤害",
    ("prefix", "Strong"): "伤害",
    ("prefix", "Ruby"): "火焰抗性",
    ("prefix", "Sapphire"): "闪电抗性",
    ("prefix", "Diamond"): "魔法抗性",
    ("prefix", "Obsidian"): "所有抗性",
    ("prefix", "Dragon's"): "法力",
    ("suffix", "of the heavens"): "所有属性",
    ("suffix", "of the fox"): "生命",
    ("suffix", "of the wolf"): "生命",
}

BUILTIN_UNIQUE = {
    "Arkaine's Valor": "阿凯尼的荣耀",
    "Griswold's Edge": "格里斯瓦德的边缘",
    "Veil of Steel": "钢铁面纱",
    "Harlequin Crest": "谐角之冠",
    "Naj's Light Plate": "纳吉的轻甲",
    "The Butcher's Cleaver": "屠夫的剁斧",
    "The Undead Crown": "亡灵王冠",
    "Empyrean Band": "苍穹之戒",
    "Optic Amulet": "视觉护身符",
    "Ring of Truth": "真实之戒",
    "Bovine Plate": "牛甲",
}

#: 词缀适用装备（d1tables 的 item_type_names）
ITEM_TYPE_CN = {
    "Weapon": "武器", "Bow": "弓", "Staff": "法杖", "Armor": "护甲",
    "Shield": "盾牌", "Helm": "头盔", "Ring": "戒指", "Amulet": "护符",
    "Misc": "杂项", "Gold": "金币",
}

#: 能力类型 -> (中文标签, 单位, 是否带 +/- 号, 数值可否指定)
# 数值可否指定 = False 表示固定效果（攻速/充能/吸血之类），不能填目标值。
POWER_NUM = {
    "IPL_TOHIT": ("命中几率", "%", True),
    "IPL_TOHIT_CURSE": ("命中几率", "%", True),
    "IPL_DAMP": ("伤害", "%", True),
    "IPL_DAMP_CURSE": ("伤害", "%", True),
    "IPL_ACP": ("防御", "%", True),
    "IPL_ACP_CURSE": ("防御", "%", True),
    "IPL_SETAC": ("防御", "", False),
    "IPL_AC_CURSE": ("防御", "", True),
    "IPL_FIRERES": ("火焰抗性", "%", True),
    "IPL_FIRERES_CURSE": ("火焰抗性", "%", True),
    "IPL_LIGHTRES": ("闪电抗性", "%", True),
    "IPL_LIGHTRES_CURSE": ("闪电抗性", "%", True),
    "IPL_MAGICRES": ("魔法抗性", "%", True),
    "IPL_MAGICRES_CURSE": ("魔法抗性", "%", True),
    "IPL_ALLRES": ("所有抗性", "%", True),
    "IPL_ALLRESZERO": ("所有抗性归零", "", True),
    "IPL_STR": ("力量", "", True),
    "IPL_STR_CURSE": ("力量", "", True),
    "IPL_MAG": ("魔法", "", True),
    "IPL_MAG_CURSE": ("魔法", "", True),
    "IPL_DEX": ("敏捷", "", True),
    "IPL_DEX_CURSE": ("敏捷", "", True),
    "IPL_VIT": ("体力", "", True),
    "IPL_VIT_CURSE": ("体力", "", True),
    "IPL_ATTRIBS": ("所有属性", "", True),
    "IPL_ATTRIBS_CURSE": ("所有属性", "", True),
    "IPL_GETHIT": ("受到伤害", "", True),
    "IPL_GETHIT_CURSE": ("受到伤害", "", True),
    "IPL_LIFE": ("生命", "", True),
    "IPL_LIFE_CURSE": ("生命", "", True),
    "IPL_MANA": ("法力", "", True),
    "IPL_MANA_CURSE": ("法力", "", True),
    "IPL_DUR": ("耐久", "%", True),
    "IPL_DUR_CURSE": ("耐久", "%", True),
    "IPL_DAMMOD": ("伤害", "%", True),
    "IPL_TARGAC": ("穿透目标防御", "", True),
    "IPL_SPLLVLADD": ("法术等级", "", True),
    "IPL_CRYSTALLINE": ("伤害", "%", True),
    "IPL_DECAY": ("伤害", "%", True),
    "IPL_LIGHT": ("光照范围", "%", False),
    "IPL_LIGHT_CURSE": ("光照范围", "%", False),
}

#: 固定效果的中文说明（数值/多段显示另行处理）
POWER_TEXT = {
    "IPL_INDESTRUCTIBLE": "坚不可摧（耐久锁定）",
    "IPL_MULT_ARROWS": "每击射出多发箭矢",
    "IPL_THORNS": "攻击者受到 1~3 点伤害",
    "IPL_NOMANA": "使用者法力清零",
    "IPL_ABSHALFTRAP": "陷阱伤害减半",
    "IPL_KNOCKBACK": "击中时击退目标",
    "IPL_3XDAMVDEM": "对恶魔伤害 +200%",
    "IPL_RNDARROWVEL": "箭矢飞行速度随机",
    "IPL_SETDAM": "伤害按固定值改写",
    "IPL_SETDUR": "耐久按固定值改写",
    "IPL_ONEHAND": "可单手持用",
    "IPL_DRAINLIFE": "持续流失生命",
    "IPL_RNDSTEALLIFE": "击中时偷取生命",
    "IPL_NOMINSTR": "无力量需求",
    "IPL_INVCURS": "改变物品外观（图标）",
    "IPL_DOPPELGANGER": "命中与伤害提升（二重身）",
    "IPL_JESTERS": "伤害在 0~600% 之间随机",
    "IPL_DEVASTATION": "偶尔造成三倍伤害",
    "IPL_PERIL": "对怪物 2 倍伤害、对自己 1 倍",
    "IPL_MANATOLIFE": "50% 法力上限转为生命",
    "IPL_LIFETOMANA": "40% 生命上限转为法力",
    "IPL_ADDMANAAC": "命中时放出充能弹",
    "IPL_FASTBLOCK": "快速格挡",
    "IPL_INVALID": "（无）",
}

FAST_ATTACK_CN = {1: "快速攻击", 2: "更快攻击", 3: "极速攻击", 4: "最快攻击"}
FAST_RECOVER_CN = {1: "快速打击回复", 2: "更快打击回复", 3: "极速打击回复"}
STEAL_CN = {3: "3%", 5: "5%"}
#: CalculateToHitBonus() 的档位（items.cpp）
TO_HIT_RANGES = {
    -50: (6, 10), -25: (1, 5), 20: (1, 5), 36: (6, 10), 51: (11, 15),
    66: (16, 20), 81: (21, 30), 96: (31, 40), 111: (41, 50), 126: (51, 75),
    151: (76, 100),
}


class _Zh:
    """翻译源（d1i18n 优先，其次 PO 兜底 JSON，最后内置表）。"""

    def __init__(self) -> None:
        self.mod = None
        self.error = None
        self.tr_map: dict[str, str] = {}
        self.ctx_map: dict[str, str] = {}
        self.source = "内置"
        try:
            mod, err = lib_module("d1i18n")
            if mod is not None:
                self.mod = mod
                self.source = f"d1i18n（{Path(getattr(mod, '__file__', '')).name}）"
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
        if self.mod is None:
            self._load_json()

    def _load_json(self) -> None:
        for base in (bundle_dir(), Path(__file__).resolve().parent):
            path = base / "zh_fallback.json"
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            self.tr_map = {clean(k): clean(v) for k, v in (data.get("tr") or {}).items()}
            self.ctx_map = {k: clean(v) for k, v in (data.get("ctx") or {}).items()}
            self.source = f"PO 兜底表（{path.name}，{len(self.tr_map)} 条）"
            return

    # -- 通用 ------------------------------------------------------
    def tr(self, text, fallback=None) -> str:
        text = clean(text)
        if not text:
            return clean(fallback) if fallback is not None else ""
        if self.mod is not None:
            fn = getattr(self.mod, "tr", None)
            if callable(fn):
                try:
                    got = clean(fn(text))
                    if got and got != text:
                        return got
                except Exception:  # noqa: BLE001
                    pass
        got = self.tr_map.get(text)
        if got:
            return got
        return clean(fallback) if fallback is not None else text

    def ctx(self, context: str, text: str) -> str:
        text = clean(text)
        if self.mod is not None:
            fn = getattr(self.mod, "tr_ctx", None) or getattr(self.mod, "pgettext", None)
            if callable(fn):
                try:
                    got = clean(fn(context, text))
                    if got:
                        return got
                except Exception:  # noqa: BLE001
                    pass
        return self.ctx_map.get(f"{context}\x04{text}") or self.tr(text)

    # -- 名称 ------------------------------------------------------
    def item_name(self, en: str, cn_hint: str = "") -> str:
        if self.mod is not None:
            fn = getattr(self.mod, "item_name_cn", None)
            if callable(fn):
                try:
                    got = clean(fn(en))
                    if got:
                        return got
                except Exception:  # noqa: BLE001
                    pass
        got = self.tr_map.get(clean(en))
        if got:
            return got
        return clean(cn_hint) or clean(en)

    def affix_name(self, kind: str, en: str) -> str:
        if self.mod is not None:
            fn = getattr(self.mod, "affix_name_cn", None)
            if callable(fn):
                try:
                    got = clean(fn(kind, en))
                    if got:
                        return got
                except Exception:  # noqa: BLE001
                    pass
        en = clean(en)
        # PO 里金属「Gold」被翻成「金币」（那是物品 Gold），词缀这里用「金」
        if kind.startswith("pre") and en == "Gold":
            return "金"
        lookups = [en]
        if kind.startswith("suf"):
            if en.lower().startswith("of "):
                lookups = [en, en[3:]]
            else:
                lookups = ["the " + en, en, "of " + en]
        for key in lookups:
            got = self.tr_map.get(key) or self.tr_map.get(key.lower())
            if got:
                return got
            got = BUILTIN_AFFIX["suffix" if kind.startswith("suf") else "prefix"].get(key)
            if got:
                return got
        return en

    def unique_name(self, en: str) -> str:
        if self.mod is not None:
            fn = getattr(self.mod, "unique_name_cn", None)
            if callable(fn):
                try:
                    got = clean(fn(en))
                    if got:
                        return got
                except Exception:  # noqa: BLE001
                    pass
        got = self.tr_map.get(clean(en))
        if got:
            return got
        return BUILTIN_UNIQUE.get(clean(en), clean(en))

    def spell_name(self, spell_id: int) -> str:
        try:
            import d1tables as T  # 延迟导入：本模块也可能在没有 lib 时用
            rec = T.spell_by_id(int(spell_id))
            if rec:
                return self.ctx("spell", rec.get("name") or "")
        except Exception:  # noqa: BLE001
            pass
        return f"法术{spell_id}"

    def item_type_cn(self, names) -> str:
        out = []
        for n in names or []:
            out.append(ITEM_TYPE_CN.get(str(n), str(n)))
        return "、".join(dict.fromkeys(out)) or "任意"


ZH = _Zh()


# ---------------------------------------------------------------- 属性说明
def _power_name(power: dict) -> str:
    return str(power.get("type_name") or power.get("power_name") or "")


def _p1p2(power: dict) -> tuple[int, int]:
    try:
        p1 = int(power.get("param1") or 0)
        p2 = int(power.get("param2") or 0)
    except Exception:  # noqa: BLE001
        return 0, 0
    if p1 > p2:
        p1, p2 = p2, p1
    return p1, p2


def _num_range(power: dict, neg: bool = False, scale: int = 1, unit: str = "") -> dict:
    p1, p2 = _p1p2(power)
    sign = -1 if neg else 1
    vmin, vmax = sign * p1 * scale, sign * p2 * scale
    if vmin > vmax:
        vmin, vmax = vmax, vmin
    return {"vmin": vmin, "vmax": vmax}


def power_value(power: dict, value: int | None = None,
                tohit: int | None = None) -> dict:
    """返回一个能力的显示信息。

    power: 词缀 dict（power_name/param1/param2）或暗金能力 dict（type_name/…）
    value: 指定数值（= SaveItemPower 的 r）；None 表示按范围显示。
    tohit: ``King's``/``Knight's`` 这类「伤害 + 命中」词缀的第二个数值
           （= ``CalculateToHitBonus(param1)``）；给出时显示实际命中而不是范围。

    dict 字段：
      name     IPL_*
      label    中文标签
      text     完整中文说明（如 "力量 +6 ~ +10"）
      vmin/vmax 数值范围（不可指定数值时为 None）
      numeric  数值是否可指定（False = 攻速/充能/吸血等固定效果）
      unit, signed
      tohit    第二数值（仅两属性词缀）
    """
    name = _power_name(power)
    p1, p2 = _p1p2(power)
    info = {"name": name, "label": "", "text": "", "vmin": None, "vmax": None,
            "numeric": False, "unit": "", "signed": True, "value": value,
            "tohit": tohit}

    # --- 纯数值型（r = RndPL(p1,p2)，显示 ±r）---
    num = POWER_NUM.get(name)
    if num is not None and name not in ("IPL_DECAY", "IPL_CRYSTALLINE", "IPL_DUR",
                                        "IPL_DUR_CURSE", "IPL_ALLRESZERO"):
        label, unit, signed = num
        neg = name.endswith("_CURSE") or name in ("IPL_AC_CURSE", "IPL_TARGAC")
        if name in ("IPL_TARGAC",):
            neg = False
        r = _num_range(power, neg=neg, unit=unit)
        info.update(label=label, unit=unit, signed=signed, **r)
        info["numeric"] = p1 != p2
        if value is not None and p1 != p2:
            v = -int(value) if neg else int(value)
            info["text"] = f"{label} {_fmt_signed(v, unit)}"
            info["value"] = int(value)
        else:
            info["text"] = _span_text(label, r["vmin"], r["vmax"], unit, signed)
        return info

    # --- 特殊数值型 ---
    if name in ("IPL_TOHIT_DAMP", "IPL_TOHIT_DAMP_CURSE", "IPL_DOPPELGANGER"):
        neg = name == "IPL_TOHIT_DAMP_CURSE"
        r = _num_range(power, neg=neg, unit="%")
        info.update(label="伤害", unit="%", **r)
        info["numeric"] = p1 != p2
        lo, hi = TO_HIT_RANGES.get(-p1 if neg else p1, (0, 0))
        if neg:
            lo, hi = -hi, -lo
        if value is not None and p1 != p2:
            v = -int(value) if neg else int(value)
            if tohit is not None and tohit != "":
                # 两条数值都给：显示实际命中（King's = 伤害 + 命中）
                info["text"] = (f"伤害 {_fmt_signed(v, '%')}，"
                                f"命中 {_fmt_signed(int(tohit))}%")
            else:
                info["text"] = (f"伤害 {_fmt_signed(v, '%')}，"
                                f"命中几率 {_fmt_signed(lo)}~{_fmt_signed(hi)}%")
        elif tohit is not None and tohit != "" and p1 != p2:
            info["text"] = (f"伤害 {_fmt_signed(r['vmin'], '%')}~{_fmt_signed(r['vmax'], '%')}，"
                            f"命中 {_fmt_signed(int(tohit))}%")
        else:
            body = _span_text("伤害", r["vmin"], r["vmax"], "%", True)
            info["text"] = f"{body}，命中几率 {_fmt_signed(lo)}~{_fmt_signed(hi)}%"
        return info
    if name == "IPL_CRYSTALLINE":
        dmg_min, dmg_max = 140 + 2 * p1, 140 + 2 * p2
        info.update(label="伤害", unit="%", vmin=dmg_min, vmax=dmg_max, numeric=p1 != p2)
        info["text"] = (f"伤害 {_fmt_signed(dmg_max, '%') if dmg_min == dmg_max else f'+{dmg_min}%~+{dmg_max}%'}，"
                        f"但最大耐久 -{p1}%~-{p2}%")
        return info
    if name in ("IPL_DUR", "IPL_DUR_CURSE"):
        neg = name == "IPL_DUR_CURSE"
        r = _num_range(power, neg=neg, unit="%")
        info.update(label="耐久", unit="%", **r)
        info["numeric"] = p1 != p2
        info["text"] = _span_text("耐久", r["vmin"], r["vmax"], "%", True)
        return info
    if name == "IPL_ALLRESZERO":
        info.update(label="所有抗性归零", text="所有抗性归零", numeric=False)
        return info
    if name == "IPL_LIGHT":
        info.update(label="光照范围", text=f"光照范围 +{10 * p1}%", numeric=False, vmin=10 * p1, vmax=10 * p2)
        return info
    if name == "IPL_LIGHT_CURSE":
        info.update(label="光照范围", text=f"光照范围 -{10 * p1}%", numeric=False,
                    vmin=-10 * p1, vmax=-10 * p2)
        return info

    # --- 两段/固定效果 ---
    if name in ("IPL_FIREDAM", "IPL_LIGHTDAM"):
        kind_cn = "火焰伤害" if name == "IPL_FIREDAM" else "闪电伤害"
        text = f"{kind_cn} {p1}" if p1 == p2 else f"{kind_cn} {p1}~{p2}"
        info.update(label=kind_cn, text=text, numeric=False)
        return info
    if name in ("IPL_FIRE_ARROWS", "IPL_LIGHT_ARROWS", "IPL_ADDACLIFE", "IPL_FIREBALL"):
        kind_cn = {"IPL_FIRE_ARROWS": "火焰箭伤害", "IPL_LIGHT_ARROWS": "闪电箭伤害",
                   "IPL_ADDACLIFE": "闪电伤害", "IPL_FIREBALL": "火球伤害"}[name]
        text = f"{kind_cn} {p1}" if p1 == p2 else f"{kind_cn} {p1}~{p2}"
        info.update(label=kind_cn, text=text, numeric=False)
        return info
    if name == "IPL_CHARGES":
        info.update(label="额外充能", text=f"额外充能次数 ×{p1}", numeric=False)
        return info
    if name == "IPL_SPELL":
        info.update(label="附加法术",
                    text=f"附加法术：{ZH.spell_name(p1)}（{p2} 充能）", numeric=False)
        return info
    if name == "IPL_STEALMANA":
        pct = STEAL_CN.get(p1, f"{p1}%")
        info.update(label="偷取法力", text=f"击中偷取 {pct} 法力", numeric=False)
        return info
    if name == "IPL_STEALLIFE":
        pct = STEAL_CN.get(p1, f"{p1}%")
        info.update(label="偷取生命", text=f"击中偷取 {pct} 生命", numeric=False)
        return info
    if name == "IPL_FASTATTACK":
        info.update(label="攻击速度", text=FAST_ATTACK_CN.get(p1, f"攻击速度档位 {p1}"),
                    numeric=False)
        return info
    if name == "IPL_FASTRECOVER":
        info.update(label="打击回复", text=FAST_RECOVER_CN.get(p1, f"打击回复档位 {p1}"),
                    numeric=False)
        return info
    if name == "IPL_SETDAM":
        info.update(label="伤害", text=f"伤害改写为 {p1}~{p2}", numeric=False)
        return info
    if name == "IPL_SETDUR":
        info.update(label="耐久", text=f"耐久改写为 {p1}", numeric=False)
        return info
    if name == "IPL_AC_CURSE":
        info.update(label="防御", text=f"防御 {_fmt_signed(-p1)}", numeric=False,
                    vmin=-p1, vmax=-p2)
        return info
    if name in POWER_TEXT:
        info.update(label=POWER_TEXT[name], text=POWER_TEXT[name], numeric=False)
        return info

    info.update(label=name or "特殊效果",
                text=POWER_TEXT.get(name) or f"特殊效果（{name or '未知'}）", numeric=False)
    return info


def _span_text(label: str, vmin: int, vmax: int, unit: str, signed: bool = True) -> str:
    if vmin == vmax:
        return f"{label} {_fmt_signed(vmin, unit) if signed else f'{vmin}{unit}'}"
    a = _fmt_signed(vmin, unit) if signed else f"{vmin}{unit}"
    b = _fmt_signed(vmax, unit) if signed else f"{vmax}{unit}"
    return f"{label} {a} ~ {b}"


def describe_power(power: dict, value: int | None = None,
                   tohit: int | None = None) -> str:
    """一条能力的中文说明（用于暗金图鉴 / 预览）。优先用 d1i18n.describe_power。

    ``tohit`` 只用于「伤害 + 命中」两属性词缀；给出时直接显示实际命中值。
    """
    if tohit is None and ZH.mod is not None:
        fn = getattr(ZH.mod, "describe_power", None)
        if callable(fn):
            try:
                text = clean(fn(dict(power), value) if value is not None else fn(dict(power)))
            except TypeError:
                try:
                    text = clean(fn(dict(power)))
                except Exception:  # noqa: BLE001
                    text = ""
            except Exception:  # noqa: BLE001
                text = ""
            if text:
                return text
    return power_value(power, value, tohit)["text"]


# ---------------------------------------------------------------- 词缀说明
def affix_name(kind: str, affix: dict) -> str:
    en = clean(affix.get("name"))
    return ZH.affix_name(kind, en)


def affix_label(kind: str, affix: dict, ilvl: int | None = None) -> str:
    """下拉里显示的名字：中文（English）+ 数值范围。"""
    en = clean(affix.get("name"))
    cn = ZH.affix_name(kind, en)
    label = f"{cn}（{en}）" if cn and cn != en else (en or "?")
    return label


def _accepts_kw(fn, name: str) -> bool:
    """函数是否显式接受某个关键字参数（兼容 d1i18n 的新旧签名）。"""
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def affix_effect_label(kind: str, affix: dict) -> str:
    """词缀的**效果名**（Round 3）：``伤害`` / ``火焰抗性`` / ``所有抗性`` /
    ``所有属性`` / ``法力`` / ``力量`` …

    下拉列表用它拼成 ``红宝石（Ruby） 火焰抗性 +51 ~ +60``，让用户在选中前就能
    看出这一条加的是什么属性（Round 2 只有名字 + 数值范围）。

    取数优先级：
      1. ``d1i18n.affix_effect_label(affix)``（core Round 3 新增）；
      2. ``d1i18n.affix_label(kind, affix, with_effect=True)`` 里的效果部分；
      3. 本模块 ``power_value(affix)["label"]``（表驱动，最稳）；
      4. ``BUILTIN_EFFECT`` 兜底（Ruby/Sapphire/Diamond/Obsidian/Dragon's 等）。
    """
    if not affix:
        return ""
    kind_key = "suffix" if str(kind or "").lower().startswith("suf") else "prefix"
    en = clean(affix.get("name"))
    mod = ZH.mod
    if mod is not None:
        fn = getattr(mod, "affix_effect_label", None)
        if callable(fn):
            try:
                got = clean(fn(dict(affix)))
            except Exception:  # noqa: BLE001
                got = ""
            if got:
                return got
        # 兼容 affix_label(..., with_effect=True)：它返回完整 label，
        # 这里把“中文（English）”与数值部分剥掉，只留效果名。
        fn2 = getattr(mod, "affix_label", None)
        if callable(fn2) and _accepts_kw(fn2, "with_effect"):
            full = plain = ""
            try:
                full = clean(fn2(kind, dict(affix), with_effect=True))
                plain = clean(fn2(kind, dict(affix)))
            except Exception:  # noqa: BLE001
                full = ""
            if full and full != plain:
                extra = full[len(plain):] if plain and full.startswith(plain) else full
                extra = clean(extra).lstrip("：:，,+ ")
                extra = re.sub(r"[+-]?\d[\d\s~\-+%]*$", "", extra).strip()
                if extra:
                    return extra
    info = power_value(affix)
    label = clean(info.get("label"))
    if label and label != en:
        return label
    return BUILTIN_EFFECT.get((kind_key, en), label or en)


def affix_value_range(affix: dict) -> tuple[int, int] | None:
    """词缀数值范围（= SaveItemPower 的 r ∈ [param1, param2]，负数给负值）。"""
    info = power_value(affix)
    if info["vmin"] is None or info["vmax"] is None:
        return None
    return int(info["vmin"]), int(info["vmax"])


def affix_desc(kind: str, affix: dict, value: int | None = None) -> str:
    """词缀说明：效果、数值范围、需求等级、适用装备。

    优先用 ``d1i18n.affix_desc``（i18n 代理用游戏 PO 文案生成，更贴近游戏内
    tooltip）；不可用时退回本模块自己拼。
    """
    if not affix:
        return ""
    if ZH.mod is not None:
        fn = getattr(ZH.mod, "affix_desc", None)
        if callable(fn):
            try:
                text = clean(fn(dict(affix), value))
            except TypeError:
                try:
                    text = clean(fn(dict(affix)))
                except Exception:  # noqa: BLE001
                    text = ""
            except Exception:  # noqa: BLE001
                text = ""
            if text:
                return text
    en = clean(affix.get("name"))
    cn = ZH.affix_name(kind, en)
    info = power_value(affix, value)
    lines = []
    head = f"{cn}（{en}）" if cn and cn != en else (cn or en)
    lines.append(f"{head}：{info['text']}")
    if info["numeric"]:
        rng = affix_value_range(affix)
        if rng:
            lines.append(f"数值范围 {_fmt_signed(rng[0])} ~ {_fmt_signed(rng[1])}"
                         f"（可指定目标值）")
    else:
        lines.append("固定效果：数值不可指定（由词缀本身决定）")
    lvl = affix.get("min_level")
    if lvl is not None:
        lines.append(f"需求物品等级 {lvl}（物品等级需 ≥ {lvl}，且 ≤ {int(lvl) * 2 + 1} 附近）")
    lines.append("适用装备：" + ZH.item_type_cn(affix.get("item_type_names") or []))
    if affix.get("ok") is False:
        lines.append("⚠ 这是「坏词缀」（游戏中带诅咒效果）")
    if affix.get("hellfire_only"):
        lines.append("⚠ 仅 Hellfire 版本可用")
    return "；".join(lines[:2]) + "\n" + "\n".join(lines[2:])


def item_full_name_cn(base_cn: str, prefix_cn: str = "", suffix_cn: str = "",
                      spell_cn: str = "") -> str:
    """按游戏的 zh_CN 模板拼中文物品名。

    英文：``Prefix Base of Suffix`` / ``Base of Spell`` / ``Prefix Base of Spell``
    中文：``SuffixPrefixBase``（PO: "{2}{0}{1}"）。
    """
    base_cn = clean(base_cn)
    pre = clean(prefix_cn)
    suf = clean(suffix_cn)
    sp = clean(spell_cn)
    if sp:
        tpl = ZH.ctx("spell", "{0} {1} of {2}") if pre else ZH.ctx("spell", "{0} of {1}")
        try:
            if pre:
                return tpl.format(pre, base_cn, sp)
            return tpl.format(base_cn, sp)
        except Exception:  # noqa: BLE001
            return f"{pre}{base_cn} of {sp}" if pre else f"{base_cn} of {sp}"
    if pre and suf:
        return f"{suf}{pre}{base_cn}"
    if pre:
        return f"{pre}{base_cn}"
    if suf:
        return f"{suf}{base_cn}"
    return base_cn


def i18n_status() -> str:
    if ZH.mod is not None:
        return f"中文数据：{ZH.source}"
    return f"中文数据：{ZH.source}"


def tr(text, fallback=None) -> str:
    return ZH.tr(text, fallback)


def item_name_cn(en: str, cn_hint: str = "") -> str:
    return ZH.item_name(en, cn_hint)


def unique_name(en: str) -> str:
    return ZH.unique_name(en)


def spell_name(spell_id: int) -> str:
    return ZH.spell_name(spell_id)
