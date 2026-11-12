"""d1itemgen.py -- Diablo 1 (DevilutionX 1.5.5, non-Hellfire) item generation.

The goal is byte-identical reproduction of what the game itself produces, so
that generated items can be written into ``stash.sv`` / ``single_*.sv`` and are
accepted (and displayed correctly) by the game.

Ported from DevilutionX 1.5.5 ``Source/items.cpp``:

    GetItemAttrs()                    items.cpp:3163
    GetItemBonus()                    items.cpp:1345
    GetItemPower()/...PrefixAndSuffix items.cpp:1245 / 1183
    SaveItemAffix() / SaveItemPower() items.cpp:1076 / 719
    PLVal()                           items.cpp:1067
    GetUniqueItem()                   items.cpp:1488
    ItemRndDur()                      items.cpp:1509
    SetupAllItems()                   items.cpp:1529
    CheckUnique()                     items.cpp:1454
    GetItemBLevel()                   items.cpp:1515
    GetStaffSpell()/GetStaffPower()   items.cpp:1272 / 1144
    GetBookSpell()                    items.cpp:627
    CalcItemValue()                   items.cpp:614
    Item::setNewAnimation()           items.cpp:4774 (SetupItem shape)
    Item::getName()                   items.cpp:4801
    GetTranslatedItemNameMagical()    items.cpp:2307 (used by validate)

RNG: ``GenerateRnd``/``AdvanceRndSeed``/``SetRndSeed`` are ported from
``Source/engine/random.cpp`` (Borland LCG 0x015A4E35, +1).  They are
bit-identical to the ``d1rng`` module shipped with the old trainer (verified in
the test suite over many seeds and ranges).

Record layout: 368 bytes, exactly ``Source/loadsave.cpp:1042 SaveItem()`` for
1.5.5 (name fields are 64 bytes).

Public API
----------
    GenItem, base_items(), eligible_affixes(), all_affixes(),
    affix_ilvl_band(), staff_spells(), generate(), validate(),
    check_combination(), record_to_fields(), fields_to_record(),
    replay_item(), describe_item()

Example
-------
    >>> from d1itemgen import generate, validate
    >>> item = generate("Long Sword", 25, rarity="magic")
    >>> item.record[:4]                     # iSeed (little endian)
    >>> item.fields["iName"]                # "King's Long Sword of the Whale"
    >>> validate(item.record)               # []
"""

from __future__ import annotations

import os
import random
import struct
import sys
from dataclasses import dataclass, field as dc_field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:  # package import (work.lib.d1itemgen)
    from . import d1tables as T
except ImportError:  # direct import (work/lib on sys.path)
    import d1tables as T


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

class ItemGenError(ValueError):
    """Raised when an item cannot be generated legally.

    ``code`` is a stable, machine-readable reason the GUI can branch on (see
    :func:`check_combination` for the full list); ``suggestions`` carries short
    actionable hints (Chinese).  Both default to something harmless so every
    historical ``raise ItemGenError("...")`` keeps working unchanged.
    """

    code = "error"
    suggestions = ()

    def __init__(self, message="", code=None, suggestions=None):
        super().__init__(message)
        if code:
            self.code = code
        self.suggestions = tuple(suggestions or ())


MAX_ITEM_LEVEL = T.CF_LEVEL  # 63 (6 bits)
RECORD_SIZE = 368

#: Highest ``ilvl`` this editor can make **droppable** on the floor.
#:
#: ``IsPItemValid()`` (msg.cpp) dispatches to one of three checks:
#:
#: * ``CF_TOWN``      -> ``IsTownItemValid()``         (level <= 30, Wirt <= 50)
#: * ``CF_UPER15``    -> ``IsUniqueMonsterItemValid()`` (level == some unique
#:   monster's base level, i.e. 1..30)
#: * everything else  -> ``IsDungeonItemValid()``       (non-Hellfire: level <= 30)
#:
#: So the record's ``CF_LEVEL`` never exceeds 30, **but** ``GetItemBLevel()``
#: gives a unique-monster drop a +4 affix window (``if (uper15) iblvl = lvl + 4``).
#: :func:`drop_plan` uses that bonus for ilvl 31..34; ``35+`` can only go to the
#: stash (the item disappears when dropped, "无效的数据包").
MAX_DROP_ILVL = 34

#: ``GetItemBLevel()`` adds this for unique-monster drops.
UNIQUE_DROP_BONUS = 4

#: Record levels that pass ``IsUniqueMonsterItemValid()``: unique monsters'
#: base ``MonstersData[].level`` values, skipping MT_DEFILER / MT_NAKRUL /
#: MT_HORKDMN (they do not use their mlvl).  Every value 1..30 occurs at least
#: once, so the 31..34 route maps onto record levels 27..30.
UNIQUE_MONSTER_LEVELS = frozenset(range(1, 31))


def droppable_level_ok(ilvl):
    """True when this editor can generate ``ilvl`` as a droppable item.

    ``0..30`` use the plain dungeon record, ``31..34`` the unique-monster route
    (:func:`drop_plan`).  This is the *generator's* capability; use
    :func:`record_droppable` to judge a finished 368-byte record.
    """
    try:
        level = int(ilvl)
    except (TypeError, ValueError):
        return False
    return 0 <= level <= MAX_DROP_ILVL


def drop_plan(ilvl):
    """How ``iCreateInfo`` must be written so ``ilvl`` survives a floor drop.

    Returns a dict::

        {"mode": "dungeon" | "unique_monster",
         "ilvl":        requested ilvl (= affix window max),
         "record_ilvl": CF_LEVEL value stored in the record (0..30),
         "uper":        0 | 15 (SetupAllItems() ``uper`` argument),
         "onlygood":    bool (CF_ONLYGOOD is forced on for uper 15),
         "affix_ilvl":  GetItemBLevel() result = affix window max,
         "flags":       CF_* bits to OR into iCreateInfo}

    ``ilvl 0..30`` -> plain dungeon record; ``ilvl 31..34`` -> unique-monster
    record ``(ilvl - 4) | CF_UPER15 | CF_ONLYGOOD``, whose affix window is
    ``[min(ilvl // 2, 25), ilvl]`` -- exactly the window the GUI promises.

    Raises :class:`ItemGenError` (code ``drop_ilvl``) when ``ilvl`` is outside
    ``0..MAX_DROP_ILVL``.
    """
    level = int(ilvl)
    if not (0 <= level <= MAX_DROP_ILVL):
        raise _drop_ilvl_error(level)
    if level <= MAX_DROP_ILVL - UNIQUE_DROP_BONUS:
        return {"mode": "dungeon", "ilvl": level, "record_ilvl": level,
                "uper": 0, "onlygood": False, "affix_ilvl": level, "flags": 0}
    record = level - UNIQUE_DROP_BONUS
    return {"mode": "unique_monster", "ilvl": level, "record_ilvl": record,
            "uper": 15, "onlygood": True, "affix_ilvl": level,
            "flags": CF_UPER15 | CF_ONLYGOOD}


def record_droppable(create_info, hellfire=False):
    """Port of the ``IsPItemValid()`` dispatch for one ``iCreateInfo`` value.

    Unlike :func:`droppable_level_ok` this checks the actual flags, so it also
    judges records imported from a save file or written by another tool.
    ``hellfire`` only affects Hellfire's looser dungeon bound and is accepted
    for signature symmetry (the editor targets non-Hellfire 1.5.5).
    """
    try:
        ci = int(create_info) & 0xFFFF
    except (TypeError, ValueError):
        return False
    level = ci & CF_LEVEL
    flags = ci & 0xFFFF & ~CF_LEVEL
    # IsCreationFlagComboValid(): pregen items never survive a pickup
    if flags & CF_PREGEN:
        return False
    # CF_USEFUL (both CF_UPER15 and CF_UPER1) is only legal on its own
    if (flags & CF_USEFUL) == CF_USEFUL and (flags & ~CF_USEFUL):
        return False
    if flags & CF_TOWN:
        # Items from town may carry exactly one town flag (hasMultipleFlags)
        if flags & (flags - 1):
            return False
        if flags & CF_BOY:
            return level <= 50  # MaxCharacterLevel
        return level <= 30
    if (flags & CF_USEFUL) == CF_UPER15:
        return level in UNIQUE_MONSTER_LEVELS
    if hellfire:
        return level <= 34  # (24 - 7) * 2
    return level <= 30

ITEM_QUALITY_NORMAL = T.ITEM_QUALITY_NORMAL
ITEM_QUALITY_MAGIC = T.ITEM_QUALITY_MAGIC
ITEM_QUALITY_UNIQUE = T.ITEM_QUALITY_UNIQUE

IPL_INVALID = T.IPL_INVALID
IPL_LASTDIABLO = T.IPL_LASTDIABLO

CF_LEVEL = T.CF_LEVEL
CF_ONLYGOOD = T.CF_ONLYGOOD
CF_UPER15 = T.CF_UPER15
CF_UPER1 = T.CF_UPER1
CF_UNIQUE = T.CF_UNIQUE
CF_PREGEN = T.CF_PREGEN
CF_SMITH = T.CREATEINFO_FLAG["CF_SMITH"]
CF_SMITHPREMIUM = T.CREATEINFO_FLAG["CF_SMITHPREMIUM"]
CF_BOY = T.CREATEINFO_FLAG["CF_BOY"]
CF_WITCH = T.CREATEINFO_FLAG["CF_WITCH"]
CF_HEALER = T.CREATEINFO_FLAG["CF_HEALER"]
CF_TOWN = T.CF_TOWN
CF_HELLFIRE = T.CF_HELLFIRE
#: ``CF_UPER15 | CF_UPER1``: "useful" items (floor potions / town portal scrolls)
CF_USEFUL = CF_UPER15 | CF_UPER1

DUR_INDESTRUCTIBLE = T.DUR_INDESTRUCTIBLE
ITEM_ANIM_WIDTH = 96


def _calculate_width2(width):
    """engine.cpp: (width - 64) / 2 (C++ truncating division)."""
    return _cdiv(width - 64, 2)


#: ``CalculateWidth2(96)`` -> 16 (engine.cpp; both operands positive).
ANIM_WIDTH2 = (ITEM_ANIM_WIDTH - 64) // 2


# ---------------------------------------------------------------------------
# RNG (engine/random.cpp)
# ---------------------------------------------------------------------------

_LCG_A = 0x015A4E35
_LCG_C = 1
_U32 = 0xFFFFFFFF
_INT32_MIN = -0x80000000


class Rng:
    """Bit-exact port of DevilutionX's ``diabloGenerator``.

    ``SetRndSeed(seed)`` -> ``Rng(seed)``; ``GenerateSeed()`` -> :meth:`advance`;
    ``AdvanceRndSeed()`` -> :meth:`advance`; ``GenerateRnd(v)`` -> :meth:`rnd`;
    ``DiscardRandomValues(n)`` -> :meth:`discard`; ``FlipCoin(f)`` -> :meth:`flip`.
    """

    __slots__ = ("state",)

    def __init__(self, seed=0):
        self.state = int(seed) & _U32

    def advance(self):
        """GenerateSeed(): advance the engine, return the raw uint32 state."""
        self.state = (self.state * _LCG_A + _LCG_C) & _U32
        return self.state

    def advance_rnd(self):
        """AdvanceRndSeed(): abs() of the state interpreted as int32_t."""
        v = self.advance()
        if v >= 0x80000000:
            sv = v - 0x100000000
            if sv == _INT32_MIN:  # abs(INT_MIN) is UB in C++, handled explicitly
                return _INT32_MIN
            return -sv
        return v

    def rnd(self, v):
        """GenerateRnd(v)."""
        v = int(v)
        if v <= 0:
            return 0
        a = self.advance_rnd()
        if v <= 0x7FFF:
            return (a >> 16) % v
        return a % v

    def discard(self, count):
        for _ in range(int(count)):
            self.advance()

    def flip(self, frequency=2):
        """FlipCoin(frequency) == GenerateRnd(frequency) == 0."""
        return self.rnd(frequency) == 0


# ---------------------------------------------------------------------------
# small C++ helpers (integer semantics matter for exact reproduction)
# ---------------------------------------------------------------------------

def _cdiv(a, b):
    """C++ integer division (truncates toward zero)."""
    a = int(a)
    b = int(b)
    if b == 0:
        raise ZeroDivisionError
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _wrap(value, bits, signed):
    value = int(value)
    mod = 1 << bits
    value %= mod
    if signed and value >= (mod >> 1):
        value -= mod
    return value


def _i8(v):
    return _wrap(v, 8, True)


def _u8(v):
    return _wrap(v, 8, False)


def _i16(v):
    return _wrap(v, 16, True)


def _u16(v):
    return _wrap(v, 16, False)


def _i32(v):
    return _wrap(v, 32, True)


def _u32(v):
    return _wrap(v, 32, False)


def _rnd_pl(rng, p1, p2):
    """RndPL(param1, param2) = param1 + GenerateRnd(param2 - param1 + 1)."""
    return int(p1) + rng.rnd(int(p2) - int(p1) + 1)


_TO_HIT_RANGES = {
    -50: (6, 10),
    -25: (1, 5),
    20: (1, 5),
    36: (6, 10),
    51: (11, 15),
    66: (16, 20),
    81: (21, 30),
    96: (31, 40),
    111: (41, 50),
    126: (51, 75),
    151: (76, 100),
}


def _calculate_to_hit_bonus(rng, level):
    """CalculateToHitBonus(); raises for unknown levels like app_fatal().

    The cursed keys (``-50``/``-25``) return ``-RndPL(lo, hi)`` in items.cpp, so
    the *magnitude* is rolled first and then negated -- drawing ``RndPL(-hi, -lo)``
    instead would consume the same number of RNG draws but map them differently
    and break replay.
    """
    if level not in _TO_HIT_RANGES:
        raise ItemGenError("CalculateToHitBonus: unknown level %r" % (level,))
    lo, hi = _TO_HIT_RANGES[level]
    bonus = _rnd_pl(rng, lo, hi)
    return -bonus if int(level) < 0 else bonus


def _plval(pv, p1, p2, minv, maxv):
    """PLVal() (items.cpp:1067)."""
    pv, p1, p2, minv, maxv = int(pv), int(p1), int(p2), int(minv), int(maxv)
    if p1 == p2:
        return minv
    if minv == maxv:
        return minv
    return minv + _cdiv((maxv - minv) * _cdiv(100 * (pv - p1), (p2 - p1)), 100)


#: Item effects whose rolled value ``r`` (``param1..param2``) is exactly what the
#: game tooltip shows.  Mapping: effect name -> tuple of
#: ``(record_field, sign, shift)``; the recorded field is
#: ``sign * r * (1 << shift)`` and the *displayed* value is ``sign * r``.
#:
#: ``shift`` is only non-zero for LIFE/MANA: ``SaveItemPower`` stores
#: ``r << 6`` in PLHP/PLMana while the character sheet / tooltip shows ``r``
#: points of life/mana.  ``min_val``/``max_val`` from the affix table are the
#: *item value* (PLVal) mapping, never the displayed bonus.
#:
#: Effects that are fixed flags, set charges/spells, behave as on-hit
#: procs or scale a percentage of the base item (CHARGES, SPELL, FASTATTACK,
#: STEALLIFE, DUR, CRYSTALLINE, ...) are intentionally absent: a numeric
#: target makes no sense for them and :func:`affix_value_range` returns None.
_VALUE_POWERS = {
    "IPL_TOHIT": (("PLToHit", 1, 0),),
    "IPL_TOHIT_CURSE": (("PLToHit", -1, 0),),
    "IPL_DAMP": (("PLDam", 1, 0),),
    "IPL_DAMP_CURSE": (("PLDam", -1, 0),),
    "IPL_TOHIT_DAMP": (("PLDam", 1, 0),),
    "IPL_TOHIT_DAMP_CURSE": (("PLDam", -1, 0),),
    "IPL_DOPPELGANGER": (("PLDam", 1, 0),),
    "IPL_ACP": (("PLAC", 1, 0),),
    "IPL_ACP_CURSE": (("PLAC", -1, 0),),
    "IPL_FIRERES": (("PLFR", 1, 0),),
    "IPL_LIGHTRES": (("PLLR", 1, 0),),
    "IPL_MAGICRES": (("PLMR", 1, 0),),
    "IPL_ALLRES": (("PLFR", 1, 0), ("PLLR", 1, 0), ("PLMR", 1, 0)),
    "IPL_STR": (("PLStr", 1, 0),),
    "IPL_STR_CURSE": (("PLStr", -1, 0),),
    "IPL_MAG": (("PLMag", 1, 0),),
    "IPL_MAG_CURSE": (("PLMag", -1, 0),),
    "IPL_DEX": (("PLDex", 1, 0),),
    "IPL_DEX_CURSE": (("PLDex", -1, 0),),
    "IPL_VIT": (("PLVit", 1, 0),),
    "IPL_VIT_CURSE": (("PLVit", -1, 0),),
    "IPL_ATTRIBS": (("PLStr", 1, 0), ("PLMag", 1, 0), ("PLDex", 1, 0), ("PLVit", 1, 0)),
    "IPL_ATTRIBS_CURSE": (("PLStr", -1, 0), ("PLMag", -1, 0), ("PLDex", -1, 0), ("PLVit", -1, 0)),
    "IPL_LIFE": (("PLHP", 1, 6),),
    "IPL_LIFE_CURSE": (("PLHP", -1, 6),),
    "IPL_MANA": (("PLMana", 1, 6),),
    "IPL_MANA_CURSE": (("PLMana", -1, 6),),
    "IPL_DAMMOD": (("PLDamMod", 1, 0),),
    "IPL_TARGAC": (("PLEnAc", 1, 0),),
}


def _signed_roll(power_name, r):
    """Signed displayed value of a rolled ``r``; None if the effect is not numeric."""
    fields = _VALUE_POWERS.get(power_name)
    if fields is None or r is None:
        return None
    return fields[0][1] * int(r)


def _power_roll_range(affix, hellfire=False):
    """``(lo, hi)`` of the internal ``r`` for an affix (TARGAC transform applied)."""
    p1, p2 = int(affix["param1"]), int(affix["param2"])
    if not hellfire and affix["power_name"] == "IPL_TARGAC":
        p1, p2 = 1 << p1, 3 << p2
    return (p1, p2) if p1 <= p2 else (p2, p1)


def _as_affix(affix, kind=None):
    """Accept an affix dict, a table index (+kind) or a name (+kind)."""
    if isinstance(affix, dict):
        if "power_name" not in affix:
            raise ItemGenError("affix dict has no power_name: %r" % (affix,))
        return dict(affix)
    if isinstance(affix, int):
        if kind is None:
            raise ItemGenError("kind='prefix'/'suffix' is required for an affix index")
        rec = T.affix_by_index(kind, affix)
        if rec is None:
            raise ItemGenError("no %s with index %d" % (kind, affix))
        return rec
    if isinstance(affix, str):
        if kind is None:
            raise ItemGenError("kind='prefix'/'suffix' is required for an affix name")
        rec = T.affix_by_name(kind, affix)
        if rec is None:
            raise ItemGenError("no %s named %r" % (kind, affix))
        return rec
    raise ItemGenError("cannot interpret affix %r" % (affix,))


def is_value_affix(affix, kind=None):
    """True when the affix's displayed bonus is a plain numeric value.

    Only these affixes accept ``prefix_value``/``suffix_value``; for everything
    else (charges, spells, attack speed, life steal, fixed flags, ...) a numeric
    target is meaningless.
    """
    return _as_affix(affix, kind)["power_name"] in _VALUE_POWERS


def affix_value_range(affix, kind=None, hellfire=False):
    """Displayed ``(min, max)`` value range of an affix, or None if not numeric.

    The range is the game's own ``param1..param2`` roll range (see
    :data:`_VALUE_POWERS`), **not** the affix table's ``min_val/max_val`` (those
    are the CalcItemValue multipliers).  Cursed affixes return negative values
    (e.g. ``Tin`` -> ``(-10, -6)``); ``of the fox`` -> ``(10, 15)``;
    ``haste`` (IPL_FASTATTACK) -> ``None``.
    """
    rec = _as_affix(affix, kind)
    fields = _VALUE_POWERS.get(rec["power_name"])
    if fields is None:
        return None
    lo, hi = _power_roll_range(rec, hellfire)
    sign = fields[0][1]
    if sign > 0:
        return (sign * lo, sign * hi)
    return (sign * hi, sign * lo)


#: Powers that roll **two** independent attributes in ``SaveItemPower``: the
#: damage percentage (``value`` below) and a separate ``CalculateToHitBonus()``
#: to-hit roll.  Twelve affixes use them (Sharp/Fine/Warrior's/Soldier's/
#: Lord's/Knight's/Master's/Champion's/King's, Clumsy/Dull, Doppelganger's), so a
#: single ``prefix_value`` is not enough to pin the item down.
_TOHIT_DAMP_POWERS = (
    "IPL_TOHIT_DAMP",
    "IPL_TOHIT_DAMP_CURSE",
    "IPL_DOPPELGANGER",
)

#: ``CalculateToHitBonus()`` (items.cpp) keys live in :data:`_TO_HIT_RANGES`
#: above; positive TOHIT_DAMP affixes use ``param1`` and the cursed variant
#: passes ``-param1`` (so Clumsy's 50 -> -50, Dull's 25 -> -25).

#: Chinese label of each *value* power, for the GUI's per-slot inputs.
_VALUE_LABELS = {
    "IPL_TOHIT": "命中",
    "IPL_DAMP": "伤害",
    "IPL_TOHIT_DAMP": "伤害",
    "IPL_DOPPELGANGER": "伤害",
    "IPL_ACP": "护甲",
    "IPL_FIRERES": "火焰抗性",
    "IPL_LIGHTRES": "闪电抗性",
    "IPL_MAGICRES": "魔法抗性",
    "IPL_ALLRES": "全抗性",
    "IPL_STR": "力量",
    "IPL_MAG": "魔法",
    "IPL_DEX": "敏捷",
    "IPL_VIT": "体力",
    "IPL_ATTRIBS": "所有属性",
    "IPL_LIFE": "生命",
    "IPL_MANA": "法力",
    "IPL_DAMMOD": "伤害",
    "IPL_TARGAC": "穿透护甲",
}


def _value_label(power_name):
    """Chinese label for a value power (curse variants fall back to the base)."""
    name = str(power_name or "")
    label = _VALUE_LABELS.get(name)
    if label is None and name.endswith("_CURSE"):
        label = _VALUE_LABELS.get(name[:-len("_CURSE")])
    return label or "数值"


def _tohit_bonus_range(power_name, param1):
    """``(lo, hi)`` of the ``CalculateToHitBonus()`` roll, or None.

    The game passes ``param1`` for TOHIT_DAMP/DOPPELGANGER and ``-param1`` for
    TOHIT_DAMP_CURSE.  The cursed variant subtracts the bonus, so its displayed
    range is negative while :data:`_TO_HIT_RANGES` stores positive numbers.
    """
    name = str(power_name or "")
    if name not in _TOHIT_DAMP_POWERS:
        return None
    key = -int(param1) if name == "IPL_TOHIT_DAMP_CURSE" else int(param1)
    rng = _TO_HIT_RANGES.get(key)
    if rng is None:
        return None
    lo, hi = rng
    if name == "IPL_TOHIT_DAMP_CURSE":
        return (-int(hi), -int(lo))
    return (int(lo), int(hi))


def affix_value_slots(affix, kind=None, hellfire=False):
    """Describe every independently targetable number of an affix.

    Most affixes have one slot; the twelve TOHIT_DAMP-style affixes have two
    (damage + to-hit), which is why a single ``prefix_value`` was incomplete.
    Each slot is a dict::

        {"key": "value" | "tohit",   # "value" is the SaveItemPower() r
         "label": "伤害" / "命中" / "力量" ...,
         "range": (lo, hi)}          # signed displayed range

    Returns ``[]`` for affixes without a numeric target (charges, spells, attack
    speed, ...).  ``prefix_value``/``suffix_value`` accept either one int
    (applies to slot 0) or a list with one entry per slot (``None`` leaves a
    slot free).
    """
    rec = _as_affix(affix, kind)
    rng = affix_value_range(rec, hellfire=hellfire)
    if rng is None:
        return []
    power = rec["power_name"]
    slots = [{"key": "value", "label": _value_label(power), "range": rng}]
    tohit = _tohit_bonus_range(power, rec["param1"])
    if tohit is not None:
        slots.append({"key": "tohit", "label": "命中", "range": tohit})
    return slots


