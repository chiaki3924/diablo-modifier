"""d1tables.py -- Diablo 1 (DevilutionX 1.5.5, non-Hellfire) item data tables.

This module parses the *authoritative* 1.5.5 data tables that are compiled into
the game binary:

    DevilutionX-1.5.5/Source/itemdat.cpp   AllItemsList / ItemPrefixes / ItemSuffixes / UniqueItems
    DevilutionX-1.5.5/Source/itemdat.h     enums (ItemType, IMISC_*, IPL_*, ICURS_*, UITYPE_*, ...)
    DevilutionX-1.5.5/Source/items.h       CF_* create-info flags, ItemSpecialEffect bit values
    DevilutionX-1.5.5/Source/spelldat.cpp  SpellsData (names / book & staff costs / levels / charges)
    DevilutionX-1.5.5/Source/cursor.cpp    inventory cell size per cursor graphic
    DevilutionX-1.5.5/Source/items.cpp     ItemCAnimTbl / ItemAnimLs (animation frame counts)

Why not the 1.6.0 TSVs?
------------------------
``devilutionX/assets/txtdata/items/*.tsv`` are shipped by the *1.6.0* source
tree and are **not** identical to 1.5.5.  Example: Short Sword is
``durability=20, value=50`` in 1.5.5 (itemdat.cpp) but ``24 / 120`` in the
1.6.0 TSV; Buckler is ``dur=10, value=50`` vs ``16 / 30``.  Using the TSV
would make every generated record disagree with the game and with the real
save.  The TSV parsers are still provided (and cross-checked in tests / the
report) because they are useful to show where the versions diverge.

Public API
----------
    base_items(include_unavailable=False, droppable_only=False,
               include_starter=False, include_unique_only=False)
                                  -> list[dict]        generatable bases by default
    affix_list(kind)              -> list[dict]        kind in {'prefix','suffix'}
    unique_list()                 -> list[dict]
    spell_list()                  -> list[dict]
    base_by_idx(idx)              -> dict | None       runtime (AllItemsList) index
    base_by_saved_idx(idx)        -> dict | None       index as stored in a .sv file
    base_by_name(name, include_starter=False,
                 include_unique_only=False,
                 include_unavailable=False) -> dict | None
    affix_by_name(kind, name)     -> dict | None
    affix_by_index(kind, i)       -> dict | None
    unique_by_id(uid)             -> dict | None
    unique_by_name(name)          -> dict | None
    runtime_to_saved(idx)         -> int               RemapItemIdxToDiablo()
    saved_to_runtime(idx)         -> int               RemapItemIdxFromDiablo()
    is_item_available(idx)        -> bool              IsItemAvailable(), non-Hellfire
    item_size(idx_or_curs)        -> (width, height)   inventory cells

All returned dicts are plain dicts (JSON friendly) and include both the raw
numeric values and human readable ``*_name`` counterparts.

Generatable bases
-----------------
``AllItemsList`` contains rows that the game never uses as random loot:

* ``starter=True`` -- the four class starting items (``IDI_WARRIOR``,
  ``IDI_ROGUE``, ``IDI_SORCERER``, ``IDI_SORCERER_DIABLO``).  They are
  ``IDROP_NEVER`` rows and the staves are configured by the class setup, not by
  the random item generator.  **Writing one into a save crashes DevilutionX
  1.5.5** (verified: ``IDI_SORCERER_DIABLO`` = saved idx 5 / runtime 166 ->
  ``0xC0000005`` access violation).  Note that ``IDI_SORCERER`` and
  ``IDI_SORCERER_DIABLO`` share saved idx 5, so the filter must be by ``id``.
* ``unique_only=True`` -- ``IMISC_UNIQUE`` rows (``Cleaver``, ``Arkaine's
  Valor``, ``Griswold's Edge``, ...).  They only ever exist as their unique
  counterpart (``SpawnUnique``), never as a normal/magic base item.
* ``equipment=False`` -- gold, potions, scrolls, books and quest props
  (``ItemType::Misc``/``Gold``/``None`` with ``ILOC_UNEQUIPABLE``).  An item
  generator has nothing useful to roll on them.

``generatable = available and equipment and not starter and not unique_only``
(74 rows in 1.5.5) and :func:`base_items` / :func:`base_by_name` only return
generatable rows by default; pass the explicit ``include_*`` flags for
debugging, for building the unique catalogue, or to generate a scroll/book
deliberately.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Source-tree mode: <repo>/lib/d1tables.py -> <repo>/data/game-tables/DevilutionX-1.5.5/Source
# Frozen (PyInstaller) mode: the build stages DevilutionX-1.5.5/Source next to
# the exe's _MEIPASS root.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent


def _data_bases():
    bases = []
    env = os.environ.get("D1_GAME_TABLES")
    if env:
        bases.append(Path(env))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(Path(meipass))
    bases.extend([
        _REPO / "data" / "game-tables",
        _REPO,
        _HERE.parents[1],  # 旧工作区布局：<ROOT>/work/lib
    ])
    return bases


def _first_dir(candidates, fallback):
    for path in candidates:
        if path.is_dir():
            return path
    return fallback


SOURCE_DIR = _first_dir(
    [base / "DevilutionX-1.5.5" / "Source" for base in _data_bases()],
    _REPO / "data" / "game-tables" / "DevilutionX-1.5.5" / "Source",
)
ROOT = SOURCE_DIR.parent.parent
TSV_DIR = _first_dir(
    [base / "devilutionX" / "assets" / "txtdata" / "items" for base in _data_bases()],
    ROOT / "devilutionX" / "assets" / "txtdata" / "items",
)

HELLFIRE = False  # the game this tool targets is Diablo 1.5.5 (non-Hellfire)


# ---------------------------------------------------------------------------
# generic C++ source helpers
# ---------------------------------------------------------------------------

def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _strip_comments(text):
    """Remove // and /* */ comments (keeps newlines so line numbers survive)."""
    out = []
    i = 0
    n = len(text)
    in_line = False
    in_block = False
    in_str = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_matching(text, start, open_ch="{", close_ch="}"):
    """Return index of the matching close_ch for the open_ch at ``start``."""
    depth = 0
    in_str = False
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced braces")


def _split_top_level(text, sep=","):
    """Split on ``sep`` at brace/paren/bracket depth 0, outside strings."""
    parts = []
    cur = []
    depth = 0
    in_str = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            cur.append(c)
        elif c in "{([":
            depth += 1
            cur.append(c)
        elif c in "})]":
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


_ENUM_RE = re.compile(r"enum\s+(?:class\s+|struct\s+)?([A-Za-z_]\w*)\s*(?::\s*[A-Za-z_:][\w:]*\s*)?\{")


