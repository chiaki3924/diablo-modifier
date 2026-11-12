"""装备生成适配层：包装 work/lib/d1itemgen.py + d1tables.py（Round 2）。

职责：
  * **底材过滤**（防崩溃核心）：只保留 ``available`` + ``droppable`` 且
    **非 starter / 非 unique_only** 的普通装备底材。``IDI_SORCERER_DIABLO``
    （Short Staff of Charged Bolt，saved idx=5 / runtime 166）永远不出现；
    itemgen2 若已提供 ``generatable``/``starter`` 字段则以它为准，但仍做防御性
    二次过滤。
  * 词缀：中文名（括号英文）、数值范围、说明、是否可指定数值。
  * 生成：``prefix_value`` / ``suffix_value`` / ``value_tolerance`` 透传，
    不支持时（旧版 itemgen）给出中文提示。
  * 暗金：89 件列表 + ``unique_detail``（中文词条明细），生成用「普通底材 +
    unique_id」。
  * 记录体检：``check_record()`` 给储物箱页的「检查异常物品」用。
"""
from __future__ import annotations

import inspect
import random
import re
import time
from dataclasses import dataclass, field

import d1zh
from d1env import MODULES, lib_module
from d1names import item_category, item_cn, item_en, item_size

# 可装备的 itype 名称 -> 界面分组
EQUIP_KINDS = {
    "Sword": "武器", "Axe": "武器", "Bow": "武器", "Mace": "武器", "Staff": "武器",
    "Shield": "防具", "Helm": "防具",
    "LightArmor": "防具", "MediumArmor": "防具", "HeavyArmor": "防具",
    "Ring": "戒指护符", "Amulet": "戒指护符",
}
KIND_ORDER = ["武器", "防具", "戒指护符"]

#: 初始装备（IDROP_NEVER + 开局自带）。绝不能当随机底材生成：
#:   IDI_WARRIOR=1(Short Sword) / IDI_ROGUE=2(Buckler) / IDI_SORCERER=5
#:   / IDI_SORCERER_DIABLO=166(Short Staff of Charged Bolt，用户崩溃元凶)
#:   另有 3=Club、4=Short Bow（战士/弓手的起始装备）。
STARTER_NAMES = {
    "Short Sword", "Buckler", "Club", "Short Bow", "Short Staff of Mana",
    "Short Staff of Charged Bolt",
}
STARTER_IDS = ("IDI_WARRIOR", "IDI_ROGUE", "IDI_SORCERER", "IDI_SORCERER_DIABLO")

#: 暗金图鉴里需要注意的「任务暗金」（底材是 IMISC_UNIQUE 专用行）
QUEST_UNIQUE_MAX = 9


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _clamp_band(lo: int, hi: int) -> tuple[int, int]:
    """把词缀合法 ilvl 区间 clamp 到界面允许的 1..50。"""
    lo = max(1, min(50, int(lo)))
    hi = max(1, min(50, int(hi)))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def _has_value(value) -> bool:
    """是否真的指定了数值（``None`` / ``""`` / 全空列表都算没指定）。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_has_value(v) for v in value)
    return True


def _value_arg(value):
    """把界面/API 的数值参数规范成 core 接受的形式。

    * 单个 int（或整数字符串）-> int；
    * ``"151/93"`` / ``"151,93"`` -> ``[151, 93]``；
    * list/tuple -> 逐项转 int，空项保留为 ``None``（= 该槽不限制）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace("，", "/").replace(",", "/")
        if "/" not in text:
            return int(text) if text else None
        parts = [p.strip() for p in text.split("/")]
        out = []
        for part in parts:
            out.append(int(part) if part not in ("", "-", "+") else None)
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None or (isinstance(item, str) and not item.strip()):
                out.append(None)
            else:
                out.append(int(item))
        return out
    return int(value)


def _local_affix_band(level: int) -> tuple[int, int]:
    """``affix_ilvl_band`` 的本地实现（core 未就绪时用）。

    ``minlvl = min(ilvl // 2, 25)`` / ``maxlvl = ilvl``，词缀等级 L 必须落在
    窗口内：``L >= 25`` 时 ilvl ∈ [L, 50]，否则 ilvl ∈ [L, min(2L+1, 50)]。
    """
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    if level >= 25:
        return _clamp_band(level, 50)
    return _clamp_band(level, min(2 * level + 1, 50))


def _is_ac_replay_mismatch(message: str) -> bool:
    """``validate`` 的问题是否是「replay mismatch AC」（满值护甲的特征）。"""
    low = str(message or "").lower()
    if "mismatch" not in low:
        return False
    return bool(re.search(r"\bac\b", low))


def _starter_indices() -> set[int]:
    out: set[int] = set()
    try:
        T = MODULES_TABLES()
        indexes = getattr(T, "ITEM_INDEXES", {}) or {}
        for key in STARTER_IDS:
            if key in indexes:
                out.add(int(indexes[key]))
    except Exception:  # noqa: BLE001
        pass
    try:
        # 兜底：已知的 1.5.5 编号（Short Sword / Buckler / Club / Short Bow /
        # Short Staff of Mana / Short Staff of Charged Bolt）
        out |= {1, 2, 3, 4, 5, 166}
    except Exception:  # noqa: BLE001
        pass
    return out


def MODULES_TABLES():
    """d1tables 模块（itemgen 已 import 它，通常在 sys.modules 里）。"""
    import sys
    for name in ("d1tables",):
        mod = sys.modules.get(name)
        if mod is not None:
            return mod
    raise RuntimeError("d1tables 尚未加载")


@dataclass
class BaseItem:
    idx: int                 # 运行时编号
    name: str                # 英文名
    cn: str                  # 中文名
    category: str            # 细分（剑/斧/…）
    kind: str = ""           # 武器/防具/戒指护符
    size: tuple[int, int] = (1, 1)
    saved_idx: int = 0
    has_unique: bool = False  # 该底材是否有对应暗金
    starter: bool = False
    unique_only: bool = False
    droppable: bool = True
    raw: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.cn}（{self.name}）" if self.name and self.name != self.cn else self.cn

    @property
    def blocked_reason(self) -> str:
        """不能作为随机底材的原因（空字符串 = 可以）。"""
        if self.starter:
            return "初始装备（starter），游戏只为开局角色生成，写进存档会导致进游戏崩溃"
        if self.unique_only:
            return "暗金专用底材（IMISC_UNIQUE），只能由暗金生成使用"
        if not self.droppable:
            return "非掉落底材（IDROP_NEVER），不能作为随机魔法底材"
        return ""

    @property
    def generatable(self) -> bool:
        return not self.blocked_reason


@dataclass
class Affix:
    raw: dict
    kind: str
    gen: "ItemGen | None" = None

    @property
    def index(self) -> int:
        return int(_pick(self.raw, "index", default=-1) or -1)

    @property
    def en(self) -> str:
        return str(_pick(self.raw, "name", default="") or "")

    @property
    def cn(self) -> str:
        return d1zh.affix_name(self.kind, self.raw)

    @property
    def min_level(self) -> int:
        return int(_pick(self.raw, "min_level", "level", "ilvl", default=0) or 0)

    @property
    def band(self) -> tuple[int, int]:
        """该词缀合法的物品等级区间 ``(lo, hi)``（Round 4）。

        游戏按 ``minlvl = min(ilvl // 2, 25)``、``maxlvl = ilvl`` 选词缀，
        所以词缀等级 L 的合法 ilvl 区间是::

            L >= 25 -> [L, 50]
            L <  25 -> [L, min(2L + 1, 50)]

        优先用 core 的 ``d1itemgen.affix_ilvl_band``（若有），否则本地算。
        结果一律 clamp 到 1..50（界面允许的范围）。
        """
        level = self.min_level
        if level > 50:
            # 词缀等级超出界面可选 ilvl 上限：**不要 clamp/swap**，
            # 保留真实 (L, 50) 让 UI 显示“需要 ilvl 60（无法生成）”。
            return (level, 50)
        mod = getattr(self.gen, "mod", None) if self.gen is not None else None
        fn = getattr(mod, "affix_ilvl_band", None) if mod is not None else None
        if callable(fn):
            try:
                lo, hi = fn(dict(self.raw))
                return _clamp_band(int(lo), int(hi))
            except Exception:  # noqa: BLE001 - core 未就绪/返回异常：本地算
                pass
        return _local_affix_band(level)

    @property
    def band_text(self) -> str:
        """``ilvl 16~33``；min_level>50 时给出无法生成的说明。"""
        level = self.min_level
        if level > 50:
            return f"需要 ilvl {level}（超出可选 1~50，无法生成）"
        band = self.band
        if band is None:
            return ""
        return f"ilvl {band[0]}~{band[1]}"

    @property
    def info(self) -> dict:
        return d1zh.power_value(self.raw)

    def range_tuple(self) -> tuple[int, int] | None:
        """可指定的数值范围（显示值，诅咒词缀为负）。"""
        if self.gen is not None:
            rng = self.gen.affix_range(self.raw, self.kind)
            if rng is not None:
                return rng
        info = self.info
        if info.get("vmin") is None or info.get("vmax") is None:
            return None
        return int(info["vmin"]), int(info["vmax"])

    @property
    def vmin(self) -> int | None:
        rng = self.range_tuple()
        return rng[0] if rng else None

    @property
    def vmax(self) -> int | None:
        rng = self.range_tuple()
        return rng[1] if rng else None

    @property
    def numeric(self) -> bool:
        """数值可否指定（攻速/充能/吸血等固定词缀为 False）。"""
        if self.gen is not None:
            return self.gen.affix_is_numeric(self.raw, self.kind)
        return bool(self.info.get("numeric"))

    @property
    def sets_ac(self) -> bool:
        """该词缀是否**直接设定** AC（``IPL_SETAC``）。

        Round 4：这种词缀与「护甲取最大值」互斥（core 会报
        ``base_stats_conflict``），GUI 用来提前禁用/提示。
        """
        return str(_pick(self.raw, "power_name", default="") or "") == "IPL_SETAC"

    @property
    def range_text(self) -> str:
        """数值范围文本；两条属性的词缀逐槽列出（伤害 / 命中各自的范围）。"""
        slots = self.value_slots
        if len(slots) > 1:
            parts = []
            for spec in slots:
                rng = spec.get("range")
                if not rng:
                    continue
                try:
                    lo, hi = int(rng[0]), int(rng[1])
                except (TypeError, ValueError, IndexError):
                    continue
                label = str(spec.get("label") or "数值")
                parts.append(f"{label} {lo:+d}" if lo == hi
                             else f"{label} {lo:+d} ~ {hi:+d}")
            if parts:
                return "，".join(parts)
        rng = self.range_tuple()
        if rng is None:
            return "固定效果"
        lo, hi = rng
        if lo == hi:
            return f"{lo:+d}"
        return f"{lo:+d} ~ {hi:+d}"

    @property
    def value_slots(self) -> list[dict]:
        """可填的数值槽位：多数词缀 1 个，``King's`` 等两条属性 2 个。

        每个槽位是 ``{"key": "value"|"tohit", "label": "伤害"/"命中",
        "range": (lo, hi)}``；界面据此显示「数值」或「伤害 / 命中」两个输入框。
        """
        if self.gen is not None:
            try:
                slots = self.gen.affix_value_slots(self.raw, self.kind)
                if slots:
                    return list(slots)
            except Exception:  # noqa: BLE001
                pass
        rng = self.range_tuple()
        if rng is None:
            return []
        return [{"key": "value", "label": self.effect or "数值", "range": rng}]

    @property
    def effect(self) -> str:
        """效果名（Round 3）：伤害 / 火焰抗性 / 所有抗性 / 所有属性 / 法力 …"""
        return d1zh.affix_effect_label(self.kind, self.raw)

    @property
    def label(self) -> str:
        """下拉文本：``红宝石（Ruby） 火焰抗性 +51 ~ +60 〔ilvl 16~33〕``。"""
        cn = self.cn
        en = self.en
        name = f"{cn}（{en}）" if cn and cn != en else (cn or en or "?")
        if len(self.value_slots) > 1:
            # 两条属性的词缀：范围里已经分别写了「伤害 …，命中 …」，不要再加效果名
            body = name
        else:
            effect = self.effect
            body = f"{name} {effect}" if effect else name
        return f"{body} {self.range_text} 〔{self.band_text}〕"

    @property
    def desc(self) -> str:
        """词缀说明；Round 4 起补充「合法 ilvl 区间」并解释窗口。"""
        text = d1zh.affix_desc(self.kind, self.raw)
        if "需要物品等级" in text:
            level = self.min_level
            if level > 50:
                text += (f"\n（需要 ilvl {level}；超出可选 1~50，无法生成）")
            else:
                band = self.band
                text += (f"\n（合法 ilvl 区间 {band[0]}~{band[1]}"
                         "；ilvl 太低或太高都会出不了）")
        return text

    def desc_for(self, value: int | None = None) -> str:
        return d1zh.affix_desc(self.kind, self.raw, value)


@dataclass
class UniqueItem:
    uid: int
    en: str
    cn: str
    base_idx: int
    base_en: str = ""
    base_cn: str = ""
    base_unique_only: bool = False
    base_available: bool = True
    min_level: int = 0
    value: int = 0
    powers: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.cn}（{self.en}）"

    @property
    def note(self) -> str:
        if not self.base_available:
            return "该暗金的底材在 1.5.5 非 Hellfire 中不可用"
        if self.uid <= QUEST_UNIQUE_MAX:
            return "任务暗金：底材是游戏专用的暗金行（IMISC_UNIQUE），生成后在游戏里就是该暗金"
        return ""

    def to_rows(self) -> list[tuple[str, str]]:
        """(类型, 中文说明) 列表；跳过游戏里显示空白的 IPL_INVCURS。"""
        out: list[tuple[str, str]] = []
        for p in self.powers or []:
            name = str(p.get("type_name") or "")
            if name in ("IPL_INVALID", "", "IPL_INVCURS"):
                continue
            out.append((name, d1zh.describe_power(p)))
        return out


@dataclass
class GenResult:
    record: bytes | None = None
    fields: dict = field(default_factory=dict)
    name: str = ""
    name_cn: str = ""
    seed: int | None = None
    create_info: int | None = None
    runtime_idx: int | None = None
    text: str = ""
    validation: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    error: str = ""
    prefix: str = ""
    suffix: str = ""
    prefix_value: int | None = None
    suffix_value: int | None = None
    unique: str = ""
    # ---- Round 4：法杖充能 / 基础属性满值 ----
    staff_spell: int | None = None       # 法术 id（记录里的 spell 字段）
    charges: int | None = None           # 当前充能
    max_charges: int | None = None       # 最大充能
    base_stats_note: str = ""            # core 写回的基础属性说明
    applied_max_ac: bool = False         # 是否真的把 AC 写成了满值
    applied_full_durability: bool = False  # 是否真的把耐久写成了满值
    # ---- Round 6：一个词缀两条数值（King's = 伤害 + 命中）----
    prefix_values: list = field(default_factory=list)   # 前缀各槽实际值（记录反推）
    suffix_values: list = field(default_factory=list)   # 后缀各槽实际值
    # ---- Round 5/6：可丢地上（ilvl<=34，31~34 走暗金怪路线）----
    droppable: bool = False              # 记录本身能被游戏判定为合法掉落物
    drop_note: str = ""                  # 可丢地上 / 只能放储物箱的说明
    drop_mode: str = ""                  # "" / "dungeon" / "unique_monster"
    record_ilvl: int | None = None       # 记录里 iCreateInfo 的实际等级
    ilvl: int | None = None              # 请求的词缀等级（31~34 时 != record_ilvl）

    @property
    def ok(self) -> bool:
        return not self.validation and not self.error