def affix_value_slot_range(affix, index=0, kind=None, hellfire=False):
    """``(lo, hi)`` of one slot of :func:`affix_value_slots`, or None."""
    slots = affix_value_slots(affix, kind, hellfire)
    try:
        return slots[int(index)]["range"]
    except (IndexError, TypeError, ValueError):
        return None


def _first_value_target(value):
    """The slot-0 target of a ``prefix_value``/``suffix_value`` argument.

    Used where only one number is needed (e.g. picking the right affix level
    band): ints pass through, ``"151/93"``/lists give their first entry.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    if isinstance(value, str):
        head = value.replace(",", "/").replace("，", "/").split("/")[0].strip()
        if not head:
            return None
        try:
            return int(head)
        except ValueError:
            return None
    return value


def _normalize_value_target(value, affix, kind):
    """Turn ``prefix_value``/``suffix_value`` into a list of ints / Nones.

    Accepts an int (slot 0 only -- backwards compatible), a string like
    ``"151/93"`` or ``"151,93"``, or a list/tuple with one entry per
    :func:`affix_value_slots` slot.  Entries may be None/"" to leave that slot
    free.  Raises :class:`ItemGenError` (code ``bad_value``) for anything else.
    """
    slots = affix_value_slots(affix, kind)
    count = len(slots)
    if not count:
        return []

    def as_int(item, slot_label):
        if item is None:
            return None
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return None
            try:
                return int(text)
            except ValueError:
                raise ItemGenError(
                    "%s_value 的「%s」必须是整数，收到 %r" % (kind, slot_label, item),
                    code="bad_value",
                    suggestions=["只填整数，例如 %s" % _range_text(slots[0]["range"])])
        if isinstance(item, float) and not item.is_integer():
            raise ItemGenError(
                "%s_value 的「%s」必须是整数，收到 %r" % (kind, slot_label, item),
                code="bad_value",
                suggestions=["只填整数，例如 %s" % _range_text(slots[0]["range"])])
        try:
            return int(item)
        except (TypeError, ValueError):
            raise ItemGenError(
                "%s_value 的「%s」必须是整数，收到 %r" % (kind, slot_label, item),
                code="bad_value")

    if isinstance(value, str):
        parts = value.replace(",", "/").replace("，", "/").replace("|", "/").split("/")
        values = [as_int(part, slots[min(i, count - 1)]["label"])
                  for i, part in enumerate(parts)]
    elif isinstance(value, (list, tuple)):
        values = [as_int(item, slots[min(i, count - 1)]["label"])
                  for i, item in enumerate(value)]
    else:
        values = [as_int(value, slots[0]["label"])]
    if len(values) > count:
        raise ItemGenError(
            "%s_value 给了 %d 个数，但「%s」只有 %d 项可指定（%s）"
            % (kind, len(values), affix["name"], count,
               "、".join(s["label"] for s in slots)),
            code="bad_value",
            suggestions=["按 %s 的顺序填 %d 个数，用 / 分隔"
                         % ("、".join(s["label"] for s in slots), count)])
    values += [None] * (count - len(values))
    return values


def _value_affix_error(affix, kind):
    kind_cn = "前缀" if kind == "prefix" else "后缀"
    return ItemGenError(
        "%s「%s」的效果 %s 不是可指定的数值效果（固定/特殊效果：充能、法术、攻速、吸血、"
        "耐久百分比等），不能指定数值；请去掉 %s_value"
        % (kind_cn, affix["name"], affix["power_name"], kind),
        code="fixed_affix_value",
        suggestions=["去掉 %s_value（该词缀的效果由词缀本身决定，没有可指定的数值）" % kind])


def _calc_item_value(f):
    """CalcItemValue() (items.cpp:614)."""
    v = f["VMult1"] + f["VMult2"]
    if v > 0:
        v *= f["ivalue"]
    if v < 0:
        v = _cdiv(f["ivalue"], v)
    v = f["VAdd1"] + f["VAdd2"] + v
    f["iIvalue"] = max(v, 1)


# ---------------------------------------------------------------------------
# record layout (loadsave.cpp:1042 SaveItem, 1.5.5, 368 bytes)
# ---------------------------------------------------------------------------

# (key, offset, struct format, C++ value type)
RECORD_LAYOUT = (
    ("iSeed", 0, "I", "u32"),
    ("iCreateInfo", 4, "H", "u16"),
    # 6..7 padding
    ("iType", 8, "i", "i8"),
    ("posx", 12, "i", "i32"),
    ("posy", 16, "i", "i32"),
    ("animFlag", 20, "I", "u32"),
    # 24..27 _iAnimData pointer
    ("numFrames", 28, "i", "i32"),
    ("currentFrame", 32, "i", "i32"),
    ("animWidth", 36, "i", "i32"),
    ("animWidth2", 40, "i", "i32"),
    # 44..47 _delFlag
    ("selFlag", 48, "B", "u8"),
    # 49..51 padding
    ("postDraw", 52, "I", "u32"),
    ("identified", 56, "I", "u32"),
    ("magical", 60, "b", "i8"),
    ("name", 61, "64s", None),
    ("iName", 125, "64s", None),
    ("loc", 189, "b", "i8"),
    ("cls", 190, "B", "u8"),
    # 191 padding
    ("curs", 192, "i", "u8"),
    ("ivalue", 196, "i", "i32"),
    ("iIvalue", 200, "i", "i32"),
    ("minDam", 204, "i", "u8"),
    ("maxDam", 208, "i", "u8"),
    ("AC", 212, "i", "i16"),
    ("flags", 216, "I", "u32"),
    ("miscId", 220, "i", "i8"),
    ("spell", 224, "i", "i8"),
    ("charges", 228, "i", "i32"),
    ("maxCharges", 232, "i", "i32"),
    ("durability", 236, "i", "i32"),
    ("maxDur", 240, "i", "i32"),
    ("PLDam", 244, "i", "i16"),
    ("PLToHit", 248, "i", "i16"),
    ("PLAC", 252, "i", "i16"),
    ("PLStr", 256, "i", "i16"),
    ("PLMag", 260, "i", "i16"),
    ("PLDex", 264, "i", "i16"),
    ("PLVit", 268, "i", "i16"),
    ("PLFR", 272, "i", "i16"),
    ("PLLR", 276, "i", "i16"),
    ("PLMR", 280, "i", "i16"),
    ("PLMana", 284, "i", "i16"),
    ("PLHP", 288, "i", "i16"),
    ("PLDamMod", 292, "i", "i16"),
    ("PLGetHit", 296, "i", "i16"),
    ("PLLight", 300, "i", "i16"),
    ("SplLvlAdd", 304, "b", "i8"),
    ("Request", 305, "b", "i8"),
    # 306..307 padding
    ("Uid", 308, "i", "i32"),
    ("FMinDam", 312, "i", "i16"),
    ("FMaxDam", 316, "i", "i16"),
    ("LMinDam", 320, "i", "i16"),
    ("LMaxDam", 324, "i", "i16"),
    ("PLEnAc", 328, "i", "i16"),
    ("PrePower", 332, "b", "i8"),
    ("SufPower", 333, "b", "i8"),
    # 334..335 padding
    ("VAdd1", 336, "i", "i32"),
    ("VMult1", 340, "i", "i32"),
    ("VAdd2", 344, "i", "i32"),
    ("VMult2", 348, "i", "i32"),
    ("MinStr", 352, "b", "i8"),
    ("MinMag", 353, "B", "u8"),
    ("MinDex", 354, "b", "i8"),
    # 355 padding
    ("StatFlag", 356, "I", "u32"),
    ("idx", 360, "i", "i32"),
    ("dwBuff", 364, "I", "u32"),
)

FIELD_DEFAULTS = {key: 0 for key, _, _, _ in RECORD_LAYOUT}
FIELD_DEFAULTS["name"] = ""
FIELD_DEFAULTS["iName"] = ""
FIELD_DEFAULTS["iType"] = -1
FIELD_DEFAULTS["PrePower"] = IPL_INVALID
FIELD_DEFAULTS["SufPower"] = IPL_INVALID
FIELD_DEFAULTS["magical"] = ITEM_QUALITY_NORMAL
FIELD_DEFAULTS["animWidth"] = ITEM_ANIM_WIDTH
FIELD_DEFAULTS["animWidth2"] = ANIM_WIDTH2

FIELD_CASTS = {
    "u8": _u8, "u16": _u16, "u32": _u32,
    "i8": _i8, "i16": _i16, "i32": _i32,
}

FIELD_CTYPE = {key: ctype for key, _, _, ctype in RECORD_LAYOUT}
FIELD_OFFSET = {key: off for key, off, _, _ in RECORD_LAYOUT}

_NAME_MAX = 63  # 64-byte field, NUL terminated


def _encode_name(value):
    if value is None:
        value = ""
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8")
    raw = raw.split(b"\0", 1)[0][:_NAME_MAX]
    # avoid cutting a multi-byte sequence in half
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw[:len(raw) - 1]
    return raw + b"\0" * (64 - len(raw))


def _name_field_bytes(f, key):
    """Encode a name field, preserving the original raw 64-byte buffer if possible.

    Real 1.5.5 records can contain uninitialised garbage *after* the NUL
    terminator inside the 64-byte name arrays (e.g. stash record #17 has
    ``b'leech'`` at offset 148).  ``record_to_fields`` exposes those buffers as
    ``name_raw``/``iName_raw``; we reuse them as long as the visible text was not
    edited, so decode->encode stays byte-exact.
    """
    encoded = _encode_name(f.get(key, ""))
    raw = f.get(key + "_raw")
    if isinstance(raw, (bytes, bytearray)) and len(raw) == 64:
        raw = bytes(raw)
        if raw.split(b"\0", 1)[0] == encoded.split(b"\0", 1)[0]:
            return raw
    return encoded


def record_to_fields(rec):
    """Decode a 368-byte item record into a dict of Python values.

    String fields (``name``/``iName``) are decoded as UTF-8 ``str``.  ``idx`` is
    the *saved* (Diablo) item index; ``base_idx`` is the corresponding runtime
    index (``-1`` when unknown).  The untouched 64-byte name buffers are kept as
    ``name_raw``/``iName_raw`` so re-encoding is byte-exact.
    """
    rec = bytes(rec)
    if len(rec) != RECORD_SIZE:
        raise ValueError("item record must be %d bytes, got %d" % (RECORD_SIZE, len(rec)))
    out = {}
    for key, off, fmt, _ctype in RECORD_LAYOUT:
        if fmt == "64s":
            raw = rec[off:off + 64]
            out[key] = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
            out[key + "_raw"] = raw
        else:
            out[key] = struct.unpack_from("<" + fmt, rec, off)[0]
    out["base_idx"] = T.saved_to_runtime(out["idx"])
    return out


def fields_to_record(f):
    """Encode a field dict into a 368-byte item record.

    Missing keys fall back to :data:`FIELD_DEFAULTS`; padding bytes are zero.
    Integer fields are truncated exactly like the C++ struct assignment.
    """
    buf = bytearray(RECORD_SIZE)
    for key, off, fmt, ctype in RECORD_LAYOUT:
        if fmt == "64s":
            buf[off:off + 64] = _name_field_bytes(f, key)
            continue
        value = f.get(key, FIELD_DEFAULTS[key])
        if ctype:
            value = FIELD_CASTS[ctype](value)
        struct.pack_into("<" + fmt, buf, off, value)
    return bytes(buf)


# ---------------------------------------------------------------------------
# name generation / panel width
# ---------------------------------------------------------------------------

#: Glyph widths of the 12px Diablo font (``fonts\12-00.clx`` from
#: ``devilutionx.mpq``, 256 glyphs).  ``GetLineWidth(text, GameFont12, 2)``
#: sums ``width + 2`` per code point and subtracts one spacing at the end;
#: ``StringInPanel`` tests the result against 254.
FONT12_WIDTHS = (
      0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,
      0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,
      5,   4,   6,   7,   7,  11,  10,   3,   4,   4,   6,   6,   4,   5,   4,   8,
     10,   4,   8,   7,   8,   7,   7,   7,   7,   7,   4,   4,   7,   6,   7,   7,
     10,  11,   7,   9,   9,   7,   7,   9,   8,   4,   4,   8,   7,  11,   9,  10,
      7,  10,   9,   7,  10,  12,  12,  15,  11,  11,   8,   5,   8,   4,   4,   8,
      4,   9,   6,   7,   8,   6,   6,   8,   7,   3,   3,   7,   6,   9,   8,   9,
      6,   9,   8,   6,   9,  10,  10,  13,   9,   9,   7,   6,   2,   6,   5,   0,
      0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,
      0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,
      0,   4,   6,   7,   6,  11,   2,   6,   5,  10,   6,   7,   6,   0,  10,   5,
      5,   6,   5,   5,   4,  11,   7,   4,   4,   3,   6,   7,   9,  10,  11,   7,
     11,  11,  11,  11,  11,  11,  10,   9,   7,   7,   7,   7,   5,   4,   5,   5,
      9,   9,  10,  10,  10,  10,  10,   7,  10,  12,  12,  12,  12,  11,   7,   8,
      9,   9,   9,   9,   9,   9,   9,   7,   6,   6,   6,   6,   4,   4,   4,   4,
      9,   8,   9,   9,   9,   9,   9,   6,   9,  10,  10,  10,  10,   9,   6,   9,
)


def line_width(text, spacing=2):
    """GetLineWidth(text, GameFont12, spacing)."""
    if not text:
        return 0
    total = 0
    for ch in str(text):
        cp = ord(ch)
        if cp == 0x200B:  # ZWSP
            continue
        if cp == 0x0A:  # newline ends the line
            break
        total += FONT12_WIDTHS[cp & 0xFF] + spacing
    return total - spacing if total else 0


def string_in_panel(text):
    """StringInPanel(text): item names longer than 254px use the short name."""
    return line_width(text) < 254


def _generate_magic_item_name(base_name, prefix, suffix):
    """GenerateMagicItemName() (items.cpp:1167)."""
    if prefix is not None and suffix is not None:
        return "%s %s of %s" % (prefix["name"], base_name, suffix["name"])
    if prefix is not None:
        return "%s %s" % (prefix["name"], base_name)
    if suffix is not None:
        return "%s of %s" % (base_name, suffix["name"])
    return base_name


def _staff_spell_name(spell):
    sp = T.spell_by_id(spell)
    return sp["name"] if sp else ""


def _generate_staff_name(base_name, spell):
    return "%s of %s" % (base_name, _staff_spell_name(spell))


def _generate_staff_name_magical(base_name, spell, prefix):
    return "%s %s of %s" % (prefix["name"], base_name, _staff_spell_name(spell))


# ---------------------------------------------------------------------------
# affix selection (GetItemPowerPrefixAndSuffix)
# ---------------------------------------------------------------------------

_GOE_ANY = T.GOE_ANY
_GOE_EVIL = T.GOE_EVIL
_GOE_GOOD = T.GOE_GOOD

_SUFFIX_STAFF_STRIP_RANGES = ((0, 1), (14, 15), (21, 22), (34, 36), (41, 44), (60, 63))


def is_prefix_valid_for_item_type(index, flgs, hellfire=False):
    """IsPrefixValidForItemType() (items.cpp:358)."""
    item_types = T.PREFIXES[index]["item_types"]
    if not hellfire:
        if index > 82:
            return False
        if 12 <= index <= 20:
            item_types &= ~T.AFFIX_STAFF
    return bool(flgs & item_types)


def is_suffix_valid_for_item_type(index, flgs, hellfire=False):
    """IsSuffixValidForItemType() (items.cpp:373)."""
    item_types = T.SUFFIXES[index]["item_types"]
    if not hellfire:
        if index > 94:
            return False
        for lo, hi in _SUFFIX_STAFF_STRIP_RANGES:
            if lo <= index <= hi:
                item_types &= ~T.AFFIX_STAFF
                break
    return bool(flgs & item_types)


_AFFIX_CACHE = {}


def _affix_candidates(kind, flgs, minlvl, maxlvl, onlygood, goe=_GOE_ANY, hellfire=False):
    """Indices that GetItemPowerPrefixAndSuffix would put in its ``l[]`` array.

    Mirrors the C++ loops exactly, including ``PLDouble`` duplicating an entry.
    """
    key = (kind, flgs, minlvl, maxlvl, bool(onlygood), goe, bool(hellfire))
    cached = _AFFIX_CACHE.get(key)
    if cached is not None:
        return cached
    table = T.PREFIXES if kind == "prefix" else T.SUFFIXES
    out = []
    for aff in table:
        i = aff["index"]
        if kind == "prefix":
            if not is_prefix_valid_for_item_type(i, flgs, hellfire):
                continue
            if aff["min_level"] < minlvl or aff["min_level"] > maxlvl:
                continue
            if onlygood and not aff["ok"]:
                continue
            if (flgs & T.AFFIX_STAFF) and aff["power_name"] in ("IPL_CHARGES", "IPL_SPELL"):
                # A staff's spell/charges come from GetStaffSpell(); an affix that
                # overwrites them would disagree with the replayed name/tooltip.
                continue
        else:
            if not is_suffix_valid_for_item_type(i, flgs, hellfire):
                continue
            if not (minlvl <= aff["min_level"] <= maxlvl):
                continue
            if (goe == _GOE_GOOD and aff["goe"] == _GOE_EVIL) or (goe == _GOE_EVIL and aff["goe"] == _GOE_GOOD):
                continue
            if onlygood and not aff["ok"]:
                continue
        out.append(i)
        if aff["double"]:
            out.append(i)
    _AFFIX_CACHE[key] = out
    return out


def _consume_power_rolls(rng, power, hellfire=False):
    """Advance the RNG exactly like ``SaveItemPower()`` and return its rolls.

    The result is ``{"value": r}`` for every power, plus ``{"tohit": h}`` for
    the two-attribute powers ``IPL_TOHIT_DAMP`` / ``IPL_TOHIT_DAMP_CURSE`` /
    ``IPL_DOPPELGANGER``:

    * ``value`` -- the signed ``r`` used by :data:`_VALUE_POWERS` (damage for
      TOHIT_DAMP, the plain bonus for everything else);
    * ``tohit`` -- the separate ``CalculateToHitBonus()`` roll.  The game rolls
      it in a *second* RNG draw, so it cannot be derived from ``value``.

    Accepts either a power dict (``type_name``/``param1``/``param2``) or an
    affix dict from :mod:`d1tables` (``power_name``/``param1``/``param2``).
    """
    p1, p2 = int(power["param1"]), int(power["param2"])
    name = power.get("type_name") or power.get("power_name")
    if not hellfire and name == "IPL_TARGAC":
        p1 = 1 << p1
        p2 = 3 << p2
    r = _rnd_pl(rng, p1, p2)
    rolls = {"value": r}
    if name in ("IPL_TOHIT_DAMP", "IPL_DOPPELGANGER"):
        r = _rnd_pl(rng, p1, p2)
        rolls["value"] = r
        rolls["tohit"] = _calculate_to_hit_bonus(rng, p1)
    elif name == "IPL_TOHIT_DAMP_CURSE":
        rolls["tohit"] = _calculate_to_hit_bonus(rng, -p1)
    return rolls


def _consume_power_rng(rng, power, hellfire=False):
    """Advance the RNG exactly like SaveItemPower() would (no field updates).

    Backwards-compatible wrapper around :func:`_consume_power_rolls` that
    returns only the primary ``r`` value.
    """
    return _consume_power_rolls(rng, power, hellfire)["value"]


def _fast_selection(rng, flgs, minlvl, maxlvl, onlygood, hellfire=False,
                    need_suffix=True, need_suffix_value=False):
    """Simulate GetItemPowerPrefixAndSuffix() -> (pre, suf, pre_rolls, suf_rolls).

    ``pre_rolls``/``suf_rolls`` are the values ``SaveItemPower`` would roll for
    the selected affixes (None when no affix was allocated in that slot); each
    is a :func:`_consume_power_rolls` dict, i.e. ``{"value": r}`` plus a
    ``"tohit"`` entry for the two-attribute TOHIT_DAMP powers.  The RNG is
    advanced exactly like the real callbacks, including the extra
    ``CalculateToHitBonus`` roll and the suffix value roll that follows the
    suffix selection.

    ``need_suffix=False`` skips the suffix part entirely -- safe because no later
    RNG consumer depends on it (the suffix value roll is the last one), and it
    makes "prefix only" searches ~40% cheaper.  ``need_suffix_value`` controls
    whether the suffix value roll itself is simulated.
    """
    allocate_prefix = rng.flip(4)
    allocate_suffix = not rng.flip(3)
    if not allocate_prefix and not allocate_suffix:
        if rng.flip():
            allocate_prefix = True
        else:
            allocate_suffix = True
    goe = _GOE_ANY
    if not onlygood and not rng.flip(3):
        onlygood = True

    pre = -1
    suf = -1
    pre_rolls = None
    suf_rolls = None
    if allocate_prefix:
        cand = _affix_candidates("prefix", flgs, minlvl, maxlvl, onlygood, goe, hellfire)
        if cand:
            pre = cand[rng.rnd(len(cand))]
            aff = T.PREFIXES[pre]
            goe = aff["goe"]
            pre_rolls = _consume_power_rolls(rng, aff, hellfire)
    if allocate_suffix and need_suffix:
        cand = _affix_candidates("suffix", flgs, minlvl, maxlvl, onlygood, goe, hellfire)
        if cand:
            suf = cand[rng.rnd(len(cand))]
            if need_suffix_value:
                suf_rolls = _consume_power_rolls(rng, T.SUFFIXES[suf], hellfire)
    return pre, suf, pre_rolls, suf_rolls


def _select_affix_indices(rng, flgs, minlvl, maxlvl, onlygood, hellfire=False):
    """GetItemPowerPrefixAndSuffix() returning (prefix_index, suffix_index)."""
    pre, suf, _pre_rolls, _suf_rolls = _fast_selection(rng, flgs, minlvl, maxlvl,
                                                       onlygood, hellfire)
    return pre, suf


def _display_name_consistent(g):
    """True when the game's name replay would show exactly the stored iName.

    For staves with ``iblvl // 2 > 25`` the game is not self-consistent: the
    generation path (GetStaffSpell -> GetItemPower) uses ``minlvl = lvl/2``
    while the display path (GetTranslatedItemNameMagical) caps minlvl at 25, so
    the two can pick different prefixes.  Such items are legal but their
    tooltip would not match their stats, so generate() skips those seeds.
    """
    if g.f["magical"] != ITEM_QUALITY_MAGIC:
        return True
    f = dict(g.f)
    f["base_idx"] = g.base["idx"]
    shown = translated_item_name_magical(f, g.hellfire)
    return shown is None or shown == g.f["iName"]


def _selection_with_names(rng, flgs, minlvl, maxlvl, onlygood, hellfire=False):
    """Selection phase returning the chosen affix dicts (for name replay)."""
    pre_idx, suf_idx = _select_affix_indices(rng, flgs, minlvl, maxlvl, onlygood, hellfire)
    prefix = T.PREFIXES[pre_idx] if pre_idx >= 0 else None
    suffix = T.SUFFIXES[suf_idx] if suf_idx >= 0 else None
    return prefix, suffix


def translated_item_name_magical(fields, hellfire=False):
    """Port of ``GetTranslatedItemNameMagical()`` (items.cpp:2307).

    This is the function the game uses to *display* an identified magic item:
    it replays the RNG from ``iSeed``/``iCreateInfo`` to recover the prefix and
    suffix, then builds the name.  ``validate()`` uses it to make sure a record's
    stored ``iName`` is what the game will actually show.

    Returns ``None`` when the game cannot build a name this way (uniques, a
    staff without a usable prefix/spell, or a non-magic item); callers should
    then skip the comparison.
    """
    if isinstance(fields, (bytes, bytearray)):
        f = record_to_fields(fields)
    else:
        f = dict(fields)
    if f.get("magical") != ITEM_QUALITY_MAGIC:
        return None
    idx = f.get("base_idx")
    if idx is None:
        idx = T.saved_to_runtime(f.get("idx", -1))
    base = T.base_by_idx(idx)
    if base is None:
        return None
    ci = int(f.get("iCreateInfo", 0)) & 0xFFFF
    lvl = ci & CF_LEVEL
    onlygood = bool(ci & (CF_ONLYGOOD | CF_SMITHPREMIUM | CF_BOY | CF_WITCH))
    misc_id = f.get("miscId", base["misc_id"])
    rng = Rng(int(f.get("iSeed", 0)))

    if ci & CF_SMITHPREMIUM:
        rng.discard(2)  # RndVendorItem and GetItemAttrs
        minlvl = _cdiv(lvl, 2)
        maxlvl = lvl
    elif ci & CF_BOY:
        rng.discard(2)
        minlvl = lvl
        maxlvl = lvl * 2
    elif ci & CF_WITCH:
        rng.discard(2)
        iblvl = -1
        if rng.rnd(100) <= 5:
            iblvl = 2 * lvl
        if iblvl == -1 and misc_id == T.IMISC_STAFF:
            iblvl = 2 * lvl
        minlvl = _cdiv(iblvl, 2)
        maxlvl = iblvl
    else:
        rng.discard(1)  # GetItemAttrs
        shim = type("_Shim", (), {})()
        shim.rng = rng
        iblvl = _get_item_blevel(shim, lvl, misc_id, onlygood, ci & CF_UPER15)
        minlvl = _cdiv(iblvl, 2)
        maxlvl = iblvl
        rng.discard(1)  # CheckUnique

    if minlvl > 25:
        minlvl = 25

    itype = f.get("iType", base["itype"])
    flgs = T.ITYPE_TO_AFFIX.get(itype, 0)
    if itype == T.ITEM_TYPE["Staff"]:
        allowspells = not hellfire or (ci & CF_SMITHPREMIUM) == 0
        if not allowspells:
            flgs = T.AFFIX_STAFF
        elif not hellfire and rng.flip(4):
            flgs = T.AFFIX_STAFF
        else:
            rng.discard(2)  # spell and charges
            preidx = _get_staff_prefix_id(rng, maxlvl, onlygood, hellfire)
            spell = f.get("spell", 0)
            if preidx == -1 or spell == T.SPELL_ID["Null"]:
                return None  # the game falls back to the stored name
            name = _generate_staff_name_magical(base["name"] or "", spell,
                                                T.PREFIXES[preidx])
            if not string_in_panel(name) and base.get("sname"):
                name = _generate_staff_name_magical(base["sname"], spell,
                                                    T.PREFIXES[preidx])
            return name[:_NAME_MAX]

    if flgs == 0:
        return None
    prefix, suffix = _selection_with_names(rng, flgs, minlvl, maxlvl, onlygood, hellfire)
    name = _generate_magic_item_name(base["name"] or "", prefix, suffix)
    if not string_in_panel(name):
        short = base.get("sname")
        if short:
            name = _generate_magic_item_name(short, prefix, suffix)
    return name[:_NAME_MAX]


# ---------------------------------------------------------------------------
# item construction (the ported C++ generator)
# ---------------------------------------------------------------------------

class _Gen:
    """Mutable state of one item being generated."""

    __slots__ = ("f", "base", "rng", "prefix_index", "suffix_index", "unique_id",
                 "hellfire", "dam_ac_flags", "prefix_value", "suffix_value",
                 "prefix_delta", "suffix_delta")

    def __init__(self, base, rng, hellfire=False):
        self.base = base
        self.rng = rng
        self.hellfire = hellfire
        self.f = dict(FIELD_DEFAULTS)
        self.f["name"] = ""
        self.f["iName"] = ""
        self.prefix_index = -1
        self.suffix_index = -1
        self.unique_id = -1
        self.dam_ac_flags = 0
        #: signed *displayed* value rolled for the affix in each slot (None when
        #: the effect is not a plain numeric bonus, see _VALUE_POWERS)
        self.prefix_value = None
        self.suffix_value = None
        #: {field: delta} actually applied by the affix in each slot
        self.prefix_delta = {}
        self.suffix_delta = {}

    # -- field access with C++ narrowing -----------------------------------
    def set(self, key, value):
        ctype = FIELD_CTYPE.get(key)
        if ctype:
            value = FIELD_CASTS[ctype](value)
        self.f[key] = value

    def add(self, key, delta):
        self.set(key, self.f[key] + delta)

    def get(self, key):
        return self.f[key]

    # -- helpers -----------------------------------------------------------
    @property
    def affix_type(self):
        return self.base["affix_type"]


def _get_book_spell_level(spell, hellfire=False):
    """spells.cpp GetSpellBookLevel(), non-spawn build."""
    if not hellfire:
        if spell in (T.SPELL_ID["Nova"], T.SPELL_ID["Apocalypse"]):
            return -1
        if spell > T.SPELL_ID["LastDiablo"]:
            return -1
    sp = T.spell_by_id(spell)
    return sp["book_lvl"] if sp else -1


def _get_staff_spell_level(spell, hellfire=False):
    """spells.cpp GetSpellStaffLevel(), non-spawn build."""
    if not hellfire and spell > T.SPELL_ID["LastDiablo"]:
        return -1
    sp = T.spell_by_id(spell)
    return sp["staff_lvl"] if sp else -1


# ---------------------------------------------------------------------------
# staff spells (GetStaffSpell selection domain)
# ---------------------------------------------------------------------------

#: ``GetStaffSpell()`` walks ``SpellID`` from Firebolt and wraps at 37.
_STAFF_SPELL_MAX_ID = 37

#: The loop jumps over these two ids (they are replaced by Telekinesis / Blood
#: Star), so no staff can ever carry them.
_STAFF_SPELL_SKIPPED = (T.SPELL_ID["Resurrect"], T.SPELL_ID["HealOther"])

_STAFF_SPELL_CACHE = {}


def _staff_spell_usable(sp, hellfire=False):
    """True when ``GetStaffSpell()`` can actually select this spell."""
    if not sp or not sp.get("name"):
        return False
    index = int(sp["index"])
    if index < T.SPELL_ID["Firebolt"] or index >= _STAFF_SPELL_MAX_ID:
        return False
    if index in _STAFF_SPELL_SKIPPED:
        return False
    if int(sp["staff_max"]) <= 0:
        return False
    return _get_staff_spell_level(index, hellfire) != -1


def _spell_name_cn(spell_id, fallback=""):
    """Chinese spell name from :mod:`d1i18n` (English fallback when missing)."""
    try:
        import d1i18n  # local import: d1i18n lazily imports this module
        cn = d1i18n.spell_name_cn(spell_id)
    except Exception:  # noqa: BLE001 - localisation is optional
        cn = ""
    return cn or fallback


def _staff_spell_rows(hellfire=False):
    """Cached :func:`staff_spells` rows (never hand out the cache itself)."""
    key = bool(hellfire)
    rows = _STAFF_SPELL_CACHE.get(key)
    if rows is None:
        rows = []
        for sp in T.SPELLS:
            if not _staff_spell_usable(sp, key):
                continue
            level = _get_staff_spell_level(sp["index"], key)
            rows.append({
                "id": int(sp["index"]),
                "index": int(sp["index"]),
                "name": sp["name"],
                "cn": _spell_name_cn(sp["index"], sp["name"]),
                "staff_min": int(sp["staff_min"]),
                "staff_max": int(sp["staff_max"]),
                "min_int": int(sp["min_int"]),
                "staff_lvl": int(level),
                # GetStaffSpell() uses l = ilvl // 2 (0 is bumped to 1), so a
                # spell needs ilvl >= 2 * staff_lvl; level 1 already works at
                # ilvl 1 because of that 0 -> 1 bump.
                "min_ilvl": (1 if level <= 1 else 2 * int(level))
                            if level != -1 else 99,
                "magic_type_name": sp.get("magic_type_name", ""),
            })
        _STAFF_SPELL_CACHE[key] = rows
    return rows


def staff_spells(hellfire=False):
    """Spells the game can put on a staff (for the GUI's spell drop-down).

    Each row is a plain dict::

        {"id": 1, "index": 1, "name": "Firebolt", "cn": "火球术",
         "staff_min": 40, "staff_max": 80, "min_int": 15,
         "staff_lvl": 1, "min_ilvl": 2, "magic_type_name": "Fire"}

    ``min_ilvl`` is the smallest item level whose ``GetStaffSpell()`` window
    (``ilvl // 2``, bumped to 1 when it would be 0) reaches the spell:
    ``1`` for ``staff_lvl <= 1`` and ``2 * staff_lvl`` otherwise.  The list is
    the exact selection domain of ``GetStaffSpell()`` (Firebolt..Bone Spirit,
    Resurrect/HealOther skipped), not the whole ``SpellsData`` table.
    """
    return [dict(row) for row in _staff_spell_rows(hellfire)]


def _bad_staff_spell_error(value, hellfire=False):
    """The shared Chinese error for an unusable ``staff_spell`` value."""
    rows = _staff_spell_rows(hellfire)
    sample = "、".join("%s（%s）" % (r["cn"], r["name"]) for r in rows[:4]) or "无"
    sp = None
    if isinstance(value, int) and not isinstance(value, bool):
        sp = T.spell_by_id(int(value))
    if sp is not None and sp.get("name"):
        return ItemGenError(
            "法术「%s」（id=%s）不会出现在法杖上：GetStaffSpell() 只在 Firebolt..%d 之间滚，"
            "并跳过 Resurrect / HealOther；请换一个法杖法术（例如 %s）"
            % (sp["name"], sp["index"], _STAFF_SPELL_MAX_ID - 1, sample),
            code="bad_staff_spell",
            suggestions=["从 staff_spells() 里选一个法术，例如：%s" % sample])
    return ItemGenError(
        "找不到法杖法术 %r（可做法杖的法术共 %d 个：%s）" % (value, len(rows), sample),
        code="bad_staff_spell",
        suggestions=["从 staff_spells() 列表里选一个法术（id 或中英文名）",
                     "例如：%s" % sample])


def _resolve_staff_spell(value, hellfire=False):
    """Resolve ``staff_spell`` to a :func:`staff_spells` row.

    Accepts the spell id (``T.SPELL_ID``), the English name, the Chinese name
    (from :mod:`d1i18n`) or a ``staff_spells()`` dict.  Raises
    :class:`ItemGenError` (``code="bad_staff_spell"``) for anything the game
    cannot put on a staff.
    """
    rows = _staff_spell_rows(hellfire)
    if isinstance(value, dict):
        value = value.get("id", value.get("index"))
    if isinstance(value, int) and not isinstance(value, bool):
        for row in rows:
            if row["id"] == int(value):
                return dict(row)
        raise _bad_staff_spell_error(int(value), hellfire)
    text = str(value).strip()
    if not text:
        raise _bad_staff_spell_error(value, hellfire)
    low = text.lower()
    for row in rows:
        if low == str(row["name"]).lower() or text == row["cn"]:
            return dict(row)
    if low.startswith("of "):
        low = low[3:]
        for row in rows:
            if low == str(row["name"]).lower():
                return dict(row)
    raise _bad_staff_spell_error(value, hellfire)


def _check_staff_charges(spell, charges, hellfire=False):
    """Validate ``staff_charges`` against the spell's roll range.

    ``None`` means "let the game roll it".  Without a spell the union range of
    all staff spells is used (the seed search then matches the charges only).
    """
    if charges is None:
        return None
    if isinstance(charges, bool):
        raise ItemGenError("staff_charges 必须是整数，收到 %r" % (charges,),
                           code="bad_staff_charges",
                           suggestions=["填一个整数充能值，或留空表示随机"])
    try:
        want = int(charges)
    except (TypeError, ValueError):
        raise ItemGenError("staff_charges 必须是整数，收到 %r" % (charges,),
                           code="bad_staff_charges",
                           suggestions=["填一个整数充能值，或留空表示随机"])
    rows = _staff_spell_rows(hellfire)
    if spell is not None:
        lo, hi = int(spell["staff_min"]), int(spell["staff_max"])
        label = "法术「%s（%s）」" % (spell.get("cn", ""), spell.get("name", "?"))
    else:
        lo = min(r["staff_min"] for r in rows)
        hi = max(r["staff_max"] for r in rows)
        label = "任意法杖法术"
    if want < lo or want > hi:
        raise ItemGenError(
            "充能 %d 超出%s的充能范围 %d~%d（游戏用 GenerateRnd 在该区间内滚点）"
            % (want, label, lo, hi),
            code="bad_staff_charges",
            suggestions=["把充能改到 %d~%d 之间" % (lo, hi),
                         "或留空表示随机充能"])
    return want


def _check_staff_spell_level(spell, ilvl):
    """Refuse a staff spell the item level cannot reach (before any search).

    ``GetStaffSpell()`` only counts spells with ``ilvl // 2 >= staff_lvl``
    (``0 -> 1`` bumped, hence ``min_ilvl``), so the GUI shows
    “该法术需要 ilvl≥N” with the same N.  Rejecting here keeps the live preview
    and ``generate()`` in agreement and avoids a multi-second seed search that
    cannot possibly succeed.
    """
    need = int(spell.get("min_ilvl") or 1)
    if int(ilvl) >= need:
        return need
    raise ItemGenError(
        "法术「%s（%s）」需要物品等级 ≥ %d（当前 ilvl=%d）；请把 ilvl 提到 %d 或换一个低阶法术"
        % (spell.get("cn") or spell.get("name", "?"), spell.get("name", "?"),
           need, int(ilvl), need),
        code="level_window",
        suggestions=["把 ilvl 提到 %d" % need,
                     "或换一个低阶法术（ilvl 要求更低的）"])


def _get_book_spell(g, lvl):
    """GetBookSpell() (items.cpp:627)."""
    if lvl == 0:
        lvl = 1
    max_spells = 37
    rv = g.rng.rnd(max_spells) + 1
    s = T.SPELL_ID["Firebolt"]
    bs = T.SPELL_ID["Firebolt"]
    guard = 0
    while rv > 0:
        guard += 1
        if guard > 1000:  # pragma: no cover - defensive, mirrors the C++ wrap guarantee
            break
        s_level = _get_book_spell_level(s, g.hellfire)
        if s_level != -1 and lvl >= s_level:
            rv -= 1
            bs = s
        s += 1
        if s == T.SPELL_ID["Resurrect"]:
            s = T.SPELL_ID["Telekinesis"]
        if s == T.SPELL_ID["HealOther"]:
            s = T.SPELL_ID["BloodStar"]
        if s == max_spells:
            s = 1
    spell_name = _staff_spell_name(bs)
    g.f["name"] = (g.f["name"] + spell_name)[:_NAME_MAX]
    g.f["iName"] = (g.f["iName"] + spell_name)[:_NAME_MAX]
    g.set("spell", bs)
    sp = T.spell_by_id(bs)
    g.set("MinMag", sp["min_int"])
    g.add("ivalue", sp["book_cost"])
    g.add("iIvalue", sp["book_cost"])
    if sp["magic_type"] == T.MAGIC_TYPE["Fire"]:
        g.set("curs", T.ITEM_CURSOR_GRAPHIC["ICURS_BOOK_RED"])
    elif sp["magic_type"] == T.MAGIC_TYPE["Lightning"]:
        g.set("curs", T.ITEM_CURSOR_GRAPHIC["ICURS_BOOK_BLUE"])
    else:
        g.set("curs", T.ITEM_CURSOR_GRAPHIC["ICURS_BOOK_GREY"])


def _get_item_attrs(g, lvl):
    """GetItemAttrs() (items.cpp:3163)."""
    base = g.base
    g.set("iType", base["itype"])
    g.set("curs", base["curs"])
    g.f["name"] = (base["name"] or "")[:_NAME_MAX]
    g.f["iName"] = (base["name"] or "")[:_NAME_MAX]
    g.set("loc", base["loc"])
    g.set("cls", base["class"])
    g.set("minDam", base["min_dam"])
    g.set("maxDam", base["max_dam"])
    g.set("AC", base["min_ac"] + g.rng.rnd(base["max_ac"] - base["min_ac"] + 1))
    g.set("flags", base["flags"])
    g.set("miscId", base["misc_id"])
    g.set("spell", base["spell"])
    g.set("magical", ITEM_QUALITY_NORMAL)
    g.set("ivalue", base["value"])
    g.set("iIvalue", base["value"])
    g.set("durability", base["durability"])
    g.set("maxDur", base["durability"])
    g.set("MinStr", base["min_str"])
    g.set("MinMag", base["min_mag"])
    g.set("MinDex", base["min_dex"])
    g.set("PrePower", IPL_INVALID)
    g.set("SufPower", IPL_INVALID)
    if g.hellfire:
        g.f["dwBuff"] |= CF_HELLFIRE
    if g.f["miscId"] == T.IMISC_BOOK:
        _get_book_spell(g, lvl)
    # Gold items would roll a value here; generation of gold is not supported.


def _save_item_power(g, power, player=None):
    """SaveItemPower() (items.cpp:719).  Returns the rolled ``r``."""
    name = power["type_name"]
    p1 = int(power["param1"])
    p2 = int(power["param2"])
    if not g.hellfire and name == "IPL_TARGAC":
        p1 = 1 << p1
        p2 = 3 << p2
        power["param1"] = p1
        power["param2"] = p2

    r = _rnd_pl(g.rng, p1, p2)

    if name == "IPL_TOHIT":
        g.add("PLToHit", r)
    elif name == "IPL_TOHIT_CURSE":
        g.add("PLToHit", -r)
    elif name == "IPL_DAMP":
        g.add("PLDam", r)
    elif name == "IPL_DAMP_CURSE":
        g.add("PLDam", -r)
    elif name == "IPL_DOPPELGANGER":
        g.dam_ac_flags |= T.ITEM_SPECIAL_EFFECT_HF["Doppelganger"]
        r = _rnd_pl(g.rng, p1, p2)
        g.add("PLDam", r)
        g.add("PLToHit", _calculate_to_hit_bonus(g.rng, p1))
    elif name == "IPL_TOHIT_DAMP":
        r = _rnd_pl(g.rng, p1, p2)
        g.add("PLDam", r)
        g.add("PLToHit", _calculate_to_hit_bonus(g.rng, p1))
    elif name == "IPL_TOHIT_DAMP_CURSE":
        g.add("PLDam", -r)
        g.add("PLToHit", _calculate_to_hit_bonus(g.rng, -p1))
    elif name == "IPL_ACP":
        g.add("PLAC", r)
    elif name == "IPL_ACP_CURSE":
        g.add("PLAC", -r)
    elif name == "IPL_SETAC":
        g.set("AC", r)
    elif name == "IPL_AC_CURSE":
        g.add("AC", -r)
    elif name == "IPL_FIRERES":
        g.add("PLFR", r)
    elif name == "IPL_LIGHTRES":
        g.add("PLLR", r)
    elif name == "IPL_MAGICRES":
        g.add("PLMR", r)
    elif name == "IPL_ALLRES":
        g.set("PLFR", max(g.f["PLFR"] + r, 0))
        g.set("PLLR", max(g.f["PLLR"] + r, 0))
        g.set("PLMR", max(g.f["PLMR"] + r, 0))
    elif name == "IPL_SPLLVLADD":
        g.set("SplLvlAdd", r)
    elif name == "IPL_CHARGES":
        g.set("charges", g.f["charges"] * p1)
        g.set("maxCharges", g.f["charges"])
    elif name == "IPL_SPELL":
        g.set("spell", p1)
        g.set("charges", p2)
        g.set("maxCharges", p2)
    elif name == "IPL_FIREDAM":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FireDamage"]
        g.f["flags"] &= ~T.ITEM_SPECIAL_EFFECT["LightningDamage"]
        g.set("FMinDam", p1)
        g.set("FMaxDam", p2)
        g.set("LMinDam", 0)
        g.set("LMaxDam", 0)
    elif name == "IPL_LIGHTDAM":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["LightningDamage"]
        g.f["flags"] &= ~T.ITEM_SPECIAL_EFFECT["FireDamage"]
        g.set("LMinDam", p1)
        g.set("LMaxDam", p2)
        g.set("FMinDam", 0)
        g.set("FMaxDam", 0)
    elif name == "IPL_STR":
        g.add("PLStr", r)
    elif name == "IPL_STR_CURSE":
        g.add("PLStr", -r)
    elif name == "IPL_MAG":
        g.add("PLMag", r)
    elif name == "IPL_MAG_CURSE":
        g.add("PLMag", -r)
    elif name == "IPL_DEX":
        g.add("PLDex", r)
    elif name == "IPL_DEX_CURSE":
        g.add("PLDex", -r)
    elif name == "IPL_VIT":
        g.add("PLVit", r)
    elif name == "IPL_VIT_CURSE":
        g.add("PLVit", -r)
    elif name == "IPL_ATTRIBS":
        g.add("PLStr", r)
        g.add("PLMag", r)
        g.add("PLDex", r)
        g.add("PLVit", r)
    elif name == "IPL_ATTRIBS_CURSE":
        g.add("PLStr", -r)
        g.add("PLMag", -r)
        g.add("PLDex", -r)
        g.add("PLVit", -r)
    elif name == "IPL_GETHIT_CURSE":
        g.add("PLGetHit", r)
    elif name == "IPL_GETHIT":
        g.add("PLGetHit", -r)
    elif name == "IPL_LIFE":
        g.add("PLHP", r << 6)
    elif name == "IPL_LIFE_CURSE":
        g.add("PLHP", -(r << 6))
    elif name == "IPL_MANA":
        g.add("PLMana", r << 6)
    elif name == "IPL_MANA_CURSE":
        g.add("PLMana", -(r << 6))
    elif name == "IPL_DUR":
        bonus = _cdiv(r * g.f["maxDur"], 100)
        g.add("maxDur", bonus)
        g.add("durability", bonus)
    elif name == "IPL_CRYSTALLINE":
        g.add("PLDam", 140 + r * 2)
        # fallthrough to IPL_DUR_CURSE
        g.set("maxDur", max(g.f["maxDur"] - _cdiv(r * g.f["maxDur"], 100), 1))
        g.set("maxDur", max(_u8(g.f["maxDur"]), 1))
        g.set("durability", g.f["maxDur"])
    elif name == "IPL_DUR_CURSE":
        g.set("maxDur", max(_u8(g.f["maxDur"] - _cdiv(r * g.f["maxDur"], 100)), 1))
        g.set("durability", g.f["maxDur"])
    elif name == "IPL_INDESTRUCTIBLE":
        g.set("durability", DUR_INDESTRUCTIBLE)
        g.set("maxDur", DUR_INDESTRUCTIBLE)
    elif name == "IPL_LIGHT":
        g.add("PLLight", p1)
    elif name == "IPL_LIGHT_CURSE":
        g.add("PLLight", -p1)
    elif name == "IPL_MULT_ARROWS":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["MultipleArrows"]
    elif name == "IPL_FIRE_ARROWS":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FireArrows"]
        g.f["flags"] &= ~T.ITEM_SPECIAL_EFFECT["LightningArrows"]
        g.set("FMinDam", p1)
        g.set("FMaxDam", p2)
        g.set("LMinDam", 0)
        g.set("LMaxDam", 0)
    elif name == "IPL_LIGHT_ARROWS":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["LightningArrows"]
        g.f["flags"] &= ~T.ITEM_SPECIAL_EFFECT["FireArrows"]
        g.set("LMinDam", p1)
        g.set("LMaxDam", p2)
        g.set("FMinDam", 0)
        g.set("FMaxDam", 0)
    elif name == "IPL_FIREBALL":
        g.f["flags"] |= (T.ITEM_SPECIAL_EFFECT["LightningArrows"] | T.ITEM_SPECIAL_EFFECT["FireArrows"])
        g.set("FMinDam", p1)
        g.set("FMaxDam", p2)
        g.set("LMinDam", 0)
        g.set("LMaxDam", 0)
    elif name == "IPL_THORNS":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["Thorns"]
    elif name == "IPL_NOMANA":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["NoMana"]
    elif name == "IPL_ABSHALFTRAP":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["HalfTrapDamage"]
    elif name == "IPL_KNOCKBACK":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["Knockback"]
    elif name == "IPL_3XDAMVDEM":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["TripleDemonDamage"]
    elif name == "IPL_ALLRESZERO":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["ZeroResistance"]
    elif name == "IPL_STEALMANA":
        if p1 == 3:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["StealMana3"]
        if p1 == 5:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["StealMana5"]
    elif name == "IPL_STEALLIFE":
        if p1 == 3:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["StealLife3"]
        if p1 == 5:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["StealLife5"]
    elif name == "IPL_TARGAC":
        if g.hellfire:
            g.set("PLEnAc", p1)
        else:
            g.add("PLEnAc", r)
    elif name == "IPL_FASTATTACK":
        if p1 == 1:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["QuickAttack"]
        if p1 == 2:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FastAttack"]
        if p1 == 3:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FasterAttack"]
        if p1 == 4:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FastestAttack"]
    elif name == "IPL_FASTRECOVER":
        if p1 == 1:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FastHitRecovery"]
        if p1 == 2:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FasterHitRecovery"]
        if p1 == 3:
            g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FastestHitRecovery"]
    elif name == "IPL_FASTBLOCK":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["FastBlock"]
    elif name == "IPL_DAMMOD":
        g.add("PLDamMod", r)
    elif name == "IPL_RNDARROWVEL":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["RandomArrowVelocity"]
    elif name == "IPL_SETDAM":
        g.set("minDam", p1)
        g.set("maxDam", p2)
    elif name == "IPL_SETDUR":
        g.set("durability", p1)
        g.set("maxDur", p1)
    elif name == "IPL_ONEHAND":
        g.set("loc", T.ILOC_ONEHAND)
    elif name == "IPL_DRAINLIFE":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["DrainLife"]
    elif name == "IPL_RNDSTEALLIFE":
        g.f["flags"] |= T.ITEM_SPECIAL_EFFECT["RandomStealLife"]
    elif name == "IPL_NOMINSTR":
        g.set("MinStr", 0)
    elif name == "IPL_INVCURS":
        g.set("curs", p1)
    elif name == "IPL_ADDACLIFE":
        g.f["flags"] |= (T.ITEM_SPECIAL_EFFECT["LightningArrows"] | T.ITEM_SPECIAL_EFFECT["FireArrows"])
        g.set("FMinDam", p1)
        g.set("FMaxDam", p2)
        g.set("LMinDam", 1)
        g.set("LMaxDam", 0)
    elif name == "IPL_ADDMANAAC":
        g.f["flags"] |= (T.ITEM_SPECIAL_EFFECT["LightningDamage"] | T.ITEM_SPECIAL_EFFECT["FireDamage"])
        g.set("FMinDam", p1)
        g.set("FMaxDam", p2)
        g.set("LMinDam", 2)
        g.set("LMaxDam", 0)
    elif name == "IPL_FIRERES_CURSE":
        g.add("PLFR", -r)
    elif name == "IPL_LIGHTRES_CURSE":
        g.add("PLLR", -r)
    elif name == "IPL_MAGICRES_CURSE":
        g.add("PLMR", -r)
    elif name in ("IPL_DEVASTATION", "IPL_PERIL", "IPL_JESTERS", "IPL_ACDEMON", "IPL_ACUNDEAD"):
        g.dam_ac_flags |= T.ITEM_SPECIAL_EFFECT_HF.get(name[4:].title().replace("_", ""), 0)
    elif name == "IPL_DECAY":
        g.dam_ac_flags |= T.ITEM_SPECIAL_EFFECT_HF["Decay"]
        g.add("PLDam", r)
    elif name == "IPL_MANATOLIFE":
        base_mana = int(getattr(player, "max_mana_base", 0) if player is not None else 0)
        portion = _cdiv((base_mana >> 6) * 50, 100) << 6
        g.add("PLMana", -portion)
        g.add("PLHP", portion)
    elif name == "IPL_LIFETOMANA":
        base_hp = int(getattr(player, "max_hp_base", 0) if player is not None else 0)
        portion = _cdiv((base_hp >> 6) * 40, 100) << 6
        g.add("PLHP", -portion)
        g.add("PLMana", portion)
    return r


def _save_item_affix(g, affix):
    """SaveItemAffix() (items.cpp:1076).

    Returns ``(rolled_r, delta)`` where ``rolled_r`` is the raw ``r`` rolled by
    SaveItemPower and ``delta`` is the ``{field: change}`` the effect applied to
    the item (used by the numeric-value search to verify the stored fields).
    """
    power = {
        "type": affix["power"],
        "type_name": affix["power_name"],
        "param1": affix["param1"],
        "param2": affix["param2"],
    }
    before = dict(g.f)
    rolled = _save_item_power(g, power)
    value = _plval(rolled, power["param1"], power["param2"], affix["min_val"], affix["max_val"])
    if g.f["VAdd1"] != 0 or g.f["VMult1"] != 0:
        g.set("VAdd2", value)
        g.set("VMult2", affix["mult_val"])
    else:
        g.set("VAdd1", value)
        g.set("VMult1", affix["mult_val"])
    delta = {}
    for key, new in g.f.items():
        old = before[key]
        if isinstance(new, int) and isinstance(old, int) and new != old:
            delta[key] = new - old
    return rolled, delta


def _get_staff_prefix_id(rng, lvl, onlygood, hellfire=False):
    """GetStaffPrefixId() (items.cpp:1091)."""
    preidx = -1
    if rng.flip(10) or onlygood:
        cand = []
        for aff in T.PREFIXES:
            i = aff["index"]
            if not is_prefix_valid_for_item_type(i, T.AFFIX_STAFF, hellfire):
                continue
            if aff["min_level"] > lvl:
                continue
            if onlygood and not aff["ok"]:
                continue
            cand.append(i)
            if aff["double"]:
                cand.append(i)
        if cand:
            preidx = cand[rng.rnd(len(cand))]
    return preidx


def _get_staff_power(g, lvl, spell, onlygood):
    """GetStaffPower() (items.cpp:1144)."""
    preidx = _get_staff_prefix_id(g.rng, lvl, onlygood, g.hellfire)
    prefix = None
    if preidx != -1:
        g.set("magical", ITEM_QUALITY_MAGIC)
        rolled, delta = _save_item_affix(g, T.PREFIXES[preidx])
        g.prefix_value = _signed_roll(T.PREFIXES[preidx]["power_name"], rolled)
        g.prefix_delta = delta
        g.set("PrePower", T.PREFIXES[preidx]["power"])
        g.prefix_index = preidx
        prefix = T.PREFIXES[preidx]

    base_name = g.base["name"] or ""
    staff_name = _generate_staff_name(base_name, spell)
    g.f["name"] = staff_name[:_NAME_MAX]
    if prefix is not None:
        magic_name = _generate_staff_name_magical(base_name, spell, prefix)
        if not string_in_panel(magic_name) and g.base.get("sname"):
            magic_name = _generate_staff_name_magical(g.base["sname"], spell, prefix)
        g.f["iName"] = magic_name[:_NAME_MAX]
    else:
        g.f["iName"] = g.f["name"]
    _calc_item_value(g.f)


def _get_staff_spell(g, lvl, onlygood):
    """GetStaffSpell() (items.cpp:1272)."""
    if not g.hellfire and g.rng.flip(4):
        _get_item_power(g, _cdiv(lvl, 2), lvl, T.AFFIX_STAFF, onlygood)
        return
    max_spells = 37
    l = _cdiv(lvl, 2)
    if l == 0:
        l = 1
    rv = g.rng.rnd(max_spells) + 1
    s = T.SPELL_ID["Firebolt"]
    bs = T.SPELL_ID["Null"]
    guard = 0
    while rv > 0:
        guard += 1
        if guard > 1000:  # pragma: no cover - defensive
            break
        s_level = _get_staff_spell_level(s, g.hellfire)
        if s_level != -1 and l >= s_level:
            rv -= 1
            bs = s
        s += 1
        if s == T.SPELL_ID["Resurrect"]:
            s = T.SPELL_ID["Telekinesis"]
        if s == T.SPELL_ID["HealOther"]:
            s = T.SPELL_ID["BloodStar"]
        if s == max_spells:
            s = T.SPELL_ID["Firebolt"]
    sp = T.spell_by_id(bs)
    if sp is None:
        raise ItemGenError("GetStaffSpell selected an unknown spell %r" % (bs,))
    minc = sp["staff_min"]
    maxc = sp["staff_max"] - minc + 1
    g.set("spell", bs)
    g.set("charges", minc + g.rng.rnd(maxc))
    g.set("maxCharges", g.f["charges"])
    g.set("MinMag", sp["min_int"])
    v = _cdiv(g.f["charges"] * sp["staff_cost"], 5)
    g.add("ivalue", v)
    g.add("iIvalue", v)
    _get_staff_power(g, lvl, bs, onlygood)


def _get_item_power(g, minlvl, maxlvl, flgs, onlygood):
    """GetItemPower() (items.cpp:1245)."""
    prefix = None
    suffix = None

    def on_prefix(aff):
        nonlocal prefix
        g.set("magical", ITEM_QUALITY_MAGIC)
        rolled, delta = _save_item_affix(g, aff)
        g.prefix_value = _signed_roll(aff["power_name"], rolled)
        g.prefix_delta = delta
        g.set("PrePower", aff["power"])
        g.prefix_index = aff["index"]
        prefix = aff

    def on_suffix(aff):
        nonlocal suffix
        g.set("magical", ITEM_QUALITY_MAGIC)
        rolled, delta = _save_item_affix(g, aff)
        g.suffix_value = _signed_roll(aff["power_name"], rolled)
        g.suffix_delta = delta
        g.set("SufPower", aff["power"])
        g.suffix_index = aff["index"]
        suffix = aff

    # The C++ version splits selection and callbacks; ours does the same so the
    # RNG consumption order is identical.
    _select_with_callbacks(g, minlvl, maxlvl, flgs, onlygood, on_prefix, on_suffix)

    i_name = _generate_magic_item_name(g.f["name"], prefix, suffix)
    if not string_in_panel(i_name):
        short = g.base.get("sname")
        if short:
            i_name = _generate_magic_item_name(short, prefix, suffix)
    g.f["iName"] = i_name[:_NAME_MAX]
    if prefix is not None or suffix is not None:
        _calc_item_value(g.f)


def _select_with_callbacks(g, minlvl, maxlvl, flgs, onlygood, on_prefix, on_suffix):
    """GetItemPowerPrefixAndSuffix() with real callbacks."""
    rng = g.rng
    allocate_prefix = rng.flip(4)
    allocate_suffix = not rng.flip(3)
    if not allocate_prefix and not allocate_suffix:
        if rng.flip():
            allocate_prefix = True
        else:
            allocate_suffix = True
    goe = _GOE_ANY
    if not onlygood and not rng.flip(3):
        onlygood = True

    if allocate_prefix:
        cand = _affix_candidates("prefix", flgs, minlvl, maxlvl, onlygood, goe, g.hellfire)
        if cand:
            idx = cand[rng.rnd(len(cand))]
            aff = T.PREFIXES[idx]
            goe = aff["goe"]
            on_prefix(aff)
    if allocate_suffix:
        cand = _affix_candidates("suffix", flgs, minlvl, maxlvl, onlygood, goe, g.hellfire)
        if cand:
            idx = cand[rng.rnd(len(cand))]
            on_suffix(T.SUFFIXES[idx])


def _get_item_bonus(g, minlvl, maxlvl, onlygood, allowspells=True):
    """GetItemBonus() (items.cpp:1345)."""
    if minlvl > 25:
        minlvl = 25
    itype = g.f["iType"]
    if itype in (T.ITEM_TYPE["Sword"], T.ITEM_TYPE["Axe"], T.ITEM_TYPE["Mace"]):
        _get_item_power(g, minlvl, maxlvl, T.AFFIX_WEAPON, onlygood)
    elif itype == T.ITEM_TYPE["Bow"]:
        _get_item_power(g, minlvl, maxlvl, T.AFFIX_BOW, onlygood)
    elif itype == T.ITEM_TYPE["Shield"]:
        _get_item_power(g, minlvl, maxlvl, T.AFFIX_SHIELD, onlygood)
    elif itype in (T.ITEM_TYPE["LightArmor"], T.ITEM_TYPE["Helm"],
                   T.ITEM_TYPE["MediumArmor"], T.ITEM_TYPE["HeavyArmor"]):
        _get_item_power(g, minlvl, maxlvl, T.AFFIX_ARMOR, onlygood)
    elif itype == T.ITEM_TYPE["Staff"]:
        if allowspells:
            _get_staff_spell(g, maxlvl, onlygood)
        else:
            _get_item_power(g, minlvl, maxlvl, T.AFFIX_STAFF, onlygood)
    elif itype in (T.ITEM_TYPE["Ring"], T.ITEM_TYPE["Amulet"]):
        _get_item_power(g, minlvl, maxlvl, T.AFFIX_MISC, onlygood)
    # None / Misc / Gold: no affixes


def _item_rnd_dur(g):
    """ItemRndDur() (items.cpp:1509)."""
    dur = g.f["durability"]
    if dur > 0 and dur != DUR_INDESTRUCTIBLE:
        g.set("durability", g.rng.rnd(_cdiv(g.f["maxDur"], 2)) + _cdiv(g.f["maxDur"], 4) + 1)


def _get_item_blevel(g, lvl, misc_id, onlygood, uper15):
    """GetItemBLevel() (items.cpp:1515)."""
    iblvl = -1
    if (g.rng.rnd(100) <= 10
            or g.rng.rnd(100) <= lvl
            or onlygood
            or misc_id in (T.IMISC_STAFF, T.IMISC_RING, T.IMISC_AMULET)):
        iblvl = lvl
    if uper15:
        iblvl = lvl + 4
    return iblvl


def _check_unique(g, lvl, uper, recreate=False):
    """CheckUnique() (items.cpp:1454).  Returns a unique id or -1."""
    if g.rng.rnd(100) > uper:
        return -1
    base_item_id = g.base["item_id"]
    uok = []
    for u in T.UNIQUES:
        if not T.is_unique_available(u["index"]):
            break
        if u["base_item_id"] == base_item_id and lvl >= u["min_level"] and (recreate or True):
            uok.append(u["index"])
    if not uok:
        return -1
    g.rng.discard(1)  # DiscardRandomValues(1)
    # C++ walks a std::bitset<128>; it ends on the last matching entry.
    numu = len(uok)
    item_data = 0
    wanted = set(uok)
    while numu > 0:
        if item_data in wanted:
            numu -= 1
        if numu > 0:
            item_data = (item_data + 1) % 128
    return item_data


def _get_unique_item(g, uid):
    """GetUniqueItem() (items.cpp:1488)."""
    uniq = T.unique_by_id(uid)
    if uniq is None:
        raise ItemGenError("unknown unique item id %r" % (uid,))
    for power in uniq["powers"]:
        if power["type"] == IPL_INVALID:
            break
        _save_item_power(g, dict(power))
    g.f["iName"] = uniq["name"][:_NAME_MAX]
    g.set("iIvalue", uniq["value"])
    if g.f["miscId"] == T.IMISC_UNIQUE:
        g.set("iSeed", uid)
    g.set("Uid", uid)
    g.set("magical", ITEM_QUALITY_UNIQUE)
    g.f["iCreateInfo"] |= CF_UNIQUE
    g.unique_id = uid


def _setup_item(g):
    """SetupItem() + Item::setNewAnimation(showAnimation=false).

    Real stash records have animFlag=0, selFlag=1, currentFrame=numberOfFrames
    (the file stores currentFrame+1), which is exactly what
    setNewAnimation(false) produces.
    """
    frames = g.base.get("anim_frames") or 1
    g.set("animFlag", 0)
    g.set("selFlag", 1)
    g.set("postDraw", 0)
    g.set("Request", 0)
    g.set("numFrames", frames)
    g.set("currentFrame", frames)  # SaveItem writes internal currentFrame + 1
    g.set("animWidth", ITEM_ANIM_WIDTH)
    g.set("animWidth2", ANIM_WIDTH2)
    g.set("identified", 0)


def _finish(g, *, identified=True, stat_flag=True, position=(0, 0)):
    g.set("posx", position[0])
    g.set("posy", position[1])
    g.set("identified", 1 if identified else 0)
    g.set("StatFlag", 1 if stat_flag else 0)
    g.set("idx", T.runtime_to_saved(g.base["idx"]) if not g.hellfire else g.base["idx"])
    return g


def _setup_all_items(base, seed, lvl, uper=0, onlygood=False, recreate=False,
                     pregen=False, hellfire=False):
    """SetupAllItems() (items.cpp:1529)."""
    g = _Gen(base, Rng(seed), hellfire)
    g.set("iSeed", seed)
    _get_item_attrs(g, _cdiv(lvl, 2))
    g.set("iCreateInfo", lvl)
    if pregen:
        g.f["iCreateInfo"] |= CF_PREGEN
    if onlygood:
        g.f["iCreateInfo"] |= CF_ONLYGOOD
    if uper == 15:
        g.f["iCreateInfo"] |= CF_UPER15
    elif uper == 1:
        g.f["iCreateInfo"] |= CF_UPER1
    if g.f["miscId"] != T.IMISC_UNIQUE:
        iblvl = _get_item_blevel(g, lvl, g.f["miscId"], onlygood, uper == 15)
        if iblvl != -1:
            uid = _check_unique(g, iblvl, uper, recreate)
            if uid == -1:
                _get_item_bonus(g, _cdiv(iblvl, 2), iblvl, onlygood, True)
            else:
                _get_unique_item(g, uid)
        if g.f["magical"] != ITEM_QUALITY_UNIQUE:
            _item_rnd_dur(g)
    else:
        if g.f["loc"] != T.ILOC_UNEQUIPABLE:
            if seed > 109 or base["item_id"] != T.unique_by_id(seed)["base_item_id"]:
                raise ItemGenError("pre-generated unique with seed %r does not match base %r"
                                   % (seed, base["name"]))
            _get_unique_item(g, seed)
    _setup_item(g)
    return g


def _gen_normal(base, seed, ilvl, onlygood=False, hellfire=False, uper=0):
    """Normal item.

    For most item types this is the ``SetupAllItems`` path where
    ``GetItemBLevel`` returns -1 (no affix roll).  Staves are special: their
    ``iMiscId`` is ``IMISC_STAFF`` so ``GetItemBLevel`` always returns a level
    and the item goes through ``GetStaffSpell``; a staff with no prefix stays
    ``ITEM_QUALITY_NORMAL`` but still gets a random spell, charges and the
    ``"<base> of <spell>"`` name (e.g. "Long Staff of Elemental").

    ``uper=15`` (unique-monster drop) only changes ``iCreateInfo``; non-staff
    normal items never reach ``GetItemBLevel``, so the fields stay the same.
    """
    if base["itype"] == T.ITEM_TYPE["Staff"]:
        g = _setup_all_items(base, seed, ilvl, uper, onlygood, False, False, hellfire)
        if g.f["magical"] != ITEM_QUALITY_NORMAL:
            raise ItemGenError("seed %d produces a magical staff, not a normal one" % seed)
        return g
    g = _Gen(base, Rng(seed), hellfire)
    g.set("iSeed", seed)
    _get_item_attrs(g, _cdiv(ilvl, 2))
    g.set("iCreateInfo", ilvl)
    if onlygood:
        g.f["iCreateInfo"] |= CF_ONLYGOOD
    if uper == 15:
        g.f["iCreateInfo"] |= CF_UPER15
    _item_rnd_dur(g)
    _setup_item(g)
    return g


def _gen_unique(base, uid, seed, ilvl, onlygood=False, hellfire=False, uper=0):
    """Unique item, SpawnUnique(DIFF_NORMAL)-compatible shape.

    ``uper=15``/``onlygood`` mirror the unique-monster drop flags; quest uniques
    (``IMISC_UNIQUE``) keep ``iCreateInfo == 0`` because their id lives in
    ``iSeed``.
    """
    uniq = T.unique_by_id(uid)
    if uniq is None:
        raise ItemGenError("unknown unique item id %r" % (uid,))
    g = _Gen(base, Rng(seed), hellfire)
    g.set("iSeed", seed)
    _get_item_attrs(g, _cdiv(ilvl, 2))
    g.set("iCreateInfo", ilvl)
    if onlygood:
        g.f["iCreateInfo"] |= CF_ONLYGOOD
    if uper == 15:
        g.f["iCreateInfo"] |= CF_UPER15
    if base["misc_id"] == T.IMISC_UNIQUE:
        # quest uniques: the id is stored in iSeed, createInfo is just CF_UNIQUE
        g.set("iCreateInfo", 0)
    _get_unique_item(g, uid)
    _setup_item(g)
    return g


# ---------------------------------------------------------------------------
# GenItem
# ---------------------------------------------------------------------------

_GENERATION_KEYS = (
    "iSeed", "iCreateInfo", "iType", "magical", "name", "iName", "loc", "cls",
    "curs", "ivalue", "iIvalue", "minDam", "maxDam", "AC", "flags", "miscId",
    "spell", "charges", "maxCharges", "durability", "maxDur", "PLDam", "PLToHit",
    "PLAC", "PLStr", "PLMag", "PLDex", "PLVit", "PLFR", "PLLR", "PLMR", "PLMana",
    "PLHP", "PLDamMod", "PLGetHit", "PLLight", "SplLvlAdd", "Uid", "FMinDam",
    "FMaxDam", "LMinDam", "LMaxDam", "PLEnAc", "PrePower", "SufPower", "VAdd1",
    "VMult1", "VAdd2", "VMult2", "MinStr", "MinMag", "MinDex", "idx",
)


@dataclass
class GenItem:
    """A generated item: its 368-byte record plus decoded fields."""

    record: bytes
    fields: dict
    base: dict
    seed: int
    create_info: int
    rarity: str = "magic"
    prefix: Optional[dict] = None
    suffix: Optional[dict] = None
    unique: Optional[dict] = None
    _extra: dict = dc_field(default_factory=dict)

    def describe(self) -> str:
        f = self.fields
        rarity = {0: "normal", 1: "magic", 2: "unique"}.get(f.get("magical"), "?")
        lines = ["%s  [%s]" % (f.get("iName") or f.get("name"), rarity)]
        lines.append("  base: %s (runtime idx=%s, saved idx=%s)  size=%dx%d" % (
            self.base.get("name"), self.base.get("idx"), f.get("idx"),
            self.base.get("width", 1), self.base.get("height", 1)))
        ci = f.get("iCreateInfo", 0)
        lines.append("  seed=%d (0x%08X)  createInfo=0x%04X  ilvl=%d" % (
            f.get("iSeed", 0), f.get("iSeed", 0), ci, ci & CF_LEVEL))
        if f.get("magical") == ITEM_QUALITY_UNIQUE:
            uid = f.get("Uid", -1)
            u = T.unique_by_id(uid) if uid >= 0 else None
            if u:
                lines.append("  unique: %s (uid=%d, base %s, min level %d)" % (
                    u["name"], uid, u["base_item_id_name"], u["min_level"]))
        if self.prefix:
            lines.append("  prefix: %s [%s] (affix #%d, lvl %d)" % (
                self.prefix["name"], self.prefix["power_name"],
                self.prefix["index"], self.prefix["min_level"]))
        if self.suffix:
            lines.append("  suffix: of %s [%s] (affix #%d, lvl %d)" % (
                self.suffix["name"], self.suffix["power_name"],
                self.suffix["index"], self.suffix["min_level"]))
        lines.append("  damage %d-%d   AC %d   dur %d/%d" % (
            f.get("minDam", 0), f.get("maxDam", 0), f.get("AC", 0),
            f.get("durability", 0), f.get("maxDur", 0)))
        if f.get("charges") or f.get("spell"):
            lines.append("  spell %s charges %d/%d" % (
                _staff_spell_name(f.get("spell", 0)), f.get("charges", 0), f.get("maxCharges", 0)))
        req = []
        if f.get("MinStr"):
            req.append("str %d" % f["MinStr"])
        if f.get("MinMag"):
            req.append("mag %d" % f["MinMag"])
        if f.get("MinDex"):
            req.append("dex %d" % f["MinDex"])
        if req:
            lines.append("  requires " + ", ".join(req))
        mods = []
        for key, label, shift in (("PLToHit", "to hit", 0), ("PLDam", "damage%", 0),
                                  ("PLAC", "AC%", 0), ("PLDamMod", "dam mod", 0),
                                  ("PLStr", "str", 0), ("PLMag", "mag", 0),
                                  ("PLDex", "dex", 0), ("PLVit", "vit", 0),
                                  ("PLHP", "life", 6), ("PLMana", "mana", 6),
                                  ("PLFR", "fire res", 0), ("PLLR", "light res", 0),
                                  ("PLMR", "magic res", 0), ("PLLight", "light radius", 0),
                                  ("PLGetHit", "get hit", 0), ("PLEnAc", "AC vs demons", 0)):
            if f.get(key):
                value = f[key] >> shift if shift else f[key]
                mods.append("%s %+d" % (label, value))
        if mods:
            lines.append("  mods: " + ", ".join(mods))
        lines.append("  value %d / %d" % (f.get("ivalue", 0), f.get("iIvalue", 0)))
        return "\n".join(lines)


def _base_stats_conflict_error(label, detail=""):
    """max_ac + IPL_SETAC: the affix overwrites the very field we want to force."""
    return ItemGenError(
        "%s用 IPL_SETAC 直接设定护甲值，和“护甲取最大”（max_ac）不能共存："
        "请取消护甲满值，或换一个不改 AC 的词缀/暗金%s"
        % (label, ("（%s）" % detail) if detail else ""),
        code="base_stats_conflict",
        suggestions=["取消护甲满值（max_ac=False）", "换一个不设定 AC 的词缀"])


def _setac_source(want_prefix=None, want_suffix=None, unique=None):
    """Human label of the affix/unique power that sets AC outright, else None."""
    if want_prefix and want_prefix.get("power_name") == "IPL_SETAC":
        return "前缀「%s」" % (want_prefix.get("name") or "?")
    if want_suffix and want_suffix.get("power_name") == "IPL_SETAC":
        return "后缀「%s」" % (want_suffix.get("name") or "?")
    for power in (unique or {}).get("powers") or ():
        if power.get("type_name") == "IPL_SETAC":
            return "暗金「%s」的固定特效" % (unique.get("name") or "?")
    return None


def _make_gen_item(g, rarity, *, identified, stat_flag, position,
                   max_ac=False, full_durability=False):
    """Encode the finished ``_Gen`` as a :class:`GenItem`.

    ``max_ac`` / ``full_durability`` are the GUI's “满值” switches.  They are
    applied **here**, i.e. right before the 368-byte record is encoded, so the
    forced values are written verbatim into the record (single player shows
    them as-is).  Such a record no longer matches the seed replay, so
    :func:`validate` must be called with ``allow_ac_override=True`` (only AC is
    affected; durability is already ignored by ``validate``).

    What actually happened is reported in ``GenItem._extra``:
    ``applied_max_ac`` / ``applied_full_durability`` / ``base_stats_note``.
    """
    prefix = T.PREFIXES[g.prefix_index] if 0 <= g.prefix_index < len(T.PREFIXES) else None
    suffix = T.SUFFIXES[g.suffix_index] if 0 <= g.suffix_index < len(T.SUFFIXES) else None
    unique = T.unique_by_id(g.unique_id) if g.unique_id >= 0 else None
    applied_max_ac = False
    applied_full_dur = False
    notes = []
    if max_ac:
        source = _setac_source(prefix, suffix, unique)
        if source:
            raise _base_stats_conflict_error(source)
        base_max_ac = int(g.base.get("max_ac") or 0)
        if base_max_ac > 0:
            # The random GetItemAttrs() roll is replaced by the table maximum.
            # Additive AC powers (IPL_AC_CURSE) keep their effect: max_ac - r.
            ac = (base_max_ac + g.prefix_delta.get("AC", 0)
                  + g.suffix_delta.get("AC", 0))
            g.set("AC", ac)
            applied_max_ac = True
            notes.append("护甲取最大 %d" % base_max_ac)
        else:
            notes.append("该底材没有护甲（max_ac=0），护甲满值未生效")
    if full_durability:
        max_dur = int(g.f.get("maxDur") or 0)
        if 0 < max_dur < DUR_INDESTRUCTIBLE:
            g.set("durability", max_dur)
            applied_full_dur = True
            notes.append("耐久取满 %d" % max_dur)
        elif max_dur == DUR_INDESTRUCTIBLE:
            # 255 is the "indestructible" sentinel (durability == maxDur == 255)
            notes.append("该物品不可破坏（耐久 %d），耐久满值未生效" % DUR_INDESTRUCTIBLE)
        elif max_dur > DUR_INDESTRUCTIBLE:
            # e.g. Gothic Plate + suffix of structure (IPL_DUR 200%) -> 300:
            # writing 300/300 would exceed the game's 255 sentinel.
            notes.append("最大耐久 %d 超过 %d（游戏上限），未强制满值"
                         % (max_dur, DUR_INDESTRUCTIBLE))
        else:
            notes.append("该物品没有耐久，耐久满值未生效")
    _finish(g, identified=identified, stat_flag=stat_flag, position=position)
    record = fields_to_record(g.f)
    fields = record_to_fields(record)
    # keep GenItem.fields JSON friendly; the raw 64-byte name buffers are only
    # needed by the codec (record_to_fields returns them)
    fields = {k: v for k, v in fields.items() if not k.endswith("_raw")}
    return GenItem(
        record=record,
        fields=fields,
        base=dict(g.base),
        seed=g.f["iSeed"],
        create_info=g.f["iCreateInfo"],
        rarity=rarity,
        prefix=prefix,
        suffix=suffix,
        unique=unique,
        _extra={"prefix_index": g.prefix_index, "suffix_index": g.suffix_index,
                "prefix_value": g.prefix_value, "suffix_value": g.suffix_value,
                "prefix_power": (prefix or {}).get("power_name"),
                "suffix_power": (suffix or {}).get("power_name"),
                "applied_max_ac": applied_max_ac,
                "applied_full_durability": applied_full_dur,
                "base_stats_note": "；".join(notes)},
    )


# ---------------------------------------------------------------------------
# public generation API
# ---------------------------------------------------------------------------

def base_items(include_unavailable=False, droppable_only=False,
               include_starter=False, include_unique_only=False,
               include_non_equipment=False):
    """Generatable base items as dicts (runtime idx order).

    Same as :func:`d1tables.base_items`: starter items (the class starting gear,
    including ``IDI_SORCERER_DIABLO``), ``IMISC_UNIQUE`` rows and
    non-equipment rows (gold, potions, scrolls, books) are hidden unless the
    explicit debugging flags are passed.  Default = the 74 equipment rows.
    """
    return T.base_items(include_unavailable=include_unavailable,
                        droppable_only=droppable_only,
                        include_starter=include_starter,
                        include_unique_only=include_unique_only,
                        include_non_equipment=include_non_equipment)


def eligible_affixes(base_idx, ilvl, kind="prefix", onlygood=False):
    """Affixes the game could pick for this base item at this item level.

    ``kind`` is ``'prefix'`` or ``'suffix'``.  The level window follows
    ``SetupAllItems`` -> ``GetItemBLevel`` -> ``GetItemBonus``:
    ``minlvl = min(ilvl // 2, 25)``, ``maxlvl = ilvl``.  Note that at very low
    levels the game may roll no bonus at all (``GetItemBLevel`` returns -1);
    the list therefore means "eligible *if* a bonus is rolled".
    """
    base = T.resolve_base(base_idx, require_available=True)
    if base is None:
        raise ItemGenError("unknown base item %r" % (base_idx,))
    if base.get("unique_only"):
        return []  # unique-only base rows never carry random affixes
    ilvl = int(ilvl)
    flgs = base["affix_type"]
    minlvl, maxlvl = _affix_window(ilvl)
    indices = _affix_candidates(kind, flgs, minlvl, maxlvl, onlygood)
    table = T.PREFIXES if str(kind).lower().startswith("pre") else T.SUFFIXES
    return [dict(table[i]) for i in indices]


def _normalize_affix_kind(kind):
    """'prefix'/'suffix' from 'prefix'/'pre'/'suffix'/'suf' (case-insensitive)."""
    text = str(kind or "").strip().lower()
    if text.startswith("pre"):
        return "prefix"
    if text.startswith("suf"):
        return "suffix"
    raise ItemGenError("kind must be 'prefix' or 'suffix', got %r" % (kind,),
                       code="bad_affix",
                       suggestions=["kind 只能是 'prefix'（前缀）或 'suffix'（后缀）"])


def affix_ilvl_band(affix):
    """The ilvl range in which an affix is selectable, as ``(lo, hi)``.

    ``GetItemBonus`` passes ``minlvl = min(ilvl // 2, 25)``, ``maxlvl = ilvl`` to
    ``GetItemPower``, and an affix with level ``L`` needs ``minlvl <= L <=
    maxlvl``.  Solving that for ``ilvl`` gives ``[L, min(2L+1, 50)]`` for
    ``L < 25`` and ``[L, 50]`` for ``L >= 25`` (clamped to the GUI's 1..50).

    Affixes whose level is **above 50** (``Strange``, ``Godly``, ``slaughter``,
    ... are level 60) can never be rolled at an ilvl the GUI offers, so they
    return ``(level, 50)`` — i.e. ``lo > hi`` — which callers must read as
    "unreachable for ilvl <= 50" instead of inventing a legal range.

    ``affix`` is an affix dict (a ``d1tables`` row or an
    :func:`all_affixes`/``eligible_affixes`` entry).
    """
    rec = _as_affix(affix)
    level = int(rec.get("min_level") or 0)
    if level > 50:
        return level, 50
    lo = max(level, 1)
    hi = 50 if lo >= 25 else min(2 * lo + 1, 50)
    return lo, hi


def all_affixes(base_idx, kind="prefix"):
    """Every affix that fits this base item's type, ignoring the item level.

    Same item-type rules as :func:`eligible_affixes` (``IsPrefix/SuffixValidFor
    ItemType``, non-Hellfire index limits, no ``IPL_CHARGES``/``IPL_SPELL`` on
    staves) but **without** the ``minlvl..maxlvl`` window, so the GUI can show
    the whole list and let the user decide the ilvl afterwards.  Entries are
    plain :mod:`d1tables` rows plus ``kind`` and the ``ilvl_min``/``ilvl_max``
    band (see :func:`affix_ilvl_band`); sorted by ``min_level`` then index.
    """
    kind = _normalize_affix_kind(kind)
    base = T.resolve_base(base_idx, require_available=True)
    if base is None:
        raise ItemGenError("unknown base item %r" % (base_idx,), code="bad_base")
    if base.get("unique_only"):
        return []  # unique-only base rows never carry random affixes
    flgs = base["affix_type"]
    table = T.PREFIXES if kind == "prefix" else T.SUFFIXES
    out = []
    seen = set()
    for aff in table:
        index = aff["index"]
        if index in seen:
            continue
        if kind == "prefix":
            if not is_prefix_valid_for_item_type(index, flgs):
                continue
            if (flgs & T.AFFIX_STAFF) and aff["power_name"] in ("IPL_CHARGES", "IPL_SPELL"):
                continue
        elif not is_suffix_valid_for_item_type(index, flgs):
            continue
        seen.add(index)
        row = dict(aff)
        row["kind"] = kind
        row["ilvl_min"], row["ilvl_max"] = affix_ilvl_band(row)
        out.append(row)
    out.sort(key=lambda a: (a["min_level"], a["index"]))
    return out


def _resolve_affix(value, kind, base=None, ilvl=None, want_value=None):
    """Resolve a requested affix (name / table index / dict) to one table row.

    Several affixes share a name ("Fine" is both a weapon damage prefix and an
    armour AC prefix, "Crimson" exists at several levels), so when a base item
    and item level are known we pick the variant that is actually valid for
    that item type and level window.  When ``want_value`` is given, a variant
    whose numeric range contains it is preferred (so ``prefix="Crimson",
    prefix_value=35`` picks the 31..40 band, not the 21..30 one).
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "index" in value and "kind" in value and value.get("kind") != kind:
            raise ItemGenError("affix %r is a %s, not a %s" % (value.get("name"), value.get("kind"), kind),
                               code="bad_affix")
        return dict(value)
    if isinstance(value, int):
        aff = T.affix_by_index(kind, value)
        if aff is None:
            raise ItemGenError("no %s with index %d" % (kind, value), code="bad_affix")
        return aff
    # string: accept "King's", "of the Fox", "the Fox", "of the fox" and
    # "of the giants" (the table name of that suffix is just "giants").
    text = str(value).strip()
    after_of = text[3:] if text.lower().startswith("of ") else text
    variants = [text, after_of]
    if after_of.lower().startswith("the "):
        variants.append(after_of[4:])
    else:
        variants.append("the " + after_of)
    candidates = []
    for target in variants:
        candidates = [a for a in T.affix_list(kind) if a["name"].lower() == target.lower()]
        if candidates:
            break
    if not candidates:
        raise ItemGenError("no %s named %r" % (kind, value), code="bad_affix")
    if base is not None:
        def valid_type(a):
            return (is_prefix_valid_for_item_type(a["index"], base["affix_type"])
                    if kind == "prefix"
                    else is_suffix_valid_for_item_type(a["index"], base["affix_type"]))
        in_window = candidates
        if ilvl is not None:
            minlvl, maxlvl = _affix_window(ilvl)
            in_window = [a for a in candidates if minlvl <= a["min_level"] <= maxlvl]
        if want_value is not None:
            def band_has_value(a):
                rng = affix_value_range(a)
                return rng is not None and rng[0] <= int(want_value) <= rng[1]
            with_value = [a for a in in_window if band_has_value(a)]
            if not with_value:
                # the user may ask for a value that belongs to another level
                # band of the same name (e.g. "Crimson" 31..40 at ilvl 20)
                with_value = [a for a in candidates if band_has_value(a)]
            if with_value:
                in_window = with_value
        for a in in_window:
            if valid_type(a):
                return dict(a)
        for a in candidates:
            if valid_type(a):
                return dict(a)
    return dict(candidates[0])


def _random_seed():
    while True:
        seed = random.SystemRandom().getrandbits(32)
        if seed != 0:
            return seed


def _affix_window(ilvl):
    """The ``minlvl..maxlvl`` window GetItemBonus() passes to GetItemPower().

    ``GetItemBLevel`` gives ``iblvl = ilvl``; ``GetItemBonus`` then calls
    ``GetItemPower(min(ilvl // 2, 25), ilvl, ...)``.
    """
    ilvl = int(ilvl)
    return min(_cdiv(ilvl, 2), 25), ilvl


def _available_affix_names(base, ilvl, kind, limit=12):
    """Short comma-separated list of the affixes the game could pick."""
    names = [a["name"] for a in eligible_affixes(base["idx"], ilvl, kind)]
    text = "、".join(names[:limit])
    if len(names) > limit:
        text += " 等 %d 个" % len(names)
    return text or "无"


def _goe_conflict(want_prefix, want_suffix):
    """True when the game's suffix GOE filter makes the pair impossible.

    ``GetItemPowerPrefixAndSuffix()`` selects the suffix with the prefix's
    ``goe``: a good prefix excludes evil suffixes and an evil prefix excludes
    good ones (``_affix_candidates`` implements the filter).  GOE_ANY prefixes
    accept both.
    """
    if not want_prefix or not want_suffix:
        return False
    p_goe = int(want_prefix.get("goe") or 0)
    s_goe = int(want_suffix.get("goe") or 0)
    return ((p_goe == _GOE_GOOD and s_goe == _GOE_EVIL)
            or (p_goe == _GOE_EVIL and s_goe == _GOE_GOOD))


def _goe_conflict_error(base, ilvl, want_prefix, want_suffix):
    """The shared Chinese error for a good/evil prefix+suffix pair."""
    p_goe = int(want_prefix.get("goe") or 0)
    s_goe = int(want_suffix.get("goe") or 0)
    p_side = "善良" if p_goe == _GOE_GOOD else "邪恶"
    s_side = "邪恶" if s_goe == _GOE_EVIL else "善良"
    neutral = [a["name"] for a in eligible_affixes(base["idx"], ilvl, "suffix")
               if not a.get("goe")]
    neutral_text = "、".join(neutral[:8]) or "无"
    return ItemGenError(
        "前缀「%s」是%s词缀，后缀「%s」是%s词缀；游戏选后缀时会排除对立阵营，"
        "两者不可能出现在同一件物品上（GOE 冲突）"
        % (want_prefix["name"], p_side,
           want_suffix["name"] if want_suffix["name"].lower().startswith("of ")
           else "of " + want_suffix["name"], s_side),
        code="goe_conflict",
        suggestions=["改用中立（GOE_ANY）后缀：%s" % neutral_text,
                     "或换一个同阵营/中立的前缀"])


def _check_affix_reachable(base, ilvl, affix, kind, onlygood):
    """Raise with a helpful message if the affix can never be picked."""
    flgs = base["affix_type"]
    minlvl, maxlvl = _affix_window(ilvl)
    kind_cn = "前缀" if kind == "prefix" else "后缀"
    if kind == "prefix":
        valid_type = is_prefix_valid_for_item_type(affix["index"], flgs, False)
    else:
        valid_type = is_suffix_valid_for_item_type(affix["index"], flgs, False)
    if not valid_type:
        names = _available_affix_names(base, ilvl, kind)
        raise ItemGenError(
            "%s「%s」不适用于「%s」（物品类型：%s）；该底材在 ilvl=%d 可用的%s：%s"
            % (kind_cn, affix["name"], base["name"], base["itype_name"], ilvl,
               kind_cn, names),
            code="bad_affix",
            suggestions=["换用该底材可用的%s：%s" % (kind_cn, names)])
    if not (minlvl <= affix["min_level"] <= maxlvl):
        if affix["min_level"] < minlvl:
            high = affix["min_level"] * 2 + 1
            raise ItemGenError(
                "%s「%s」是 %d 级词缀，低于 ilvl=%d 允许的窗口 %d..%d；"
                "请把 ilvl 降到 %d（%d..%d 都可以）"
                % (kind_cn, affix["name"], affix["min_level"], ilvl, minlvl,
                   maxlvl, high, affix["min_level"], high),
                code="level_window",
                suggestions=["把 ilvl 降到 %d（%d..%d 都可以）"
                             % (high, affix["min_level"], high)])
        raise ItemGenError(
            "%s「%s」需要词缀等级 %d，ilvl=%d 只允许 %d..%d；"
            "请把 ilvl 提到 %d（或更高）"
            % (kind_cn, affix["name"], affix["min_level"], ilvl, minlvl, maxlvl,
               affix["min_level"]),
            code="level_window",
            suggestions=["把 ilvl 提到 %d（或更高）" % affix["min_level"]])
    if kind == "prefix" and (flgs & T.AFFIX_STAFF) and affix["power_name"] == "IPL_CHARGES":
        raise ItemGenError(
            "前缀「%s」是充能词缀（IPL_CHARGES），法杖的充能来自法术，游戏不会用它"
            % affix["name"],
            code="bad_affix",
            suggestions=["法杖请换一个非充能前缀，或不指定前缀"])
    if onlygood and not affix["ok"]:
        names = _available_affix_names(base, ilvl, kind)
        raise ItemGenError(
            "%s「%s」是“坏”词缀（PLOk=false），不能出现在 onlygood 物品上；"
            "该底材在 ilvl=%d 可用的%s：%s"
            % (kind_cn, affix["name"], ilvl, kind_cn, names),
            code="bad_affix",
            suggestions=["取消 onlygood，或换用：%s" % names])
    if kind == "prefix" and affix["index"] > 82:
        raise ItemGenError(
            "前缀「%s」是 Hellfire 专用（非 Hellfire 版本只允许 index <= 82）" % affix["name"],
            code="bad_affix",
            suggestions=["换一个普通前缀"])
    if kind == "suffix" and affix["index"] > 94:
        raise ItemGenError(
            "后缀「%s」是 Hellfire 专用（非 Hellfire 版本只允许 index <= 94）" % affix["name"],
            code="bad_affix",
            suggestions=["换一个普通后缀"])


_SPECIAL_MISC = (T.IMISC_STAFF, T.IMISC_RING, T.IMISC_AMULET)


def _fast_blevel(rng, ilvl, misc_id, onlygood, uper15=False):
    """GetItemBLevel() -> iblvl (-1 = no affix roll).

    Inlined (hot path of the seed search) but with the exact short-circuit
    order: the first ``GenerateRnd(100)`` always runs, the second one only when
    the first missed.  ``uper15`` (unique-monster drop) overrides the result
    with ``ilvl + 4`` exactly like the C++ code, after the same two draws.
    """
    if rng.rnd(100) <= 10:
        iblvl = ilvl
    elif rng.rnd(100) <= ilvl:
        iblvl = ilvl
    elif onlygood or misc_id in _SPECIAL_MISC:
        iblvl = ilvl
    else:
        iblvl = -1
    return ilvl + 4 if uper15 else iblvl


def _fast_magic_selection(base, ilvl, seed, hellfire=False, onlygood=False,
                          need_suffix=True, need_suffix_value=False, uper=0):
    """Cheaply predict the affix selection of a non-staff magical item.

    Returns ``(prefix_index, suffix_index, prefix_rolls, suffix_rolls)`` or None
    when the seed does not produce a magical item at all.  Only valid for
    non-staff bases; the caller must confirm with a full ``SetupAllItems`` pass.
    ``uper=15`` models a unique-monster drop (``CheckUnique`` at 15%, iblvl +4).
    """
    rng = Rng(seed)
    rng.rnd(base["max_ac"] - base["min_ac"] + 1)  # GetItemAttrs
    iblvl = _fast_blevel(rng, ilvl, base["misc_id"], onlygood, uper15=(uper == 15))
    if iblvl == -1:
        return None
    if rng.rnd(100) <= uper:  # CheckUnique: returns -1 when GenerateRnd(100) > uper
        # CheckUnique only consumes the extra DiscardRandomValues(1) when at
        # least one unique matches this base item; otherwise it returns -1 and
        # GetItemBonus still runs.
        has_unique = any(
            T.is_unique_available(u["index"])
            and u["base_item_id"] == base["item_id"]
            and iblvl >= u["min_level"]
            for u in T.UNIQUES)
        if has_unique:
            return None
    minlvl = min(_cdiv(iblvl, 2), 25)
    maxlvl = iblvl
    return _fast_selection(rng, base["affix_type"], minlvl, maxlvl, onlygood, hellfire,
                           need_suffix=need_suffix, need_suffix_value=need_suffix_value)


def _fast_staff_selection(base, ilvl, seed, hellfire=False, onlygood=False,
                          need_suffix=True, need_suffix_value=False, uper=0):
    """Predict a *stat-affix* staff (no random spell) selection.

    ``GetStaffSpell()`` first does ``FlipCoin(4)``: 25% of the seeds go to
    ``GetItemPower(lvl/2, lvl, AFFIX_STAFF)`` (a staff with ordinary stat
    affixes, no spell/charges), the other 75% roll a random spell.  This helper
    only returns a selection for the 25% stat-affix branch; None means "not a
    stat staff" (or not magical), so the caller can skip the seed.
    """
    rng = Rng(seed)
    rng.rnd(base["max_ac"] - base["min_ac"] + 1)  # GetItemAttrs
    iblvl = _fast_blevel(rng, ilvl, base["misc_id"], onlygood, uper15=(uper == 15))
    if iblvl == -1:
        return None
    if rng.rnd(100) <= uper:  # CheckUnique (uper == 0 for dungeon drops)
        has_unique = any(
            T.is_unique_available(u["index"])
            and u["base_item_id"] == base["item_id"]
            and iblvl >= u["min_level"]
            for u in T.UNIQUES)
        if has_unique:
            return None
    if not rng.flip(4):
        return None  # GetStaffSpell rolls a random spell instead (75%)
    # GetStaffSpell -> GetItemPower(_cdiv(iblvl, 2), iblvl, AFFIX_STAFF, onlygood)
    minlvl = _cdiv(iblvl, 2)
    maxlvl = iblvl
    return _fast_selection(rng, T.AFFIX_STAFF, minlvl, maxlvl, onlygood, hellfire,
                           need_suffix=need_suffix, need_suffix_value=need_suffix_value)


def _fast_affix_indices(base, ilvl, seed, hellfire=False):
    """Backwards-compatible helper: (prefix_index, suffix_index) for non-staff bases."""
    fast = _fast_magic_selection(base, ilvl, seed, hellfire)
    if fast is None:
        return None
    return fast[0], fast[1]


def _merge_deltas(a, b):
    out = dict(a)
    for key, value in b.items():
        out[key] = out.get(key, 0) + value
    return out


def _slot_value_ok(g, slot, affix, want, tolerance):
    """The item really carries every requested slot value (+-tolerance).

    ``want`` is whatever the caller passed as ``prefix_value``/``suffix_value``
    (int, ``"151/93"`` or a list); :func:`_normalize_value_target` turns it into
    one target per slot.  Slot 0 is the ``SaveItemPower()`` roll, slot 1 (only
    for TOHIT_DAMP-style powers) is the separate ``PLToHit`` roll.
    """
    power = affix["power_name"]
    fields = _VALUE_POWERS.get(power)
    if fields is None:
        return False
    slots = affix_value_slots(affix)
    wants = _normalize_value_target(want, affix, slot)
    if len(wants) != len(slots):
        return False
    delta = g.prefix_delta if slot == "prefix" else g.suffix_delta
    other = g.suffix_delta if slot == "prefix" else g.prefix_delta
    signed = g.prefix_value if slot == "prefix" else g.suffix_value
    for spec, target in zip(slots, wants):
        if target is None:
            continue
        if spec["key"] == "tohit":
            actual = int(delta.get("PLToHit", 0) or 0)
            if actual == 0 or abs(actual - target) > tolerance:
                return False
            # PLToHit may be shared with the other affix; then only the delta matters.
            if "PLToHit" not in other and int(g.f.get("PLToHit", 0) or 0) != actual:
                return False
            continue
        if signed is None or abs(signed - target) > tolerance:
            return False
        for key, _sign, shift in fields:
            expected = signed * (1 << shift)
            if delta.get(key, 0) != expected:
                return False
            # When the other affix also touches this field the record stores the
            # sum (e.g. Brutal + of slaying both add PLDam), so only compare the
            # absolute field value when the field belongs to this affix alone.
            if key not in other and g.f[key] != expected:
                return False
    return True


def _verify_values(g, want_prefix, prefix_value, want_suffix, suffix_value, tolerance):
    if prefix_value is not None and not _slot_value_ok(g, "prefix", want_prefix, prefix_value, tolerance):
        return False
    if suffix_value is not None and not _slot_value_ok(g, "suffix", want_suffix, suffix_value, tolerance):
        return False
    return True


def _format_value_failure(base, ilvl, slot, affix, want, tolerance, tried, closest):
    kind = "前缀" if slot == "prefix" else "后缀"
    label = affix["name"] if slot == "prefix" else "of " + affix["name"]
    if closest is None:
        detail = "该词缀在 %d 次尝试中从未被选中" % tried
    else:
        _slot_label, value, diff = closest
        detail = "%s最接近 %+d，差距 %d" % (
            "%s" % _slot_label if len(affix_value_slots(affix)) > 1 else "",
            value, diff)
    slot_rng = affix_value_range(affix)
    rng_lo, rng_hi = slot_rng
    return ItemGenError(
        "未找到 %s %s = %s（%s）；%r ilvl=%d 的可选范围是 %+d~%+d，已尝试 %d 个种子"
        "（容差 %d）" % (kind, label, _value_target_text(affix, want), detail,
                        base["name"], ilvl, rng_lo, rng_hi, tried, tolerance),
        code="seed_not_found",
        suggestions=[
            "提高 max_tries（当前 %d）" % tried,
            "放宽容差 value_tolerance（当前 %d）" % tolerance,
            "只指定一个数值，或换一个 seed 起点",
        ])


def _value_target_text(affix, want):
    """'+151/+93' style text for messages, e.g. '伤害 +151 / 命中 +93'."""
    if want is None:
        return "?"
    slots = affix_value_slots(affix)
    if len(slots) == 1:
        try:
            return "%+d" % int(want if not isinstance(want, (list, tuple)) else want[0])
        except (TypeError, ValueError):
            return str(want)
    if isinstance(want, (list, tuple)):
        parts = []
        for spec, item in zip(slots, want):
            if item is not None:
                parts.append("%s %+d" % (spec["label"], int(item)))
        return " / ".join(parts) or "?"
    return str(want)


def _check_value_target(affix, kind, value, tolerance):
    """Validate requested numeric affix value(s) before searching.

    ``value`` may be an int, ``"151/93"`` or a list (see
    :func:`_normalize_value_target`).  Every requested slot is range-checked
    against :func:`affix_value_slots`; the normalized list is returned so
    callers can reuse it.
    """
    if value is None or value == "":
        return []
    if affix is None:
        raise ItemGenError(
            "%s_value 需要同时指定 %s（要指定哪个词缀的数值）" % (kind, kind),
            code="bad_affix",
            suggestions=["同时指定 %s 和 %s_value，或去掉 %s_value" % (kind, kind, kind)])
    if not is_value_affix(affix):
        raise _value_affix_error(affix, kind)
    slots = affix_value_slots(affix)
    wants = _normalize_value_target(value, affix, kind)
    tol = max(0, int(tolerance))
    param = "前缀" if kind == "prefix" else "后缀"
    label = affix["name"] if kind == "prefix" else "of " + affix["name"]
    for spec, want in zip(slots, wants):
        if want is None:
            continue
        lo, hi = spec["range"]
        if want < lo - tol or want > hi + tol:
            nearest = lo if want < lo else hi
            diff = abs(want - nearest)
            what = ("「%s」" % spec["label"]) if len(slots) > 1 else ""
            raise ItemGenError(
                "未找到 %s %s %s= %+d（最接近 %+d，差距 %d）；该词缀的可选范围是 %+d~%+d"
                % (param, label, what, want, nearest, diff, lo, hi),
                code="value_out_of_range",
                suggestions=["把 %s_value 的「%s」改到 %+d~%+d 之间"
                             % (kind, spec["label"], lo, hi)])
    return wants


def _range_text(rng):
    """'+31~+40' for suggestions; '固定效果' when not numeric."""
    if rng is None:
        return "固定效果"
    return "%+d~%+d" % (rng[0], rng[1]) if rng[0] != rng[1] else "%+d" % rng[0]


def _search_seed(base, ilvl, want_prefix, want_suffix, start_seed, max_tries,
                 onlygood=False, hellfire=False, want_prefix_value=None,
                 want_suffix_value=None, value_tolerance=0,
                 allow_staff_spells=True, want_spell=None, want_charges=None,
                 require_spell=False, uper=0, display_ilvl=None):
    """Find a seed whose generated item carries exactly the requested affixes.

    When ``want_prefix_value``/``want_suffix_value`` are given, the roll of the
    matching affix must equal the target (+-``value_tolerance``) as well; the
    values are predicted in the fast selection pass (exact RNG consumption) and
    re-verified on the full ``SetupAllItems`` result.  Raises
    :class:`ItemGenError` with a "未找到 前缀 X = 值（最接近 ...）" message when the
    value search fails.

    ``want_spell``/``want_charges`` are the spell-staff targets
    (``GetStaffSpell()`` output).  They are only checked on the full
    ``SetupAllItems`` result, i.e. in the "cannot be predicted" branch that
    spell staves use anyway; ``want_charges`` alone matches any spell.
    ``require_spell`` only demands ``spell > 0`` and ``charges > 0`` (a "random
    spell" staff).
    """
    want_pre = want_prefix["index"] if want_prefix else None
    want_suf = want_suffix["index"] if want_suffix else None
    tolerance = max(0, int(value_tolerance))
    staff = base["itype"] == T.ITEM_TYPE["Staff"]
    stat_staff = staff and not allow_staff_spells
    want_value = want_prefix_value is not None or want_suffix_value is not None
    need_suffix = want_suf is not None
    need_suffix_value = want_suffix_value is not None
    pre_targets = (_normalize_value_target(want_prefix_value, want_prefix, "prefix")
                   if want_prefix_value is not None else [])
    suf_targets = (_normalize_value_target(want_suffix_value, want_suffix, "suffix")
                   if want_suffix_value is not None else [])
    closest = {}
    tried = 0
    seed = int(start_seed) & 0xFFFFFFFF

    def slot_values(rolls, affix):
        """Predicted displayed values of every slot from a fast-pass roll dict."""
        if rolls is None:
            return []
        out = []
        for spec in affix_value_slots(affix):
            if spec["key"] == "tohit":
                out.append(rolls.get("tohit"))
            else:
                out.append(_signed_roll(affix["power_name"], rolls.get("value")))
        return out

    def values_ok(rolls, affix, targets, slot):
        values = slot_values(rolls, affix)
        if not values:
            return False
        best = None
        for spec, target, value in zip(affix_value_slots(affix), targets, values):
            if target is None:
                continue
            if value is None:
                return False
            diff = abs(value - target)
            if best is None or diff < best[2]:
                best = (spec["label"], value, diff)
            if diff > tolerance:
                if best is not None and (
                        slot not in closest or best[2] < closest[slot][2]):
                    closest[slot] = best
                return False
        return True

    def spell_ok(g):
        if require_spell and not (g.f["spell"] > 0 and g.f["charges"] > 0):
            return False
        if want_spell is not None and g.f["spell"] != want_spell:
            return False
        if want_charges is not None and g.f["charges"] != want_charges:
            return False
        return True

    while tried < max_tries:
        if seed == 0:
            seed = 1
        tried += 1
        fast = None
        if not staff:
            fast = _fast_magic_selection(base, ilvl, seed, hellfire, onlygood,
                                         need_suffix, need_suffix_value, uper=uper)
        elif stat_staff:
            fast = _fast_staff_selection(base, ilvl, seed, hellfire, onlygood,
                                         need_suffix, need_suffix_value, uper=uper)
        if fast is not None:
            pre, suf, pre_rolls, suf_rolls = fast
            ok = True
            if want_pre is not None and pre != want_pre:
                ok = False
            if want_suf is not None and suf != want_suf:
                ok = False
            if ok and want_prefix_value is not None:
                ok = values_ok(pre_rolls, want_prefix, pre_targets, "prefix")
            if ok and want_suffix_value is not None:
                ok = values_ok(suf_rolls, want_suffix, suf_targets, "suffix")
            if ok:
                g = _setup_all_items(base, seed, ilvl, uper, onlygood, False, False, hellfire)
                if g.f["magical"] == ITEM_QUALITY_MAGIC \
                        and (want_pre is None or g.prefix_index == want_pre) \
                        and (want_suf is None or g.suffix_index == want_suf) \
                        and (not stat_staff or (g.f["spell"] == 0 and g.f["charges"] == 0)) \
                        and _display_name_consistent(g) \
                        and spell_ok(g) \
                        and _verify_values(g, want_prefix, want_prefix_value,
                                           want_suffix, want_suffix_value, tolerance):
                    return g
        elif staff and not stat_staff:
            # Spell staves (allow_staff_spells=True) cannot be predicted cheaply.
            g = _setup_all_items(base, seed, ilvl, uper, onlygood, False, False, hellfire)
            if g.f["magical"] == ITEM_QUALITY_MAGIC:
                if (want_pre is None or g.prefix_index == want_pre) and \
                        (want_suf is None or g.suffix_index == want_suf) and \
                        _display_name_consistent(g) and \
                        spell_ok(g) and \
                        _verify_values(g, want_prefix, want_prefix_value,
                                       want_suffix, want_suffix_value, tolerance):
                    return g
        seed = (seed + 1) & 0xFFFFFFFF
    if want_value:
        shown_ilvl = ilvl if display_ilvl is None else int(display_ilvl)
        if want_prefix_value is not None:
            raise _format_value_failure(base, shown_ilvl, "prefix", want_prefix,
                                        want_prefix_value, tolerance, tried,
                                        closest.get("prefix"))
        raise _format_value_failure(base, shown_ilvl, "suffix", want_suffix,
                                    want_suffix_value, tolerance, tried,
                                    closest.get("suffix"))
    return None


def generate(base_idx, ilvl=1, rarity="normal", seed=None, prefix=None, suffix=None,
             unique_id=None, max_tries=200000, strict=True, identified=True,
             stat_flag=True, position=(0, 0), onlygood=False, hellfire=False,
             unique=None, prefix_value=None, suffix_value=None, value_tolerance=0,
             allow_staff_spells=False, allow_non_equipment=False,
             max_ac=False, full_durability=False, staff_spell=None,
             staff_charges=None, require_staff_spell=False,
             droppable=False):
    """Generate one legal Diablo 1 item record.

    Parameters
    ----------
    base_idx : int | str
        Runtime ``_item_indexes`` value (``IDI_*``), or an item name
        (``"Long Sword"``).  A saved-file index is accepted as a fallback when
        the integer does not name an available runtime item.  Class starting
        items (``IDI_WARRIOR`` / ``IDI_ROGUE`` / ``IDI_SORCERER`` /
        ``IDI_SORCERER_DIABLO``) are **rejected**: writing one into a save
        crashes DevilutionX 1.5.5.
    ilvl : int
        Item level (the affix window's upper bound).  Stored in the low 6 bits
        of ``iCreateInfo`` (0..63); ``GetItemAttrs`` receives ``ilvl // 2``,
        exactly like ``SetupAllItems``.  With ``droppable=True`` the supported
        range is 0..34 and 31..34 are written through the unique-monster route
        (record level ``ilvl - 4`` plus ``CF_UPER15|CF_ONLYGOOD``), which gives
        the same affix window (``GetItemBLevel`` adds 4).
    rarity : 'normal' | 'magic' | 'unique'
    seed : int | None
        ``None`` picks a random seed.  For ``magic`` with ``prefix``/``suffix``
        the seed is the *start* of the search.
    prefix, suffix : str | int | dict | None
        Requested affix (name, table index or affix dict).  Implemented by
        **seed search**: the generator tries seeds until the game's own affix
        selection lands on the requested affix, then emits the full record.
        This guarantees the stored name/stats are exactly what the game will
        recompute from ``iSeed``+``iCreateInfo``.
    prefix_value, suffix_value : int | str | list | None
        Target **displayed** value of the matching affix (e.g. ``+15`` strength,
        ``+20`` fire resistance, ``+81`` damage%, ``+15`` life).  The value is
        the game's own ``param1..param2`` roll (never the affix table's
        ``min_val/max_val``, which drives CalcItemValue); LIFE/MANA count in
        points (the record stores ``r << 6`` in PLHP/PLMana).  Cursed affixes
        use negative targets.  Only affixes listed in :data:`_VALUE_POWERS`
        accept a value; for charges/spells/attack-speed/life-steal/... a
        numeric target raises :class:`ItemGenError`.

        Twelve TOHIT_DAMP-style affixes (King's, Knight's, Master's, ... and
        Clumsy/Dull/Doppelganger's) roll **two** numbers; use a list with one
        entry per slot (see :func:`affix_value_slots`), e.g.
        ``prefix_value=[151, 93]`` for King's = 151% damage + 93 to-hit, or the
        string ``"151/93"``.  A single int still targets slot 0 (damage) and
        leaves the to-hit roll free; ``None`` leaves a slot free.
    value_tolerance : int
        Accept ``|rolled - target| <= value_tolerance`` (default 0 = exact).
    allow_staff_spells : bool
        Default False: a magical staff is generated as a **stat-affix staff**
        (e.g. "Long Staff of haste"), never as a random spell staff.  Spell
        staves are what the game itself rolls 75% of the time, but they carry
        an arbitrary spell/charges that the editor cannot verify, so they are
        opt-in.  For staves ``ilvl > 51`` the game's own name replay disagrees
        with the generation path, so stat staves are refused there.
    allow_non_equipment : bool
        Default False: gold/potion/scroll/book/quest rows (``ILOC_UNEQUIPABLE``)
        are refused with a Chinese error.  Pass True to generate them anyway
        (books still roll a spell through ``GetBookSpell``).
    unique_id : int | str | None
        Unique item id or name (only for ``rarity='unique'``).  ``unique=`` is
        accepted as an alias (see PROJECT_BRIEF.md).  When ``base_idx`` is None
        the base item is derived from the unique table.
    max_tries : int
        Seed search budget (default 200000).  Exact affix + value searches need
        roughly 1/(affix chance * value range) seeds; requesting two values at
        once multiplies the cost.
    strict : bool
        Raise :class:`ItemGenError` on failure; when False, return ``None``.
    identified, stat_flag : bool
        Values stored in the record.  The game displays affix names only for
        identified items; ``_iStatFlag`` is the "requirements met" cache and is
        recomputed by the game when the item is picked up.
    max_ac : bool
        Force the recorded ``AC`` to the base table's ``max_ac`` (only for bases
        with ``max_ac > 0``).  Written straight into the 368-byte record, so
        single-player shows it as-is, but the record no longer replays from its
        seed: validate it with ``allow_ac_override=True``.  Refused
        (``code="base_stats_conflict"``) when the chosen affix or unique power
        sets AC outright (``IPL_SETAC``); additive AC effects still stack.
    full_durability : bool
        Force ``durability = maxDur`` (skipped for ``maxDur == 0`` and when the
        maximum is ``>= DUR_INDESTRUCTIBLE`` (255): 255 is the "indestructible"
        sentinel and ``IPL_DUR`` suffixes can push ``maxDur`` past it, so such
        items keep their natural durability.  ``validate()`` already ignores
        durability, so no extra flag is needed there.
    staff_spell : int | str | dict | None
        Spell for a staff (``None`` = let the game roll one).  Accepts the spell
        id, the English name or the Chinese name — see :func:`staff_spells`.
        Normal staves accept it directly (that is the game's own 75% path);
        magical spell staves need ``allow_staff_spells=True`` and cannot carry a
        suffix (``code="staff_spell_suffix"``).  Non-staff bases raise
        ``code="bad_staff_spell"``.  A spell the item level cannot reach is
        refused before the seed search (``code="level_window"``, message names
        the required ilvl).
    staff_charges : int | None
        Exact charges target for the staff spell, inside the spell's
        ``[staff_min, staff_max]`` (a random spell is rolled until it matches
        when no ``staff_spell`` was given).  Out of range raises
        ``code="bad_staff_charges"``.
    require_staff_spell : bool
        ``True`` = the item must really carry a spell (``spell > 0`` and
        ``charges > 0``), i.e. a "random spell staff" instead of a stat-affix
        staff.  Implies ``allow_staff_spells=True``; the spell/charges
        constrained requests always run the full ``max_tries`` budget instead of
        the cheap 10k loop.
    droppable : bool
        Default ``False`` (historical behaviour: any ilvl 0..63 is accepted).
        ``True`` guarantees the record can be dropped on the floor: an
        ``ilvl > 30`` request is refused with ``code="drop_ilvl"`` because
        ``IsDungeonItemValid()`` rejects it and the game shows "无效的数据包"
        while the item disappears.  ``ilvl <= 30`` is generated unchanged.

    Returns
    -------
    GenItem
    """
    if unique_id is None and unique is not None:
        unique_id = unique
    try:
        return _generate(base_idx, ilvl, rarity, seed, prefix, suffix, unique_id,
                         max_tries, identified, stat_flag, position, onlygood, hellfire,
                         prefix_value=prefix_value, suffix_value=suffix_value,
                         value_tolerance=value_tolerance,
                         allow_staff_spells=allow_staff_spells,
                         allow_non_equipment=allow_non_equipment,
                         max_ac=max_ac, full_durability=full_durability,
                         staff_spell=staff_spell, staff_charges=staff_charges,
                         require_staff_spell=require_staff_spell,
                         droppable=droppable)
    except ItemGenError:
        if strict:
            raise
        return None


#: reason codes returned by :func:`check_combination` (and by
#: ``ItemGenError.code`` when ``generate()`` fails).
COMBINATION_CODES = (
    "ok",                  # legal (and, when searched, found within budget)
    "bad_base",            # unknown / starter / unique-only / non-equipment base
    "bad_affix",           # affix does not exist / does not fit this item type
    "level_window",        # affix min_level outside the ilvl window
    "goe_conflict",        # good prefix + evil suffix (or vice versa)
    "fixed_affix_value",   # a numeric value was given for a fixed effect
    "value_out_of_range",  # target value outside param1..param2 (+tolerance)
    "seed_not_found",      # combination legal, but no seed within the budget
    "staff_ilvl",          # stat-affix staff above ilvl 51 (name-replay quirk)
    "bad_rarity",          # rarity is not normal/magic/unique
    "bad_ilvl",            # ilvl outside 0..63
    "bad_value",           # non-integer prefix_value/suffix_value
    "base_stats_conflict",  # max_ac + IPL_SETAC (the affix sets AC itself)
    "staff_spell_suffix",  # spell staff + suffix (the game never does that)
    "bad_staff_spell",     # unknown/unusable spell, or staff options on a non-staff
    "bad_staff_charges",   # charges outside the spell's staff_min..staff_max
    "drop_ilvl",           # droppable=True but ilvl > MAX_DROP_ILVL (34)
    "error",               # unexpected internal problem (message has details)
)


def _drop_ilvl_error(ilvl):
    """The contract error for "droppable=True but ilvl > 34"."""
    return ItemGenError(
        "ilvl %d 的物品丢地上会被游戏判定为非法数据包并消失；"
        "可丢地上的最高 ilvl 是 %d（31~34 走暗金怪掉落路线），"
        "请把 ilvl 降到 %d 或以下，或取消‘保证可丢地上’" % (ilvl, MAX_DROP_ILVL, MAX_DROP_ILVL),
        code="drop_ilvl",
        suggestions=["把 ilvl 降到 %d（或更低）" % MAX_DROP_ILVL,
                     "ilvl 31~34 会自动改用暗金怪路线（记录等级 -4 + CF_UPER15）",
                     "ilvl>%d 的物品只能放储物箱" % MAX_DROP_ILVL])


def _affix_name_for_display(kind, affix):
    if not affix:
        return ""
    name = affix.get("name") or ""
    if kind == "suffix" and not name.lower().startswith("of "):
        return "of " + name
    return name


def _level_window_suggestions(ilvl, want_prefix, want_suffix):
    """Actionable ilvl hints for both affixes of a level_window failure."""
    out = []
    minlvl, maxlvl = _affix_window(ilvl)
    for kind, affix in (("prefix", want_prefix), ("suffix", want_suffix)):
        if not affix:
            continue
        kind_cn = "前缀" if kind == "prefix" else "后缀"
        level = int(affix["min_level"])
        if level > maxlvl:
            out.append("%s「%s」需要词缀等级 %d：把 ilvl 提到 %d（或更高）"
                       % (kind_cn, affix["name"], level, level))
        elif level < minlvl:
            high = level * 2 + 1
            out.append("%s「%s」是 %d 级词缀：把 ilvl 降到 %d（%d..%d 都可以）"
                       % (kind_cn, affix["name"], level, high, level, high))
    return out


def check_combination(base_idx, ilvl, rarity="magic", prefix=None, suffix=None,
                      prefix_value=None, suffix_value=None, onlygood=False,
                      unique_id=None, seed=1, max_tries=None, value_tolerance=0,
                      allow_staff_spells=False, allow_non_equipment=False,
                      max_ac=False, full_durability=False, staff_spell=None,
                      staff_charges=None, require_staff_spell=False,
                      droppable=False):
    """Pre-flight check of one item request, for the GUI's error dialog.

    Returns a plain dict (never raises for user input)::

        {"ok": bool, "code": str, "message": str,
         "suggestions": [str, ...], "prefix": dict | None, "suffix": dict | None}

    ``code`` is one of :data:`COMBINATION_CODES`.  The rules are the *same*
    functions ``generate()`` uses (``_reject_base`` / ``_resolve_affix`` /
    ``_check_value_target`` / ``_check_affix_reachable`` / ``_search_seed`` /
    ``_affix_window``), so a pre-check can never disagree with generation.

    ``max_tries=None`` (default) validates the rules only -- no seed is
    searched, so the call is cheap enough for a live GUI hint.  Pass an int to
    also run the real seed search within that budget; a legal combination that
    the budget cannot satisfy comes back as ``seed_not_found`` (with the closest
    value in ``message`` when a numeric target was requested).  ``seed`` is the
    start of that search (default 1, so pre-checks are reproducible).

    ``prefix`` / ``suffix`` in the result are the **resolved** table rows, so
    the GUI can show "you picked the level-31..40 Crimson band" etc.

    ``max_ac`` / ``full_durability`` / ``staff_spell`` / ``staff_charges`` /
    ``require_staff_spell`` mirror the :func:`generate` keyword arguments: the
    same rules are checked here (``base_stats_conflict`` / ``bad_staff_spell`` /
    ``bad_staff_charges`` / ``staff_spell_suffix`` / ``level_window`` for a spell
    the item level cannot reach), but no seed is ever searched for them.

    ``droppable=True`` mirrors :func:`generate`: an ``ilvl > 30`` request fails
    with ``code="drop_ilvl"`` (the game's drop validation would reject it).
    """
    result = {"ok": False, "code": "ok", "message": "",
              "suggestions": [], "prefix": None, "suffix": None}

    def fail(code, message, suggestions=None):
        result["ok"] = False
        result["code"] = code
        result["message"] = message
        unique = []
        for item in suggestions or ():
            if item and item not in unique:
                unique.append(item)
        result["suggestions"] = unique
        return result

    def passed(message="规则检查通过"):
        result["ok"] = True
        result["code"] = "ok"
        result["message"] = message
        result["suggestions"] = []
        return result

    want_spell = None
    want_charges = None

    def staff_text():
        parts = []
        if want_spell is not None:
            parts.append("法术 %s" % _staff_spell_name(want_spell))
        if want_charges is not None:
            parts.append("%d 充能" % want_charges)
        if require_staff_spell:
            parts.append("随机法术法杖（会要求 seed 真正带法术，生成时跑完整 max_tries）")
        return "，".join(parts)

    try:
        rarity = str(rarity).lower()
        if rarity in ("plain", "ordinary"):
            rarity = "normal"
        if rarity not in ("normal", "magic", "unique"):
            return fail("bad_rarity",
                        "稀有度必须是 normal（普通）/ magic（魔法）/ unique（暗金），收到 %r"
                        % (rarity,),
                        ["把稀有度改成 normal / magic / unique"])
        # Asking for a spell staff implies allowing spell staves (see _generate).
        if require_staff_spell:
            allow_staff_spells = True

        # ---- base item (same resolution order as _generate) --------------
        if base_idx is None:
            if rarity != "unique" or unique_id is None:
                return fail("bad_base", "没有指定底材（base_idx）", ["先在底材列表里选一件"])
            uniq0 = (T.unique_by_id(unique_id) if isinstance(unique_id, int)
                     else T.unique_by_name(unique_id))
            if uniq0 is None:
                return fail("bad_base", "找不到暗金 %r" % (unique_id,),
                            ["换一个暗金名称或编号"])
            base = T.base_by_idx(_unique_base_index(uniq0))
            if base is None:
                return fail("bad_base", "暗金「%s」没有可用底材" % uniq0["name"], [])
        else:
            base = T.resolve_base(base_idx, require_available=True)
            if base is None:
                alt = _lookup_any_base(base_idx)
                if alt is not None:
                    _reject_base(alt, rarity, allow_non_equipment)  # raises bad_base
                return fail("bad_base", "找不到底材 %r" % (base_idx,),
                            ["从底材列表里选一个可装备底材"])
        _reject_base(base, rarity, allow_non_equipment)

        ilvl = int(ilvl)
        if ilvl < 0 or ilvl > MAX_ITEM_LEVEL:
            return fail("bad_ilvl",
                        "ilvl 必须是 0..%d（存档里是 6 位字段），收到 %d"
                        % (MAX_ITEM_LEVEL, ilvl),
                        ["把 ilvl 改成 0..%d 之间" % MAX_ITEM_LEVEL])
        if droppable and not droppable_level_ok(ilvl):
            exc = _drop_ilvl_error(ilvl)
            return fail(exc.code, str(exc), exc.suggestions)
        plan = drop_plan(ilvl) if droppable else None
        record_ilvl = plan["record_ilvl"] if plan else ilvl
        uper = plan["uper"] if plan else 0
        affix_ilvl = plan["affix_ilvl"] if plan else ilvl
        if plan and plan["onlygood"]:
            onlygood = True

        is_staff = base["itype"] == T.ITEM_TYPE["Staff"]
        if rarity == "magic" and is_staff and not allow_staff_spells and ilvl > 51:
            return fail("staff_ilvl",
                        "法杖在 ilvl > 51 时游戏自身的名字重放与生成路径不一致（1.5.5 已知怪癖），"
                        "不能生成属性词缀法杖",
                        ["把 ilvl 降到 51（或更低）",
                         "或传 allow_staff_spells=True 生成法术法杖"])

        # ---- staff spell / charges (checked before any early return) ------
        if staff_spell is not None or staff_charges is not None or require_staff_spell:
            if not is_staff:
                return fail("bad_staff_spell",
                            "「%s」不是法杖（%s 类物品），不能指定法术/充能；只有 Staff 底材"
                            "会走 GetStaffSpell()" % (base["name"], base["itype_name"]),
                            ["去掉 staff_spell/staff_charges/require_staff_spell",
                             "或换一个法杖底材（Short Staff / Long Staff / War Staff ...）"])
            try:
                spell_row = (_resolve_staff_spell(staff_spell, False)
                             if staff_spell is not None else None)
                if spell_row is not None:
                    _check_staff_spell_level(spell_row, ilvl)
                want_spell = spell_row["id"] if spell_row is not None else None
                want_charges = _check_staff_charges(spell_row, staff_charges, False)
            except ItemGenError as exc:
                return fail(exc.code or "bad_staff_spell", str(exc), exc.suggestions)
            if rarity == "unique":
                return fail("bad_staff_spell",
                            "暗金法杖的属性来自暗金表，不会走 GetStaffSpell()，"
                            "不能指定法术/充能",
                            ["去掉 staff_spell/staff_charges/require_staff_spell",
                             "或改用 rarity='normal'/'magic' 的法杖"])

        # ---- affixes ------------------------------------------------------
        try:
            want_prefix = _resolve_affix(prefix, "prefix", base, affix_ilvl,
                                         _first_value_target(prefix_value))
        except ItemGenError:
            names = _available_affix_names(base, affix_ilvl, "prefix")
            return fail("bad_affix",
                        "找不到前缀「%s」；该底材在 ilvl=%d 可用的前缀：%s"
                        % (prefix, ilvl, names),
                        ["换一个可用前缀：%s" % names])
        try:
            want_suffix = _resolve_affix(suffix, "suffix", base, affix_ilvl,
                                         _first_value_target(suffix_value))
        except ItemGenError:
            names = _available_affix_names(base, affix_ilvl, "suffix")
            return fail("bad_affix",
                        "找不到后缀「%s」；该底材在 ilvl=%d 可用的后缀：%s"
                        % (suffix, ilvl, names),
                        ["换一个可用后缀：%s" % names])
        result["prefix"] = want_prefix
        result["suffix"] = want_suffix

        # ---- staff spell rules that depend on the affixes ------------------
        if want_spell is not None or want_charges is not None or require_staff_spell:
            if rarity == "magic":
                if not allow_staff_spells:
                    return fail("bad_staff_spell",
                                "魔法法术法杖需要 allow_staff_spells=True（默认只生成属性"
                                "词缀法杖；法术/充能来自 GetStaffSpell()）",
                                ["传 allow_staff_spells=True 生成游戏原生的法术法杖",
                                 "或去掉 staff_spell/staff_charges/require_staff_spell"])
                if want_suffix is not None:
                    return fail("staff_spell_suffix",
                                "法术法杖没有后缀：GetStaffSpell() → GetStaffPower() 只会给"
                                "前缀，游戏不可能生成「%s」+ 后缀「%s」的法杖"
                                % (base["name"], want_suffix["name"]),
                                ["法术法杖没有后缀，请去掉后缀"])

        # ---- 满值 conflicts (max_ac vs IPL_SETAC) -------------------------
        if max_ac:
            source = _setac_source(want_prefix, want_suffix)
            if source:
                exc = _base_stats_conflict_error(source)
                return fail(exc.code, str(exc), exc.suggestions)

        # ---- numeric values / rarity rules (same order as _generate) ------
        if rarity != "magic":
            if prefix_value is not None or suffix_value is not None:
                return fail("bad_affix",
                            "prefix_value/suffix_value 只适用于魔法物品（rarity='magic'）",
                            ["去掉数值，或把稀有度改成“魔法”"])
        else:
            if prefix_value is not None and want_prefix is None:
                return fail("bad_affix", "prefix_value 需要同时指定 prefix",
                            ["同时选择前缀并填写数值，或去掉前缀数值"])
            if suffix_value is not None and want_suffix is None:
                return fail("bad_affix", "suffix_value 需要同时指定 suffix",
                            ["同时选择后缀并填写数值，或去掉后缀数值"])
            _check_value_target(want_prefix, "prefix", prefix_value, value_tolerance)
            _check_value_target(want_suffix, "suffix", suffix_value, value_tolerance)

        if rarity == "magic" and base["affix_type"] == 0:
            return fail("bad_affix",
                        "「%s」是 %s 类物品，游戏不会给它投随机词缀"
                        % (base["name"], base["itype_name"]),
                        ["换一个可装备底材"])

        if rarity == "normal":
            if want_prefix or want_suffix:
                return fail("bad_affix", "普通物品（normal）不能带词缀",
                            ["把稀有度改成“魔法”，或去掉前缀/后缀"])
            staff_part = staff_text()
            return passed("规则检查通过：普通「%s」ilvl=%d 可以生成%s"
                          % (base["name"], ilvl,
                             ("（%s）" % staff_part) if staff_part else ""))

        if rarity == "unique":
            if want_prefix or want_suffix:
                return fail("bad_affix", "暗金物品的属性来自暗金表，不能指定前缀/后缀",
                            ["去掉前缀/后缀，改用暗金编号生成"])
            uniq = None
            if unique_id is not None:
                uniq = (T.unique_by_id(unique_id) if isinstance(unique_id, int)
                        else T.unique_by_name(unique_id))
                if uniq is None:
                    return fail("bad_base", "找不到暗金 %r" % (unique_id,),
                                ["换一个暗金名称或编号"])
                ub = T.base_by_idx(_unique_base_index(uniq))
                if ub is None or ub["idx"] != base["idx"]:
                    return fail("bad_base",
                                "暗金「%s」的底材是「%s」，不是「%s」"
                                % (uniq["name"], ub["name"] if ub else "?", base["name"]),
                                ["把底材改成「%s」" % (ub["name"] if ub else "?")])
                if uniq["min_level"] > ilvl:
                    return fail("level_window",
                                "暗金「%s」需要物品等级 %d，ilvl=%d 不够；请把 ilvl 提到 %d"
                                % (uniq["name"], uniq["min_level"], ilvl, uniq["min_level"]),
                                ["把 ilvl 提到 %d（或更高）" % uniq["min_level"]])
            else:
                # same pick as _generate: first available unique that fits
                candidates = [u for u in T.UNIQUES
                              if u["base_item_id"] == base["item_id"]
                              and T.is_unique_available(u["index"])
                              and u["min_level"] <= ilvl]
                uniq = candidates[0] if candidates else None
            if max_ac and uniq is not None:
                source = _setac_source(unique=uniq)
                if source:
                    exc = _base_stats_conflict_error(source)
                    return fail(exc.code, str(exc), exc.suggestions)
            return passed("规则检查通过：暗金「%s」ilvl=%d 可以生成" % (base["name"], ilvl))

        # ---- magic: reachability (item type + level window + onlygood) ----
        try:
            if want_prefix is not None:
                _check_affix_reachable(base, affix_ilvl, want_prefix, "prefix", onlygood)
        except ItemGenError as exc:
            suggestions = (list(_level_window_suggestions(affix_ilvl, want_prefix, want_suffix))
                           if exc.code == "level_window" else list(exc.suggestions))
            return fail(exc.code or "bad_affix", str(exc), suggestions)
        try:
            if want_suffix is not None:
                _check_affix_reachable(base, affix_ilvl, want_suffix, "suffix", onlygood)
        except ItemGenError as exc:
            suggestions = (list(_level_window_suggestions(affix_ilvl, want_prefix, want_suffix))
                           if exc.code == "level_window" else list(exc.suggestions))
            return fail(exc.code or "bad_affix", str(exc), suggestions)

        # ---- good/evil conflict ------------------------------------------
        if _goe_conflict(want_prefix, want_suffix):
            exc = _goe_conflict_error(base, affix_ilvl, want_prefix, want_suffix)
            return fail(exc.code, str(exc), exc.suggestions)

        # ---- optional real seed search ------------------------------------
        if max_tries is None:
            staff_part = staff_text()
            return passed("规则检查通过：未搜索种子（传 max_tries 可顺便验证能否生成）"
                          + (("；%s" % staff_part) if staff_part else ""))
        if want_prefix is None and want_suffix is None \
                and want_spell is None and want_charges is None \
                and not require_staff_spell:
            return passed("规则检查通过：未指定词缀，任意魔法种子都可以")

        try:
            found = _search_seed(base, record_ilvl, want_prefix, want_suffix, int(seed),
                                 int(max_tries), onlygood, False,
                                 want_prefix_value=prefix_value,
                                 want_suffix_value=suffix_value,
                                 value_tolerance=value_tolerance,
                                 allow_staff_spells=allow_staff_spells,
                                 want_spell=want_spell, want_charges=want_charges,
                                 require_spell=require_staff_spell, uper=uper,
                     display_ilvl=ilvl)
        except ItemGenError as exc:
            return fail(exc.code or "seed_not_found", str(exc), exc.suggestions)
        if found is None:
            names = []
            if want_prefix:
                names.append(want_prefix["name"])
            if want_suffix:
                names.append(_affix_name_for_display("suffix", want_suffix))
            if want_spell is not None:
                names.append("法术 %s" % _staff_spell_name(want_spell))
            if want_charges is not None:
                names.append("%d 充能" % want_charges)
            if require_staff_spell:
                names.append("随机法术（spell/charges > 0）")
            return fail(
                "seed_not_found",
                "组合本身合法，但在 %d 个种子的预算内没找到「%s」+ %s（ilvl=%d）；"
                "该组合没有数值目标，所以没有“最接近值”可报告"
                % (max_tries, base["name"], " + ".join(names) or "(未指定词缀)", ilvl),
                ["提高 max_tries（当前 %d）" % max_tries,
                 "换一个 seed 起点",
                 "只指定前缀或后缀其中一个"])
        return passed("组合合法，预算内找到：%s" % found.f["iName"])
    except ItemGenError as exc:
        return fail(exc.code or "error", str(exc), exc.suggestions)
    except Exception as exc:  # noqa: BLE001 - the GUI must always get a dict
        return fail("error", "预检时出现意外问题：%s: %s" % (type(exc).__name__, exc), [])



def _reject_base(base, rarity="normal", allow_non_equipment=False):
    """Refuse base rows the game must not use for a normal/magic/unique item."""
    if base.get("starter"):
        item_id = base.get("id") or base["name"]
        alternative = _droppable_alternative(base)
        raise ItemGenError(
            "初始装备（%s）不能作为随机底材生成：%r（saved idx=%s, runtime idx=%s）是职业"
            "初始物品，写入存档会让游戏崩溃（已验证 IDI_SORCERER_DIABLO → 0xC0000005）；"
            "请改用普通底材（%s）"
            % (item_id, base["name"], base.get("saved_idx"), base.get("idx"),
               alternative or "无同名普通底材"),
            code="bad_base",
            suggestions=["换用普通底材：%s" % alternative] if alternative else [])
    if not base.get("available"):
        raise ItemGenError(
            "%r 在非 Hellfire 版本中不可用（quest/Hellfire-only 底材）" % base["name"],
            code="bad_base",
            suggestions=["换一个普通底材"])
    if base.get("unique_only") and rarity != "unique":
        raise ItemGenError(
            "「%s」是 unique-only 底材（IMISC_UNIQUE）：游戏只会通过 SpawnUnique 创建它，"
            "不能作为普通/魔法物品；请改用普通底材 + unique_id" % base["name"],
            code="bad_base",
            suggestions=["改用普通底材 + unique_id（例如用暗金图鉴生成该暗金）"])
    if not base.get("equipment") and not allow_non_equipment:
        raise ItemGenError(
            "「%s」不是可装备底材（%s / %s：金币、药水、卷轴、书或任务物品），v2 生成器默认"
            "只生成可装备物品；如确实需要请传 allow_non_equipment=True"
            % (base["name"], base.get("itype_name"), base.get("loc_name")),
            code="bad_base",
            suggestions=["换一个可装备底材（武器/防具/戒指/项链）"])


def _droppable_alternative(base):
    """Name of the droppable/canonical row with the same name (for error messages)."""
    for rec in T.base_items(include_unavailable=True, include_starter=True,
                            include_unique_only=True):
        if rec["name"] == base["name"] and rec["generatable"] and rec["idx"] != base["idx"]:
            return "%s (runtime idx=%s)" % (rec["name"], rec["idx"])
    if base.get("itype_name") == "Staff":
        # the starter staves have unique names ("Short Staff of Charged Bolt"),
        # so point at the ordinary staff bases instead
        return "Short Staff (runtime idx=151) / Long Staff (runtime idx=152)"
    return None


def _lookup_any_base(identifier):
    """Resolve a base identifier even if it is starter/unique-only/unavailable."""
    if isinstance(identifier, int):
        return T.base_by_idx(identifier) or T.base_by_saved_idx(identifier)
    s = str(identifier).strip()
    if s.upper().startswith("IDI_"):
        val = T.ITEM_INDEXES.get(s.upper())
        if val is not None:
            return T.base_by_idx(val)
    return (T.base_by_name(s, include_starter=True, include_unique_only=True,
                           include_unavailable=True, include_non_equipment=True)
            or T.base_by_sname(s, include_starter=True, include_unique_only=True,
                               include_unavailable=True, include_non_equipment=True))


def _generate(base_idx, ilvl, rarity, seed, prefix, suffix, unique_id,
              max_tries, identified, stat_flag, position, onlygood, hellfire,
              prefix_value=None, suffix_value=None, value_tolerance=0,
              allow_staff_spells=False, allow_non_equipment=False,
              max_ac=False, full_durability=False, staff_spell=None,
              staff_charges=None, require_staff_spell=False, droppable=False):
    # Asking for a spell staff implies allowing spell staves (they are the only
    # way GetStaffSpell() can produce spell > 0 on a magical staff).
    if require_staff_spell and not allow_staff_spells:
        allow_staff_spells = True
    rarity = str(rarity).lower()
    if rarity in ("plain", "ordinary"):
        rarity = "normal"
    if rarity not in ("normal", "magic", "unique"):
        raise ItemGenError("rarity must be 'normal', 'magic' or 'unique', got %r" % (rarity,),
                           code="bad_rarity")
    if base_idx is None:
        if rarity != "unique" or unique_id is None:
            raise ItemGenError("base_idx is required (except for rarity='unique' with unique_id)",
                               code="bad_base")
        uniq0 = T.unique_by_id(unique_id) if isinstance(unique_id, int) else T.unique_by_name(unique_id)
        if uniq0 is None:
            raise ItemGenError("unknown unique item %r" % (unique_id,), code="bad_base")
        base = T.base_by_idx(_unique_base_index(uniq0))
        if base is None:
            raise ItemGenError("unique %r has no base item" % (uniq0["name"],), code="bad_base")
    else:
        base = T.resolve_base(base_idx, require_available=True)
        if base is None:
            alt = _lookup_any_base(base_idx)
            if alt is not None:
                _reject_base(alt, rarity, allow_non_equipment)  # raises with the reason
            raise ItemGenError("找不到底材 %r（或该底材在非 Hellfire 版本不可用）" % (base_idx,),
                               code="bad_base",
                               suggestions=["从底材列表里选一个可装备底材"])
    _reject_base(base, rarity, allow_non_equipment)
    if not base["name"]:
        raise ItemGenError("base item %r has no name (invalid table row)" % (base_idx,),
                           code="bad_base")
    ilvl = int(ilvl)
    if ilvl < 0 or ilvl > MAX_ITEM_LEVEL:
        raise ItemGenError("ilvl must be 0..%d (iCreateInfo level field is 6 bits), got %d"
                           % (MAX_ITEM_LEVEL, ilvl),
                           code="bad_ilvl",
                           suggestions=["把 ilvl 改成 0..%d 之间" % MAX_ITEM_LEVEL])
    if droppable and not droppable_level_ok(ilvl):
        raise _drop_ilvl_error(ilvl)
    plan = drop_plan(ilvl) if droppable else None
    record_ilvl = plan["record_ilvl"] if plan else ilvl
    uper = plan["uper"] if plan else 0
    affix_ilvl = plan["affix_ilvl"] if plan else ilvl
    if plan and plan["onlygood"]:
        onlygood = True

    is_staff = base["itype"] == T.ITEM_TYPE["Staff"]
    if rarity == "magic" and is_staff and not allow_staff_spells and ilvl > 51:
        raise ItemGenError(
            "法杖在 ilvl > 51 时游戏自身的名字重放与生成路径不一致（1.5.5 已知怪癖），"
            "不能生成属性词缀法杖：请把 ilvl 降到 51 或以下，或传 allow_staff_spells=True "
            "生成游戏原生的法术法杖",
            code="staff_ilvl",
            suggestions=["把 ilvl 降到 51（或更低）",
                         "或传 allow_staff_spells=True 生成法术法杖"])

    want_prefix = _resolve_affix(prefix, "prefix", base, affix_ilvl,
                                 _first_value_target(prefix_value))
    want_suffix = _resolve_affix(suffix, "suffix", base, affix_ilvl,
                                 _first_value_target(suffix_value))

    # ---- staff spell / charges (GetStaffSpell path) ----------------------
    want_spell = None
    want_charges = None
    if staff_spell is not None or staff_charges is not None or require_staff_spell:
        if not is_staff:
            raise ItemGenError(
                "「%s」不是法杖（%s 类物品），不能指定法术/充能：只有 Staff 底材会走 "
                "GetStaffSpell()" % (base["name"], base["itype_name"]),
                code="bad_staff_spell",
                suggestions=["去掉 staff_spell/staff_charges/require_staff_spell",
                             "或换一个法杖底材（Short Staff / Long Staff / War Staff ...）"])
        if staff_spell is not None:
            spell_row = _resolve_staff_spell(staff_spell, hellfire)
            _check_staff_spell_level(spell_row, ilvl)
            want_spell = spell_row["id"]
        else:
            spell_row = None
        want_charges = _check_staff_charges(spell_row, staff_charges, hellfire)
        if rarity == "magic":
            if not allow_staff_spells:
                raise ItemGenError(
                    "魔法法术法杖需要 allow_staff_spells=True（默认只生成属性词缀法杖，"
                    "法术/充能来自 GetStaffSpell()，游戏 75% 的法杖走这条路）",
                    code="bad_staff_spell",
                    suggestions=["传 allow_staff_spells=True 生成游戏原生的法术法杖",
                                 "或去掉 staff_spell/staff_charges 生成属性法杖"])
            if want_suffix is not None:
                raise ItemGenError(
                    "法术法杖没有后缀：GetStaffSpell() → GetStaffPower() 只会给前缀，"
                    "游戏不可能生成「%s」+ 后缀「%s」的法杖"
                    % (base["name"], want_suffix["name"]),
                    code="staff_spell_suffix",
                    suggestions=["法术法杖没有后缀，请去掉后缀"])
        elif rarity == "unique":
            raise ItemGenError(
                "暗金法杖的属性来自暗金表，不会走 GetStaffSpell()，不能指定法术/充能",
                code="bad_staff_spell",
                suggestions=["去掉 staff_spell/staff_charges",
                             "或改用 rarity='normal'/'magic' 的法杖"])

    # ---- 满值 switches: cheap pre-checks (the real write happens in
    # _make_gen_item, right before the record is encoded) ------------------
    if max_ac:
        source = _setac_source(want_prefix, want_suffix)
        if source:
            raise _base_stats_conflict_error(source)

    if rarity != "magic":
        if prefix_value is not None or suffix_value is not None:
            raise ItemGenError("prefix_value/suffix_value 只适用于 rarity='magic' 的词缀",
                               code="bad_affix",
                               suggestions=["去掉数值，或把稀有度改成“魔法”"])
    else:
        if prefix_value is not None and want_prefix is None:
            raise ItemGenError("prefix_value 需要同时指定 prefix（要指定哪个前缀的数值）",
                               code="bad_affix",
                               suggestions=["同时选择前缀和填写前缀数值，或去掉前缀数值"])
        if suffix_value is not None and want_suffix is None:
            raise ItemGenError("suffix_value 需要同时指定 suffix（要指定哪个后缀的数值）",
                               code="bad_affix",
                               suggestions=["同时选择后缀和填写后缀数值，或去掉后缀数值"])
        _check_value_target(want_prefix, "prefix", prefix_value, value_tolerance)
        _check_value_target(want_suffix, "suffix", suffix_value, value_tolerance)

    if rarity == "magic" and base["affix_type"] == 0:
        raise ItemGenError("%r is a %s item: the game never rolls random affixes on it"
                           % (base["name"], base["itype_name"]),
                           code="bad_affix",
                           suggestions=["这类物品不能带随机词缀，请换一个可装备底材"])

    if rarity == "normal":
        if want_prefix or want_suffix:
            raise ItemGenError("normal items cannot carry affixes (use rarity='magic')",
                               code="bad_affix",
                               suggestions=["把稀有度改成“魔法”，或去掉前缀/后缀"])
        s = int(seed) if seed is not None else _random_seed()
        s &= 0xFFFFFFFF
        if base["itype"] == T.ITEM_TYPE["Staff"]:
            # A normal staff must come out of GetStaffSpell without a prefix.
            tries = 0
            while tries < int(max_tries):
                tries += 1
                if s == 0:
                    s = 1
                try:
                    g = _gen_normal(base, s, record_ilvl, onlygood, hellfire, uper=uper)
                except ItemGenError:
                    s = (s + 1) & 0xFFFFFFFF
                    continue
                if want_spell is not None and g.f["spell"] != want_spell:
                    s = (s + 1) & 0xFFFFFFFF
                    continue
                if want_charges is not None and g.f["charges"] != want_charges:
                    s = (s + 1) & 0xFFFFFFFF
                    continue
                if require_staff_spell and not (g.f["spell"] > 0 and g.f["charges"] > 0):
                    s = (s + 1) & 0xFFFFFFFF
                    continue
                return _make_gen_item(g, "normal", identified=identified,
                                      stat_flag=stat_flag, position=position,
                                      max_ac=max_ac, full_durability=full_durability)
            raise ItemGenError(
                "在 %d 个种子的预算内没能生成%s的普通「%s」（ilvl=%d）"
                % (max_tries,
                   ("带法术 %s %d 充能" % (_staff_spell_name(want_spell), want_charges))
                   if want_spell is not None and want_charges is not None else
                   ("带法术 %s" % _staff_spell_name(want_spell))
                   if want_spell is not None else
                   ("%d 充能" % want_charges) if want_charges is not None else
                   "随机法术" if require_staff_spell else "无前缀",
                   base["name"], ilvl),
                code="seed_not_found",
                suggestions=["提高 max_tries", "换一个 seed 起点",
                             "充能值换一个（普通法杖只在该法术的 staff_min~staff_max 内滚）"])
        g = _gen_normal(base, s, record_ilvl, onlygood, hellfire, uper=uper)
        return _make_gen_item(g, "normal", identified=identified, stat_flag=stat_flag,
                              position=position, max_ac=max_ac,
                              full_durability=full_durability)

    if rarity == "unique":
        if want_prefix or want_suffix:
            raise ItemGenError("unique items use their table powers, not affixes",
                               code="bad_affix",
                               suggestions=["去掉前缀/后缀（暗金物品的属性来自暗金表）"])
        if not base["available"]:
            raise ItemGenError("%r 在非 Hellfire 版本中不可用" % base["name"],
                               code="bad_base")
        uniq = None
        if unique_id is not None:
            if isinstance(unique_id, int):
                uniq = T.unique_by_id(unique_id)
            else:
                uniq = T.unique_by_name(unique_id)
            if uniq is None:
                raise ItemGenError("unknown unique item %r" % (unique_id,), code="bad_base")
            ub = T.base_by_idx(_unique_base_index(uniq))
            if ub is None or ub["idx"] != base["idx"]:
                raise ItemGenError("unique %r is based on %r, not %r"
                                   % (uniq["name"], ub["name"] if ub else "?", base["name"]),
                                   code="bad_base",
                                   suggestions=["底材改成 %r" % (ub["name"] if ub else "?")])
        else:
            candidates = [u for u in T.UNIQUES
                          if u["base_item_id"] == base["item_id"]
                          and T.is_unique_available(u["index"])
                          and u["min_level"] <= ilvl]
            if not candidates:
                raise ItemGenError(
                    "no unique item exists for %r at ilvl %d (try a higher ilvl)"
                    % (base["name"], ilvl),
                    code="level_window",
                    suggestions=["把 ilvl 提高，或换一个底材"])
            uniq = candidates[0]
        if uniq["min_level"] > ilvl:
            raise ItemGenError("unique %r requires item level %d (ilvl=%d)"
                               % (uniq["name"], uniq["min_level"], ilvl),
                               code="level_window",
                               suggestions=["把 ilvl 提到 %d" % uniq["min_level"]])
        if max_ac:
            source = _setac_source(unique=uniq)
            if source:
                raise _base_stats_conflict_error(source)
        s = int(seed) if seed is not None else _random_seed()
        s &= 0xFFFFFFFF
        g = _gen_unique(base, uniq["index"], s, record_ilvl, onlygood, hellfire,
                        uper=uper)
        return _make_gen_item(g, "unique", identified=identified, stat_flag=stat_flag,
                              position=position, max_ac=max_ac,
                              full_durability=full_durability)

    # ---- magic ----
    if want_prefix is not None:
        _check_affix_reachable(base, affix_ilvl, want_prefix, "prefix", onlygood)
    if want_suffix is not None:
        _check_affix_reachable(base, affix_ilvl, want_suffix, "suffix", onlygood)
    if _goe_conflict(want_prefix, want_suffix):
        raise _goe_conflict_error(base, affix_ilvl, want_prefix, want_suffix)

    # A spell request ("random spell" counts too) is ~1/(24 spells * charge
    # range * prefix chance), so it must never run inside the cheap 10k loop
    # below -- otherwise a legal request fails for lack of budget.
    spell_wanted = (want_spell is not None or want_charges is not None
                    or require_staff_spell)
    if want_prefix is None and want_suffix is None and not spell_wanted:
        # No constraints: any seed that yields a magic item is fine.  For staves
        # the default is a stat-affix staff (no random spell/charges).
        start = int(seed) if seed is not None else _random_seed()
        start &= 0xFFFFFFFF
        stat_only = is_staff and not allow_staff_spells
        s = start
        tries = 0
        while tries < min(int(max_tries), 10000):
            tries += 1
            if s == 0:
                s = 1
            g = _setup_all_items(base, s, record_ilvl, uper, onlygood, False, False,
                                 hellfire)
            if g.f["magical"] == ITEM_QUALITY_MAGIC and _display_name_consistent(g):
                if not stat_only or (g.f["spell"] == 0 and g.f["charges"] == 0):
                    return _make_gen_item(g, "magic", identified=identified,
                                          stat_flag=stat_flag, position=position,
                                          max_ac=max_ac,
                                          full_durability=full_durability)
            s = (s + 1) & 0xFFFFFFFF
        raise ItemGenError(
            "在 %d 个种子的预算内没能生成魔法「%s」（ilvl=%d）：该等级游戏可能根本不投词缀，"
            "或种子搜索预算不足" % (min(int(max_tries), 10000), base["name"], ilvl),
            code="seed_not_found",
            suggestions=["把 ilvl 提高", "提高 max_tries", "换一个 seed 起点"])

    start = int(seed) if seed is not None else _random_seed()
    start &= 0xFFFFFFFF
    g = _search_seed(base, record_ilvl, want_prefix, want_suffix, start, int(max_tries),
                     onlygood, hellfire,
                     want_prefix_value=prefix_value, want_suffix_value=suffix_value,
                     value_tolerance=value_tolerance,
                     allow_staff_spells=allow_staff_spells,
                     want_spell=want_spell, want_charges=want_charges,
                     require_spell=require_staff_spell, uper=uper,
                     display_ilvl=ilvl)
    if g is None:
        names = []
        if want_prefix:
            names.append(want_prefix["name"])
        if want_suffix:
            names.append("of " + want_suffix["name"])
        if want_spell is not None:
            names.append("法术 %s" % _staff_spell_name(want_spell))
        if want_charges is not None:
            names.append("%d 充能" % want_charges)
        if require_staff_spell:
            names.append("随机法术（spell/charges > 0）")
        prefix_names = "、".join(
            a["name"] for a in eligible_affixes(base["idx"], ilvl, "prefix"))[:400] or "无"
        raise ItemGenError(
            "组合本身合法，但在 %d 个种子的预算内没找到「%s」+ %s（ilvl=%d）："
            "该组合没有数值目标，所以没有“最接近值”可报告；可提高 max_tries/换 seed 起点"
            % (max_tries, base["name"], " + ".join(names) or "(未指定词缀)", ilvl),
            code="seed_not_found",
            suggestions=["提高 max_tries（当前 %d）" % max_tries,
                         "换一个 seed 起点",
                         "该底材在 ilvl=%d 可用的前缀：%s" % (ilvl, prefix_names)])
    return _make_gen_item(g, "magic", identified=identified, stat_flag=stat_flag,
                          position=position, max_ac=max_ac,
                          full_durability=full_durability)


def _unique_base_index(uniq):
    """The base item index the game uses for a unique (first table match).

    Unique-only (``IMISC_UNIQUE``) base rows such as ``Griswold's Edge`` are
    legitimate here, so the starter/unique-only/non-equipment filters are
    explicitly disabled.
    """
    for rec in T.base_items(include_unavailable=True, include_starter=True,
                            include_unique_only=True, include_non_equipment=True):
        if rec["item_id"] == uniq["base_item_id"]:
            return rec["idx"]
    return -1


def unique_detail(unique):
    """Catalogue entry for one unique item (for the GUI's unique list).

    ``unique`` may be a unique id, a unique name or a unique dict.  Returns::

        {
          "uid": 77, "index": 77,
          "name": "Naj's Light Plate", "name_en": "Naj's Light Plate",
          "base_idx": 68, "base_saved_idx": 64,
          "base_name": "Plate Mail", "base_name_en": "Plate Mail",
          "base_id": None, "base_itype": "HeavyArmor",
          "min_level": 22, "value": 12000, "num_powers": 5,
          "available": True,
          "powers": [{"type": 42, "type_name": "IPL_AC", "param1": 0,
                      "param2": 0}, ...],
        }

    English names only: the Chinese names/descriptions come from
    ``d1i18n`` (unique_name_cn / affix_desc-like formatting).  ``base_idx`` is
    the *runtime* ``AllItemsList`` index the record must be written with.
    """
    uniq = None
    if isinstance(unique, dict):
        uniq = dict(unique)
    elif isinstance(unique, int):
        uniq = T.unique_by_id(unique)
    else:
        uniq = T.unique_by_name(unique)
    if uniq is None:
        raise ItemGenError("unknown unique item %r" % (unique,))
    base = T.base_by_idx(_unique_base_index(uniq))
    if base is None:
        # Some quest uniques point at a base row the non-Hellfire build cannot
        # store (e.g. Bovine Plate / IDI_LGTFORGE); still return a complete
        # catalogue entry with available=False instead of raising.
        return {
            "uid": uniq["index"],
            "index": uniq["index"],
            "name": uniq["name"],
            "name_en": uniq["name"],
            "base_idx": -1,
            "base_saved_idx": -1,
            "base_name": None,
            "base_name_en": None,
            "base_id": None,
            "base_itype": None,
            "min_level": uniq["min_level"],
            "value": uniq["value"],
            "num_powers": uniq["num_powers"],
            "available": False,
            "powers": [{"type": p["type"],
                        "type_name": p["type_name"],
                        "param1": p["param1"],
                        "param2": p["param2"]} for p in uniq["powers"]],
        }
    return {
        "uid": uniq["index"],
        "index": uniq["index"],
        "name": uniq["name"],
        "name_en": uniq["name"],
        "base_idx": base["idx"],
        "base_saved_idx": base["saved_idx"],
        "base_name": base["name"],
        "base_name_en": base["name"],
        "base_id": base["id"],
        "base_itype": base["itype_name"],
        "min_level": uniq["min_level"],
        "value": uniq["value"],
        "num_powers": uniq["num_powers"],
        "available": bool(T.is_unique_available(uniq["index"]) and base["available"]),
        "powers": [{"type": p["type"],
                    "type_name": p["type_name"],
                    "param1": p["param1"],
                    "param2": p["param2"]} for p in uniq["powers"]],
    }


def unique_base(unique):
    """Return the base item dict the game builds a unique item on.

    ``unique`` may be a unique index, a unique name or a unique dict (as
    returned by :func:`d1tables.unique_list`).  Note that quest uniques use
    their own ``IMISC_UNIQUE`` table row (e.g. "Griswold's Edge"), not the
    ordinary weapon with a similar name.
    """
    uniq = None
    if isinstance(unique, dict):
        uniq = dict(unique)
    elif isinstance(unique, int):
        uniq = T.unique_by_id(unique)
    else:
        uniq = T.unique_by_name(unique)
    if uniq is None:
        return None
    return T.base_by_idx(_unique_base_index(uniq))


# ---------------------------------------------------------------------------
# replay + validation
# ---------------------------------------------------------------------------

def replay_item(rec_or_fields, hellfire=False):
    """Recreate the item the game would build from ``(idx, iSeed, iCreateInfo)``.

    Returns a :class:`GenItem`.  Raises :class:`ItemGenError` when the record is
    not reproducible this way (vendor items, pre-generated quest items, or an
    inconsistent record).
    """
    if isinstance(rec_or_fields, (bytes, bytearray)):
        f = record_to_fields(rec_or_fields)
    else:
        f = dict(rec_or_fields)
    idx = f.get("base_idx")
    if idx is None:
        idx = T.saved_to_runtime(f["idx"])
    base = T.base_by_idx(idx)
    if base is None:
        raise ItemGenError("record idx %r does not map to a known item" % (f.get("idx"),))
    ci = f["iCreateInfo"] & 0xFFFF
    lvl = ci & CF_LEVEL
    uper = 15 if ci & CF_UPER15 else 1 if ci & CF_UPER1 else 0
    onlygood = bool(ci & CF_ONLYGOOD)
    magical = f["magical"]
    seed = f["iSeed"]

    if magical == ITEM_QUALITY_UNIQUE:
        uid = f.get("Uid", -1)
        uniq = T.unique_by_id(uid)
        if uniq is None:
            raise ItemGenError("unique record with invalid Uid %r" % (uid,))
        g = _Gen(base, Rng(seed), hellfire)
        g.set("iSeed", seed)
        _get_item_attrs(g, _cdiv(lvl, 2))
        g.set("iCreateInfo", ci & ~CF_UNIQUE)
        _get_unique_item(g, uid)
        _setup_item(g)
        return _make_gen_item(g, "unique", identified=bool(f.get("identified")),
                              stat_flag=bool(f.get("StatFlag")),
                              position=(f.get("posx", 0), f.get("posy", 0)))

    if magical == ITEM_QUALITY_MAGIC:
        g = _setup_all_items(base, seed, lvl, uper, onlygood, False,
                             bool(ci & CF_PREGEN), hellfire)
        return _make_gen_item(g, "magic", identified=bool(f.get("identified")),
                              stat_flag=bool(f.get("StatFlag")),
                              position=(f.get("posx", 0), f.get("posy", 0)))

    if base["itype"] == T.ITEM_TYPE["Staff"]:
        # normal staves still went through GetStaffSpell (spell + charges + name)
        g = _setup_all_items(base, seed, lvl, uper, onlygood, False,
                             bool(ci & CF_PREGEN), hellfire)
        g.set("iCreateInfo", ci)
        return _make_gen_item(g, "normal", identified=bool(f.get("identified")),
                              stat_flag=bool(f.get("StatFlag")),
                              position=(f.get("posx", 0), f.get("posy", 0)))

    g = _gen_normal(base, seed, lvl, onlygood, hellfire)
    g.set("iCreateInfo", ci)
    return _make_gen_item(g, "normal", identified=bool(f.get("identified")),
                          stat_flag=bool(f.get("StatFlag")),
                          position=(f.get("posx", 0), f.get("posy", 0)))


def _compare_generation(replayed, expected, ignore=()):
    """Return a list of ``(key, replayed_value, record_value)`` mismatches."""
    diffs = []
    for key in _GENERATION_KEYS:
        if key in ignore:
            continue
        a = replayed.fields.get(key)
        b = expected.get(key)
        if a != b:
            diffs.append((key, a, b))
    return diffs


def validate(rec, replay=True, hellfire=False, allow_ac_override=False):
    """Check that a 368-byte record is a legal, self-consistent 1.5.5 item.

    Returns a list of human readable problems; an empty list means the record is
    exactly what the game would generate for its ``(idx, iSeed, iCreateInfo)``
    (or, for vendor items whose RNG stream cannot be replayed, that all
    structural and table rules hold).

    ``allow_ac_override=True`` is for items generated with ``max_ac=True``: the
    record's ``AC`` was written directly (the base maximum) instead of being
    rolled from the seed, so the replay comparison skips ``AC``.  Everything
    else — including the 368-byte length and all other replay fields — is still
    checked.  ``durability`` is always ignored (worn/repaired game state).
    """
    problems = []
    rec = bytes(rec)
    if len(rec) != RECORD_SIZE:
        return ["record length is %d, expected %d" % (len(rec), RECORD_SIZE)]
    f = record_to_fields(rec)

    # ---- identity / table consistency ----
    saved_idx = f["idx"]
    if hellfire:
        base = T.base_by_idx(saved_idx)
    else:
        base = T.base_by_saved_idx(saved_idx)
    if base is None:
        return ["idx=%d is not a valid %s item index" % (saved_idx, "Hellfire" if hellfire else "Diablo")]
    if not hellfire and not T.is_item_available(base["idx"]):
        problems.append("idx=%d (%s) is not available in the non-Hellfire game"
                        % (saved_idx, base["name"]))
    if f["iType"] != base["itype"]:
        problems.append("iType=%d does not match table value %d for %s"
                        % (f["iType"], base["itype"], base["name"]))
    if f["magical"] != ITEM_QUALITY_UNIQUE:
        # unique table powers may change the equip location (IPL_ONEHAND) or the
        # cursor graphic (IPL_INVCURS); those are verified by replay instead.
        if f["loc"] != base["loc"]:
            problems.append("loc=%d does not match table value %d for %s"
                            % (f["loc"], base["loc"], base["name"]))
        # spell books pick their cursor graphic from the rolled spell
        if base["misc_id"] != T.IMISC_BOOK and f["curs"] != base["curs"]:
            problems.append("curs=%d does not match table value %d for %s"
                            % (f["curs"], base["curs"], base["name"]))
    if f["cls"] != base["class"]:
        problems.append("class=%d does not match table value %d for %s"
                        % (f["cls"], base["class"], base["name"]))
    if f["miscId"] != base["misc_id"]:
        problems.append("miscId=%d does not match table value %d for %s"
                        % (f["miscId"], base["misc_id"], base["name"]))
    if not f["name"].strip():
        problems.append("name is empty")
    if not f["iName"].strip():
        problems.append("iName is empty")

    # ---- flags / powers valid for this build ----
    if not hellfire and f["dwBuff"] & CF_HELLFIRE:
        problems.append("dwBuff has the Hellfire bit set on a non-Hellfire record")
    if not hellfire:
        if f["PrePower"] > IPL_LASTDIABLO:
            problems.append("PrePower=%d is a Hellfire-only effect" % f["PrePower"])
        if f["SufPower"] > IPL_LASTDIABLO:
            problems.append("SufPower=%d is a Hellfire-only effect" % f["SufPower"])
        if f["PrePower"] < -1 or f["SufPower"] < -1:
            problems.append("affix power fields must be -1 or a valid effect id")

    if f["magical"] not in (0, 1, 2):
        problems.append("magical=%d is not a valid item quality" % f["magical"])

    # ---- structural sanity ----
    if f["durability"] < 0:
        problems.append("durability is negative")
    if f["maxDur"] < 0:
        problems.append("maxDur is negative")
    if f["maxDur"] and f["durability"] > f["maxDur"]:
        problems.append("durability %d exceeds maxDur %d" % (f["durability"], f["maxDur"]))
    if f["minDam"] < 0 or f["maxDam"] < 0 or f["minDam"] > f["maxDam"]:
        problems.append("invalid damage range %d-%d" % (f["minDam"], f["maxDam"]))
    if f["AC"] < -32768 or f["AC"] > 32767:
        problems.append("AC=%d out of int16 range" % f["AC"])
    for key in ("MinStr", "MinMag", "MinDex"):
        if not (0 <= f[key] <= 255):
            problems.append("%s=%d out of range 0..255" % (key, f[key]))
    if f["charges"] < 0 or f["maxCharges"] < 0 or f["charges"] > f["maxCharges"]:
        problems.append("invalid charges %d/%d" % (f["charges"], f["maxCharges"]))
    if f["iIvalue"] < 0:
        problems.append("iIvalue=%d should not be negative" % f["iIvalue"])
    if f["ivalue"] < 0:
        problems.append("ivalue is negative")
    if f["identified"] not in (0, 1):
        problems.append("identified=%d should be 0/1" % f["identified"])
    if f["StatFlag"] not in (0, 1):
        problems.append("StatFlag=%d should be 0/1" % f["StatFlag"])

    # ---- affix presence rules ----
    if f["magical"] == ITEM_QUALITY_NORMAL:
        if f["PrePower"] != IPL_INVALID or f["SufPower"] != IPL_INVALID:
            problems.append("normal item has affix power ids set (%d/%d)"
                            % (f["PrePower"], f["SufPower"]))
    elif f["magical"] == ITEM_QUALITY_MAGIC:
        if f["PrePower"] == IPL_INVALID and f["SufPower"] == IPL_INVALID:
            problems.append("magical item has no affix power ids")
        for key, kind in (("PrePower", "prefix"), ("SufPower", "suffix")):
            power = f[key]
            if power == IPL_INVALID:
                continue
            table = T.PREFIXES if kind == "prefix" else T.SUFFIXES
            matches = [a for a in table
                       if a["power"] == power
                       and (is_prefix_valid_for_item_type(a["index"], base["affix_type"], hellfire)
                            if kind == "prefix"
                            else is_suffix_valid_for_item_type(a["index"], base["affix_type"], hellfire))]
            if not matches:
                problems.append("%s effect %d (%s) has no applicable affix for %s"
                                % (kind, power, T.ITEM_EFFECT_TYPE_NAME.get(power, "?"), base["name"]))
        if f["VAdd1"] == 0 and f["VMult1"] == 0 and f["VAdd2"] == 0 and f["VMult2"] == 0:
            problems.append("magical item has no affix values (VAdd/VMult all zero)")
    else:  # unique items use their table powers, no random affix slots
        if f["iCreateInfo"] & CF_UNIQUE == 0:
            pass  # reported in the unique section below

    # ---- unique item rules ----
    if f["magical"] == ITEM_QUALITY_UNIQUE:
        uid = f["Uid"]
        uniq = T.unique_by_id(uid)
        if uniq is None:
            problems.append("Uid=%d is not a valid unique item id" % uid)
        else:
            if not hellfire and not T.is_unique_available(uid):
                problems.append("Uid=%d (%s) is not available in the non-Hellfire game"
                                % (uid, uniq["name"]))
            if uniq["base_item_id"] != base["item_id"]:
                problems.append("Uid=%d (%s) is based on %s, record is %s"
                                % (uid, uniq["name"], uniq["base_item_id_name"], base["name"]))
            if f["iName"] != uniq["name"]:
                problems.append("unique iName=%r does not match table name %r"
                                % (f["iName"], uniq["name"]))
            if not (f["iCreateInfo"] & CF_UNIQUE):
                problems.append("unique item without CF_UNIQUE in iCreateInfo")
            if base["misc_id"] == T.IMISC_UNIQUE and f["iSeed"] != uid:
                problems.append("quest unique iSeed=%d should equal Uid=%d" % (f["iSeed"], uid))
    elif f["magical"] == ITEM_QUALITY_MAGIC:
        if f["iCreateInfo"] == 0:
            problems.append("magical item with iCreateInfo == 0 cannot replay its name")
        if f["iCreateInfo"] & CF_UNIQUE:
            problems.append("magical item with CF_UNIQUE set")
        if f["Uid"] not in (0, -1):
            problems.append("magical item has Uid=%d set" % f["Uid"])
        if "%s" in f["iName"]:
            problems.append("placeholder in iName")
    else:
        if f["Uid"] not in (0, -1):
            problems.append("normal item has Uid=%d set" % f["Uid"])

    # ---- full replay comparison ----
    if replay and not (f["iCreateInfo"] & CF_TOWN) and not (f["iCreateInfo"] & CF_SMITH):
        try:
            rp = replay_item(f, hellfire=hellfire)
        except ItemGenError as exc:
            problems.append("replay failed: %s" % (exc,))
        else:
            ignore = set()
            # Durability is mutable game state (items get worn down and repaired
            # at Griswold); a fresh ItemRndDur value cannot be expected to match.
            ignore.add("durability")
            if allow_ac_override:
                # max_ac=True wrote the base table maximum straight into the
                # record; the game would roll min_ac..max_ac from the seed.
                ignore.add("AC")
            if f["magical"] == ITEM_QUALITY_UNIQUE and (f["iCreateInfo"] & CF_UNIQUE) \
                    and (f["iCreateInfo"] & ~CF_UNIQUE) == 0:
                ignore.add("AC")  # quest uniques roll AC before SetRndSeed
            for key, got, want in _compare_generation(rp, f, ignore):
                problems.append("replay mismatch %s: game would set %r, record has %r"
                                % (key, got, want))
    elif replay:
        # vendor items: verify the base name at least
        if f["magical"] == ITEM_QUALITY_NORMAL and f["iName"] != (base["name"] or ""):
            if not (base["misc_id"] == T.IMISC_BOOK and f["iName"].startswith("Book of ")):
                problems.append("vendor normal item iName=%r does not match base name %r"
                                % (f["iName"], base["name"]))
    # ---- what the game will actually display ----
    if f["magical"] == ITEM_QUALITY_MAGIC:
        shown = translated_item_name_magical(f, hellfire)
        if shown is not None and shown != f["iName"]:
            # Known 1.5.5 quirk: for staves with ilvl//2 > 25 the generation
            # path and the display path use different min-level windows.
            staff_quirk = (f["iType"] == T.ITEM_TYPE["Staff"]
                           and (f["iCreateInfo"] & CF_LEVEL) > 51)
            if not staff_quirk:
                problems.append("game would display %r, record iName is %r"
                                % (shown, f["iName"]))
    return problems


def describe_item(rec):
    """Convenience: decode a record and return a :class:`GenItem` for describe()."""
    return replay_item(rec)


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("record layout bytes:", RECORD_SIZE)
    print("font width 'Leather of Aut':", line_width("Leather of Aut"))
    sword = T.base_by_name("Long Sword")
    print("Long Sword:", sword["idx"], sword["saved_idx"], sword["size"], sword["durability"], sword["value"])
    it = generate(sword["idx"], 30, "magic", seed=1234567)
    print(it.describe())
    print("record length", len(it.record))
    print("validate:", validate(it.record))