def parse_enum(text, enum_name):
    """Parse ``enum [class] enum_name [: type] { ... }`` into an ordered dict.

    Supports explicit values referring to earlier enumerators and the usual
    integer expressions (``1 << 6``, ``(1 << 6) - 1``, ``1U << 31``, ...).
    """
    text = _strip_comments(text)
    m = None
    for cand in _ENUM_RE.finditer(text):
        if cand.group(1) == enum_name:
            m = cand
            break
    if m is None:
        raise KeyError("enum %s not found" % enum_name)
    open_idx = m.end() - 1
    close_idx = _find_matching(text, open_idx)
    body = text[open_idx + 1:close_idx]
    result = {}
    ns = {}
    value = -1
    for item in _split_top_level(body):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, expr = item.split("=", 1)
            name = name.strip()
            expr = expr.strip()
            expr = re.sub(r"(\d)[uUlL]+\b", r"\1", expr)
            expr = expr.replace("::", "_")
            try:
                value = int(eval(expr, {"__builtins__": {}}, dict(ns)))  # noqa: S307 - trusted local source
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("cannot evaluate enum %s.%s = %r (%s)" % (enum_name, name, expr, exc))
            ns[name] = value
        else:
            name = item.strip()
            value += 1
            ns[name] = value
        result[name] = value
    return result


def _reverse_enum(enum, alias_suffixes=("FIRST", "LAST", "NONE", "INVALID", "FIRSTQUEST", "LASTQUEST")):
    """value -> preferred name (first name that is not an alias)."""
    rev = {}
    for name, val in enum.items():
        if val < 0:
            continue
        if name in rev:
            continue
        if any(name.endswith(s) for s in alias_suffixes):
            continue
        rev[val] = name
    # fill holes with any name
    for name, val in enum.items():
        if val >= 0 and val not in rev:
            rev[val] = name
    return rev


def parse_table(text, table_name):
    """Parse ``const <T> table_name[] = { ... };`` into a list of entry strings."""
    text = _strip_comments(text)
    pat = re.compile(r"\b" + re.escape(table_name) + r"\s*\[\s*\]\s*=\s*\{")
    m = pat.search(text)
    if m is None:
        raise KeyError("table %s not found" % table_name)
    open_idx = m.end() - 1
    close_idx = _find_matching(text, open_idx)
    body = text[open_idx + 1:close_idx]
    entries = []
    for item in _split_top_level(body):
        item = item.strip()
        if not item:
            continue
        if not (item.startswith("{") and item.endswith("}")):
            raise ValueError("unexpected table entry in %s: %r" % (table_name, item[:120]))
        entries.append(item[1:-1])
    return entries


_STR_RE = re.compile(r'^(?:[NP]_\(\s*(?:"[^"]*"\s*,\s*)?"([^"]*)"\s*\)|"([^"]*)")$')


def parse_string(tok):
    """Parse ``N_("x")``, ``P_("ctx", "x")``, ``"x"`` or ``nullptr``."""
    tok = tok.strip()
    if tok in ("nullptr", "NULL", "0", ""):
        return None
    m = _STR_RE.match(tok)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    raise ValueError("not a string literal: %r" % tok)


def parse_ident(tok):
    """Parse ``ItemType::Gold`` -> (scope, 'Gold'); ``IDROP_REGULAR`` -> (None, name)."""
    tok = tok.strip()
    if "::" in tok:
        scope, name = tok.rsplit("::", 1)
        return scope, name
    return None, tok


def to_int(tok):
    tok = tok.strip()
    tok = re.sub(r"(\d)[uUlL]+\b", r"\1", tok)
    return int(eval(tok, {"__builtins__": {}}, {}))  # noqa: S307 - trusted local source


# ---------------------------------------------------------------------------
# enums loaded from the 1.5.5 headers
# ---------------------------------------------------------------------------

_HEADERS = {}


def _header(name):
    if name not in _HEADERS:
        _HEADERS[name] = _read(SOURCE_DIR / name)
    return _HEADERS[name]


ITEM_INDEXES = parse_enum(_header("itemdat.h"), "_item_indexes")
ITEM_INDEX_NAME = _reverse_enum(ITEM_INDEXES, alias_suffixes=("FIRSTQUEST", "LASTQUEST", "LAST", "NONE"))

ITEM_TYPE = parse_enum(_header("itemdat.h"), "ItemType")
ITEM_TYPE_NAME = _reverse_enum(ITEM_TYPE)
ITEM_CLASS = parse_enum(_header("itemdat.h"), "item_class")
ITEM_CLASS_NAME = _reverse_enum(ITEM_CLASS)
ITEM_EQUIP_TYPE = parse_enum(_header("itemdat.h"), "item_equip_type")
ITEM_EQUIP_TYPE_NAME = _reverse_enum(ITEM_EQUIP_TYPE)
ITEM_DROP_RATE = parse_enum(_header("itemdat.h"), "item_drop_rate")
ITEM_DROP_RATE_NAME = _reverse_enum(ITEM_DROP_RATE)
ITEM_MISC_ID = parse_enum(_header("itemdat.h"), "item_misc_id")
ITEM_MISC_ID_NAME = _reverse_enum(ITEM_MISC_ID)
ITEM_EFFECT_TYPE = parse_enum(_header("itemdat.h"), "item_effect_type")
ITEM_EFFECT_TYPE_NAME = _reverse_enum(ITEM_EFFECT_TYPE)
UNIQUE_BASE_ITEM = parse_enum(_header("itemdat.h"), "unique_base_item")
UNIQUE_BASE_ITEM_NAME = _reverse_enum(UNIQUE_BASE_ITEM)
ITEM_CURSOR_GRAPHIC = parse_enum(_header("itemdat.h"), "item_cursor_graphic")
ITEM_CURSOR_GRAPHIC_NAME = _reverse_enum(ITEM_CURSOR_GRAPHIC)
ITEM_SPECIAL_EFFECT = parse_enum(_header("itemdat.h"), "ItemSpecialEffect")
ITEM_SPECIAL_EFFECT_HF = parse_enum(_header("itemdat.h"), "ItemSpecialEffectHf")
AFFIX_ITEM_TYPE = parse_enum(_header("itemdat.h"), "AffixItemType")
GOOD_OR_EVIL = parse_enum(_header("itemdat.h"), "goodorevil")
ITEM_QUALITY = parse_enum(_header("items.h"), "item_quality")
CREATEINFO_FLAG = parse_enum(_header("items.h"), "icreateinfo_flag")
CREATEINFO_FLAG2 = parse_enum(_header("items.h"), "icreateinfo_flag2")
SPELL_ID = parse_enum(_header("spelldat.h"), "SpellID")
SPELL_ID_NAME = _reverse_enum(SPELL_ID)
MAGIC_TYPE = parse_enum(_header("spelldat.h"), "MagicType")

# frequently used constants (kept as module level for readability)
ITEM_QUALITY_NORMAL = ITEM_QUALITY["ITEM_QUALITY_NORMAL"]
ITEM_QUALITY_MAGIC = ITEM_QUALITY["ITEM_QUALITY_MAGIC"]
ITEM_QUALITY_UNIQUE = ITEM_QUALITY["ITEM_QUALITY_UNIQUE"]

CF_LEVEL = CREATEINFO_FLAG["CF_LEVEL"]
CF_ONLYGOOD = CREATEINFO_FLAG["CF_ONLYGOOD"]
CF_UPER15 = CREATEINFO_FLAG["CF_UPER15"]
CF_UPER1 = CREATEINFO_FLAG["CF_UPER1"]
CF_UNIQUE = CREATEINFO_FLAG["CF_UNIQUE"]
CF_SMITH = CREATEINFO_FLAG["CF_SMITH"]
CF_SMITHPREMIUM = CREATEINFO_FLAG["CF_SMITHPREMIUM"]
CF_BOY = CREATEINFO_FLAG["CF_BOY"]
CF_WITCH = CREATEINFO_FLAG["CF_WITCH"]
CF_HEALER = CREATEINFO_FLAG["CF_HEALER"]
CF_PREGEN = CREATEINFO_FLAG["CF_PREGEN"]
CF_TOWN = CREATEINFO_FLAG["CF_TOWN"]
CF_HELLFIRE = CREATEINFO_FLAG2["CF_HELLFIRE"]