def friendly_error(exc: Exception) -> str:
    """把 d1itemgen 的英文异常翻成能看懂的中文提示（保留细节）。"""
    text = str(exc)
    low = text.lower()
    code = str(getattr(exc, "code", "") or "")
    # ---- Round 4：法术法杖 / 满值冲突 ----
    if code == "bad_staff_spell":
        return f"法术/充能设置不合法：{text}"
    if code == "bad_staff_charges":
        return f"充能值不合法（必须在该法术的 staff_min~staff_max 内）：{text}"
    if code == "staff_spell_suffix":
        return f"法术法杖没有后缀，请去掉后缀：{text}"
    if code == "base_stats_conflict":
        return f"基础属性满值与所选词缀/底材冲突：{text}"
    if code == "staff_ilvl":
        return f"法杖 ilvl 太高（1.5.5 已知怪癖）：{text}"
    if code == "drop_ilvl":
        return f"ilvl 太高，丢地上会提示「无效的数据包」并消失：{text}"
    if "staff spell" in low or "staff_spell" in low or "法术法杖" in text:
        return f"法术法杖设置有问题：{text}"
    if "staff charge" in low or ("charges" in low and "staff" in low):
        return f"法杖充能设置有问题：{text}"
    if "base stats conflict" in low or "护甲取最大" in text or "base_stats_conflict" in low:
        return f"基础属性满值与所选词缀冲突：{text}"
    if "not a starter" in low or "starter" in low:
        return f"初始装备（starter）不能作为随机底材生成：{text}"
    if "unique-only" in low or "unique only" in low:
        return f"这是暗金专用底材，不能当普通/魔法底材生成：{text}"
    if "no unique" in low or ("unique" in low and "based on" in low):
        return f"该底材没有匹配的暗金物品：{text}"
    if "no prefix" in low or "no suffix" in low:
        return f"该等级/底材下不存在该词条：{text}"
    if "not valid for" in low:
        return f"该词条不适用于这个底材：{text}"
    if "requires item level" in low or "requires affix level" in low:
        return f"物品等级不够：{text}"
    if "unknown or unavailable base" in low:
        return f"这个底材不能生成：{text}"
    if "hellfire" in low:
        return f"该词条只属于 Hellfire：{text}"
    if "cannot carry affixes" in low:
        return f"普通物品不能带词条：{text}"
    if "value" in low and ("not found" in low or "no seed" in low
                           or "closest" in low or "within" in low):
        return f"没找到符合该数值的组合：{text}"
    return text


#: 失败原因分类（Round 3）。GUI 用这些 code 决定提示语气与建议。
FAIL_BASE = "base_illegal"                 # 底材非法（starter / unique_only / 不可用）
FAIL_AFFIX_LEVEL_LOW = "affix_level_too_low"     # 词缀等级 > ilvl 窗口上限
FAIL_AFFIX_LEVEL_HIGH = "affix_level_too_high"   # 词缀等级 < ilvl 窗口下限
FAIL_AFFIX_TYPE = "affix_wrong_type"       # 词缀不适用于该底材类型
FAIL_AFFIX_MISSING = "affix_missing"       # 该等级/底材下不存在该词缀
FAIL_FIXED_VALUE = "fixed_no_value"         # 固定效果词缀不能指定数值
FAIL_VALUE_RANGE = "value_out_of_range"    # 目标数值超出词缀范围
FAIL_SEARCH = "search_budget"              # 组合合法，但搜索预算内没找到
FAIL_ILVL = "ilvl_range"                   # ilvl 越界
FAIL_NO_AFFIX = "base_no_affix"            # 该底材类型永远不会滚词缀
FAIL_NO_BONUS = "no_bonus_roll"            # 该等级游戏可能不滚词缀
FAIL_STAFF = "staff_ilvl"                  # 法杖 ilvl>51 的已知怪癖
FAIL_DROP_ILVL = "drop_ilvl"               # 勾选“保证可丢地上”但 ilvl>34
FAIL_VALIDATE = "validate_failed"          # 生成成功但校验失败
FAIL_NORMAL_AFFIX = "normal_with_affix"    # 普通物品不能带词缀
FAIL_OTHER = "other"

_KIND_CN = {"prefix": "前缀", "suffix": "后缀"}

#: 失败 code -> 弹窗标题（core 只给 code 时也能给中文标题）
_CODE_TITLE = {
    # core d1itemgen.check_combination / ItemGenError.code（Round 3）
    "bad_base": "底材非法（游戏规则不允许）",
    "bad_affix": "该词缀不能用于这个底材/等级（游戏规则不允许）",
    "level_window": "词缀等级窗口不匹配（游戏规则不允许）",
    "goe_conflict": "善良/邪恶词缀冲突（游戏规则不允许）",
    "fixed_affix_value": "这是固定效果词缀，不能指定数值",
    "value_out_of_range": "目标数值超出该词缀的范围",
    "seed_not_found": "组合合法，但搜索预算内没找到（不是非法组合）",
    "staff_ilvl": "法杖 ilvl 太高（1.5.5 已知怪癖）",
    "drop_ilvl": "ilvl 太高，丢地上会消失（游戏判定为非法数据包）",
    "bad_ilvl": "ilvl 越界",
    "bad_rarity": "稀有度有误",
    "bad_value": "数值有误",
    # ---- Round 4：法术法杖 / 基础属性满值 ----
    "bad_staff_spell": "法术/充能设置不合法（游戏规则不允许）",
    "bad_staff_charges": "充能值超出该法术允许的范围",
    "staff_spell_suffix": "法术法杖没有后缀（游戏规则不允许）",
    "base_stats_conflict": "基础属性满值与所选词缀冲突（游戏规则不允许）",
    # 本适配层自己的 code
    FAIL_BASE: "底材非法（游戏规则不允许）",
    FAIL_AFFIX_LEVEL_LOW: "词缀等级不够（游戏规则不允许）",
    FAIL_AFFIX_LEVEL_HIGH: "ilvl 太高，该词缀落在窗口之外（游戏规则不允许）",
    FAIL_AFFIX_TYPE: "该词缀不能出现在这个底材上（游戏规则不允许）",
    FAIL_AFFIX_MISSING: "该等级/底材下不存在这个词缀",
    FAIL_FIXED_VALUE: "这是固定效果词缀，不能指定数值",
    FAIL_VALUE_RANGE: "目标数值超出该词缀的范围",
    FAIL_SEARCH: "组合合法，但搜索预算内没找到（不是非法组合）",
    FAIL_ILVL: "ilvl 越界",
    FAIL_NO_AFFIX: "该底材不会滚词缀（游戏规则不允许）",
    FAIL_NO_BONUS: "该 ilvl 下游戏可能不滚词缀",
    FAIL_STAFF: "法杖 ilvl 太高（1.5.5 已知怪癖）",
    FAIL_DROP_ILVL: "ilvl 太高，丢地上会消失（游戏判定为非法数据包）",
    FAIL_VALIDATE: "合法性校验未通过",
    FAIL_NORMAL_AFFIX: "普通物品不能带词缀",
}

#: core code -> 本适配层的 code（让 GUI 的分类逻辑只看一套 code）
_CORE_TO_LOCAL = {
    "bad_base": FAIL_BASE,
    "bad_affix": FAIL_AFFIX_TYPE,
    "level_window": FAIL_AFFIX_LEVEL_LOW,
    "goe_conflict": FAIL_AFFIX_TYPE,
    "fixed_affix_value": FAIL_FIXED_VALUE,
    "value_out_of_range": FAIL_VALUE_RANGE,
    "seed_not_found": FAIL_SEARCH,
    "staff_ilvl": FAIL_STAFF,
    "drop_ilvl": FAIL_DROP_ILVL,
    "bad_ilvl": FAIL_ILVL,
    "bad_rarity": FAIL_ILVL,
    "bad_value": FAIL_VALUE_RANGE,
    "bad_staff_spell": "bad_staff_spell",
    "bad_staff_charges": "bad_staff_charges",
    "staff_spell_suffix": "staff_spell_suffix",
    "base_stats_conflict": "base_stats_conflict",
}


def _refine_level_code(code: str, message: str) -> str:
    """core 把「等级太高/太低」都归为 level_window；按中文消息拆成两个 code。"""
    if code != FAIL_AFFIX_LEVEL_LOW:
        return code
    text = str(message or "")
    if ("降到" in text or "太高" in text or "below this item" in text
            or "use a lower ilvl" in text):
        return FAIL_AFFIX_LEVEL_HIGH
    return code


def _title_for_code(code: str) -> str:
    code = str(code or "")
    if code in _CODE_TITLE:
        return _CODE_TITLE[code]
    low = code.lower()
    for key, title in _CODE_TITLE.items():
        if key.lower() == low:
            return title
    return "组合预检未通过"


def _default_suggestions(code: str) -> list[str]:
    """core 没给建议时，按失败类别补一套通用建议。"""
    if code == FAIL_SEARCH:
        return _suggest_search()
    if code == FAIL_VALUE_RANGE:
        return ["按「范围」提示填一个范围内的值", "或者把「容差」调大一点"]
    if code == FAIL_FIXED_VALUE:
        return ["把「目标值」清空（留空 = 用词缀自带的效果）",
                "或者换一个数值型词缀（抗性/力量/伤害% 之类）"]
    if code == FAIL_STAFF:
        return ["把 ilvl 降到 51 或更低", "换一个非法杖底材"]
    if code == FAIL_DROP_ILVL:
        return ["把 ilvl 降到 34（或更低）",
                "ilvl 31~34 会自动走暗金怪路线（记录等级 -4 + CF_UPER15），最高可选 34",
                "或者取消「保证可丢地上」：ilvl>34 的物品只能放储物箱"]
    if code == FAIL_NORMAL_AFFIX:
        return ["把稀有度改成「魔法」", "或者把前缀/后缀都留「（随机合法）」"]
    if code == "bad_staff_spell":
        return ["只在「法杖」底材上指定法术/充能",
                "换一个下拉里的法术（或用「（随机法术）」）"]
    if code == "bad_staff_charges":
        return ["把充能值改成该法术显示的 min~max 之间",
                "或者留空 = 随机充能"]
    if code == "staff_spell_suffix":
        return ["法术法杖只有前缀、没有后缀：把后缀留「（随机合法）」或清空",
                "想要后缀请改选「属性法杖」"]
    if code == "base_stats_conflict":
        return ["取消「护甲取最大」，或者换一个不是直接设定 AC 的词缀",
                "「耐久取满」与词缀无关，可以保留"]
    return []


@dataclass
class ComboCheck:
    """生成前预检 / 失败分类的结果（GUI 直接显示）。"""

    ok: bool = True
    code: str = ""
    title: str = ""
    message: str = ""
    suggestions: list[str] = field(default_factory=list)
    detail: str = ""            # 英文原文 / 额外技术细节（灰色小字）
    source: str = ""            # "core" / "local"

    def text(self) -> str:
        """拼成给人看的完整中文说明（预览区 / 弹窗都用它）。"""
        lines = [self.title or ("组合合法" if self.ok else "无法生成该物品")]
        if self.message:
            lines.append(self.message)
        if self.suggestions:
            lines.append("")
            lines.append("建议：")
            lines.extend(f"  · {s}" for s in self.suggestions)
        if self.detail:
            lines.append("")
            lines.append(f"（技术细节：{self.detail}）")
        return "\n".join(lines)


def _suggest_ilvl(need: int) -> list[str]:
    hi = max(need, min(50, 2 * need + 1))
    return [
        f"把 ilvl 提到 {need} 或更高（该词缀可用区间 {need}~{hi}）",
        f"或者把 ilvl 设成 {min(hi, max(need, 30))} 左右再试",
        "不想改 ilvl 就换一个需求量等级更低的词缀",
    ]


def _suggest_lower_ilvl(max_ilvl: int) -> list[str]:
    return [
        f"把 ilvl 降到 {max_ilvl} 或更低（词缀等级必须 ≥ ilvl//2）",
        "或者换一个等级更高的词缀",
        "也可以直接留「（随机合法）」，让程序自己挑词缀",
    ]


def _suggest_search() -> list[str]:
    return [
        "把「容差」调大一点（例如 3~5），给搜索留余地",
        "只指定一个数值（前缀或后缀），另一个留空随机",
        "换一个数值范围更常见的词缀，或稍微调整 ilvl",
        "把数量降到 1 件、再点一次生成（每次换随机起点）",
    ]


