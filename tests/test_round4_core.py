#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 4 core tests: max base stats, spell staves, all affixes, ilvl bands.

Run with Python 3.12 from the repository root::

    python tests/test_round4_core.py

What this suite covers (see work/docs/ROUND4_BRIEF.md section 3.1):

* ``generate(max_ac=True, full_durability=True)``: the recorded ``AC`` is the
  base table's ``max_ac`` and ``durability == maxDur`` (written straight into
  the 368-byte record), ``validate(allow_ac_override=True)`` is clean while the
  default ``validate()`` reports **only** the AC replay mismatch.
  ``GenItem._extra`` reports ``applied_max_ac`` / ``applied_full_durability`` /
  ``base_stats_note``.  Indestructible items and AC-less bases are skipped.
* ``base_stats_conflict``: ``max_ac`` cannot coexist with an ``IPL_SETAC``
  affix (synthetic row) nor with a ``IPL_SETAC`` unique power (Arkaine's Valor).
* ``staff_spell`` / ``staff_charges``: normal staves (the game's own 75% path)
  and magical spell staves (``allow_staff_spells=True``, prefix only), English
  and Chinese spell names, exact charges, ``validate()`` clean; error codes
  ``bad_staff_spell`` / ``bad_staff_charges`` / ``staff_spell_suffix``.
* ``staff_spells()``: the GetStaffSpell selection domain with ``min_ilvl``.
* ``all_affixes()`` / ``affix_ilvl_band()``: the ilvl-ignoring affix list is a
  superset of ``eligible_affixes()``, and the band ``[L, min(2L+1, 50)]`` /
  ``[L, 50]`` agrees with the game's ``[ilvl//2, ilvl]`` window at ilvl 20/30/50.

Safety: **nothing** is written to disk.  Every test only builds in-memory
``GenItem`` records; ``%APPDATA%\diasurgical\devilution\`` is never touched.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import d1tables as T          # noqa: E402
import d1i18n as I            # noqa: E402
import d1itemgen as G         # noqa: E402

#: ``check_combination`` must keep returning exactly these keys (the adapter
#: and the Round 3 tests rely on it).
RESULT_KEYS = {"ok", "code", "message", "suggestions", "prefix", "suffix"}

#: ``staff_spells()`` rows must at least carry these keys.
SPELL_KEYS = {"id", "name", "cn", "staff_min", "staff_max", "min_int", "min_ilvl"}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _base(name):
    rec = T.base_by_name(name)
    check(rec is not None, "base item %r not found in d1tables" % (name,))
    return rec


def _idx(name):
    return _base(name)["idx"]


def _expect_error(code, fn, *args, **kwargs):
    """Run ``fn`` and require an ``ItemGenError`` with the given ``code``."""
    try:
        fn(*args, **kwargs)
    except G.ItemGenError as exc:
        check(exc.code == code,
              "expected code %r, got %r (%s)" % (code, exc.code, exc))
        return exc
    raise AssertionError("expected ItemGenError(%r), nothing was raised" % (code,))


def _spell_row(spell_id):
    for row in G.staff_spells():
        if row["id"] == int(spell_id):
            return row
    raise AssertionError("spell %r is missing from staff_spells()" % (spell_id,))


# ---------------------------------------------------------------------------
# staff_spells()
# ---------------------------------------------------------------------------

def test_staff_spells_table():
    """staff_spells(): GetStaffSpell domain + min_ilvl derived from staff_lvl."""
    rows = G.staff_spells()
    check(len(rows) >= 20, "expected ~24 staff spells, got %d" % len(rows))
    ids = [r["id"] for r in rows]
    check(len(set(ids)) == len(ids), "staff_spells() returned duplicate ids")
    check(ids == sorted(ids), "staff_spells() should be in SpellID order")

    for row in rows:
        missing = SPELL_KEYS - set(row)
        check(not missing, "staff_spells() row %r misses %r" % (row.get("name"), missing))
        check(row["name"] and row["cn"], "row needs both names: %r" % (row,))
        check(0 < row["staff_min"] <= row["staff_max"],
              "bad charge range %r" % (row,))
        level = G._get_staff_spell_level(row["id"])
        check(level != -1, "%s must be usable on a staff" % row["name"])
        # GetStaffSpell() uses l = ilvl // 2 with 0 bumped to 1, so level 1
        # already works at ilvl 1 while level L >= 2 needs ilvl >= 2L.
        expected = 1 if level <= 1 else 2 * level
        check(row["min_ilvl"] == expected,
              "min_ilvl %r should be %d for %s (staff_lvl %d)"
              % (row["min_ilvl"], expected, row["name"], level))

    firebolt = _spell_row(T.SPELL_ID["Firebolt"])
    check(firebolt["id"] == 1 and firebolt["min_ilvl"] == 1,
          "Firebolt (staff_lvl 1) should be reachable at ilvl 1: %r" % (firebolt,))
    healing = _spell_row(T.SPELL_ID["Healing"])
    check(healing["min_ilvl"] == 1,
          "every staff_lvl 1 spell should need ilvl 1 only: %r" % (healing,))
    apocalypse = _spell_row(T.SPELL_ID["Apocalypse"])
    check(apocalypse["min_ilvl"] == 30,
          "Apocalypse (staff_lvl 15) should need ilvl 30: %r" % (apocalypse,))
    check(I.spell_name_cn(1) in [r["cn"] for r in rows],
          "the Chinese name from d1i18n should be used (Firebolt)")
    for bad in ("Null", "Identify", "Resurrect", "HealOther"):
        sid = T.SPELL_ID.get(bad)
        check(sid not in ids, "%s must not be in the staff spell list" % bad)
    print("    %d staff spells; Firebolt min_ilvl=%d, Apocalypse min_ilvl=%d"
          % (len(rows), firebolt["min_ilvl"], apocalypse["min_ilvl"]))

    # ilvl 1 really produces Firebolt (the pre-fix formula claimed ilvl 2)
    item = G.generate(_idx("Long Staff"), 1, "normal", seed=3, max_tries=20000,
                      staff_spell="Firebolt")
    check(item.fields["spell"] == T.SPELL_ID["Firebolt"],
          "ilvl=1 must be able to roll Firebolt: %r" % (item.fields,))
    check(G.validate(item.record) == [], "the ilvl=1 staff must validate")
    print("    ilvl=1 Firebolt: %r charges=%d" % (item.fields["iName"],
                                                  item.fields["charges"]))


# ---------------------------------------------------------------------------
# (e) all_affixes() / affix_ilvl_band()
# ---------------------------------------------------------------------------

def test_all_affixes_superset():
    """all_affixes() ignores ilvl and is a superset of eligible_affixes()."""
    names = ["Long Sword", "Chain Mail", "Long Staff", "Ring", "Short Bow",
             "Small Shield", "Cap", "Buckler"]
    for name in names:
        idx = _idx(name)
        for kind in ("prefix", "suffix"):
            every = G.all_affixes(idx, kind)
            check(every, "%s %s: all_affixes() is empty" % (name, kind))
            indices = [a["index"] for a in every]
            check(len(set(indices)) == len(indices),
                  "%s %s: duplicate affixes %r" % (name, kind, indices))
            check(all(a.get("kind") == kind for a in every),
                  "%s %s: every row must carry kind=%r" % (name, kind, kind))
            check([a["min_level"] for a in every] == sorted(a["min_level"] for a in every),
                  "%s %s: rows should be sorted by min_level" % (name, kind))
            for row in every:
                lo, hi = G.affix_ilvl_band(row)
                check((row["ilvl_min"], row["ilvl_max"]) == (lo, hi),
                      "%s %s: ilvl_min/max %r != band %r"
                      % (name, kind, (row["ilvl_min"], row["ilvl_max"]), (lo, hi)))

            for ilvl in (1, 10, 20, 30, 40, 50):
                eligible = G.eligible_affixes(idx, ilvl, kind)
                check(len(every) >= len(eligible),
                      "%s %s ilvl=%d: all_affixes %d < eligible %d"
                      % (name, kind, ilvl, len(every), len(eligible)))
                have = set(indices)
                missing = [a["index"] for a in eligible if a["index"] not in have]
                check(not missing,
                      "%s %s ilvl=%d: eligible affixes missing from all_affixes: %r"
                      % (name, kind, ilvl, missing))
            print("    %-12s %-6s all=%2d eligible(ilvl 1/20/50)=%2d/%2d/%2d"
                  % (name, kind, len(every),
                     len(G.eligible_affixes(idx, 1, kind)),
                     len(G.eligible_affixes(idx, 20, kind)),
                     len(G.eligible_affixes(idx, 50, kind))))

    check(G.all_affixes(_base("Short Sword")["idx"], "suffix"),
          "weapons must have suffixes")


def test_affix_ilvl_band():
    """band == the ilvl range where [ilvl//2, ilvl] contains the affix level."""
    brutal = [a for a in T.PREFIXES if a["name"] == "Brutal"]
    check(len(brutal) == 1, "expected exactly one Brutal prefix")
    check(G.affix_ilvl_band(brutal[0]) == (16, 33),
          "Brutal (min_level 16) band should be 16~33, got %r"
          % (G.affix_ilvl_band(brutal[0]),))
    heavens = [a for a in T.SUFFIXES if a["name"] == "the heavens"]
    check(heavens, "suffix 'the heavens' missing from the table")
    check(G.affix_ilvl_band(heavens[0]) == (max(1, heavens[0]["min_level"]), 50),
          "a level>=25 affix must reach ilvl 50: %r" % (G.affix_ilvl_band(heavens[0]),))

    # the three item levels the contract names, checked against the real window
    for ilvl in (20, 30, 50):
        minlvl, maxlvl = G._affix_window(ilvl)
        for aff in T.PREFIXES + T.SUFFIXES:
            level = int(aff["min_level"])
            if level > 50:      # unreachable at ilvl<=50, band is clamped
                continue
            lo, hi = G.affix_ilvl_band(dict(aff))
            in_band = lo <= ilvl <= hi
            in_window = minlvl <= level <= maxlvl
            check(in_band == in_window,
                  "ilvl=%d %s「%s」lvl=%d: band %r says %s, window %r says %s"
                  % (ilvl, aff["kind"], aff["name"], level, (lo, hi), in_band,
                     (minlvl, maxlvl), in_window))
        print("    ilvl=%2d window %d..%d: all bands agree" % (ilvl, minlvl, maxlvl))

    # explicit contract examples
    check(16 <= 20 <= 33 and 16 <= 30 <= 33 and not (16 <= 50 <= 33),
          "Brutal must be usable at ilvl 20/30 but not at 50")
    check(not (21 <= 20 <= 43) and 21 <= 30 <= 43,
          "a level-21 affix must not work at ilvl 20 but work at 30")

    # clamping to the GUI's 1..50 range; levels above 50 are *unreachable* and
    # are reported as lo > hi instead of a fake "50~50" range
    fake = {"min_level": 0, "power_name": "IPL_STR", "name": "fake"}
    check(G.affix_ilvl_band(fake) == (1, 3), "min_level 0 must clamp to 1~3")
    fake["min_level"] = 60
    check(G.affix_ilvl_band(fake) == (60, 50),
          "min_level 60 must report lo>hi: %r" % (G.affix_ilvl_band(fake),))
    high = [a for a in T.PREFIXES + T.SUFFIXES if a["min_level"] > 50]
    check(high, "expected some level>50 affixes in the table")
    for aff in high:
        lo, hi = G.affix_ilvl_band(dict(aff))
        check(lo > hi and lo == aff["min_level"] and hi == 50,
              "level>50 affix %r must be unreachable (lo>hi), got %r"
              % (aff["name"], (lo, hi)))
    # ... and no ilvl <= 50 can actually roll them
    for ilvl in (20, 30, 50):
        minlvl, maxlvl = G._affix_window(ilvl)
        for aff in high:
            check(not (minlvl <= aff["min_level"] <= maxlvl),
                  "level>50 affix %r must not be in the ilvl=%d window"
                  % (aff["name"], ilvl))
    print("    Brutal 16~33, level-21 affix 21~43, levels>=25 reach 50, "
          "%d level>50 affixes -> (L, 50)" % len(high))


# ---------------------------------------------------------------------------
# (a) max_ac / full_durability
# ---------------------------------------------------------------------------

def test_max_ac_and_full_durability():
    """max_ac/full_durability are written into the record and validated."""
    base = _base("Chain Mail")
    item = G.generate(base["idx"], 20, "normal", seed=12345,
                      max_ac=True, full_durability=True)
    check(item.fields["AC"] == base["max_ac"],
          "AC %d should be base max_ac %d" % (item.fields["AC"], base["max_ac"]))
    check(item.fields["durability"] == item.fields["maxDur"] == base["durability"],
          "durability %d/%d should be the full %d"
          % (item.fields["durability"], item.fields["maxDur"], base["durability"]))
    check(item._extra["applied_max_ac"] is True, "_extra.applied_max_ac should be True")
    check(item._extra["applied_full_durability"] is True,
          "_extra.applied_full_durability should be True")
    check(item._extra["base_stats_note"], "_extra.base_stats_note should not be empty")
    check(len(item.record) == G.RECORD_SIZE, "record must stay 368 bytes")

    check(G.validate(item.record, allow_ac_override=True) == [],
          "validate(allow_ac_override=True) must be clean: %r"
          % (G.validate(item.record, allow_ac_override=True),))
    problems = G.validate(item.record)
    check(len(problems) == 1, "default validate should only report AC, got %r" % (problems,))
    check("AC" in problems[0] and "replay mismatch" in problems[0],
          "the only problem must be the AC replay mismatch: %r" % (problems,))
    print("    normal %s: AC=%d dur=%d/%d  default validate -> %r"
          % (base["name"], item.fields["AC"], item.fields["durability"],
             item.fields["maxDur"], problems))

    # a magical armour keeps its affixes while AC/durability are forced
    magic = G.generate(base["idx"], 20, "magic", prefix="Crimson", seed=1,
                       max_ac=True, full_durability=True)
    check(magic.fields["AC"] == base["max_ac"], "magic AC should be max_ac")
    check(magic.fields["durability"] == magic.fields["maxDur"] == base["durability"],
          "magic durability should be full")
    check(magic.fields["magical"] == G.ITEM_QUALITY_MAGIC, "should still be magical")
    check(G.validate(magic.record, allow_ac_override=True) == [],
          "magic record with forced stats must validate: %r"
          % (G.validate(magic.record, allow_ac_override=True),))
    print("    magic  %s: %s  AC=%d dur=%d  validate ok"
          % (base["name"], magic.fields["iName"], magic.fields["AC"],
             magic.fields["durability"]))

    # untouched generation still replays exactly (no allow_ac_override needed)
    plain = G.generate(base["idx"], 20, "normal", seed=12345)
    check(G.validate(plain.record) == [],
          "a normal record must still validate without allow_ac_override")


def test_max_stats_skips_not_applicable():
    """full_durability skips indestructible items; max_ac skips AC-less bases."""
    sword = _base("Long Sword")
    weapon = G.generate(sword["idx"], 30, "normal", seed=5,
                        max_ac=True, full_durability=True)
    check(weapon._extra["applied_max_ac"] is False,
          "a sword has max_ac=0, applied_max_ac must be False")
    check("护甲" in weapon._extra["base_stats_note"],
          "the note should explain why max_ac did nothing: %r"
          % (weapon._extra["base_stats_note"],))
    check(weapon._extra["applied_full_durability"] is True,
          "a sword is not indestructible, durability should be forced")
    check(weapon.fields["durability"] == weapon.fields["maxDur"],
          "durability should equal maxDur")

    # Leather of Aut carries IPL_INDESTRUCTIBLE -> maxDur/durability are 255
    indestr = G.generate(None, 30, "unique", unique="Leather of Aut",
                         full_durability=True)
    check(indestr.fields["maxDur"] == G.DUR_INDESTRUCTIBLE,
          "Leather of Aut should be indestructible (255), got %r"
          % (indestr.fields["maxDur"],))
    check(indestr._extra["applied_full_durability"] is False,
          "indestructible items must skip full_durability")
    check("不可破坏" in indestr._extra["base_stats_note"],
          "the note should mention indestructibility: %r"
          % (indestr._extra["base_stats_note"],))
    check(G.validate(indestr.record) == [],
          "the untouched unique should validate: %r" % (G.validate(indestr.record),))
    print("    sword note=%r | indestructible note=%r"
          % (weapon._extra["base_stats_note"], indestr._extra["base_stats_note"]))


# ---------------------------------------------------------------------------
# (b) base_stats_conflict (max_ac vs IPL_SETAC)
# ---------------------------------------------------------------------------

def test_setac_conflict():
    """max_ac is refused when the affix/unique sets AC outright."""
    chain = _base("Chain Mail")
    setac = dict(T.PREFIXES[0])          # any real row, effect replaced
    setac["power_name"] = "IPL_SETAC"
    setac["power"] = 75
    exc = _expect_error("base_stats_conflict", G.generate, chain["idx"], 20, "magic",
                        prefix=setac, max_ac=True)
    check("取消护甲满值" in str(exc), "the message should suggest dropping max_ac: %s" % exc)
    check(any("换一个" in s for s in exc.suggestions),
          "suggestions should offer switching the affix: %r" % (exc.suggestions,))

    # Arkaine's Valor's first power is IPL_SETAC
    arkaine = T.unique_by_name("Arkaine's Valor")
    check(arkaine is not None, "Arkaine's Valor missing from the unique table")
    _expect_error("base_stats_conflict", G.generate, None, 30, "unique",
                  unique="Arkaine's Valor", max_ac=True)

    # same rule in check_combination (before any seed search)
    combo = G.check_combination(chain["idx"], 20, "magic", prefix=setac, max_ac=True)
    check(set(combo) == RESULT_KEYS, "result keys changed: %r" % (sorted(combo),))
    check(not combo["ok"] and combo["code"] == "base_stats_conflict",
          "check_combination should report base_stats_conflict: %r" % (combo,))
    combo = G.check_combination(None, 30, "unique", unique_id="Arkaine's Valor",
                                max_ac=True)
    check(combo["code"] == "base_stats_conflict",
          "unique SETAC conflict missing in check_combination: %r" % (combo,))
    # ... while an ordinary armour is fine
    combo = G.check_combination(chain["idx"], 20, "magic", max_ac=True)
    check(combo["ok"], "max_ac on a normal armour must stay legal: %r" % (combo,))
    print("    prefix conflict + unique conflict (Arkaine's Valor) both refused")


# ---------------------------------------------------------------------------
# (c) normal staves with a chosen spell / charges
# ---------------------------------------------------------------------------

def test_normal_staff_spell():
    """Normal staves accept staff_spell/staff_charges (English and Chinese)."""
    staff = _base("Long Staff")
    firebolt = _spell_row(T.SPELL_ID["Firebolt"])
    charges = firebolt["staff_min"] + 17
    check(firebolt["staff_min"] <= charges <= firebolt["staff_max"],
          "test charges must be inside the Firebolt range")

    item = G.generate(staff["idx"], 30, "normal", seed=1, max_tries=20000,
                      staff_spell="Firebolt", staff_charges=charges)
    check(item.fields["spell"] == T.SPELL_ID["Firebolt"],
          "spell %r should be Firebolt" % (item.fields["spell"],))
    check(item.fields["charges"] == charges, "charges %r != %d"
          % (item.fields["charges"], charges))
    check(item.fields["maxCharges"] == charges,
          "maxCharges should equal charges for a staff spell")
    check(item.fields["magical"] == G.ITEM_QUALITY_NORMAL,
          "a normal staff must stay ITEM_QUALITY_NORMAL")
    check("Firebolt" in item.fields["iName"],
          "the name should be '<base> of Firebolt': %r" % (item.fields["iName"],))
    check(G.validate(item.record) == [],
          "normal spell staff must replay exactly: %r" % (G.validate(item.record),))
    print("    %s: %r spell=%d charges=%d/%d"
          % (staff["name"], item.fields["iName"], item.fields["spell"],
             item.fields["charges"], item.fields["maxCharges"]))

    cn = I.spell_name_cn(T.SPELL_ID["Firebolt"])
    item_cn = G.generate(staff["idx"], 30, "normal", seed=99, max_tries=20000,
                         staff_spell=cn, staff_charges=charges)
    check(item_cn.fields["spell"] == T.SPELL_ID["Firebolt"],
          "the Chinese name %r should resolve to Firebolt" % (cn,))
    check(item_cn.fields["charges"] == charges, "Chinese variant charges mismatch")
    check(G.validate(item_cn.record) == [], "Chinese variant must validate")
    print("    Chinese name %r resolved to spell %d" % (cn, item_cn.fields["spell"]))


def test_normal_staff_charges_only():
    """staff_charges without staff_spell still matches any rolled spell."""
    staff = _base("Long Staff")
    item = G.generate(staff["idx"], 30, "normal", seed=1, max_tries=50000,
                      staff_charges=57)
    check(item.fields["charges"] == 57, "charges %r != 57" % (item.fields["charges"],))
    spell = T.spell_by_id(item.fields["spell"])
    check(spell is not None, "a spell must have been rolled")
    check(spell["staff_min"] <= 57 <= spell["staff_max"],
          "57 charges must be inside %s's range %d~%d"
          % (spell["name"], spell["staff_min"], spell["staff_max"]))
    check(G.validate(item.record) == [], "charges-only staff must validate")
    print("    charges 57 rolled on %s (%d~%d)"
          % (spell["name"], spell["staff_min"], spell["staff_max"]))


# ---------------------------------------------------------------------------
# (d) magical spell staves
# ---------------------------------------------------------------------------

def test_magic_spell_staff():
    """allow_staff_spells=True gives a magical spell staff (prefix, no suffix)."""
    staff = _base("Long Staff")
    apocalypse = _spell_row(T.SPELL_ID["Apocalypse"])
    charges = 10
    check(apocalypse["staff_min"] <= charges <= apocalypse["staff_max"],
          "10 charges must be inside the Apocalypse range")

    item = G.generate(staff["idx"], 30, "magic", seed=1, max_tries=50000,
                      allow_staff_spells=True, staff_spell="Apocalypse",
                      staff_charges=charges)
    check(item.fields["magical"] == G.ITEM_QUALITY_MAGIC,
          "a spell staff with a prefix must be magical")
    check(item.prefix is not None, "GetStaffPower() must have chosen a prefix")
    check(item.suffix is None, "spell staves never get a suffix")
    check(item.fields["spell"] == T.SPELL_ID["Apocalypse"],
          "spell %r should be Apocalypse" % (item.fields["spell"],))
    check(item.fields["charges"] == charges, "charges %r != %d"
          % (item.fields["charges"], charges))
    check(G.validate(item.record) == [],
          "magical spell staff must replay exactly: %r" % (G.validate(item.record),))
    print("    %r prefix=%s spell=%d charges=%d validate ok"
          % (item.fields["iName"], item.prefix["name"], item.fields["spell"],
             item.fields["charges"]))

    # an explicitly requested prefix + spell + charges
    item2 = G.generate(staff["idx"], 30, "magic", seed=1, max_tries=60000,
                       allow_staff_spells=True, prefix="Knight's",
                       staff_spell="Apocalypse", staff_charges=charges)
    check(item2.prefix is not None and item2.prefix["name"] == "Knight's",
          "prefix should be Knight's, got %r" % (item2.prefix,))
    check(item2.fields["spell"] == T.SPELL_ID["Apocalypse"],
          "spell should be Apocalypse")
    check(item2.fields["charges"] == charges, "charges should match")
    check(G.validate(item2.record) == [],
          "requested prefix + spell staff must validate: %r"
          % (G.validate(item2.record),))
    print("    %r (seed %d) validate ok" % (item2.fields["iName"], item2.seed))


def test_require_staff_spell():
    """require_staff_spell=True always yields spell > 0 and charges > 0."""
    staff = _base("Long Staff")

    # magical: without the flag the cheap branch happily returns a stat staff
    stat = G.generate(staff["idx"], 30, "magic", seed=1, max_tries=20000,
                      allow_staff_spells=True)
    # (this one may or may not carry a spell -- that is exactly the problem)
    print("    allow_staff_spells only: %r spell=%d charges=%d"
          % (stat.fields["iName"], stat.fields["spell"], stat.fields["charges"]))

    for seed in (1, 2, 3, 4, 5):
        magic = G.generate(staff["idx"], 30, "magic", seed=seed, max_tries=20000,
                           require_staff_spell=True)
        check(magic.fields["spell"] > 0 and magic.fields["charges"] > 0,
              "require_staff_spell seed=%d returned spell=%d charges=%d"
              % (seed, magic.fields["spell"], magic.fields["charges"]))
        check(magic.fields["magical"] == G.ITEM_QUALITY_MAGIC,
              "a spell staff needs a prefix to be magical")
        check(magic.prefix is not None and magic.suffix is None,
              "spell staves have a prefix and no suffix")
        check(G.validate(magic.record) == [],
              "required spell staff must validate: %r" % (G.validate(magic.record),))
    print("    5/5 seeds: %r spell=%d charges=%d"
          % (magic.fields["iName"], magic.fields["spell"], magic.fields["charges"]))

    # normal rarity: the "random spell" staff of the game
    normal = G.generate(staff["idx"], 30, "normal", seed=1, max_tries=20000,
                        require_staff_spell=True)
    check(normal.fields["spell"] > 0 and normal.fields["charges"] > 0,
          "a normal staff with require_staff_spell must carry a spell")
    check(normal.fields["magical"] == G.ITEM_QUALITY_NORMAL,
          "normal spell staves stay quality normal")
    check(G.validate(normal.record) == [], "normal required-spell staff must validate")

    # rules: check_combination accepts it and explains the requirement
    combo = G.check_combination(staff["idx"], 30, "magic", require_staff_spell=True)
    check(set(combo) == RESULT_KEYS, "result keys changed: %r" % (sorted(combo),))
    check(combo["ok"], "a random spell staff is a legal request: %r" % (combo,))
    check("法术" in combo["message"],
          "the message should mention the spell requirement: %r" % (combo["message"],))
    suffix = G.check_combination(staff["idx"], 30, "magic", suffix="of the fox",
                                 require_staff_spell=True)
    check(suffix["code"] == "staff_spell_suffix",
          "a required spell staff cannot have a suffix: %r" % (suffix,))
    _expect_error("bad_staff_spell", G.generate, _idx("Long Sword"), 30, "normal",
                  require_staff_spell=True)
    _expect_error("bad_staff_spell", G.generate, staff["idx"], 30, "unique",
                  require_staff_spell=True)
    check(G.check_combination(_idx("Long Sword"), 30, "normal",
                              require_staff_spell=True)["code"] == "bad_staff_spell",
          "require_staff_spell on a sword must fail the pre-check")
    print("    normal %r, magic %r; non-staff/unique refused"
          % (normal.fields["iName"], magic.fields["iName"]))


def test_full_durability_over_255():
    """full_durability never writes a maxDur above the 255 sentinel."""
    plate = _base("Gothic Plate")
    check(plate["durability"] == 100, "Gothic Plate durability changed: %r"
          % (plate["durability"],))
    # suffix of structure (IPL_DUR 101..200%) pushes maxDur past 255 on seed 397
    item = G.generate(plate["idx"], 20, "magic", suffix="structure", seed=397,
                      full_durability=True)
    check(item.fields["maxDur"] > G.DUR_INDESTRUCTIBLE,
          "this test needs maxDur > 255, got %r" % (item.fields["maxDur"],))
    check(item._extra["applied_full_durability"] is False,
          "maxDur > 255 must not be forced to full")
    check(str(G.DUR_INDESTRUCTIBLE) in item._extra["base_stats_note"],
          "the note should mention the 255 limit: %r"
          % (item._extra["base_stats_note"],))
    check(item.fields["durability"] < item.fields["maxDur"],
          "durability must stay at its natural roll")
    check(G.validate(item.record) == [],
          "an over-255 maxDur item must still validate: %r"
          % (G.validate(item.record),))
    print("    Gothic Plate of structure: maxDur=%d dur=%d note=%r"
          % (item.fields["maxDur"], item.fields["durability"],
             item._extra["base_stats_note"]))


def test_spell_search_full_budget():
    """Spell/charges requests use the full max_tries budget, not the 10k loop."""
    staff = _base("Long Staff")
    bone = _spell_row(T.SPELL_ID["BoneSpirit"])
    # Bone Spirit + 40 charges: the first matching seed is 10013, i.e. just
    # beyond the old `min(max_tries, 10000)` cheap loop.
    item = G.generate(staff["idx"], 30, "magic", seed=1, max_tries=12000,
                      allow_staff_spells=True, staff_spell="Bone Spirit",
                      staff_charges=40)
    check(item.fields["spell"] == bone["id"],
          "spell %r should be Bone Spirit (%d)" % (item.fields["spell"], bone["id"]))
    check(item.fields["charges"] == 40, "charges %r != 40" % (item.fields["charges"],))
    check(item.seed > 10000,
          "this case only proves the fix when the hit is beyond 10k seeds, got %d"
          % (item.seed,))
    check(G.validate(item.record) == [], "the found staff must validate")
    print("    Bone Spirit/40 charges found at seed %d (> 10000)" % (item.seed,))


def test_staff_spell_level_guard():
    """A spell the ilvl cannot reach is refused before any seed search."""
    staff = _base("Long Staff")
    apocalypse = _spell_row(T.SPELL_ID["Apocalypse"])
    need = apocalypse["min_ilvl"]
    check(need == 30, "Apocalypse should need ilvl 30, got %r" % (need,))

    exc = _expect_error("level_window", G.generate, staff["idx"], 20, "normal",
                        staff_spell="Apocalypse")
    text = str(exc)
    check("需要物品等级" in text and str(need) in text,
          "the message should name the required ilvl: %s" % text)
    check(any("把 ilvl 提到 %d" % need in s for s in exc.suggestions),
          "suggestions should offer the required ilvl: %r" % (exc.suggestions,))

    combo = G.check_combination(staff["idx"], 20, "normal", staff_spell="Apocalypse")
    check(set(combo) == RESULT_KEYS, "result keys changed: %r" % (sorted(combo),))
    check(combo["code"] == "level_window",
          "check_combination should report level_window: %r" % (combo,))
    check(str(need) in combo["message"], "the message should name the ilvl: %r"
          % (combo["message"],))
    check(any("把 ilvl 提到 %d" % need in s for s in combo["suggestions"]),
          "the suggestions should name the ilvl: %r" % (combo["suggestions"],))

    # at exactly min_ilvl the same request is legal (and generation works)
    ok = G.check_combination(staff["idx"], need, "normal", staff_spell="Apocalypse")
    check(ok["ok"], "ilvl=%d should be legal for Apocalypse: %r" % (need, ok))
    item = G.generate(staff["idx"], need, "normal", seed=1, max_tries=20000,
                      staff_spell="Apocalypse")
    check(item.fields["spell"] == T.SPELL_ID["Apocalypse"], "should have rolled it")
    check(G.validate(item.record) == [], "the boundary item must validate")

    # every staff spell follows its own min_ilvl
    for row in G.staff_spells()[:6]:
        below = max(0, row["min_ilvl"] - 1)
        if below == 0:
            continue
        _expect_error("level_window", G.generate, staff["idx"], below, "normal",
                      staff_spell=row["id"])
        ok = G.check_combination(staff["idx"], row["min_ilvl"], "normal",
                                 staff_spell=row["id"])
        check(ok["ok"], "ilvl=%d should be legal for %s: %r"
              % (row["min_ilvl"], row["name"], ok))
    print("    Apocalypse needs ilvl>=%d; ilvl=%d refused, ilvl=%d generates %r"
          % (need, 20, need, item.fields["iName"]))


def test_staff_error_codes():
    """bad_staff_spell / bad_staff_charges / staff_spell_suffix."""
    staff = _base("Long Staff")
    sword = _base("Long Sword")
    apocalypse = _spell_row(T.SPELL_ID["Apocalypse"])

    exc = _expect_error("staff_spell_suffix", G.generate, staff["idx"], 30, "magic",
                        allow_staff_spells=True, staff_spell="Apocalypse",
                        suffix="of the fox")
    check("去掉后缀" in "".join(exc.suggestions) or "去掉后缀" in str(exc),
          "the suffix error should tell the user to drop the suffix: %r"
          % (exc.suggestions,))

    _expect_error("bad_staff_spell", G.generate, staff["idx"], 30, "magic",
                  staff_spell="Apocalypse")           # allow_staff_spells missing
    _expect_error("bad_staff_spell", G.generate, staff["idx"], 30, "unique",
                  staff_spell="Apocalypse")
    _expect_error("bad_staff_spell", G.generate, sword["idx"], 30, "normal",
                  staff_spell="Apocalypse")           # not a staff base
    _expect_error("bad_staff_spell", G.generate, staff["idx"], 30, "normal",
                  staff_spell="No Such Spell")
    _expect_error("bad_staff_spell", G.generate, staff["idx"], 30, "normal",
                  staff_spell=T.SPELL_ID["Identify"])  # never on a staff
    _expect_error("bad_staff_charges", G.generate, staff["idx"], 30, "normal",
                  staff_spell="Apocalypse", staff_charges=apocalypse["staff_max"] + 1)
    _expect_error("bad_staff_charges", G.generate, staff["idx"], 30, "normal",
                  staff_spell="Apocalypse", staff_charges=0)
    _expect_error("bad_staff_charges", G.generate, staff["idx"], 30, "normal",
                  staff_spell="Apocalypse", staff_charges="many")
    print("    staff_spell_suffix / bad_staff_spell x5 / bad_staff_charges x3")


def test_check_combination_staff():
    """check_combination validates the staff options without searching seeds."""
    staff = _base("Long Staff")
    sword = _base("Long Sword")

    ok = G.check_combination(staff["idx"], 30, "normal",
                             staff_spell="Firebolt", staff_charges=57)
    check(set(ok) == RESULT_KEYS, "result keys changed: %r" % (sorted(ok),))
    check(ok["ok"] and ok["code"] == "ok",
          "a normal staff with a spell is legal: %r" % (ok,))
    check("Firebolt" in ok["message"], "the message should name the spell: %r"
          % (ok["message"],))

    suffix = G.check_combination(staff["idx"], 30, "magic", suffix="of the fox",
                                 allow_staff_spells=True, staff_spell="Apocalypse")
    check(suffix["code"] == "staff_spell_suffix",
          "spell staff + suffix should be staff_spell_suffix: %r" % (suffix,))
    no_allow = G.check_combination(staff["idx"], 30, "magic", staff_spell="Apocalypse")
    check(no_allow["code"] == "bad_staff_spell",
          "magic spell staff without allow_staff_spells: %r" % (no_allow,))
    non_staff = G.check_combination(sword["idx"], 30, "normal", staff_spell="Apocalypse")
    check(non_staff["code"] == "bad_staff_spell",
          "staff options on a sword should fail: %r" % (non_staff,))
    unique = G.check_combination(staff["idx"], 30, "unique", staff_spell="Apocalypse")
    check(unique["code"] == "bad_staff_spell",
          "uniques never take staff spells: %r" % (unique,))
    bad = G.check_combination(staff["idx"], 30, "normal", staff_charges=9999)
    check(bad["code"] == "bad_staff_charges",
          "out-of-range charges: %r" % (bad,))

    # legal magical spell staff (rules only, no seed search)
    legal = G.check_combination(staff["idx"], 30, "magic", prefix="Knight's",
                                allow_staff_spells=True, staff_spell="Apocalypse",
                                staff_charges=10)
    check(legal["ok"], "a magical spell staff with a prefix is legal: %r" % (legal,))
    print("    normal ok / suffix / no-allow / non-staff / unique / charges")


# ---------------------------------------------------------------------------
# validate(allow_ac_override=True) scope
# ---------------------------------------------------------------------------

def test_validate_ac_override_scope():
    """allow_ac_override skips only AC: length and other fields still checked."""
    base = _base("Chain Mail")
    item = G.generate(base["idx"], 20, "normal", seed=12345,
                      max_ac=True, full_durability=True)
    check(G.validate(item.record, allow_ac_override=True) == [], "clean record")

    check(G.validate(item.record[:10], allow_ac_override=True) ==
          ["record length is 10, expected %d" % G.RECORD_SIZE],
          "the 368-byte length check must not be skipped")

    fields = G.record_to_fields(item.record)
    fields["AC"] += 7                      # any AC is accepted with the flag
    fields["PLDam"] += 5                   # but other fields are not
    patched = G.fields_to_record(fields)
    problems = G.validate(patched, allow_ac_override=True)
    check(problems, "a corrupted PLDam must still be reported")
    check(any("PLDam" in p for p in problems),
          "the problem should be the PLDam replay mismatch: %r" % (problems,))
    check(not any("AC" in p for p in problems),
          "AC must be ignored with allow_ac_override=True: %r" % (problems,))

    # durability keeps being ignored without the flag (worn/repaired game state)
    fields = G.record_to_fields(item.record)
    fields["durability"] = max(1, fields["maxDur"] // 2)
    check(G.validate(G.fields_to_record(fields), allow_ac_override=True) == [],
          "durability must stay ignored by validate()")
    print("    AC ignored, PLDam reported, length enforced, durability ignored")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("staff_spells() selection domain", test_staff_spells_table),
    ("all_affixes() superset of eligible_affixes()", test_all_affixes_superset),
    ("affix_ilvl_band() vs the ilvl//2 window (20/30/50)", test_affix_ilvl_band),
    ("max_ac + full_durability write the record", test_max_ac_and_full_durability),
    ("max_ac/full_durability skip non-applicable items",
     test_max_stats_skips_not_applicable),
    ("base_stats_conflict (IPL_SETAC)", test_setac_conflict),
    ("normal staff with staff_spell + staff_charges", test_normal_staff_spell),
    ("normal staff with charges only", test_normal_staff_charges_only),
    ("magical spell staff (prefix, no suffix)", test_magic_spell_staff),
    ("require_staff_spell (random spell staff)", test_require_staff_spell),
    ("spell/charges search uses the full budget", test_spell_search_full_budget),
    ("full_durability above the 255 sentinel", test_full_durability_over_255),
    ("staff spell ilvl guard (min_ilvl)", test_staff_spell_level_guard),
    ("staff error codes", test_staff_error_codes),
    ("check_combination() staff rules", test_check_combination_staff),
    ("validate(allow_ac_override=True) scope", test_validate_ac_override_scope),
]


def main():
    print("Round 4 core tests (max base stats / spell staves / all affixes / bands)")
    print("python:", sys.version.split()[0], "| lib:", LIB)

    failures = 0
    start = time.time()
    for index, (name, fn) in enumerate(TESTS, start=1):
        print("\n[%d/%d] %s" % (index, len(TESTS), name))
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - test runner
            failures += 1
            print("    FAILED: %s" % exc)
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print("    OK")

    elapsed = time.time() - start
    total = len(TESTS)
    print("\n%d/%d tests passed in %.2fs" % (total - failures, total, elapsed))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