DUR_INDESTRUCTIBLE = 255

IPL_INVALID = ITEM_EFFECT_TYPE["IPL_INVALID"]
IPL_LASTDIABLO = ITEM_EFFECT_TYPE["IPL_LASTDIABLO"]
IPL_TOHIT_DAMP = ITEM_EFFECT_TYPE["IPL_TOHIT_DAMP"]
IPL_TOHIT_DAMP_CURSE = ITEM_EFFECT_TYPE["IPL_TOHIT_DAMP_CURSE"]
IPL_DOPPELGANGER = ITEM_EFFECT_TYPE["IPL_DOPPELGANGER"]
IPL_TARGAC = ITEM_EFFECT_TYPE["IPL_TARGAC"]
IPL_CHARGES = ITEM_EFFECT_TYPE["IPL_CHARGES"]
IPL_SPELL = ITEM_EFFECT_TYPE["IPL_SPELL"]

IMISC_NONE = ITEM_MISC_ID["IMISC_NONE"]
IMISC_BOOK = ITEM_MISC_ID["IMISC_BOOK"]
IMISC_STAFF = ITEM_MISC_ID["IMISC_STAFF"]
IMISC_UNIQUE = ITEM_MISC_ID["IMISC_UNIQUE"]
IMISC_RING = ITEM_MISC_ID["IMISC_RING"]
IMISC_AMULET = ITEM_MISC_ID["IMISC_AMULET"]

ILOC_NONE = ITEM_EQUIP_TYPE["ILOC_NONE"]
ILOC_ONEHAND = ITEM_EQUIP_TYPE["ILOC_ONEHAND"]
ILOC_TWOHAND = ITEM_EQUIP_TYPE["ILOC_TWOHAND"]
ILOC_ARMOR = ITEM_EQUIP_TYPE["ILOC_ARMOR"]
ILOC_HELM = ITEM_EQUIP_TYPE["ILOC_HELM"]
ILOC_RING = ITEM_EQUIP_TYPE["ILOC_RING"]
ILOC_AMULET = ITEM_EQUIP_TYPE["ILOC_AMULET"]
ILOC_UNEQUIPABLE = ITEM_EQUIP_TYPE["ILOC_UNEQUIPABLE"]
ILOC_BELT = ITEM_EQUIP_TYPE["ILOC_BELT"]
ILOC_INVALID = ITEM_EQUIP_TYPE["ILOC_INVALID"]

AFFIX_MISC = AFFIX_ITEM_TYPE["Misc"]
AFFIX_BOW = AFFIX_ITEM_TYPE["Bow"]
AFFIX_STAFF = AFFIX_ITEM_TYPE["Staff"]
AFFIX_WEAPON = AFFIX_ITEM_TYPE["Weapon"]
AFFIX_SHIELD = AFFIX_ITEM_TYPE["Shield"]
AFFIX_ARMOR = AFFIX_ITEM_TYPE["Armor"]

GOE_ANY = GOOD_OR_EVIL["GOE_ANY"]
GOE_EVIL = GOOD_OR_EVIL["GOE_EVIL"]
GOE_GOOD = GOOD_OR_EVIL["GOE_GOOD"]

#: The four class starting items (``InitPlayer`` in the game source).  They are
#: ``IDROP_NEVER`` rows; the three staffs are "starter spell staves" whose
#: spell/charges come from the class setup, not from the random generator.
#: Using one as a random base item makes DevilutionX 1.5.5 crash, so they are
#: never generatable.  Matched by ``IDI_*`` name (not by number) because
#: ``IDI_SORCERER`` and ``IDI_SORCERER_DIABLO`` both use saved idx 5.
STARTER_ITEM_IDS = ("IDI_WARRIOR", "IDI_ROGUE", "IDI_SORCERER", "IDI_SORCERER_DIABLO")
STARTER_ID_SET = frozenset(name for name in STARTER_ITEM_IDS if name in ITEM_INDEXES)

#: Maps ItemType -> AffixItemType flag(s), mirroring GetItemBonus().
ITYPE_TO_AFFIX = {
    ITEM_TYPE["Sword"]: AFFIX_WEAPON,
    ITEM_TYPE["Axe"]: AFFIX_WEAPON,
    ITEM_TYPE["Mace"]: AFFIX_WEAPON,
    ITEM_TYPE["Bow"]: AFFIX_BOW,
    ITEM_TYPE["Shield"]: AFFIX_SHIELD,
    ITEM_TYPE["LightArmor"]: AFFIX_ARMOR,
    ITEM_TYPE["Helm"]: AFFIX_ARMOR,
    ITEM_TYPE["MediumArmor"]: AFFIX_ARMOR,
    ITEM_TYPE["HeavyArmor"]: AFFIX_ARMOR,
    ITEM_TYPE["Staff"]: AFFIX_STAFF,
    ITEM_TYPE["Ring"]: AFFIX_MISC,
    ITEM_TYPE["Amulet"]: AFFIX_MISC,
}


# ---------------------------------------------------------------------------
# itemdat.cpp tables
# ---------------------------------------------------------------------------

def _parse_power(tok):
    """Parse ``{ IPL_X, p1, p2 }`` / ``{ IPL_X }`` / ``{ }`` -> ItemPower dict."""
    tok = tok.strip()
    if tok.startswith("{"):
        tok = tok[1:-1]
    parts = _split_top_level(tok)
    if not parts or not parts[0].strip():
        return {"type": IPL_INVALID, "type_name": "IPL_INVALID", "param1": 0, "param2": 0}
    _, type_name = parse_ident(parts[0])
    ptype = ITEM_EFFECT_TYPE[type_name]
    p1 = to_int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
    p2 = to_int(parts[2]) if len(parts) > 2 and parts[2].strip() else 0
    return {"type": ptype, "type_name": type_name, "param1": p1, "param2": p2}


def _parse_item_types(tok):
    """Parse ``AffixItemType::Weapon | AffixItemType::Bow`` into an int bitmask."""
    parts = [p.strip() for p in tok.split("|")]
    flags = 0
    names = []
    for p in parts:
        _, name = parse_ident(p)
        if name == "None":
            continue
        flags |= AFFIX_ITEM_TYPE[name]
        names.append(name)
    return flags, names


def _item_type_flags_text(flags):
    return [name for name, val in AFFIX_ITEM_TYPE.items() if name != "None" and flags & val]