def classify_error(exc: Exception | str) -> ComboCheck:
    """把 d1itemgen 的异常翻成「原因 + 建议」的中文分类结果（Round 3）。"""
    text = str(exc)
    low = text.lower()

    # core 的 ItemGenError 带 .code / .suggestions（Round 3）：直接用，最准确
    core_code = str(getattr(exc, "code", "") or "")
    if core_code and core_code not in ("ok", "error"):
        local = _CORE_TO_LOCAL.get(core_code, core_code)
        local = _refine_level_code(local, text)
        sugg = [str(s) for s in (getattr(exc, "suggestions", None) or [])]
        return ComboCheck(
            ok=False, code=local,
            title=_CODE_TITLE.get(local) or _title_for_code(core_code),
            message=text,
            suggestions=sugg or _default_suggestions(local),
            detail=f"core code={core_code}")

    m = re.search(r"(prefix|suffix) '([^']+)' requires affix level (\d+), but ilvl=(\d+) "
                  r"only allows (\d+)\.\.(\d+) \(raise ilvl to at least (\d+)\)", text)
    if m:
        kind, name, lv, ilvl, lo, hi, need = m.groups()
        kind_cn = _KIND_CN.get(kind, kind)
        return ComboCheck(
            ok=False, code=FAIL_AFFIX_LEVEL_LOW,
            title="词缀等级不够（游戏规则不允许）",
            message=(f"{kind_cn}「{name}」需要词缀等级 {lv}；"
                     f"ilvl={ilvl} 只允许 {lo}~{hi}；请把 ilvl 提到 {need}。"),
            suggestions=_suggest_ilvl(int(need)), detail=text)

    m = re.search(r"(prefix|suffix) '([^']+)' is a level-(\d+) affix, below this item's "
                  r"affix window (\d+)\.\.(\d+).*e\.g\. ilvl <= (\d+)", text)
    if m:
        kind, name, lv, lo, hi, max_ilvl = m.groups()
        kind_cn = _KIND_CN.get(kind, kind)
        return ComboCheck(
            ok=False, code=FAIL_AFFIX_LEVEL_HIGH,
            title="ilvl 太高，该词缀落在窗口之外（游戏规则不允许）",
            message=(f"{kind_cn}「{name}」是 {lv} 级词缀，低于 ilvl 允许的窗口 {lo}~{hi}；"
                     f"请把 ilvl 降到 {max_ilvl} 或更低。"),
            suggestions=_suggest_lower_ilvl(int(max_ilvl)), detail=text)

    m = re.search(r"(prefix|suffix) '([^']+)' is not valid for ([^(]+)\(item type ([^)]+)\)",
                  text)
    if m:
        kind, name, base, itype = m.groups()
        kind_cn = _KIND_CN.get(kind, kind)
        return ComboCheck(
            ok=False, code=FAIL_AFFIX_TYPE,
            title="该词缀不能出现在这个底材上（游戏规则不允许）",
            message=(f"{kind_cn}「{name}」不适用于「{base.strip()}」"
                     f"（底材类型 {itype.strip()}）。"),
            suggestions=["换一个适用于该底材的词缀（下拉里只列适用的）",
                         "或者换一个底材（例如武器/护甲/戒指各有自己的词缀池）"],
            detail=text)

    if "不是可指定的数值效果" in text or "fixed effect" in low:
        return ComboCheck(
            ok=False, code=FAIL_FIXED_VALUE,
            title="这是固定效果词缀，不能指定数值",
            message=text,
            suggestions=["把「目标值」清空（留空 = 用词缀自带的效果）",
                         "或者换一个数值型词缀（力量/敏捷/抗性/伤害% 之类）"],
            detail="")

    if "no seed produced" in low or ("tries" in low and "no seed" in low):
        return ComboCheck(
            ok=False, code=FAIL_SEARCH,
            title="组合合法，但搜索预算内没找到（不是非法组合）",
            message=("这个「底材 + 词缀 + 数值」在游戏规则上是允许的，"
                     "但程序在限定次数的种子搜索里没碰巧命中。\n"
                     "通常是指定数值太苛刻，或两个词缀同时出现概率太低。"),
            suggestions=_suggest_search(), detail=text[:400])

    if "已尝试" in text and "种子" in text:
        return ComboCheck(
            ok=False, code=FAIL_SEARCH,
            title="合法，但没搜到符合该数值的种子",
            message=text,
            suggestions=_suggest_search(), detail="")

    if "可选范围" in text:
        return ComboCheck(ok=False, code=FAIL_VALUE_RANGE,
                          title="目标数值超出该词缀的范围",
                          message=text,
                          suggestions=["按「范围」提示填一个范围内的值",
                                       "或者把「容差」调大一点"], detail="")

    if "starter" in low or "初始装备" in text:
        return ComboCheck(
            ok=False, code=FAIL_BASE,
            title="底材非法（初始装备 starter）",
            message=(f"{friendly_error(exc)}\n"
                     "这类物品游戏只为开局角色生成，写进存档会导致进游戏崩溃。"),
            suggestions=["换一个普通底材（列表里已经过滤掉了 starter）",
                         "法杖类请选 Short Staff / Long Staff 这些普通底材"],
            detail="")

    if "unique-only" in low or "unique only" in low or "IMISC_UNIQUE" in text:
        return ComboCheck(
            ok=False, code=FAIL_BASE,
            title="底材非法（暗金专用底材）",
            message=friendly_error(exc),
            suggestions=["普通/魔法物品请选普通底材",
                         "想要这件暗金请用「暗金图鉴」页生成"],
            detail="")

    if "unknown or unavailable base" in low or "not available in the non-hellfire" in low:
        return ComboCheck(
            ok=False, code=FAIL_BASE,
            title="底材不可用",
            message=friendly_error(exc),
            suggestions=["换一个底材（该底材在 1.5.5 非 Hellfire 里不可用）"],
            detail="")

    if "ilvl must be" in low:
        return ComboCheck(ok=False, code=FAIL_ILVL, title="ilvl 越界",
                          message="ilvl 必须是 0~63（界面允许 1~50）。",
                          suggestions=["把 ilvl 改成 1~50 之间的值"], detail=text)

    if "never rolls random affixes" in low:
        return ComboCheck(
            ok=False, code=FAIL_NO_AFFIX,
            title="该底材不会滚词缀（游戏规则不允许）",
            message=friendly_error(exc),
            suggestions=["这个底材只能生成普通物品：把稀有度改成「普通」",
                         "或者换一个能带词缀的底材（武器/护甲/戒指/护符）"],
            detail="")

    if "could not generate a magical" in low:
        return ComboCheck(
            ok=False, code=FAIL_NO_BONUS,
            title="该 ilvl 下游戏可能不滚词缀",
            message=friendly_error(exc),
            suggestions=[f"把 ilvl 调高一点（当前 ilvl 太低时游戏会生成无词缀物品）",
                         "或者留「（随机合法）」词缀再试"],
            detail=text)

    if ("base_stats_conflict" in low or "base stats conflict" in low
            or ("护甲" in text and "满值" in text)):
        return ComboCheck(
            ok=False, code="base_stats_conflict",
            title="基础属性满值与所选词缀冲突（游戏规则不允许）",
            message=friendly_error(exc),
            suggestions=["取消「护甲取最大」，或者换一个不是直接设定 AC 的词缀",
                         "「耐久取满」与词缀无关，可以保留"],
            detail=text)

    if "staff_spell_suffix" in low or ("法术法杖" in text and "后缀" in text):
        return ComboCheck(
            ok=False, code="staff_spell_suffix",
            title="法术法杖没有后缀（游戏规则不允许）",
            message=friendly_error(exc),
            suggestions=["把后缀留「（随机合法）」或清空",
                         "想要后缀请改选「属性法杖」"],
            detail=text)

    if "bad_staff_charges" in low or ("充能" in text and "范围" in text):
        return ComboCheck(
            ok=False, code="bad_staff_charges",
            title="充能值超出该法术允许的范围",
            message=friendly_error(exc),
            suggestions=["把充能值改成该法术显示的 min~max 之间", "或者留空 = 随机充能"],
            detail=text)

    if "bad_staff_spell" in low or "staff spell" in low or "staff_spell" in low:
        return ComboCheck(
            ok=False, code="bad_staff_spell",
            title="法术/充能设置不合法（游戏规则不允许）",
            message=friendly_error(exc),
            suggestions=["只在法杖底材上指定法术/充能", "或改回「（随机法术）」"],
            detail=text)

    if "法杖在 ilvl" in text or "allow_staff_spells" in text:
        return ComboCheck(
            ok=False, code=FAIL_STAFF,
            title="法杖 ilvl 太高（1.5.5 已知怪癖）",
            message=text,
            suggestions=["把 ilvl 降到 51 或更低", "换一个非法杖底材"],
            detail="")

    if "normal items cannot carry affixes" in low:
        return ComboCheck(
            ok=False, code=FAIL_NORMAL_AFFIX,
            title="普通物品不能带词缀",
            message="当前稀有度是「普通」，不能指定前缀/后缀。",
            suggestions=["把稀有度改成「魔法」", "或者把前缀/后缀都留「（随机合法）」"],
            detail=text)

    if "no prefix" in low or "no suffix" in low:
        return ComboCheck(
            ok=False, code=FAIL_AFFIX_MISSING,
            title="该等级/底材下不存在这个词缀",
            message=friendly_error(exc),
            suggestions=["调高 ilvl 让更多词缀进入窗口", "换一个下拉里能选到的词缀"],
            detail=text)

    return ComboCheck(ok=False, code=FAIL_OTHER, title="生成失败",
                      message=friendly_error(exc), suggestions=[], detail=text)


def classify_validation(bad: list[str] | str) -> ComboCheck:
    """生成成功但 ``d1itemgen.validate`` 不通过时的中文说明（不弹 traceback）。"""
    if isinstance(bad, str):
        bad = [bad]
    bad = [str(x) for x in (bad or [])]
    low = " ".join(bad).lower()
    suggestions = [
        "换一个底材 / 词缀再生成（这件没有写入任何存档）",
        "如果是法杖：把 ilvl 降到 51 以下再试",
        "把生成的 seed 和底材记下来反馈（这是生成器的 bug，不是你的操作问题）",
    ]
    if "name" in low and ("replay" in low or "mismatch" in low):
        title = "名字重放不一致（生成器与游戏的重算结果不同）"
        message = ("这件物品的文字名在游戏里会显示成另一种组合，"
                   "为避免存档里出现名字/属性错位的物品，程序拒绝写入。")
    elif "replay" in low or "mismatch" in low:
        title = "seed 重放校验失败"
        message = ("把记录里的 seed 交回游戏重算，得到的属性与记录不一致；"
                   "写入后游戏会把它显示成别的属性。")
    elif "starter" in low:
        title = "记录里是初始装备（会导致游戏崩溃）"
        message = "这条记录被判定为 starter 物品，绝对不能写进存档。"
    elif "size" in low or "length" in low:
        title = "记录长度异常"
        message = "生成结果不是合法的 368 字节物品记录。"
    else:
        title = "合法性校验未通过"
        message = "\n".join(bad[:8])
    return ComboCheck(ok=False, code=FAIL_VALIDATE, title=title, message=message,
                      suggestions=suggestions, detail="\n".join(bad[:8]))