def _parse_base_entries():
    entries = parse_table(_read(SOURCE_DIR / "itemdat.cpp"), "AllItemsList")
    items = []
    for pos, entry in enumerate(entries):
        fields = _split_top_level(entry)
        if len(fields) < 22:
            raise ValueError("bad ItemData entry #%d: %r" % (pos, entry[:120]))
        rec = {}
        rec["idx"] = pos
        rec["id"] = ITEM_INDEX_NAME.get(pos)
        rec["drop_rate"] = ITEM_DROP_RATE[parse_ident(fields[0])[1]]
        rec["class"] = ITEM_CLASS[parse_ident(fields[1])[1]]
        rec["loc"] = ITEM_EQUIP_TYPE[parse_ident(fields[2])[1]]
        rec["curs"] = ITEM_CURSOR_GRAPHIC[parse_ident(fields[3])[1]]
        rec["itype"] = ITEM_TYPE[parse_ident(fields[4])[1]]
        rec["item_id"] = UNIQUE_BASE_ITEM[parse_ident(fields[5])[1]]
        rec["name"] = parse_string(fields[6])
        rec["sname"] = parse_string(fields[7])
        rec["min_mlvl"] = to_int(fields[8])
        rec["durability"] = to_int(fields[9])
        rec["min_dam"] = to_int(fields[10])
        rec["max_dam"] = to_int(fields[11])
        rec["min_ac"] = to_int(fields[12])
        rec["max_ac"] = to_int(fields[13])
        rec["min_str"] = to_int(fields[14])
        rec["min_mag"] = to_int(fields[15])
        rec["min_dex"] = to_int(fields[16])
        rec["flags"] = 0
        for p in str(fields[17]).split("|"):
            _, fname = parse_ident(p)
            if fname == "None":
                continue
            rec["flags"] |= ITEM_SPECIAL_EFFECT[fname]
        rec["misc_id"] = ITEM_MISC_ID[parse_ident(fields[18])[1]]
        rec["spell"] = SPELL_ID[parse_ident(fields[19])[1]]
        rec["usable"] = str(fields[20]).strip() == "true"
        rec["value"] = to_int(fields[21])
        # names for readability
        rec["itype_name"] = ITEM_TYPE_NAME.get(rec["itype"], "?")
        rec["class_name"] = ITEM_CLASS_NAME.get(rec["class"], "?")
        rec["loc_name"] = ITEM_EQUIP_TYPE_NAME.get(rec["loc"], "?")
        rec["curs_name"] = ITEM_CURSOR_GRAPHIC_NAME.get(rec["curs"], "?")
        rec["misc_id_name"] = ITEM_MISC_ID_NAME.get(rec["misc_id"], "?")
        rec["spell_name"] = SPELL_ID_NAME.get(rec["spell"], "?")
        rec["item_id_name"] = UNIQUE_BASE_ITEM_NAME.get(rec["item_id"], "?")
        rec["drop_rate_name"] = ITEM_DROP_RATE_NAME.get(rec["drop_rate"], "?")
        rec["flags_hex"] = rec["flags"]
        if rec["spell"] < 0:
            rec["spell_name"] = "Null" if rec["spell"] == 0 else "?"
        items.append(rec)
    return items


def _parse_affix_entries(table_name, kind):
    entries = parse_table(_read(SOURCE_DIR / "itemdat.cpp"), table_name)
    out = []
    for pos, entry in enumerate(entries):
        fields = _split_top_level(entry)
        if len(fields) < 3:
            raise ValueError("bad affix entry #%d: %r" % (pos, entry[:120]))
        name = parse_string(fields[0])
        power = _parse_power(fields[1])
        if name is None or name == "" or power["type"] == IPL_INVALID:
            continue  # sentinel
        rec = {
            "kind": kind,
            "index": pos,
            "name": name,
            "power": power["type"],
            "power_name": power["type_name"],
            "param1": power["param1"],
            "param2": power["param2"],
            "min_level": to_int(fields[2]),
            "item_types": 0,
            "min_val": to_int(fields[7]) if len(fields) > 7 else 0,
            "max_val": to_int(fields[8]) if len(fields) > 8 else 0,
            "mult_val": to_int(fields[9]) if len(fields) > 9 else 0,
        }
        item_types, _ = _parse_item_types(fields[3])
        rec["item_types"] = item_types
        rec["item_type_names"] = _item_type_flags_text(item_types)
        rec["goe"] = GOOD_OR_EVIL[parse_ident(fields[4])[1]]
        rec["goe_name"] = parse_ident(fields[4])[1]
        rec["double"] = str(fields[5]).strip() == "true"
        rec["ok"] = str(fields[6]).strip() == "true"
        # The 1.5.5 table contains Hellfire-only rows after the Diablo ones;
        # IsPrefixValidForItemType()/IsSuffixValidForItemType() reject them.
        rec["hellfire_only"] = (pos > 82) if kind == "prefix" else (pos > 94)
        out.append(rec)
    return out


def _parse_unique_entries():
    entries = parse_table(_read(SOURCE_DIR / "itemdat.cpp"), "UniqueItems")
    out = []
    for pos, entry in enumerate(entries):
        fields = _split_top_level(entry)
        if len(fields) < 6:
            raise ValueError("bad unique entry #%d: %r" % (pos, entry[:120]))
        name = parse_string(fields[0])
        base = parse_ident(fields[1])[1]
        if name is None or base == "UITYPE_INVALID":
            continue
        powers_txt = fields[5].strip()
        if powers_txt.startswith("{"):
            powers_txt = powers_txt[1:-1]
        powers = []
        for ptxt in _split_top_level(powers_txt):
            if not ptxt.strip():
                continue
            p = _parse_power(ptxt)
            if p["type"] == IPL_INVALID:
                continue
            powers.append(p)
        rec = {
            "index": pos,
            "name": name,
            "base_item_id": UNIQUE_BASE_ITEM[base],
            "base_item_id_name": base,
            "min_level": to_int(fields[2]),
            "num_powers": to_int(fields[3]),
            "value": to_int(fields[4]),
            "powers": powers,
        }
        out.append(rec)
    return out


def _parse_spells():
    entries = parse_table(_read(SOURCE_DIR / "spelldat.cpp"), "SpellsData")
    out = []
    for pos, entry in enumerate(entries):
        fields = _split_top_level(entry)
        if len(fields) < 14:
            raise ValueError("bad SpellData entry #%d: %r" % (pos, entry[:120]))
        rec = {
            "index": pos,
            "name": parse_string(fields[0]),
            "book_cost10": to_int(fields[2]),
            "staff_cost10": to_int(fields[3]),
            "mana_cost": to_int(fields[4]),
            "flags": fields[5].strip(),
            "book_lvl": to_int(fields[6]),
            "staff_lvl": to_int(fields[7]),
            "min_int": to_int(fields[8]),
            "staff_min": to_int(fields[12]),
            "staff_max": to_int(fields[13]),
        }
        rec["book_cost"] = rec["book_cost10"] * 10
        rec["staff_cost"] = rec["staff_cost10"] * 10
        rec["magic_type"] = (
            MAGIC_TYPE["Lightning"] if "Lightning" in rec["flags"]
            else MAGIC_TYPE["Magic"] if "Magic" in rec["flags"]
            else MAGIC_TYPE["Fire"]
        )
        rec["magic_type_name"] = MAGIC_TYPE and _reverse_enum(MAGIC_TYPE).get(rec["magic_type"], "?")
        out.append(rec)
    return out