class ItemGen:
    """d1itemgen 包装器。"""

    def __init__(self) -> None:
        self.mod, self.error = lib_module("d1itemgen")
        self._base_cache: list[BaseItem] | None = None
        self._base_all_cache: list[BaseItem] | None = None
        self._unique_cache: list[UniqueItem] | None = None
        self._starter = _starter_indices()
        if self.mod is not None:
            for attr in ("_MODULES", "_PYC_MODULES"):
                d = getattr(self.mod, attr, None)
                if isinstance(d, dict) and MODULES.load():
                    for name, obj in MODULES.modules.items():
                        d.setdefault(name, obj)

    # ------------------------------------------------------------ 状态
    @property
    def ready(self) -> bool:
        return self.mod is not None

    @property
    def supports_values(self) -> bool:
        """itemgen 是否支持 prefix_value / suffix_value。"""
        if not self.ready:
            return False
        try:
            return "prefix_value" in inspect.signature(self.mod.generate).parameters
        except Exception:  # noqa: BLE001
            return False

    @property
    def supports_unique_detail(self) -> bool:
        return self.ready and callable(getattr(self.mod, "unique_detail", None))

    @property
    def max_drop_ilvl(self) -> int:
        """core ``MAX_DROP_ILVL``（默认 34）：丢地上合法的最高 ilvl。

        31~34 走暗金怪掉落路线（记录等级 -4 + ``CF_UPER15``），
        35 及以上只能放储物箱。
        """
        try:
            return int(getattr(self.mod, "MAX_DROP_ILVL", 34) or 34)
        except (TypeError, ValueError):
            return 34

    def record_droppable(self, create_info: int | None) -> bool:
        """记录级掉落校验（= 游戏 ``IsPItemValid``）；core 未就绪时退回 ilvl 判断。"""
        fn = getattr(self.mod, "record_droppable", None)
        if callable(fn) and create_info is not None:
            try:
                return bool(fn(int(create_info)))
            except Exception:  # noqa: BLE001
                pass
        if create_info is None:
            return False
        return (int(create_info) & 0x3F) <= self.max_drop_ilvl

    def supports_value_slots(self) -> bool:
        """core 是否支持一个词缀两条数值（King's = 伤害 + 命中）。"""
        return self.ready and callable(getattr(self.mod, "affix_value_slots", None))

    def affix_value_slots(self, affix, kind: str = "prefix") -> list[dict]:
        """词缀可填的数值槽位（``[{"key","label","range"}]``）；不支持时退回单槽。"""
        raw = affix.raw if isinstance(affix, Affix) else dict(affix or {})
        k = affix.kind if isinstance(affix, Affix) else str(kind or "prefix")
        fn = getattr(self.mod, "affix_value_slots", None)
        if callable(fn):
            try:
                slots = list(fn(raw, k))
                if slots:
                    return [{"key": str(s.get("key") or "value"),
                             "label": str(s.get("label") or "数值"),
                             "range": tuple(s.get("range") or (0, 0))}
                            for s in slots]
            except Exception:  # noqa: BLE001
                pass
        rng = self.affix_range(raw, k)
        if rng is None:
            return []
        try:
            label = d1zh.affix_effect_label(k, raw) or "数值"
        except Exception:  # noqa: BLE001
            label = "数值"
        return [{"key": "value", "label": label, "range": tuple(rng)}]

    def status_text(self) -> str:
        if not self.ready:
            return f"生成器未就绪（d1itemgen 缺失）：{self.error or ''} 暂可用「简易随机：写角色背包」"
        bits = ["生成器已就绪（d1itemgen）", "随机/自选词条", "暗金图鉴", "合法性校验"]
        bits.insert(1, "可指定数值" if self.supports_values else "数值随机（旧版 itemgen）")
        return "；".join(bits)

    # ------------------------------------------------------------ 基础物品
    def _tables(self):
        try:
            return MODULES_TABLES()
        except Exception:  # noqa: BLE001
            return None

    def _uniques_for_base(self, idx: int) -> list:
        if not self.ready:
            return []
        T = getattr(self.mod, "T", None)
        fn = getattr(T, "uniques_for_base", None)
        if fn is None:
            return []
        try:
            return list(fn(idx) or [])
        except Exception:  # noqa: BLE001
            return []

    def uniques_for_base(self, idx: int) -> list[dict]:
        return self._uniques_for_base(idx)

    def _unique_uid(self, unique):
        if unique is None:
            return None
        if isinstance(unique, int):
            return int(unique)
        if isinstance(unique, dict):
            for k in ("index", "uid", "id"):
                if unique.get(k) is not None:
                    return int(unique[k])
            unique = unique.get("name")
        if isinstance(unique, str):
            text = unique.strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            T = getattr(self.mod, "T", None)
            for obj in (T, self.mod):
                fn = getattr(obj, "unique_by_name", None) if obj is not None else None
                if callable(fn):
                    try:
                        rec = fn(text)
                    except Exception:  # noqa: BLE001
                        rec = None
                    if rec:
                        return int(rec.get("index", rec.get("uid")))
            try:
                return int(text)
            except ValueError:
                raise ValueError(f"找不到名为 {text!r} 的暗金物品")
        return None

    def _is_starter(self, d: dict, idx: int, name: str) -> bool:
        # 注意：只有**编号**才可靠 —— "Short Sword"/"Buckler"/"Club"/"Short Bow"
        # 这些名字同时被起始装备（IDROP_NEVER）和正常掉落版共用，按名字判断会
        # 把可用的掉落版一起误杀。
        if idx in self._starter:
            return True
        for key in ("starter", "is_starter", "starting"):
            if d.get(key):
                return True
        return False

    def base_items(self, include_blocked: bool = False) -> list[BaseItem]:
        """可装备**普通**底材列表（默认不含 starter / unique_only / 非掉落）。

        include_blocked=True 时返回全部可装备底材（用于体检/调试，界面不会用）。
        """
        if self._base_cache is not None and not include_blocked:
            return self._base_cache
        if self._base_all_cache is not None and include_blocked:
            return self._base_all_cache
        items: list[BaseItem] = []
        if self.ready:
            raw = self._raw_bases(include_blocked)
            best: dict[str, tuple[tuple, BaseItem]] = {}
            for d in raw:
                if not isinstance(d, dict):
                    continue
                itype_name = str(_pick(d, "itype_name", default="") or "")
                kind = EQUIP_KINDS.get(itype_name, "")
                if not kind:
                    continue                      # 跳过 Gold / Misc / 药水 / 卷轴
                if d.get("available") is False:
                    continue
                if d.get("usable"):
                    continue
                idx = self._runtime_idx(d)
                if idx is None:
                    continue
                name = str(_pick(d, "name", "iName", "english", default="") or "")
                cn = str(_pick(d, "cn", "name_cn", default="") or "") or item_cn(idx)
                cn = d1zh.item_name_cn(name, cn) if name else cn
                if not name:
                    name = item_en(idx)
                cat = str(_pick(d, "category", "type", default="") or "") or item_category(idx)
                size = _pick(d, "size", default=None)
                if not (isinstance(size, (tuple, list)) and len(size) == 2):
                    size = (int(_pick(d, "width", default=item_size(idx)[0])),
                            int(_pick(d, "height", default=item_size(idx)[1])))
                saved_idx = int(_pick(d, "saved_idx", default=0) or 0)
                drop = str(_pick(d, "drop_rate_name", default="") or "")
                t = self._tables()
                unique_misc = int(getattr(t, "IMISC_UNIQUE", 27) if t is not None else 27)
                misc_id = d.get("misc_id")
                unique_only = bool(d.get("unique_only")) or (
                    misc_id is not None and int(misc_id) == unique_misc)
                starter = self._is_starter(d, int(idx), name)
                droppable = d.get("droppable")
                if droppable is None:
                    droppable = drop != "IDROP_NEVER"
                b = BaseItem(idx=int(idx), name=name, cn=cn or name, category=cat,
                             kind=kind, size=(int(size[0]), int(size[1])),
                             saved_idx=saved_idx,
                             has_unique=bool(self._uniques_for_base(int(idx))),
                             starter=starter, unique_only=unique_only,
                             droppable=bool(droppable), raw=d)
                if not b.generatable and not include_blocked:
                    continue
                key = name.lower()
                # 同名去重：优先掉落版，再看 saved_idx 小者
                score = (b.droppable and not b.unique_only and not b.starter, -saved_idx)
                cur = best.get(key)
                if cur is None or score > cur[0]:
                    best[key] = (score, b)
            items = [b for _, b in best.values()]
        if not items and not include_blocked:
            items = [b for b in self._fallback_base_items() if b.generatable]
        items.sort(key=lambda b: (KIND_ORDER.index(b.kind) if b.kind in KIND_ORDER else 9,
                                  b.saved_idx or b.idx))
        if include_blocked:
            self._base_all_cache = items
        else:
            self._base_cache = items
        return items

    def _raw_bases(self, include_blocked: bool) -> list[dict]:
        """取原始底材表：**尽量拿全集**，过滤由本适配层自己做（防御性）。"""
        T = self._tables()
        if T is not None and hasattr(T, "base_items"):
            for kwargs in (
                dict(include_unavailable=True, include_starter=True,
                     include_unique_only=True),
                dict(include_unavailable=True),
                dict(),
            ):
                try:
                    return list(T.base_items(**kwargs) or [])
                except TypeError:
                    continue
                except Exception:  # noqa: BLE001
                    break
        try:
            return list(self.mod.base_items() or [])
        except Exception:  # noqa: BLE001
            return []

    def _runtime_idx(self, d: dict):
        idx = _pick(d, "runtime_idx", "idx", "idx_runtime", "item_idx")
        if idx is None:
            return None
        try:
            idx = int(idx)
        except Exception:  # noqa: BLE001
            return None
        name = str(_pick(d, "name", "iName", default="") or "")
        try:
            rt_names = MODULES.d1items.ITEM_NAMES
        except Exception:  # noqa: BLE001
            return idx
        if rt_names.get(idx) and (not name or rt_names.get(idx) == name):
            return idx
        try:
            alt = int(MODULES.d1save.saved_to_runtime(idx))
            if rt_names.get(alt) and (not name or rt_names.get(alt) == name):
                return alt
        except Exception:  # noqa: BLE001
            pass
        return idx

    def _fallback_base_items(self) -> list[BaseItem]:
        """d1itemgen 缺失时，从 d1items 表构造基础物品列表（仅常规装备）。"""
        out: list[BaseItem] = []
        ids = [119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129]
        ids += list(range(118, 161))
        for idx in ids:
            en = item_en(idx)
            if not en:
                continue
            cat = item_category(idx)
            kind = "武器" if cat in ("剑", "斧", "锤/棍", "弓", "法杖") else (
                "防具" if cat in ("盾牌", "头盔", "护甲") else (
                    "戒指护符" if cat == "戒指/项链" else ""))
            if not kind:
                continue
            b = BaseItem(idx=idx, name=en, cn=d1zh.item_name_cn(en, item_cn(idx)),
                         category=cat, kind=kind, size=item_size(idx), has_unique=True,
                         starter=idx in self._starter, raw={})
            if b.generatable:
                out.append(b)
        return out

    def base_item_by_idx(self, idx: int) -> BaseItem | None:
        for b in self.base_items(include_blocked=True):
            if b.idx == idx:
                return b
        return None

    def _base_record(self, base_idx) -> dict | None:
        """运行时编号 -> 底材表行（不要求 available；找不到返回 None）。"""
        idx = int(base_idx)
        T = self._tables()
        if T is not None:
            try:
                rec = T.resolve_base(idx, require_available=False)
            except Exception:  # noqa: BLE001
                rec = None
            if isinstance(rec, dict) and rec:
                return dict(rec)
        b = self.base_item_by_idx(idx)
        if b is not None and isinstance(b.raw, dict) and b.raw:
            return dict(b.raw)
        return None

    @staticmethod
    def _natural_durability(max_dur: int) -> tuple[int, int]:
        """游戏 ``ItemRndDur()`` 的自然耐久范围（C++ 整型除法，上限 maxDur）。

        C++ 源码是 ``durability = GenerateRnd(maxDur / 2) + maxDur / 4 + 1``，
        其中 ``/`` 是**截断整除**（不是 ceil）。``GenerateRnd(n)`` 取
        ``0..n-1``（``n <= 0`` 时为 0），所以::

            lo = maxDur // 4 + 1
            hi = maxDur // 2 + maxDur // 4      （再用 maxDur 封顶）

        例如 maxDur=55 -> 14~40；maxDur=35 -> 9~25。
        """
        max_dur = int(max_dur or 0)
        if max_dur <= 0:
            return 0, 0
        quarter = max_dur // 4
        half = max_dur // 2
        lo = max(1, min(quarter + 1, max_dur))
        hi = min(half + quarter, max_dur) if half > 0 else lo
        return lo, max(lo, hi)

    def base_preview(self, base_idx: int) -> dict:
        """纯本地的底材属性预览（Round 4），**不生成物品、不搜 seed**。

        返回字段（合同 3.2）::

            base_cn/base_en/kind/itype_name/istype/affix_type/size
            min_dam/max_dam/min_ac/max_ac
            dur_min/dur_max   # 游戏自然滚动范围
            max_dur/durability_raw
            req_str/req_dex/req_mag/value
            can_max_ac / can_full_dur
        """
        if isinstance(base_idx, BaseItem):
            base_idx = base_idx.idx
        idx = int(base_idx)
        rec = self._base_record(idx) or {}
        b = self.base_item_by_idx(idx)
        name = str(_pick(rec, "name", "iName", default="") or "") or (b.name if b else "")
        cn = d1zh.item_name_cn(name, item_cn(idx))
        itype_name = str(_pick(rec, "itype_name", "type", default="") or "")
        if not itype_name and b is not None and isinstance(b.raw, dict):
            itype_name = str(b.raw.get("itype_name") or "")
        kind = EQUIP_KINDS.get(itype_name, "") or (b.kind if b else "")
        default_w, default_h = (b.size if b is not None else (1, 1))
        width = int(_pick(rec, "width", default=default_w) or 1)
        height = int(_pick(rec, "height", default=default_h) or 1)
        size = _pick(rec, "size", default=None)
        if not (isinstance(size, (tuple, list)) and len(size) == 2):
            size = (width, height)
        max_dur = int(_pick(rec, "durability", default=0) or 0)
        dur_min, dur_max = self._natural_durability(max_dur)
        max_ac = int(_pick(rec, "max_ac", default=0) or 0)
        t = self._tables()
        try:
            dur_ind = int(getattr(t, "DUR_INDESTRUCTIBLE", 255) or 255)
        except Exception:  # noqa: BLE001
            dur_ind = 255
        can_full_dur = max_dur > 0 and max_dur not in (dur_ind, 299)
        return {
            "base_idx": idx,
            "label": (b.label if b is not None else (f"{cn}（{name}）" if name and name != cn else cn or name)),
            "base_cn": cn,
            "base_en": name,
            "kind": kind,
            "itype_name": itype_name,
            "istype": int(_pick(rec, "itype", default=0) or 0),
            "affix_type": int(_pick(rec, "affix_type", default=0) or 0),
            "size": (int(size[0]), int(size[1])),
            "min_dam": int(_pick(rec, "min_dam", default=0) or 0),
            "max_dam": int(_pick(rec, "max_dam", default=0) or 0),
            "min_ac": int(_pick(rec, "min_ac", default=0) or 0),
            "max_ac": max_ac,
            "dur_min": int(dur_min),
            "dur_max": int(dur_max),
            "max_dur": max_dur,
            "durability_raw": max_dur,
            "req_str": int(_pick(rec, "min_str", "MinStr", default=0) or 0),
            "req_mag": int(_pick(rec, "min_mag", "MinMag", default=0) or 0),
            "req_dex": int(_pick(rec, "min_dex", "MinDex", default=0) or 0),
            "value": int(_pick(rec, "value", default=0) or 0),
            "can_max_ac": max_ac > 0,
            "can_full_dur": bool(can_full_dur),
        }

    def check_base(self, base) -> str:
        """生成前拦截：返回中文原因，空字符串表示通过。"""
        if base is None:
            return "请先在左侧列表里选择一个基础物品。"
        idx = base if isinstance(base, int) else base.idx
        if idx in self._starter:
            return (f"运行时编号 {idx} 是初始装备（starter，如 Short Sword / "
                    "Short Staff of Charged Bolt），游戏不会随机生成，写进存档会导致进游戏崩溃。")
        b = base if isinstance(base, BaseItem) else self.base_item_by_idx(idx)
        if b is not None:
            reason = b.blocked_reason
            if reason:
                return f"「{b.label}」：{reason}。"
        return ""

    # ------------------------------------------------------------ 词缀
    def eligible_affixes(self, base_idx: int, ilvl: int, kind: str = "prefix") -> list[Affix]:
        if not self.ready:
            return []
        fn = getattr(self.mod, "eligible_affixes", None)
        if fn is None:
            return []
        try:
            raw = fn(base_idx, ilvl, kind) or []
        except TypeError:
            try:
                raw = fn(base_idx, ilvl, kind=kind) or []
            except Exception:  # noqa: BLE001
                return []
        except Exception:  # noqa: BLE001
            return []
        out: list[Affix] = []
        seen = set()
        for a in raw:
            if not isinstance(a, dict):
                a = {"name": str(a)}
            aff = Affix(raw=a, kind=kind, gen=self)
            key = (aff.en.lower(), aff.vmin, aff.vmax)
            if key in seen:
                continue
            seen.add(key)
            out.append(aff)
        return out

    def all_affixes(self, base_idx: int, kind: str = "prefix") -> list[Affix]:
        """该底材类型**全部适用词缀**，不看 ilvl（Round 4，合同 3.2）。

        有 core ``d1itemgen.all_affixes`` 时直接用它；否则从
        ``T.PREFIXES`` / ``T.SUFFIXES`` 过滤
        ``is_prefix_valid_for_item_type`` / ``is_suffix_valid_for_item_type``
        （排除 unique_only 底材）。每项都是带 ``band`` 的 :class:`Affix`，
        ``label`` 末尾带 ``〔ilvl L~H〕``。
        """
        kind = "suffix" if str(kind or "").lower().startswith("suf") else "prefix"
        if not self.ready:
            return []
        if isinstance(base_idx, BaseItem):
            base_idx = base_idx.idx
        base = self._base_record(base_idx)
        if isinstance(base, dict) and base.get("unique_only"):
            return []
        raw = None
        fn = getattr(self.mod, "all_affixes", None)
        if callable(fn):
            try:
                raw = list(fn(int(base_idx), kind) or [])
            except TypeError:
                try:
                    raw = list(fn(int(base_idx), kind=kind) or [])
                except Exception:  # noqa: BLE001
                    raw = None
            except Exception:  # noqa: BLE001 - core 未就绪：用本地表
                raw = None
        if raw is None:
            raw = self._local_all_affixes(base_idx, kind, base)
        out: list[Affix] = []
        seen = set()
        for a in raw:
            if not isinstance(a, dict):
                a = {"name": str(a)}
            aff = Affix(raw=dict(a), kind=kind, gen=self)
            key = aff.index if aff.index >= 0 else (
                aff.en.lower(), aff.min_level, aff.vmin, aff.vmax)
            if key in seen:
                continue
            seen.add(key)
            out.append(aff)
        return out

    def _local_all_affixes(self, base_idx, kind: str, base: dict | None = None) -> list[dict]:
        """core 没有 ``all_affixes`` 时的本地实现（只按底材类型过滤）。"""
        T = self._tables()
        if T is None:
            return []
        if base is None:
            base = self._base_record(base_idx)
        if not isinstance(base, dict) or base.get("unique_only"):
            return []
        flgs = int(base.get("affix_type") or 0)
        table = getattr(T, "PREFIXES" if kind == "prefix" else "SUFFIXES", []) or []
        valid_fn = None
        if self.ready:
            valid_fn = getattr(
                self.mod,
                "is_prefix_valid_for_item_type" if kind == "prefix"
                else "is_suffix_valid_for_item_type",
                None)
        out: list[dict] = []
        for row in table:
            if not isinstance(row, dict):
                continue
            try:
                index = int(row.get("index", -1))
            except Exception:  # noqa: BLE001
                continue
            if index < 0:
                continue
            ok = None
            if callable(valid_fn):
                try:
                    ok = bool(valid_fn(index, flgs, False))
                except Exception:  # noqa: BLE001
                    ok = None
            if ok is None:
                # 校验函数不可用：退回类型位掩码 + 非 Hellfire 过滤
                if row.get("hellfire_only"):
                    continue
                ok = bool(flgs & int(row.get("item_types") or 0))
            if ok:
                out.append(dict(row))
        return out

    @staticmethod
    def affix_label(a) -> str:
        if isinstance(a, Affix):
            return a.label
        if isinstance(a, dict):
            return Affix(raw=a, kind=str(a.get("kind") or "prefix")).label
        return str(a)

    # -- 词缀数值能力（itemgen2 的 is_value_affix / affix_value_range）--
    def affix_is_numeric(self, affix: dict, kind: str = "prefix") -> bool:
        fn = getattr(self.mod, "is_value_affix", None) if self.ready else None
        if callable(fn):
            try:
                return bool(fn(affix, kind))
            except Exception:  # noqa: BLE001
                pass
        return bool(d1zh.power_value(affix).get("numeric"))

    def affix_range(self, affix: dict, kind: str = "prefix"):
        fn = getattr(self.mod, "affix_value_range", None) if self.ready else None
        if callable(fn):
            try:
                rng = fn(affix, kind)
            except TypeError:
                try:
                    rng = fn(affix)
                except Exception:  # noqa: BLE001
                    rng = None
            except Exception:  # noqa: BLE001
                rng = None
            if rng is not None:
                try:
                    lo, hi = int(rng[0]), int(rng[1])
                    return (lo, hi) if lo <= hi else (hi, lo)
                except Exception:  # noqa: BLE001
                    return None
        info = d1zh.power_value(affix)
        if info.get("vmin") is None or info.get("vmax") is None:
            return None
        return int(info["vmin"]), int(info["vmax"])

    # ------------------------------------------------------------ 暗金
    def uniques(self, include_unavailable: bool = False) -> list[UniqueItem]:
        """暗金列表。

        默认 89 件（1.5.5 非 Hellfire 可用）；``include_unavailable=True`` 时
        连 Bovine Plate 这种底材不可用的也返回（界面用来解释为什么少一件）。
        """
        all_items = self._unique_all()
        if include_unavailable:
            return all_items
        return [u for u in all_items if u.base_available]

    def _unique_all(self) -> list[UniqueItem]:
        if self._unique_cache is not None:
            return self._unique_cache
        out: list[UniqueItem] = []
        T = self._tables()
        if T is None:
            return out
        try:
            rows = T.unique_list()
        except Exception:  # noqa: BLE001
            return out
        for u in rows:
            uid = int(u.get("index", -1))
            en = str(u.get("name") or "")
            ub = None
            if self.ready:
                try:
                    ub = self.mod.unique_base(u)
                except Exception:  # noqa: BLE001
                    ub = None
            if ub is None:
                ub = {}
            base_idx = int(ub.get("idx", -1) or -1)
            base_en = str(ub.get("name") or "")
            base_cn = d1zh.item_name_cn(base_en, item_cn(base_idx) if base_idx >= 0 else "")
            item = UniqueItem(
                uid=uid, en=en, cn=d1zh.unique_name(en), base_idx=base_idx,
                base_en=base_en, base_cn=base_cn,
                base_unique_only=bool(ub.get("unique_only")),
                base_available=bool(ub.get("available", False)),
                min_level=int(u.get("min_level", 0) or 0),
                value=int(u.get("value", 0) or 0),
                powers=list(u.get("powers") or []),
                raw=u,
            )
            out.append(item)
        self._unique_cache = out
        return out

    def unique_by_uid(self, uid: int) -> UniqueItem | None:
        for u in self.uniques(include_unavailable=True):
            if u.uid == int(uid):
                return u
        return None

    def unique_detail(self, uid) -> dict:
        """暗金明细：优先用 itemgen2 的 unique_detail(uid)，再补中文说明。"""
        item = self.unique_by_uid(int(uid))
        data: dict = {}
        if self.supports_unique_detail:
            try:
                data = dict(self.mod.unique_detail(int(uid)) or {})
            except Exception:  # noqa: BLE001
                data = {}
        if item is None:
            return data
        data.setdefault("uid", item.uid)
        data.setdefault("name", item.en)
        data.setdefault("name_cn", item.cn)
        data.setdefault("base_idx", item.base_idx)
        data.setdefault("base_name", item.base_en)
        data.setdefault("base_name_cn", item.base_cn)
        data.setdefault("min_level", item.min_level)
        data.setdefault("value", item.value)
        data.setdefault("powers", item.powers)
        data["item"] = item
        data["rows"] = item.to_rows()
        data["note"] = item.note
        return data

    def unique_base(self, uid) -> dict:
        if not self.ready:
            return {}
        try:
            return dict(self.mod.unique_base(int(uid)) or {})
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------ 法杖法术（Round 4）
    @staticmethod
    def _normalize_spell(row: dict) -> dict:
        """统一法术行：``id/name/cn/staff_min/staff_max/min_int``（保留 core 附加字段）。"""
        out = dict(row)
        sid = _pick(row, "id", "index", "spell")
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            sid = -1
        name = str(_pick(row, "name", default="") or "")
        cn = str(_pick(row, "cn", "name_cn", default="") or "")
        if not cn and sid >= 0:
            try:
                cn = d1zh.spell_name(sid)
            except Exception:  # noqa: BLE001
                cn = ""
        out.update({
            "id": sid,
            "name": name,
            "cn": cn or name,
            "staff_min": int(_pick(row, "staff_min", default=0) or 0),
            "staff_max": int(_pick(row, "staff_max", default=0) or 0),
            "min_int": int(_pick(row, "min_int", default=0) or 0),
        })
        return out

    def spells(self) -> list[dict]:
        """可做法杖的法术列表（Round 4）。

        有 core ``d1itemgen.staff_spells()`` 时用它；否则从 ``T.SPELLS``
        构造（只保留非 Hellfire、staff_lvl 有效、staff_min>0 的法术，
        与 ``GetStaffSpell()`` 的 37 次抽样范围一致）。
        """
        if self.ready:
            fn = getattr(self.mod, "staff_spells", None)
            if callable(fn):
                try:
                    raw = list(fn() or [])
                except Exception:  # noqa: BLE001
                    raw = []
                out = [self._normalize_spell(row) for row in raw if isinstance(row, dict)]
                out = [r for r in out if r["id"] >= 0 and r["staff_max"] >= r["staff_min"] > 0]
                if out:
                    return out
        return self._local_spells()

    def _local_spells(self) -> list[dict]:
        T = self._tables()
        rows = list(getattr(T, "SPELLS", []) or []) if T is not None else []
        spec = getattr(T, "SPELL_ID", {}) or {}
        try:
            last = int(spec.get("LastDiablo", 36) or 36)
        except Exception:  # noqa: BLE001
            last = 36
        last = min(last, 36)  # GetStaffSpell 只在 1..36 里抽（max_spells=37）
        skip = {"null", "resurrect", "healother"}
        out: list[dict] = []
        for sid, row in enumerate(rows):
            if sid <= 0 or sid > last or not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if not name or name.strip().lower().replace(" ", "") in skip:
                continue
            try:
                staff_lvl = int(row.get("staff_lvl"))
            except (TypeError, ValueError):
                staff_lvl = -1
            if staff_lvl < 0:
                continue
            item = self._normalize_spell(dict(row, id=sid))
            if item["staff_min"] <= 0 or item["staff_max"] < item["staff_min"]:
                continue
            out.append(item)
        return out

    def resolve_spell(self, value) -> dict | None:
        """把 int / 英文名 / 中文名 / dict 解析成法术行（失败返回 None）。"""
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("id", "index", "spell"):
                if value.get(key) is not None:
                    value = value[key]
                    break
            else:
                return None
        if isinstance(value, int):
            return self._spell_by_id(int(value))
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return self._spell_by_id(int(text))
        T = self._tables()
        if T is not None:
            fn = getattr(T, "spell_by_name", None)
            if callable(fn):
                try:
                    rec = fn(text)
                except Exception:  # noqa: BLE001
                    rec = None
                if isinstance(rec, dict) and rec:
                    return self._normalize_spell(rec)
        low = text.lower()
        for row in self.spells():
            if low in (str(row.get("name") or "").lower(),
                       str(row.get("cn") or "").lower()):
                return dict(row)
        return None

    def _spell_by_id(self, sid: int) -> dict | None:
        T = self._tables()
        if T is not None:
            fn = getattr(T, "spell_by_id", None)
            if callable(fn):
                try:
                    rec = fn(int(sid))
                except Exception:  # noqa: BLE001
                    rec = None
                if isinstance(rec, dict) and rec:
                    return self._normalize_spell(dict(rec, id=int(sid)))
        for row in self.spells():
            if int(row["id"]) == int(sid):
                return dict(row)
        return None

    def _spell_id(self, value) -> int | None:
        """法术引用 -> 法术 id（无法解析返回 None，交给 core 报错）。"""
        rec = self.resolve_spell(value)
        if rec is None:
            return None
        try:
            return int(rec.get("id"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_none(value) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------ 生成
    def generate(self, base_idx, ilvl: int, rarity: str = "magic", seed=None,
                 prefix=None, suffix=None, unique=None,
                 prefix_value: int | str | list | None = None,
                 suffix_value: int | str | list | None = None,
                 value_tolerance: int = 0, max_tries: int | None = None,
                 progress=None, cancel=None, timeout: float | None = None,
                 max_ac: bool = False, full_durability: bool = False,
                 staff_spell=None, staff_charges: int | None = None,
                 allow_staff_spells: bool | None = None,
                 require_staff_spell: bool = False,
                 droppable: bool = False) -> GenResult:
        if not self.ready:
            raise RuntimeError("d1itemgen 未就绪，无法生成完整 368 字节记录")
        if isinstance(base_idx, BaseItem):
            base_idx = base_idx.idx
        fn = self.mod.generate
        params = inspect.signature(fn).parameters
        kwargs = {}
        if "ilvl" in params:
            kwargs["ilvl"] = int(ilvl)
        if "rarity" in params:
            kwargs["rarity"] = rarity
        if "seed" in params:
            kwargs["seed"] = None if seed in (None, "", "随机") else int(seed)
        if "prefix" in params:
            kwargs["prefix"] = prefix
        if "suffix" in params:
            kwargs["suffix"] = suffix
        uid = self._unique_uid(unique)
        if "unique_id" in params and uid is not None:
            kwargs["unique_id"] = uid
        elif "unique" in params and uid is not None:
            kwargs["unique"] = uid
        if prefix_value is not None and "prefix_value" in params:
            kwargs["prefix_value"] = _value_arg(prefix_value)
        if suffix_value is not None and "suffix_value" in params:
            kwargs["suffix_value"] = _value_arg(suffix_value)
        if value_tolerance and "value_tolerance" in params:
            kwargs["value_tolerance"] = int(value_tolerance)
        # 搜索预算：
        #   * 不用数值时 20 万次足够（通常 <0.2s）；
        #   * 指定数值时按 1/(范围积) 的概率，需要 200 万次才稳定（~1.2s）。
        has_value = _has_value(prefix_value) or _has_value(suffix_value)
        if max_tries is None:
            max_tries = 2000000 if has_value else 200000
        for extra in ("max_tries", "max_attempts", "tries"):
            if extra in params:
                kwargs[extra] = int(max_tries)
        if "progress" in params:
            kwargs["progress"] = progress
        if "cancel" in params:
            kwargs["cancel"] = cancel
        if "timeout" in params and timeout:
            kwargs["timeout"] = float(timeout)

        # ---- Round 4：基础属性满值 / 法术法杖（只在 core 支持时透传）----
        supports_max_ac = "max_ac" in params
        supports_full_dur = "full_durability" in params
        supports_staff_spell = "staff_spell" in params
        supports_require_staff = "require_staff_spell" in params
        if supports_max_ac:
            kwargs["max_ac"] = bool(max_ac)
        if supports_full_dur:
            kwargs["full_durability"] = bool(full_durability)
        allow_staff = allow_staff_spells
        if allow_staff is None:
            allow_staff = (staff_spell is not None or staff_charges is not None
                           or bool(require_staff_spell))
        if "allow_staff_spells" in params:
            kwargs["allow_staff_spells"] = bool(allow_staff)
        spell_id = self._spell_id(staff_spell)
        charge_target = self._int_or_none(staff_charges)
        if supports_staff_spell:
            kwargs["staff_spell"] = spell_id if spell_id is not None else staff_spell
        if "staff_charges" in params and charge_target is not None:
            kwargs["staff_charges"] = charge_target
        if supports_require_staff:
            kwargs["require_staff_spell"] = bool(require_staff_spell)

        # ---- Round 5：保证可丢地上（core 支持时透传；旧 core 不传）----
        supports_droppable = "droppable" in params
        if supports_droppable:
            kwargs["droppable"] = bool(droppable)

        t0 = time.time()
        item = fn(base_idx, **kwargs)
        elapsed = time.time() - t0

        res = GenResult(elapsed=elapsed)
        res.ilvl = int(ilvl)
        res.record = getattr(item, "record", None)
        res.fields = dict(getattr(item, "fields", {}) or {})
        res.name = str(_pick(res.fields, "iName", "name", default="")
                       or getattr(item, "name", "") or "")
        res.seed = _pick(res.fields, "iSeed", "seed", default=getattr(item, "seed", None))
        res.create_info = _pick(res.fields, "iCreateInfo", "create_info",
                                default=getattr(item, "create_info", None))
        base = getattr(item, "base", {}) or {}
        res.runtime_idx = base.get("idx")
        if res.runtime_idx is None:
            res.runtime_idx = _pick(res.fields, "runtime_idx", default=base_idx)
        # ---- Round 5/6：记录级掉落校验（= 游戏 IsPItemValid）----
        try:
            level = (int(res.create_info) & 0x3F
                     if res.create_info is not None else None)
        except (TypeError, ValueError):
            level = None
        res.record_ilvl = level
        res.droppable = bool(res.create_info is not None
                             and self.record_droppable(res.create_info))
        if res.create_info is not None:
            res.drop_mode = ("unique_monster"
                             if (int(res.create_info) & 0xC0) == 0xC0 else "dungeon")
        if droppable and not supports_droppable:
            res.droppable = False
            res.drop_note = ("当前生成器未支持「保证可丢地上」（core 无 droppable 参数），"
                             "本次未做掉落校验")
        elif droppable:
            if res.drop_mode == "unique_monster":
                res.drop_note = (f"可丢地上：是（暗金怪掉落路线：记录等级 {level} + "
                                 f"CF_UPER15，词缀等级 {ilvl}）")
            elif res.droppable:
                res.drop_note = f"可丢地上：是（ilvl {level} ≤ {self.max_drop_ilvl}）"
            else:
                res.drop_note = (f"可丢地上：否（ilvl {level} 的记录仍不合法，"
                                 "只能放储物箱）")
        elif level is not None and not res.droppable:
            res.drop_note = (f"ilvl {level} 的记录不是合法掉落物：只能放储物箱；"
                             "丢地上会提示「无效的数据包」并消失")
        # ---- Round 4：法术/充能 + 基础属性满值（core 把实际应用情况写在 _extra）----
        try:
            spell_raw = res.fields.get("spell")
            res.staff_spell = int(spell_raw) if spell_raw not in (None, "") else None
        except (TypeError, ValueError):
            res.staff_spell = None
        if res.staff_spell is not None and res.staff_spell <= 0:
            res.staff_spell = None  # 0 = SpellID::Null
        for attr, key in (("charges", "charges"), ("max_charges", "maxCharges")):
            try:
                value = res.fields.get(key)
                setattr(res, attr, int(value) if value is not None else None)
            except (TypeError, ValueError):
                setattr(res, attr, None)
        extra = getattr(item, "_extra", None) or {}
        res.applied_max_ac = bool(extra.get("applied_max_ac", False))
        res.applied_full_durability = bool(extra.get("applied_full_durability", False))
        res.base_stats_note = str(extra.get("base_stats_note") or "")
        base_max_ac = int(base.get("max_ac") or 0)
        base_max_dur = int(base.get("durability") or 0)
        if "applied_max_ac" not in extra and supports_max_ac and max_ac and base_max_ac > 0:
            try:
                res.applied_max_ac = int(res.fields.get("AC") or 0) == base_max_ac
            except (TypeError, ValueError):
                res.applied_max_ac = False
        if ("applied_full_durability" not in extra and supports_full_dur
                and full_durability and base_max_dur > 0):
            try:
                res.applied_full_durability = int(res.fields.get("durability") or 0) == base_max_dur
            except (TypeError, ValueError):
                res.applied_full_durability = False
        notes: list[str] = []
        if max_ac and not res.applied_max_ac:
            notes.append("「护甲满值」未生效（当前生成器未支持，已按随机处理）"
                         if not supports_max_ac else "「护甲满值」未生效")
        if full_durability and not res.applied_full_durability:
            notes.append("「耐久满值」未生效（当前生成器未支持，已按随机处理）"
                         if not supports_full_dur else "「耐久满值」未生效")
        if (staff_spell is not None or staff_charges is not None) and not supports_staff_spell:
            notes.append("当前生成器未支持指定法术/充能（已按随机处理）")
        if notes and not res.base_stats_note:
            res.base_stats_note = "；".join(notes)
        pre = getattr(item, "prefix", None)
        suf = getattr(item, "suffix", None)
        uniq = getattr(item, "unique", None)
        if isinstance(pre, dict):
            res.prefix = d1zh.affix_name("prefix", pre)
            res.prefix_values = self.affix_actual_values(pre, res.fields)
            res.prefix_value = res.prefix_values[0] if res.prefix_values else None
        if isinstance(suf, dict):
            res.suffix = d1zh.affix_name("suffix", suf)
            res.suffix_values = self.affix_actual_values(suf, res.fields)
            res.suffix_value = res.suffix_values[0] if res.suffix_values else None
        if isinstance(uniq, dict):
            res.unique = d1zh.unique_name(str(uniq.get("name") or ""))
        res.name_cn = self._chinese_name(res, base, pre, suf, uniq)
        if res.record:
            res.validation = list(self.validate(res.record, allow_ac_override=bool(max_ac)))
        res.text = self._chinese_describe(res, base, pre, suf, uniq)
        describe = getattr(item, "describe", None)
        if callable(describe):
            try:
                raw = str(describe())
            except Exception:  # noqa: BLE001
                raw = ""
            if raw:
                res.text += "\n\n—— 技术详情（d1itemgen 原文）——\n" + raw
        if not res.text:
            res.text = self._auto_describe(res)
        # ---- Round 4：强制法术法杖（core4 新参数）未满足时明确提示 ----
        if require_staff_spell:
            if not supports_require_staff:
                res.text += ("\n（注意：当前生成器未支持「强制法术法杖」，"
                             "结果可能不带法术）")
            elif res.staff_spell is None:
                res.text += ("\n（注意：生成结果没有法术/充能，"
                             "不符合「强制法术法杖」）")
        return res

    #: 词缀能力 -> (记录字段, 符号)：用来把「实际数值」从记录里取回来
    POWER_FIELD = {
        "IPL_TOHIT": ("PLToHit", 1), "IPL_TOHIT_CURSE": ("PLToHit", -1),
        "IPL_DAMP": ("PLDam", 1), "IPL_DAMP_CURSE": ("PLDam", -1),
        # King's / Knight's / ... : 第一个数值是伤害%，第二个是命中
        "IPL_TOHIT_DAMP": ("PLDam", 1),
        "IPL_TOHIT_DAMP_CURSE": ("PLDam", -1),
        "IPL_DOPPELGANGER": ("PLDam", 1),
        "IPL_ACP": ("PLAC", 1), "IPL_ACP_CURSE": ("PLAC", -1),
        "IPL_SETAC": ("AC", 1), "IPL_AC_CURSE": ("AC", -1),
        "IPL_FIRERES": ("PLFR", 1), "IPL_FIRERES_CURSE": ("PLFR", -1),
        "IPL_LIGHTRES": ("PLLR", 1), "IPL_LIGHTRES_CURSE": ("PLLR", -1),
        "IPL_MAGICRES": ("PLMR", 1), "IPL_MAGICRES_CURSE": ("PLMR", -1),
        "IPL_ALLRES": ("PLFR", 1),
        "IPL_STR": ("PLStr", 1), "IPL_STR_CURSE": ("PLStr", -1),
        "IPL_MAG": ("PLMag", 1), "IPL_MAG_CURSE": ("PLMag", -1),
        "IPL_DEX": ("PLDex", 1), "IPL_DEX_CURSE": ("PLDex", -1),
        "IPL_VIT": ("PLVit", 1), "IPL_VIT_CURSE": ("PLVit", -1),
        "IPL_ATTRIBS": ("PLStr", 1), "IPL_ATTRIBS_CURSE": ("PLStr", -1),
        "IPL_GETHIT": ("PLGetHit", 1), "IPL_GETHIT_CURSE": ("PLGetHit", 1),
        "IPL_LIFE": ("PLHP", 64), "IPL_LIFE_CURSE": ("PLHP", 64),
        "IPL_MANA": ("PLMana", 64), "IPL_MANA_CURSE": ("PLMana", 64),
        "IPL_DAMMOD": ("PLDamMod", 1),
        "IPL_SPLLVLADD": ("SplLvlAdd", 1),
        "IPL_TARGAC": ("PLEnAc", 1),
    }

    def affix_actual_value(self, affix: dict, fields: dict) -> int | None:
        """从记录字段反推词缀的实际数值（r）；失败返回 None。"""
        spec = self.POWER_FIELD.get(str(affix.get("power_name") or ""))
        if not spec:
            return None
        field, scale = spec
        raw = fields.get(field)
        if raw is None:
            return None
        try:
            raw = int(raw)
        except Exception:  # noqa: BLE001
            return None
        if scale == 64:
            return int(raw / 64) if raw % 64 == 0 else (raw >> 6)
        return raw * scale

    #: 一个词缀同时滚「伤害 + 命中」两条数值的能力
    TOHIT_DAMP_POWERS = ("IPL_TOHIT_DAMP", "IPL_TOHIT_DAMP_CURSE",
                         "IPL_DOPPELGANGER")

    def affix_actual_values(self, affix: dict, fields: dict) -> list[int | None]:
        """按 :meth:`affix_value_slots` 的顺序，从记录里取回每个槽的实际值。

        第二个槽（命中）在记录里合并进 ``PLToHit``；对于 ``King's`` 等前缀，
        那条记录就是它滚出来的 ``r + CalculateToHitBonus(p1)``。
        """
        out: list[int | None] = []
        for spec in self.affix_value_slots(affix, "prefix"):
            if spec.get("key") == "tohit":
                try:
                    out.append(int(fields.get("PLToHit") or 0))
                except (TypeError, ValueError):
                    out.append(None)
            else:
                out.append(self.affix_actual_value(affix, fields))
        return out

    def _chinese_describe(self, res: GenResult, base: dict, pre, suf, uniq) -> str:
        f = res.fields or {}
        lines = [f"名称：{res.name or '?'}"]
        if res.name_cn:
            lines.append(f"中文名：{res.name_cn}")
        base_en = str(base.get("name") or "")
        base_cn = d1zh.item_name_cn(base_en, item_cn(int(base.get("idx", -1) or -1)))
        lines.append(f"底材：{base_cn}（{base_en}）    运行时 idx={base.get('idx')}")
        quality = f.get("magical", 0)
        quality_cn = {0: "普通", 1: "魔法", 2: "暗金"}.get(int(quality), str(quality))
        level_txt = f"ilvl={int(f.get('iCreateInfo', 0)) & 0x3F}"
        if res.drop_mode == "unique_monster" and res.ilvl:
            level_txt = (f"ilvl={res.ilvl}（暗金怪路线：记录等级 {res.record_ilvl} + "
                         "CF_UPER15）")
        lines.append(f"品质：{quality_cn}    {level_txt}    seed={res.seed}")
        stats = []
        if int(f.get("minDam") or 0) or int(f.get("maxDam") or 0):
            if f.get("minDam") == f.get("maxDam"):
                stats.append(f"伤害 {f.get('minDam')}")
            else:
                stats.append(f"伤害 {f.get('minDam')}~{f.get('maxDam')}")
        if int(f.get("AC") or 0):
            stats.append(f"防御 {f.get('AC')}")
        if int(f.get("maxDur") or 0):
            stats.append(f"耐久 {f.get('durability')}/{f.get('maxDur')}")
        if stats:
            lines.append("属性：" + "，".join(stats))
        # ---- Round 4：基础属性满值说明 ----
        stat_bits: list[str] = []
        if res.applied_max_ac:
            stat_bits.append("护甲取最大")
        if res.applied_full_durability:
            stat_bits.append("耐久取满")
        if stat_bits:
            line = "基础属性：" + " / ".join(stat_bits) + "（直接写入记录"
            if res.base_stats_note:
                line += f"；{res.base_stats_note}"
            lines.append(line + "）")
        elif res.base_stats_note:
            lines.append(f"基础属性：{res.base_stats_note}")
        req = []
        for key, label in (("MinStr", "力量"), ("MinMag", "魔法"), ("MinDex", "敏捷")):
            v = int(f.get(key) or 0)
            if v:
                req.append(f"{label} {v}")
        if req:
            lines.append("需求：" + "，".join(req))
        # ---- Round 4：法术法杖（火弹 / 充能 12/12）----
        if res.staff_spell is not None and (res.charges or res.max_charges):
            spell = self._spell_by_id(res.staff_spell) or {}
            spell_cn = str(spell.get("cn") or "") or d1zh.spell_name(res.staff_spell)
            spell_en = str(spell.get("name") or "")
            shown = (f"{spell_cn}（{spell_en}）" if spell_cn and spell_en and spell_cn != spell_en
                     else (spell_cn or spell_en or f"#{res.staff_spell}"))
            charges = int(res.charges or 0)
            max_charges = int(res.max_charges if res.max_charges is not None else charges)
            lines.append(f"法术：{shown} 充能 {charges}/{max_charges}")
        lines.append(f"价值：{f.get('ivalue', 0):,}（鉴定后 {f.get('iIvalue', 0):,}）")
        if res.drop_note:
            lines.append(f"掉落：{res.drop_note}")
        # ---- 词条 ----
        lines.append("")
        lines.append("词条：")
        any_line = False
        for aff, kind in ((pre, "prefix"), (suf, "suffix")):
            if not isinstance(aff, dict):
                continue
            values = self.affix_actual_values(aff, f)
            value = values[0] if values else None
            tohit = values[1] if len(values) > 1 else None
            info = d1zh.power_value(aff, value, tohit=tohit)
            name = d1zh.affix_name(kind, aff)
            en = str(aff.get("name") or "")
            if d1zh.power_value(aff).get("numeric") is False:
                # 固定效果：用词缀说明，不猜数值
                lines.append(f"  · {'前缀' if kind == 'prefix' else '后缀'}：{name}（{en}）"
                             f"—— {d1zh.describe_power(aff)}")
            elif info.get("text"):
                lines.append(f"  · {'前缀' if kind == 'prefix' else '后缀'}：{name}（{en}）"
                             f"—— {info['text']}")
            else:
                lines.append(f"  · {'前缀' if kind == 'prefix' else '后缀'}：{name}（{en}）")
            any_line = True
        if isinstance(uniq, dict):
            lines.append(f"  · 暗金：{d1zh.unique_name(str(uniq.get('name') or ''))}"
                         f"（Uid={uniq.get('index')}，固定词条）")
            for p in (uniq.get("powers") or []):
                tname = str(p.get("type_name") or "")
                if tname in ("IPL_INVALID", "", "IPL_INVCURS"):
                    continue
                lines.append(f"      - {d1zh.describe_power(p)}")
            any_line = True
        if not any_line:
            lines.append("  （无词条）")
        return "\n".join(lines)

    def _chinese_name(self, res: GenResult, base: dict, pre, suf, uniq) -> str:
        base_en = str(base.get("name") or "")
        base_cn = d1zh.item_name_cn(base_en, item_cn(int(base.get("idx", -1) or -1)))
        if isinstance(uniq, dict):
            return d1zh.unique_name(str(uniq.get("name") or ""))
        pre_cn = d1zh.affix_name("prefix", pre) if isinstance(pre, dict) else ""
        suf_cn = d1zh.affix_name("suffix", suf) if isinstance(suf, dict) else ""
        spell_cn = ""
        try:
            spell_id = int((res.fields or {}).get("spell", -1))
            if spell_id >= 0:
                spell_cn = d1zh.spell_name(spell_id)
        except Exception:  # noqa: BLE001
            spell_cn = ""
        if base.get("itype_name") == "Staff" and spell_cn:
            return d1zh.item_full_name_cn(base_cn, pre_cn, "", spell_cn)
        return d1zh.item_full_name_cn(base_cn, pre_cn, suf_cn)

    def validate(self, record: bytes, allow_ac_override: bool = False) -> list[str]:
        """跑 core ``validate()``；``allow_ac_override`` 时忽略 AC 重放差异。

        core 支持 ``allow_ac_override`` 参数就直接透传；旧版 core 不支持时，
        这里把「replay mismatch AC」过滤掉（其余规则仍然全部保留）。
        """
        if not self.ready:
            return []
        fn = getattr(self.mod, "validate", None)
        if fn is None:
            return []
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        sentinel = object()
        got = sentinel
        if "allow_ac_override" in params:
            try:
                got = fn(bytes(record), allow_ac_override=bool(allow_ac_override))
            except TypeError:
                got = sentinel
        if got is sentinel:
            try:
                got = fn(bytes(record))
            except Exception as exc:  # noqa: BLE001
                return [f"校验异常：{exc}"]
        out = [str(x) for x in (got or [])]
        if allow_ac_override and "allow_ac_override" not in params:
            out = [x for x in out if not _is_ac_replay_mismatch(x)]
        return out

    def _auto_describe(self, res: GenResult) -> str:
        f = res.fields or {}
        lines = [f"名称：{res.name or f.get('iName') or f.get('name') or '?'}"]
        if res.name_cn:
            lines.append(f"中文名：{res.name_cn}")
        keys = [("minDam", "伤害下限"), ("maxDam", "伤害上限"), ("AC", "防御"),
                ("durability", "耐久"), ("maxDur", "耐久上限"), ("ivalue", "价值"),
                ("iIvalue", "价值(鉴定)"), ("MinStr", "需要力量"),
                ("MinMag", "需要魔法"), ("MinDex", "需要敏捷")]
        for k, label in keys:
            if k in f and f[k] not in (None, 0):
                lines.append(f"{label}：{f[k]}")
        if res.seed is not None:
            lines.append(f"seed：{res.seed}")
        if res.create_info is not None:
            lines.append(f"create_info：0x{int(res.create_info):04X}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 记录体检
    def check_record(self, record: bytes, deep: bool = True) -> list[tuple[str, str]]:
        """检查一条 368 字节物品记录是否可疑（储物箱页用）。

        deep=True 时额外跑 ``d1itemgen.validate``（重放 seed，慢但更全）。
        返回 [(severity, 中文原因)]，severity: "fatal" / "warn"。
        """
        issues: list[tuple[str, str]] = []
        if not record or len(record) < 368:
            return [("fatal", "记录长度不足 368 字节")]
        try:
            f = self._record_fields(record)
        except Exception as exc:  # noqa: BLE001
            return [("warn", f"记录解析失败：{exc}")]
        saved_idx = int(f.get("saved_idx", -1) or -1)
        rt_idx = -1
        try:
            rt_idx = int(MODULES.d1save.saved_to_runtime(saved_idx))
        except Exception:  # noqa: BLE001
            rt_idx = saved_idx
        name = str(f.get("name") or f.get("iName") or "")
        magical = int(f.get("magical", 0) or 0)
        # 只按运行时编号判断 starter：Short Sword / Buckler / Club / Short Bow
        # 这些名字同时被「起始装备」和「正常掉落版」共用。
        if rt_idx in self._starter:
            issues.append((
                "fatal",
                f"运行时编号 {rt_idx}（saved {saved_idx}）是初始装备 starter"
                f"「{name}」—— 会导致进游戏崩溃（0xC0000005）"))
        base = None
        T = self._tables()
        try:
            if T is not None:
                base = T.base_by_idx(rt_idx)
                if base is None:
                    base = T.base_by_saved_idx(saved_idx)
            if base is not None:
                if base.get("unique_only") and magical != 2:
                    issues.append((
                        "fatal",
                        f"「{base.get('name')}」是暗金专用底材（IMISC_UNIQUE），"
                        f"但记录品质是 {magical}（非暗金）"))
                if base.get("available") is False:
                    issues.append((
                        "warn",
                        f"底材「{base.get('name')}」在 1.5.5 非 Hellfire 中不可用"
                        f"（runtime {rt_idx}）"))
            elif T is not None:
                issues.append(("warn", f"运行时编号 {rt_idx} 不在物品表里（未知底材）"))
        except Exception:  # noqa: BLE001
            pass
        # ---- Round 5/6：非掉落物丢地上会消失（非致命，只提示）----
        try:
            create_info = int(f.get("create_info") or 0)
        except (TypeError, ValueError):
            create_info = 0
        item_level = create_info & 0x3F
        if not self.record_droppable(create_info):
            mode = ("暗金怪路线" if (create_info & 0xC0) == 0xC0
                    else "普通地牢掉落规则")
            issues.append((
                "warn",
                f"物品等级 {item_level}（{mode}）不满足游戏的掉落校验："
                "丢地上会提示「无效的数据包」并消失；只能放储物箱"))
        if deep:
            # Round 4：满值护甲是**直接写进记录**的，重放必然对不上 AC。
            # 这是用户显式选择的结果，只给 warn（且默认不勾选删除），不是 fatal。
            try:
                rec_ac = int(f.get("AC") or 0)
            except (TypeError, ValueError):
                rec_ac = 0
            try:
                base_max_ac = int((base or {}).get("max_ac") or 0)
            except (TypeError, ValueError):
                base_max_ac = 0
            full_ac = base_max_ac > 0 and rec_ac == base_max_ac
            for bad in self.validate(record):
                if _is_ac_replay_mismatch(bad) and full_ac:
                    issues.append((
                        "warn",
                        "护甲为满值（直接写入记录，非 seed 重放值）"))
                    continue
                issues.append(("fatal" if "mismatch" in bad.lower() else "warn",
                               f"d1itemgen 校验：{bad}"))
        return issues

    @staticmethod
    def _record_fields(record: bytes) -> dict:
        from d1stash_adapter import record_fields
        return record_fields(record)

    # ------------------------------------------------------------ 生成预检（Round 3）
    @property
    def supports_check_combination(self) -> bool:
        """core 是否已提供 ``d1itemgen.check_combination``。"""
        return bool(self.ready and callable(getattr(self.mod, "check_combination", None)))

    def check_combination(self, base, ilvl: int, rarity: str = "magic", prefix=None,
                          suffix=None, prefix_value: int | None = None,
                          suffix_value: int | None = None,
                          value_tolerance: int = 0,
                          max_ac: bool = False, full_durability: bool = False,
                          staff_spell=None, staff_charges: int | None = None,
                          allow_staff_spells: bool | None = None,
                          require_staff_spell: bool = False,
                          droppable: bool = False) -> ComboCheck:
        """生成**之前**判断「底材 + 词缀 + 数值」是否合法。

        优先调用 core 的 ``d1itemgen.check_combination()``（Round 3 新增）；
        没有/抛错时退回本适配层的规则实现（复刻 itemgen 的等级窗口与类型判定），
        返回统一的中文 :class:`ComboCheck`（ok / reason code / 建议）。

        Round 4 参数 ``max_ac`` / ``full_durability`` / ``staff_spell`` /
        ``staff_charges`` / ``allow_staff_spells``：先在 core 签名里查，
        只在 core 支持时透传；core 未就绪时由本地规则尽量给出提示。

        Round 5/6 ``droppable``：同样只在 core 支持时透传；core 未就绪时本地
        规则也会在 ``ilvl > 34`` 时返回 ``drop_ilvl``（31~34 走暗金怪路线）。
        """
        base_idx = base.idx if isinstance(base, BaseItem) else base
        allow_staff = allow_staff_spells
        if allow_staff is None:
            allow_staff = (staff_spell is not None or staff_charges is not None
                           or bool(require_staff_spell))
        spell_id = self._spell_id(staff_spell)
        charges = self._int_or_none(staff_charges)
        core = getattr(self.mod, "check_combination", None) if self.ready else None
        if callable(core):
            try:
                raw = self._call_core_check(
                    core, base_idx, ilvl, rarity, prefix, suffix,
                    prefix_value, suffix_value, value_tolerance,
                    max_ac=bool(max_ac), full_durability=bool(full_durability),
                    staff_spell=(spell_id if spell_id is not None else staff_spell),
                    staff_charges=charges, allow_staff_spells=bool(allow_staff),
                    require_staff_spell=bool(require_staff_spell),
                    droppable=bool(droppable))
                chk = self._normalize_core_check(raw)
                if chk is not None:
                    chk.source = "core"
                    if not chk.ok and not chk.suggestions:
                        base_len = _suggest_search() if chk.code in (
                            FAIL_SEARCH, FAIL_VALUE_RANGE) else []
                        chk.suggestions = base_len
                    return chk
            except Exception:  # noqa: BLE001 - core 未就绪/签名不合：退回本地规则
                pass
        chk = self._local_check_combination(
            base_idx, ilvl, rarity, prefix, suffix,
            prefix_value, suffix_value, value_tolerance,
            max_ac=bool(max_ac), full_durability=bool(full_durability),
            staff_spell=staff_spell, staff_charges=staff_charges,
            allow_staff_spells=bool(allow_staff),
            require_staff_spell=bool(require_staff_spell),
            droppable=bool(droppable))
        chk.source = "local"
        return chk

    def _call_core_check(self, core, base_idx, ilvl, rarity, prefix, suffix,
                         prefix_value, suffix_value, tolerance, *,
                         max_ac=False, full_durability=False, staff_spell=None,
                         staff_charges=None, allow_staff_spells=False,
                         require_staff_spell=False, droppable=False):
        """按 core 函数的实际签名传参（新旧签名都能兼容）。"""
        try:
            params = inspect.signature(core).parameters
        except (TypeError, ValueError):
            params = {}
        names = {
            "base_idx": base_idx, "base": base_idx, "base_item": base_idx,
            "ilvl": int(ilvl), "item_level": int(ilvl), "level": int(ilvl),
            "rarity": rarity, "prefix": prefix, "suffix": suffix,
            "prefix_value": prefix_value, "suffix_value": suffix_value,
            "value_tolerance": int(tolerance), "tolerance": int(tolerance),
            # ---- Round 4（只有 core 签名里有才会传）----
            "max_ac": bool(max_ac),
            "full_durability": bool(full_durability),
            "staff_spell": staff_spell,
            "staff_charges": staff_charges,
            "allow_staff_spells": bool(allow_staff_spells),
            "require_staff_spell": bool(require_staff_spell),
            # ---- Round 5（只有 core 签名里有才会传）----
            "droppable": bool(droppable),
        }
        kwargs = {name: names[name] for name in params if name in names}
        if kwargs:
            return core(**kwargs)
        return core(base_idx, int(ilvl), rarity=rarity, prefix=prefix, suffix=suffix,
                    prefix_value=prefix_value, suffix_value=suffix_value,
                    value_tolerance=int(tolerance))

    @staticmethod
    def _normalize_core_check(raw) -> ComboCheck | None:
        """把 core 的返回值（tuple / dict / bool / ComboCheck）统一成 ComboCheck。"""
        if raw is None:
            return None
        if isinstance(raw, ComboCheck):
            return raw
        code = ""
        message = ""
        suggestions: list[str] = []
        detail = ""
        if isinstance(raw, bool):
            ok = raw
        elif isinstance(raw, (tuple, list)):
            if not raw:
                return None
            ok = bool(raw[0])
            if len(raw) > 1 and raw[1] is not None:
                code = str(raw[1])
            if len(raw) > 2 and raw[2] is not None:
                message = str(raw[2])
            if len(raw) > 3 and raw[3]:
                suggestions = [str(x) for x in raw[3]]
            if len(raw) > 4 and raw[4]:
                detail = str(raw[4])
        elif isinstance(raw, dict):
            ok = bool(raw.get("ok", raw.get("allowed", raw.get("valid", True))))
            code = str(raw.get("code") or raw.get("reason_code") or "")
            message = str(raw.get("message") or raw.get("reason") or raw.get("msg") or "")
            for key in ("suggestions", "advice", "hints", "tips"):
                if raw.get(key):
                    suggestions = [str(x) for x in raw[key]]
                    break
            if raw.get("detail"):
                detail = str(raw["detail"])
        else:
            return None
        if ok:
            return ComboCheck(ok=True, code="", title="组合合法（预检通过）",
                              message=message, suggestions=suggestions, detail=detail)
        local_code = _CORE_TO_LOCAL.get(code, code)
        local_code = _refine_level_code(local_code, message)
        title = _CODE_TITLE.get(local_code) or _title_for_code(code)
        if not suggestions:
            suggestions = _default_suggestions(local_code)
        return ComboCheck(ok=False, code=local_code, title=title,
                          message=message, suggestions=suggestions, detail=detail)

    def _local_check_combination(self, base_idx, ilvl, rarity, prefix, suffix,
                                 prefix_value, suffix_value, tolerance, *,
                                 max_ac=False, full_durability=False, staff_spell=None,
                                 staff_charges=None, allow_staff_spells=False,
                                 require_staff_spell=False, droppable=False) -> ComboCheck:
        """core 未就绪时的本地预检：复刻 itemgen 的底材/类型/等级窗口规则。"""
        b = base_idx
        if isinstance(b, BaseItem):
            b_idx = b.idx
            b_obj = b
        else:
            b_idx = None if b is None else int(b)
            b_obj = self.base_item_by_idx(b_idx) if b_idx is not None else None
        if b_obj is None:
            return ComboCheck(ok=False, code=FAIL_BASE, title="底材非法（未选择/未知底材）",
                              message="请先在左侧列表里选择一个底材。",
                              suggestions=["在「1. 选择底材」里点一个装备"])
        reason = self.check_base(b_obj)
        if reason:
            return ComboCheck(
                ok=False, code=FAIL_BASE, title="底材非法（游戏规则不允许）",
                message=reason,
                suggestions=["换一个普通底材（starter / 暗金专用底材都不能当随机底材）",
                             "法杖请选 Short Staff / Long Staff 这类普通底材"])
        try:
            ilvl = int(ilvl)
        except (TypeError, ValueError):
            return ComboCheck(ok=False, code=FAIL_ILVL, title="ilvl 有误",
                              message="ilvl（物品等级）必须是整数。",
                              suggestions=["把 ilvl 改成 1~50 之间的整数"])
        # ---- Round 5/6：保证可丢地上（core 未就绪时的本地规则）----
        if droppable and ilvl > self.max_drop_ilvl:
            return ComboCheck(
                ok=False, code=FAIL_DROP_ILVL,
                title="ilvl 太高，丢地上会消失（游戏判定为非法数据包）",
                message=(f"ilvl {ilvl} 的物品丢地上会被游戏判定为非法数据包并消失；"
                         f"可丢地上的最高 ilvl 是 {self.max_drop_ilvl}"
                         "（31~34 自动走暗金怪掉落路线）"),
                suggestions=[f"把 ilvl 降到 {self.max_drop_ilvl}（或更低）",
                             "31~34 会自动改用暗金怪路线（记录等级 -4 + CF_UPER15）",
                             f"或取消「保证可丢地上」：ilvl>{self.max_drop_ilvl} "
                             "的物品只能放储物箱"])
        if not (1 <= ilvl <= 50):
            return ComboCheck(ok=False, code=FAIL_ILVL, title="ilvl 越界",
                              message=f"ilvl={ilvl} 超出允许范围 1~50。",
                              suggestions=["把 ilvl 改成 1~50 之间的值"])
        rarity = str(rarity or "magic").lower()
        T = self._tables()
        base_rec = None
        if T is not None:
            try:
                base_rec = T.resolve_base(b_obj.idx, require_available=True)
            except Exception:  # noqa: BLE001
                base_rec = None

        # ---- Round 4：法杖法术 / 充能（本地规则，core 未就绪时也提示）----
        is_staff = (
            str((base_rec or {}).get("itype_name") or "") == "Staff"
            or str((b_obj.raw or {}).get("itype_name") or "") == "Staff")
        if (staff_spell is not None or staff_charges is not None) and not is_staff:
            return ComboCheck(
                ok=False, code="bad_staff_spell",
                title="只有法杖才能指定法术/充能",
                message=f"「{b_obj.label}」不是法杖，不能带法术充能。",
                suggestions=["换一个法杖底材（Short Staff / Long Staff …）",
                             "或者把法术/充能留空"])
        if require_staff_spell and not is_staff:
            return ComboCheck(
                ok=False, code="bad_staff_spell",
                title="只有法杖才能做「法术法杖」",
                message=f"「{b_obj.label}」不是法杖，不能强制带法术。",
                suggestions=["换一个法杖底材（Short Staff / Long Staff …）",
                             "或者取消「法术法杖（带充能）」"])
        spell = None
        if staff_spell is not None:
            spell = self.resolve_spell(staff_spell)
            if spell is None:
                return ComboCheck(
                    ok=False, code="bad_staff_spell",
                    title="找不到该法术",
                    message=f"法术 {staff_spell!r} 不在法术表里。",
                    suggestions=["从下拉里重新选一个法术", "或者用「（随机法术）」"])
        if staff_charges is not None:
            if spell is None:
                return ComboCheck(
                    ok=False, code="bad_staff_charges",
                    title="填了充能但没选法术",
                    message="要先选一个法术，才能指定它的充能值。",
                    suggestions=["先选法术，再填充能", "或者把充能留空 = 随机"])
            charge = self._int_or_none(staff_charges)
            if charge is None:
                return ComboCheck(
                    ok=False, code="bad_staff_charges",
                    title="充能必须是整数",
                    message=f"充能值 {staff_charges!r} 不是整数。",
                    suggestions=["填一个整数，或留空 = 随机充能"])
            lo, hi = int(spell["staff_min"]), int(spell["staff_max"])
            if not lo <= charge <= hi:
                return ComboCheck(
                    ok=False, code="bad_staff_charges",
                    title="充能值超出该法术的范围",
                    message=(f"「{spell['cn'] or spell['name']}」的充能范围是 "
                             f"{lo}~{hi}；你填的是 {charge}。"),
                    suggestions=[f"把充能改成 {lo}~{hi} 之间", "或者留空 = 随机充能"])
        if (rarity == "magic" and (staff_spell is not None or require_staff_spell)
                and suffix is not None):
            return ComboCheck(
                ok=False, code="staff_spell_suffix",
                title="法术法杖没有后缀（游戏规则不允许）",
                message="法术法杖只有前缀；带后缀会和游戏生成的「Base of Spell」名字冲突。",
                suggestions=["把后缀留「（随机合法）」或清空",
                             "想要后缀请改选「属性法杖」"])
        if (rarity == "magic" and (staff_spell is not None or require_staff_spell)
                and not allow_staff_spells):
            return ComboCheck(
                ok=False, code="bad_staff_spell",
                title="魔法法术法杖需要显式允许",
                message="当前设置是「属性法杖」，不能同时指定法术；请切到「法术法杖」。",
                suggestions=["把形态改成「法术法杖（带充能）」",
                             "或者把法术留空 = 属性法杖"])
        # ---- Round 4：基础属性满值（本地规则）----
        rec_max_ac = int((base_rec or {}).get("max_ac") or 0)
        rec_max_dur = int((base_rec or {}).get("durability") or 0)
        dur_ind = 255
        if T is not None:
            try:
                dur_ind = int(getattr(T, "DUR_INDESTRUCTIBLE", 255) or 255)
            except Exception:  # noqa: BLE001
                dur_ind = 255
        if max_ac and rec_max_ac <= 0:
            return ComboCheck(
                ok=False, code="base_stats_conflict",
                title="该底材没有护甲，不能取护甲最大值",
                message=f"「{b_obj.label}」的护甲是 0（不是防具）。",
                suggestions=["取消「护甲取最大」",
                             "或者换一个防具底材（衣服 / 盾 / 头盔）"])
        if full_durability and (rec_max_dur <= 0 or rec_max_dur in (dur_ind, 299)):
            return ComboCheck(
                ok=False, code="base_stats_conflict",
                title="该底材不能取满耐久",
                message=(f"「{b_obj.label}」没有耐久，或耐久是不可破坏值"
                         f"（{rec_max_dur}）。"),
                suggestions=["取消「耐久取满」", "或者换一个有耐久的底材"])
        if max_ac:
            for kind in ("prefix", "suffix"):
                value = prefix if kind == "prefix" else suffix
                if value is None:
                    continue
                aff = self._affix_record(kind, value)
                if isinstance(aff, dict) and str(aff.get("power_name") or "") == "IPL_SETAC":
                    return ComboCheck(
                        ok=False, code="base_stats_conflict",
                        title="「护甲取最大」与该词缀冲突",
                        message=(f"{_KIND_CN[kind]}「{aff.get('name')}」会直接设定护甲值，"
                                 "不能和「护甲取最大」同时使用。"),
                        suggestions=["取消「护甲取最大」",
                                     "或者换一个不是直接设定 AC 的词缀"])

        if rarity != "magic":
            if prefix is not None or suffix is not None or prefix_value is not None \
                    or suffix_value is not None:
                return ComboCheck(
                    ok=False, code=FAIL_NORMAL_AFFIX, title="普通物品不能带词缀",
                    message="当前稀有度是「普通」，不能指定前缀/后缀/数值。",
                    suggestions=["把稀有度改成「魔法」", "或者把词缀都留「（随机合法）」"])
            if rarity == "unique" and T is not None:
                return ComboCheck(ok=True, code="", title="组合合法（暗金由 unique_id 决定）",
                                  message="暗金物品的词条由暗金表决定，生成时会校验。")
            return ComboCheck(ok=True, code="", title="组合合法（普通物品）",
                              message="普通物品没有词缀，可以直接生成。")

        if base_rec is not None and int(base_rec.get("affix_type") or 0) == 0:
            return ComboCheck(
                ok=False, code=FAIL_NO_AFFIX, title="该底材不会滚词缀",
                message=f"「{b_obj.label}」这种类型游戏永远不会随机加词缀。",
                suggestions=["把稀有度改成「普通」", "或者换一个能带词缀的底材"])

        minlvl = min(ilvl // 2, 25)
        maxlvl = ilvl
        for kind, value, want_value in (("prefix", prefix, prefix_value),
                                        ("suffix", suffix, suffix_value)):
            kind_cn = _KIND_CN[kind]
            if value is None:
                if want_value is not None:
                    return ComboCheck(
                        ok=False, code=FAIL_FIXED_VALUE,
                        title="只填了数值、没选词缀",
                        message=f"要指定{kind_cn}数值，请先选一个{kind_cn}。",
                        suggestions=[f"先在{kind_cn}下拉里选词条", "或清空目标值"])
                continue
            aff = self._affix_record(kind, value)
            if aff is None:
                return ComboCheck(
                    ok=False, code=FAIL_AFFIX_MISSING,
                    title=f"找不到该{kind_cn}",
                    message=f"该{kind_cn}在当前词缀表里不存在（可能已随版本变化）。",
                    suggestions=["重新选一次下拉里的词条", "或者点「刷新 (F5)」"])
            name = str(aff.get("name") or "?")
            if kind == "suffix" and not name.lower().startswith("of "):
                shown = "of " + name
            else:
                shown = name
            if base_rec is not None:
                try:
                    valid = (self.mod.is_prefix_valid_for_item_type(
                        aff["index"], base_rec["affix_type"], False) if kind == "prefix"
                        else self.mod.is_suffix_valid_for_item_type(
                            aff["index"], base_rec["affix_type"], False))
                except Exception:  # noqa: BLE001
                    valid = True
                if not valid:
                    return ComboCheck(
                        ok=False, code=FAIL_AFFIX_TYPE,
                        title=f"该{kind_cn}不能出现在这个底材上",
                        message=f"{kind_cn}「{shown}」不适用于「{b_obj.label}」。",
                        suggestions=["换一个适用于该底材的词缀（下拉里只列适用的）",
                                     "或者换一个底材"])
            lv = int(aff.get("min_level") or 0)
            if lv > maxlvl:
                return ComboCheck(
                    ok=False, code=FAIL_AFFIX_LEVEL_LOW,
                    title="词缀等级不够（游戏规则不允许）",
                    message=(f"{kind_cn}「{shown}」需要词缀等级 {lv}；"
                             f"ilvl={ilvl} 只允许 {minlvl}~{maxlvl}；"
                             f"请把 ilvl 提到 {lv}。"),
                    suggestions=_suggest_ilvl(lv),
                    detail=(f"{kind} '{name}' requires affix level {lv}, but ilvl={ilvl} "
                            f"only allows {minlvl}..{maxlvl} (raise ilvl to at least {lv})"))
            if lv < minlvl:
                max_ilvl = min(50, 2 * lv + 1)
                return ComboCheck(
                    ok=False, code=FAIL_AFFIX_LEVEL_HIGH,
                    title="ilvl 太高，该词缀落在窗口之外（游戏规则不允许）",
                    message=(f"{kind_cn}「{shown}」是 {lv} 级词缀，低于 ilvl 允许的窗口 "
                             f"{minlvl}~{maxlvl}；请把 ilvl 降到 {max_ilvl} 或更低。"),
                    suggestions=_suggest_lower_ilvl(max_ilvl),
                    detail=(f"{kind} '{name}' is a level-{lv} affix, below this item's "
                            f"affix window {minlvl}..{maxlvl}; e.g. ilvl <= {max_ilvl}"))
            if (kind == "prefix" and int(aff.get("index") or 0) > 82) or (
                    kind == "suffix" and int(aff.get("index") or 0) > 94):
                return ComboCheck(
                    ok=False, code=FAIL_AFFIX_TYPE,
                    title=f"该{kind_cn}只属于 Hellfire",
                    message=f"{kind_cn}「{shown}」在 1.5.5 非 Hellfire 里不存在。",
                    suggestions=["换一个非 Hellfire 的词缀"])
            if want_value is not None:
                try:
                    numeric = bool(self.mod.is_value_affix(aff))
                except Exception:  # noqa: BLE001
                    numeric = bool(d1zh.power_value(aff).get("numeric"))
                if not numeric:
                    return ComboCheck(
                        ok=False, code=FAIL_FIXED_VALUE,
                        title=f"「{shown}」是固定效果，不能指定数值",
                        message=(f"{kind_cn}「{shown}」的效果（充能/法术/攻速/吸血/"
                                 "固定伤害之类）不是可指定的数值。"),
                        suggestions=[f"把{kind_cn}的「目标值」清空",
                                     "或者换一个数值型词缀（抗性/力量/伤害%）"])
                rng_slots = self.affix_value_slots(aff, kind)
                if not rng_slots:
                    rng = self.affix_range(aff, kind)
                    if rng is not None:
                        rng_slots = [{"key": "value", "label": "数值",
                                      "range": (int(rng[0]), int(rng[1]))}]
                try:
                    wants = _value_arg(want_value)
                except (TypeError, ValueError):
                    return ComboCheck(
                        ok=False, code=FAIL_VALUE_RANGE, title="目标值不是整数",
                        message=f"{kind_cn}的目标值必须是整数"
                                "（两条属性的词缀按「伤害/命中」顺序用 / 分隔）。",
                        suggestions=["填一个范围内的整数，或留空随机"])
                if not isinstance(wants, list):
                    wants = [wants]
                tol = max(0, int(tolerance or 0))
                for idx, spec in enumerate(rng_slots):
                    want = wants[idx] if idx < len(wants) else None
                    if want is None:
                        continue
                    lo, hi = int(spec["range"][0]), int(spec["range"][1])
                    label = str(spec.get("label") or "数值")
                    what = f"「{label}」" if len(rng_slots) > 1 else ""
                    if want < lo - tol or want > hi + tol:
                        nearest = lo if want < lo else hi
                        return ComboCheck(
                            ok=False, code=FAIL_VALUE_RANGE,
                            title=f"目标值超出「{shown}」的范围",
                            message=(f"{kind_cn}「{shown}」{what}的数值范围是 "
                                     f"{lo:+d} ~ {hi:+d}；你填的是 {want:+d}"
                                     f"（最接近 {nearest:+d}）。"),
                            suggestions=[f"把{what or '目标值'}改成 {lo:+d}~{hi:+d} 之间",
                                         "或者把「容差」调大一点"])
        has_affix = prefix is not None or suffix is not None
        if has_affix or prefix_value is not None or suffix_value is not None:
            return ComboCheck(
                ok=True, code="", title="组合合法（预检通过，游戏规则允许）",
                message=("该「底材 + 词缀 + 数值」符合游戏规则。生成时程序会搜索 seed，"
                         "通常 1~3 秒；若搜索不到会提示放宽容差。"),
                suggestions=["如果生成失败，先放宽容差或只指定一个数值"])
        return ComboCheck(ok=True, code="", title="组合合法（随机词缀）",
                          message="随机合法词缀，直接生成即可。")

    def _affix_record(self, kind: str, value) -> dict | None:
        """把 index / name / dict 解析成词缀表行（内部用）。"""
        T = self._tables()
        if T is None:
            return None
        try:
            if isinstance(value, dict):
                return dict(value)
            if isinstance(value, int):
                return T.affix_by_index(kind, int(value))
            fn = getattr(self.mod, "_resolve_affix", None) if self.ready else None
            if callable(fn):
                return fn(value, kind)
            text = str(value).strip()
            for a in T.affix_list(kind):
                if a.get("name", "").lower() in (text.lower(), text.lower().replace("of ", "")):
                    return dict(a)
        except Exception:  # noqa: BLE001
            return None
        return None

    # ------------------------------------------------------------ 简易随机（无 itemgen）
    def simple_backpack_item(self, base_idx: int, ilvl: int, rarity: str = "magic") -> GenResult:
        """不依赖 itemgen：随机 seed + create_info，让游戏自己重建物品。"""
        rng = random.SystemRandom()
        seed = rng.getrandbits(32) or 1
        lvl = max(1, min(63, int(ilvl) * 2))
        if rarity == "normal":
            ci = 0
        elif rarity == "unique":
            ci = lvl | 0x200 | 0x40
        else:
            ci = lvl | 0x40  # CF_ONLYGOOD，保证出词缀
        bits = self.base_item_by_idx(base_idx)
        name = bits.label if bits else f"item {base_idx}"
        return GenResult(record=None, fields={"seed": seed, "create_info": ci,
                                             "runtime_idx": base_idx},
                         name=name, seed=seed, create_info=ci, runtime_idx=base_idx,
                         text=(f"简易随机（写角色背包，游戏按 seed 重建）\n"
                               f"物品：{name}\nseed：{seed}（0x{seed:08X}）\n"
                               f"create_info：{ci}（等级 {lvl}）"),
                         validation=[])


def add_to_backpack(savefile, runtime_idx: int, seed: int, create_info: int):
    """把物品加到角色背包（调用方负责 SaveFile 的备份/保存）。

    返回 HeroPack.add_item 的结果；**None 表示没加进去**（背包满，
    或该底材在 d1save 里没有可复用的 368 字节模板）。
    """
    pack = savefile.pack
    try:
        res = pack.add_item(int(runtime_idx), seed=int(seed), create_info=int(create_info), value=0)
    except TypeError:
        res = pack.add_item(int(runtime_idx), seed=int(seed), create_info=int(create_info))
    except Exception:  # noqa: BLE001
        return None
    return res