def _parse_item_anim():
    """Return (ItemCAnimTbl, ItemAnimLs) from items.cpp."""
    text = _strip_comments(_read(SOURCE_DIR / "items.cpp"))

    def arr(name):
        m = re.search(r"\b" + re.escape(name) + r"\s*\[\s*\]\s*=\s*\{", text)
        if m is None:
            raise KeyError(name)
        close = _find_matching(text, m.end() - 1)
        nums = [int(x) for x in re.findall(r"-?\d+", text[m.end():close])]
        return nums

    return arr("ItemCAnimTbl"), arr("ItemAnimLs")


CURSOR_FIRSTITEM = 12  # cursor.h: enum cursor_id { ..., CURSOR_HOURGLASS, CURSOR_FIRSTITEM }


def _parse_cursor_sizes():
    """Return {curs: (width_cells, height_cells)} from cursor.cpp.

    ``GetInventorySize()`` computes ``GetInvItemSize(item._iCurs + CURSOR_FIRSTITEM)``
    and ``GetInvItemSize(cursId)`` indexes the arrays with ``cursId - 1``, i.e.
    array index ``item._iCurs + 11``.  Pixel sizes are multiples of 28 (one
    inventory cell).
    """
    text = _strip_comments(_read(SOURCE_DIR / "cursor.cpp"))

    def arr(name):
        m = re.search(r"\b" + re.escape(name) + r"\s*\[\s*(?:InvItems1Size)?\s*\]\s*=\s*\{", text)
        if m is None:
            raise KeyError(name)
        close = _find_matching(text, m.end() - 1)
        body = text[m.end():close]
        vals = []
        for tok in _split_top_level(body):
            tok = tok.strip()
            if not tok:
                continue
            vals.append(int(eval(tok, {"__builtins__": {}}, {})))  # noqa: S307
        return vals

    w1 = arr("InvItemWidth1")
    h1 = arr("InvItemHeight1")
    sizes = {}
    for curs in range(0, len(w1) - CURSOR_FIRSTITEM + 1):
        idx = curs + CURSOR_FIRSTITEM - 1
        if idx >= len(w1) or idx >= len(h1):
            break
        sizes[curs] = (max(1, w1[idx] // 28), max(1, h1[idx] // 28))
    return sizes


ITEM_CURSOR_SIZE = _parse_cursor_sizes()
ITEM_CANIM, ITEM_ANIM_LS = _parse_item_anim()

_RAW_BASE_ITEMS = _parse_base_entries()
_BASE_BY_IDX = {r["idx"]: r for r in _RAW_BASE_ITEMS}
PREFIXES = _parse_affix_entries("ItemPrefixes", "prefix")
SUFFIXES = _parse_affix_entries("ItemSuffixes", "suffix")
UNIQUES = _parse_unique_entries()
SPELLS = _parse_spells()

# ---------------------------------------------------------------------------
# spell book whitelist (1.5.5 non-Hellfire)
# ---------------------------------------------------------------------------

#: ``SpellID::LastDiablo`` -- Bone Spirit, the last spell of the original book.
D1_LAST_SPELL = 36
#: Hellfire spells start here (``SpellID::Mana``); all of them are hidden.
D1_HELLFIRE_FIRST_SPELL = 37
D1_HELLFIRE_LAST_SPELL = 46
#: ``pSplLvl`` slots in a Hellfire-capable 1.5.5 save (0..36 + 37..46).
D1_SPELL_SLOTS = 47

#: Spells that ``spells.cpp GetSpellBookLevel()`` rejects in the non-Hellfire
#: build even though ``spelldat.cpp`` carries a book level for them.
SPELL_NOVA = 18
SPELL_APOCALYPSE = 24

#: Spells that exist in the table but cannot be learned in single player.
SPELL_RESURRECT = 32
SPELL_HEAL_OTHER = 34

#: The three class skills (book level -1, known by one class from the start).
SPELL_ITEM_REPAIR = 26
SPELL_STAFF_RECHARGE = 27
SPELL_TRAP_DISARM = 28

#: Spells that are not part of the 1.5.5 single-player book at all: the Hellfire
#: range 37..46 plus the single-player unlearnable books.  The three class
#: skills (26/27/28) are deliberately **not** listed: they are class abilities
#: that the game grants via ``pMemSpells`` even with a level of 0.
SPELL_NON_ORIGINAL = frozenset({5, 9, 16, 17, 18, 19, 22, 24, 25, 32, 34}) | frozenset(
    range(D1_HELLFIRE_FIRST_SPELL, D1_HELLFIRE_LAST_SPELL + 1))


# ---------------------------------------------------------------------------
# index remapping (loadsave.cpp RemapItemIdxToDiablo / FromDiablo)
# ---------------------------------------------------------------------------

def runtime_to_saved(idx):
    """_item_indexes -> index stored in a .sv file (Diablo numbering)."""
    i = int(idx)
    if i == ITEM_INDEXES["IDI_SORCERER_DIABLO"]:
        return ITEM_INDEXES["IDI_SORCERER"]
    if (83 <= i <= 86) or i == 92 or i >= 161:
        return -1
    if i >= 93:
        i -= 1
    if i >= 87:
        i -= 4
    return i


def saved_to_runtime(idx):
    """Index stored in a .sv file -> runtime _item_indexes (-1 if unknown)."""
    i = int(idx)
    if i < 0:
        return -1
    if i == ITEM_INDEXES["IDI_SORCERER"]:
        return ITEM_INDEXES["IDI_SORCERER_DIABLO"]
    if i >= 156:
        i += 5
    if i >= 88:
        i += 1
    if i >= 83:
        i += 4
    return i


def is_item_available(idx):
    """IsItemAvailable(), non-Hellfire build."""
    i = int(idx)
    if i < 0 or i > ITEM_INDEXES["IDI_LAST"]:
        return False
    if HELLFIRE:
        return True
    return (
        i != ITEM_INDEXES["IDI_MAPOFDOOM"]
        and i != ITEM_INDEXES["IDI_LGTFORGE"]
        and not (ITEM_INDEXES["IDI_OIL"] <= i <= ITEM_INDEXES["IDI_GREYSUIT"])
        and not (83 <= i <= 86)
        and i != 92
        and not (161 <= i <= 165)
        and i != ITEM_INDEXES["IDI_SORCERER"]
    )


def is_unique_available(uid):
    """IsUniqueAvailable(), non-Hellfire build."""
    return HELLFIRE or int(uid) <= 89


# ---------------------------------------------------------------------------
# public lookups
# ---------------------------------------------------------------------------

def _finalize_base(rec):
    """Add derived fields (saved idx, size, affix type) to a base item dict."""
    out = dict(rec)
    out["saved_idx"] = runtime_to_saved(rec["idx"])
    # A row is usable in a non-Hellfire save only if the game's own remapper can
    # store it (Arena Potion etc. map to -1 and would be written as gold).
    out["available"] = is_item_available(rec["idx"]) and (HELLFIRE or out["saved_idx"] >= 0)
    w, h = ITEM_CURSOR_SIZE.get(rec["curs"], (1, 1))
    out["width"] = w
    out["height"] = h
    out["size"] = (w, h)
    out["affix_type"] = ITYPE_TO_AFFIX.get(rec["itype"], 0)
    out["type"] = rec["itype_name"]  # GUI-friendly alias for itype_name
    out["anim_frames"] = _anim_frames(rec["curs"])
    # IMISC_UNIQUE base rows only ever exist as their unique counterpart
    # (SpawnUnique / pre-generated quest items), never as normal/magic items.
    out["unique_only"] = rec["misc_id"] == IMISC_UNIQUE
    # Class starting items: IDROP_NEVER rows that the game hands out in
    # InitPlayer().  The staves are starter spell staves and crash the game
    # when put into a save (see STARTER_ITEM_IDS).
    out["starter"] = rec["id"] in STARTER_ID_SET
    # IDROP_NEVER rows are starting/quest items the game never drops or sells
    # as random loot (e.g. IDI_WARRIOR is the warrior's starting "Short Sword",
    # while the droppable Short Sword is runtime index 119).
    out["droppable"] = rec["drop_rate"] != ITEM_DROP_RATE["IDROP_NEVER"]
    # GUI convenience: the "normal loot" version of a name (droppable, not a
    # unique-only quest relic).
    out["canonical"] = out["droppable"] and not out["unique_only"]
    # Equipment: what an item generator can usefully create.  Gold, potions,
    # scrolls, books and quest props are IMISC_* rows with ILOC_UNEQUIPABLE.
    # (Availability is handled separately: some quest/unique-only equipment rows
    # are not writable to a non-Hellfire save but are still equipment.)
    out["equipment"] = (
        rec["itype"] not in (ITEM_TYPE["Misc"], ITEM_TYPE["Gold"], ITEM_TYPE["None"])
        and rec["loc"] != ILOC_UNEQUIPABLE
    )
    # The single flag random generation must respect: only these rows may be
    # used as the base of a normal/magic/unique item (74 rows in 1.5.5).
    out["generatable"] = (
        out["available"]
        and out["equipment"]
        and not out["starter"]
        and not out["unique_only"]
    )
    return out


def _anim_frames(curs):
    """ItemAnimLs[ItemCAnimTbl[curs]] -- number of animation frames for a cursor graphic."""
    if 0 <= curs < len(ITEM_CANIM):
        it = ITEM_CANIM[curs]
        if 0 <= it < len(ITEM_ANIM_LS):
            return ITEM_ANIM_LS[it]
    return 1


_BASE_FINAL = [_finalize_base(r) for r in _RAW_BASE_ITEMS]
_BASE_BY_IDX_FINAL = {r["idx"]: r for r in _BASE_FINAL}

# saved idx -> base item, following the game's loader (loadsave.cpp
# RemapItemIdxFromDiablo).  Building this from ``runtime_to_saved`` would be
# wrong for the IDI_SORCERER / IDI_SORCERER_DIABLO pair, which both map to
# saved index 5; the loader always resolves 5 to IDI_SORCERER_DIABLO (166).
_BASE_BY_SAVED = {}
for _saved in range(0, 256):
    _runtime = saved_to_runtime(_saved)
    _rec = _BASE_BY_IDX_FINAL.get(_runtime)
    if _rec is not None and runtime_to_saved(_runtime) == _saved:
        _BASE_BY_SAVED.setdefault(_saved, _rec)
del _saved, _runtime, _rec


def base_items(include_unavailable=False, droppable_only=False,
               include_starter=False, include_unique_only=False,
               include_non_equipment=False):
    """Base items as dicts (runtime idx order), generatable equipment by default.

    Only rows with ``generatable=True`` are returned unless the explicit
    ``include_*`` debugging flags are given:

    * ``include_unavailable=True`` -- also rows the non-Hellfire game never
      loads (oils, runes, Cathedral Map, Arena Potion, ...).
    * ``include_starter=True`` -- also the four class starting items
      (``IDI_WARRIOR`` / ``IDI_ROGUE`` / ``IDI_SORCERER`` /
      ``IDI_SORCERER_DIABLO``).  **Never generate items on these**, see
      :data:`STARTER_ITEM_IDS`.
    * ``include_unique_only=True`` -- also ``IMISC_UNIQUE`` rows whose name is
      the unique's name (``Cleaver``, ``Arkaine's Valor``, ...).
    * ``include_non_equipment=True`` -- also gold, potions, scrolls, books and
      quest props (``ILOC_UNEQUIPABLE`` rows).
    * ``droppable_only=True`` -- only rows with ``droppable=True``
      (``IDROP_NEVER`` starting/quest rows are hidden).

    With all flags off this returns the 74 equipment rows that can legally be
    written to a non-Hellfire save (5 staves, rings, amulets, weapons, armour,
    shields).  72 of them are regular drops; the 2 exceptions are the warrior's
    alternate starting ``Buckler`` (runtime 2) / ``Club`` (runtime 3), which are
    plain ``IDROP_NEVER`` rows that the game loads as ordinary items (unlike the
    spell staves they carry no class-specific spell state).  Use
    ``droppable_only=True`` for the 72 genuine drop rows.
    """
    out = []
    for r in _BASE_FINAL:
        if not include_unavailable and not r["available"]:
            continue
        if not include_starter and r["starter"]:
            continue
        if not include_unique_only and r["unique_only"]:
            continue
        if not include_non_equipment and not r["equipment"]:
            continue
        if droppable_only and not r["droppable"]:
            continue
        out.append(dict(r))
    return out


def base_by_idx(idx):
    r = _BASE_BY_IDX_FINAL.get(int(idx))
    return dict(r) if r else None


def base_by_saved_idx(idx):
    r = _BASE_BY_SAVED.get(int(idx))
    return dict(r) if r else None


def _pick_base(candidates):
    """Prefer droppable+available, then available, then the first candidate."""
    if not candidates:
        return None
    for r in candidates:
        if r["available"] and r["droppable"]:
            return r
    for r in candidates:
        if r["available"]:
            return r
    return candidates[0]


def base_by_name(name, include_starter=False, include_unique_only=False,
                 include_unavailable=False, include_non_equipment=False):
    """Look up a base item by full name; only generatable equipment by default.

    Several names are shared by more than one table row (the starting items and
    quest relics are duplicated as `IDROP_NEVER` rows, and there are three
    identical "Ring" rows).  Prefer the droppable, available row -- that is the
    item the game itself generates.

    Rows that are not generatable (starter items / ``IMISC_UNIQUE`` rows /
    gold, potions, scrolls, books) are skipped by default, so
    ``base_by_name("Short Staff of Charged Bolt")``, ``base_by_name("Cleaver")``
    and ``base_by_name("Scroll of Identify")`` return ``None``.  Pass the
    matching ``include_*`` flag to inspect them anyway.
    """
    if name is None:
        return None
    target = str(name).strip().lower()
    cands = [r for r in _BASE_FINAL if r["name"] and r["name"].strip().lower() == target]
    if not include_unavailable:
        avail = [r for r in cands if r["available"]]
        if avail:
            cands = avail
    if not include_starter:
        cands = [r for r in cands if not r["starter"]]
    if not include_unique_only:
        cands = [r for r in cands if not r["unique_only"]]
    if not include_non_equipment:
        equip = [r for r in cands if r["equipment"]]
        if equip:
            cands = equip
    r = _pick_base(cands)
    return dict(r) if r else None


def base_by_sname(name, include_starter=False, include_unique_only=False,
                  include_unavailable=False, include_non_equipment=False):
    if name is None:
        return None
    target = str(name).strip().lower()
    cands = [r for r in _BASE_FINAL if r["sname"] and r["sname"].strip().lower() == target]
    if not include_unavailable:
        avail = [r for r in cands if r["available"]]
        if avail:
            cands = avail
    if not include_starter:
        cands = [r for r in cands if not r["starter"]]
    if not include_unique_only:
        cands = [r for r in cands if not r["unique_only"]]
    if not include_non_equipment:
        equip = [r for r in cands if r["equipment"]]
        if equip:
            cands = equip
    r = _pick_base(cands)
    return dict(r) if r else None


def base_by_id(item_id):
    """Look up a base item by its ``IDI_*`` enum name."""
    if item_id is None:
        return None
    target = str(item_id).strip().upper()
    val = ITEM_INDEXES.get(target)
    if val is None:
        return None
    return base_by_idx(val)


def affix_list(kind):
    kind = str(kind).lower()
    if kind.startswith("pre"):
        src = PREFIXES
    elif kind.startswith("suf"):
        src = SUFFIXES
    else:
        raise ValueError("kind must be 'prefix' or 'suffix', got %r" % (kind,))
    return [dict(r) for r in src]


def affix_by_index(kind, index):
    for r in affix_list(kind):
        if r["index"] == int(index):
            return r
    return None


def affix_by_name(kind, name):
    """Look up an affix by name, tolerating the "of "/"the " variants.

    The table stores suffix names without the leading "of " (``giants``,
    ``the fox``, ``strength``) while the game displays and users type
    ``of giants`` / ``of the fox``.  The exact name is tried first, then the
    "of "-stripped / "the "-stripped forms, so both spellings resolve.
    """
    if name is None:
        return None
    text = str(name).strip()
    after_of = text[3:] if text.lower().startswith("of ") else text
    variants = [text]
    variants.append(after_of if text.lower().startswith("of ") else "of " + text)
    if after_of.lower().startswith("the "):
        variants.append(after_of[4:])
    else:
        variants.append("the " + after_of)
    table = affix_list(kind)
    for target in variants:
        for r in table:
            if r["name"].lower() == target.lower():
                return r
    return None


def unique_list(include_unavailable=False):
    if include_unavailable:
        return [dict(r) for r in UNIQUES]
    return [dict(r) for r in UNIQUES if is_unique_available(r["index"])]


def unique_by_id(uid):
    for r in UNIQUES:
        if r["index"] == int(uid):
            return dict(r)
    return None


def unique_by_name(name):
    if name is None:
        return None
    target = str(name).strip().lower()
    for r in UNIQUES:
        if r["name"].lower() == target:
            return dict(r)
    return None


def uniques_for_base(base_idx):
    """Unique items whose UIItemId matches this base item (CheckUnique prefilter)."""
    base = base_by_idx(base_idx)
    if base is None:
        return []
    return [dict(r) for r in UNIQUES if r["base_item_id"] == base["item_id"]]


def spell_list():
    return [dict(r) for r in SPELLS]


def spell_by_id(sid):
    sid = int(sid)
    if 0 <= sid < len(SPELLS):
        return dict(SPELLS[sid])
    return None


def spell_by_name(name):
    target = str(name).strip().lower()
    for r in SPELLS:
        if r["name"] and r["name"].lower() == target:
            return dict(r)
    return None


def spell_book_level(spell_id):
    """``GetSpellBookLevel()`` of the 1.5.5 non-Hellfire game (``spells.cpp``).

    ``-1`` means "cannot be learned".  Besides the table's ``sBookLvl == -1``
    rows, the game rejects Nova and Apocalypse explicitly and every id above
    Bone Spirit (36) because those are Hellfire spells.
    """
    sid = int(spell_id)
    if sid < 0 or sid >= len(SPELLS):
        return -1
    if not HELLFIRE:
        if sid in (SPELL_NOVA, SPELL_APOCALYPSE):
            return -1
        if sid > D1_LAST_SPELL:
            return -1
    return int(SPELLS[sid]["book_lvl"])


def spell_bitmask(spell_id):
    """``pMemSpells`` bit of a spell id.

    The game walks the bitmap with ``spell = 1`` for Firebolt (see
    ``objects.cpp``), i.e. **spell 1 -> bit 0**: ``1 << (id - 1)``.  Id 0 (the
    ``Null`` placeholder) owns no bit and returns 0.
    """
    sid = int(spell_id)
    if sid < 1:
        return 0
    return 1 << (sid - 1)


def spell_cn(spell_id):
    """Chinese name of a spell (zh_CN translation, English fallback)."""
    sid = int(spell_id)
    rec = spell_by_id(sid)
    en = (rec or {}).get("name") or ""
    try:
        import d1i18n  # lazy: d1i18n imports d1tables lazily itself
        cn = d1i18n.spell_name_cn(sid)
    except Exception:  # noqa: BLE001 - translations are optional
        cn = ""
    if cn and not cn.startswith("法术 #"):
        return cn
    return en or ("法术%d" % sid)


def non_original_spells():
    """Spell ids that are not part of the 1.5.5 single-player book, sorted.

    Hellfire's 37..46 plus the single-player unlearnable books
    (Identify/Infravision/Doom Serpents/Blood Ritual/Nova/Invisibility/Rage/
    Apocalypse/Etherealize/Resurrect/Heal Other).  The three class skills
    (26/27/28) are **not** included -- they are class abilities.
    """
    return sorted(SPELL_NON_ORIGINAL)


def learnable_spells(multiplayer=False):
    """Spells the 1.5.5 spell book can actually teach, in spell-id order.

    Single player gets the 22 original Diablo spells; ``multiplayer=True``
    adds Heal Other (34), which only exists in multiplayer games.  Never
    returned: Nova/Apocalypse (rejected by ``GetSpellBookLevel``), the four
    unlearnable books (Identify/Infravision/Doom Serpents/Blood Ritual/
    Invisibility/Rage/Etherealize), Resurrect, the three class skills
    (Item Repair/Staff Recharge/Trap Disarm) and every Hellfire spell (37+).

    Each row is ``{"index", "name", "cn", "book_lvl"}``.
    """
    out = []
    for sid in range(1, D1_LAST_SPELL + 1):
        if sid in (SPELL_NOVA, SPELL_APOCALYPSE):
            continue
        if sid == SPELL_HEAL_OTHER and not multiplayer:
            continue
        book = spell_book_level(sid)
        if book < 0:
            continue
        rec = SPELLS[sid]
        out.append({
            "index": sid,
            "name": rec["name"],
            "cn": spell_cn(sid),
            "book_lvl": book,
        })
    return out


def item_size(idx_or_curs, is_curs=False):
    """Inventory size in cells given a runtime item idx (default) or cursor graphic."""
    if is_curs:
        return ITEM_CURSOR_SIZE.get(int(idx_or_curs), (1, 1))
    base = base_by_idx(idx_or_curs)
    if base is None:
        return (1, 1)
    return (base["width"], base["height"])


def resolve_base(identifier, require_available=False):
    """Resolve an int runtime index / saved index / enum name / item name to a base dict.

    Precedence for ints: runtime index first (if the item is available), then
    saved index.  ``require_available`` rejects quest/Hellfire-only items.
    """
    rec = None
    if isinstance(identifier, int):
        rec = base_by_idx(identifier)
        if rec is not None and (not require_available or rec["available"]):
            return rec
        alt = base_by_saved_idx(identifier)
        if alt is not None and (not require_available or alt["available"]):
            return alt
        return rec
    s = str(identifier).strip()
    if s.upper().startswith("IDI_"):
        val = ITEM_INDEXES.get(s.upper())
        if val is not None:
            rec = base_by_idx(val)
            if rec is not None and (not require_available or rec["available"]):
                return rec
    rec = base_by_name(s)
    if rec is not None and (not require_available or rec["available"]):
        return rec
    rec = base_by_sname(s)
    if rec is not None and (not require_available or rec["available"]):
        return rec
    return None


# ---------------------------------------------------------------------------
# 1.6.0 TSV parsers (kept for cross-checks, see itemgen_report.md)
# ---------------------------------------------------------------------------

def _read_tsv(name):
    path = TSV_DIR / name
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        header = None
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            cols = line.split("\t")
            if header is None:
                header = cols
                continue
            rows.append(dict(zip(header, cols)))
    return header, rows


def _tsv_int(value):
    value = (value or "").strip()
    return int(value) if value else 0


def parse_itemdat_tsv():
    """Parse the 1.6.0 ``itemdat.tsv`` into dicts shaped like :func:`base_items`."""
    header, rows = _read_tsv("itemdat.tsv")
    out = []
    for row in rows:
        rec = {
            "id": row["id"],
            "drop_rate_name": row["dropRate"],
            "class_name": row["class"],
            "loc_name": row["equipType"],
            "curs_name": row["cursorGraphic"],
            "itype_name": row["itemType"],
            "item_id_name": row["uniqueBaseItem"],
            "name": row["name"] or None,
            "sname": row["shortName"] or None,
            "min_mlvl": _tsv_int(row["minMonsterLevel"]),
            "durability": _tsv_int(row["durability"]),
            "min_dam": _tsv_int(row["minDamage"]),
            "max_dam": _tsv_int(row["maxDamage"]),
            "min_ac": _tsv_int(row["minArmor"]),
            "max_ac": _tsv_int(row["maxArmor"]),
            "min_str": _tsv_int(row["minStrength"]),
            "min_mag": _tsv_int(row["minMagic"]),
            "min_dex": _tsv_int(row["minDexterity"]),
            "misc_id_name": row["miscId"],
            "spell_name": row["spell"],
            "usable": row["usable"] == "true",
            "value": _tsv_int(row["value"]),
        }
        if rec["itype_name"] in ITEM_TYPE:
            rec["itype"] = ITEM_TYPE[rec["itype_name"]]
        out.append(rec)
    return out


def parse_affix_tsv(kind):
    fname = "item_prefixes.tsv" if str(kind).lower().startswith("pre") else "item_suffixes.tsv"
    header, rows = _read_tsv(fname)
    out = []
    for row in rows:
        rec = {
            "kind": "prefix" if fname.startswith("item_prefixes") else "suffix",
            "name": row["name"],
            "power_name": row["power"],
            "param1": _tsv_int(row["power.value1"]),
            "param2": _tsv_int(row["power.value2"]),
            "min_level": _tsv_int(row["minLevel"]),
            "item_type_names": [x for x in row["itemTypes"].split(",") if x],
            "goe_name": row["alignment"],
            "chance": _tsv_int(row["chance"]),
            "ok": row["useful"] == "true",
            "min_val": _tsv_int(row["minVal"]),
            "max_val": _tsv_int(row["maxVal"]),
            "mult_val": _tsv_int(row["multVal"]),
        }
        out.append(rec)
    return out


def parse_unique_tsv():
    header, rows = _read_tsv("unique_itemdat.tsv")
    out = []
    for row in rows:
        powers = []
        for i in range(6):
            type_key = "power%d" % i
            if type_key not in row or not row[type_key]:
                continue
            powers.append({
                "type_name": row[type_key],
                "param1": _tsv_int(row.get("%s.value1" % type_key)),
                "param2": _tsv_int(row.get("%s.value2" % type_key)),
            })
        out.append({
            "name": row["name"],
            "base_item_id_name": row["uniqueBaseItem"],
            "min_level": _tsv_int(row["minLevel"]),
            "value": _tsv_int(row["value"]),
            "powers": powers,
        })
    return out


def compare_with_tsv():
    """Compare the authoritative 1.5.5 tables against the 1.6.0 TSV assets.

    Returns a dict with per-field difference counts and a few examples.  This is
    used by the test suite / report to document *why* the TSVs are not used.
    """
    tsv_items = parse_itemdat_tsv()
    src_items = [r for r in _BASE_FINAL if r["name"] and r["available"]]
    by_id = {r["id"]: r for r in src_items if r["id"]}
    by_name = {}
    for r in src_items:
        by_name.setdefault(r["name"], r)
    numeric = ["durability", "min_dam", "max_dam", "min_ac", "max_ac",
               "min_str", "min_mag", "min_dex", "value", "min_mlvl"]
    diffs = {field: [] for field in numeric}
    matched = 0
    unmatched = []
    for row in tsv_items:
        src = by_id.get(row["id"]) or by_name.get(row["name"])
        if src is None:
            unmatched.append(row.get("id") or row.get("name"))
            continue
        matched += 1
        for field in numeric:
            if row[field] != src[field]:
                diffs[field].append((row["name"], src[field], row[field]))
    return {
        "source_items": len(src_items),
        "tsv_items": len(tsv_items),
        "matched_by_id_or_name": matched,
        "unmatched_tsv_rows": unmatched,
        "field_diffs": {k: v for k, v in diffs.items() if v},
        "total_field_diffs": sum(len(v) for v in diffs.values()),
        "examples": {
            k: v[:5] for k, v in diffs.items() if v
        },
    }


if __name__ == "__main__":  # tiny self check
    print("source:", SOURCE_DIR)
    print("base items:", len(_RAW_BASE_ITEMS),
          "available:", len(base_items(include_unavailable=False, include_starter=True,
                                       include_unique_only=True, include_non_equipment=True)))
    print("generatable:", len(base_items()),
          "| starter:", sum(1 for r in _BASE_FINAL if r["starter"]),
          "| unique_only:", sum(1 for r in _BASE_FINAL if r["unique_only"]),
          "| non-equipment:", sum(1 for r in _BASE_FINAL if not r["equipment"]))
    print("starter rows:", [(r["idx"], r["saved_idx"], r["id"], r["name"])
                            for r in _BASE_FINAL if r["starter"]])
    print("prefixes:", len(PREFIXES), "suffixes:", len(SUFFIXES), "uniques:", len(UNIQUES))
    print("spells:", len(SPELLS), "cursor sizes:", len(ITEM_CURSOR_SIZE))
    for name in ("Short Sword", "Leather Armor", "Amulet", "Ring", "Book of "):
        b = base_by_name(name)
        print(name, "->", None if not b else (b["idx"], b["saved_idx"], b["itype_name"],
                                              b["size"], b["durability"], b["value"]))
    print("saved 154 ->", base_by_saved_idx(154)["name"],
          "runtime", base_by_saved_idx(154)["idx"])
    comp = compare_with_tsv()
    print("TSV diff fields:", {k: len(v) for k, v in comp["field_diffs"].items()})
