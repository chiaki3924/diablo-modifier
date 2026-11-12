#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 3 core tests: affix effect labels, combination pre-check, stash pages.

Run with Python 3.12 from the repository root::

    python tests/test_round3_core.py

What this suite covers (see work/docs/core3_report.md):

* ``d1i18n.affix_effect_label()``: the short effect name used by the GUI
  drop-downs (火焰抗性 / 闪电抗性 / 全抗性 / 所有属性 / 法力 / 攻速 / 吸血 / 充能 ...).
* ``d1i18n.affix_label(kind, affix, with_effect=True)``: the full drop-down
  line, e.g. ``红宝石（Ruby） 火焰抗性 +51~+60`` and
  ``翼龙的（Dragon's） 法力 +51~+60``; fixed effects say ``固定效果：…``.
  A full sweep checks every prefix/suffix row uses the *generator's* own range.
* ``d1itemgen.check_combination()``: ok / bad_base / bad_affix / level_window /
  goe_conflict / fixed_affix_value / value_out_of_range / seed_not_found /
  staff_ilvl, including the Ring + Obsidian + of the heavens example at
  ilvl 20 / 30 / 40 / 50.
* ``ItemGenError.code`` on the matching ``generate()`` failures.
* ``d1stash2.Stash.add_record(record, page=...)``: 0-based pages, empty page,
  existing page, non-existent page, full page (fallback vs ``strict_page``),
  out-of-range page numbers, and save/reload of sparse pages.

Safety: every stash test works on a ``work\tmp`` copy of
``tests/fixtures/saves/stash.sv``.  The real save
(``%APPDATA%\diasurgical\devilution\stash.sv``) is only **read** and its SHA256
is compared before/after the run.
"""

from __future__ import annotations

import hashlib
import os
import shutil
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
import d1stash2 as S          # noqa: E402

TMP = os.path.join(ROOT, "tests", "tmp", "test_round3_core_%d" % os.getpid())
FIXTURES = os.environ.get("D1_TEST_SAVES") or os.path.join(
    ROOT, "tests", "fixtures", "saves")
BACKUP_STASH = os.path.join(FIXTURES, "stash.sv")
if not os.path.isfile(BACKUP_STASH):
    print("SKIP: 需要 tests/fixtures/saves/stash.sv")
    raise SystemExit(0)
LIVE_STASH = os.path.join(os.environ.get("APPDATA", ""),
                          "diasurgical", "devilution", "stash.sv")
#: 103-item live baseline (2026-11-11 20:35, 5 user-generated uniques).
#: Only the prefix is pinned -- the user may keep playing; the hard check is
#: "the test run did not change the file".
LIVE_BASELINE_SHA_PREFIX = "89CE5C08"

RESULT_KEYS = {"ok", "code", "message", "suggestions", "prefix", "suffix"}
EMPTY_GRID = [[0] * S.STASH_GRID_W for _ in range(S.STASH_GRID_H)]
FULL_GRID = [[999] * S.STASH_GRID_W for _ in range(S.STASH_GRID_H)]

LIVE_BEFORE = None


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _ring():
    return T.base_by_name("Ring")["idx"]


def _sword():
    return T.base_by_name("Long Sword")["idx"]


def _staff():
    return T.base_by_name("Long Staff")["idx"]


def _expect_fail(result, code, label, contains=()):
    check(isinstance(result, dict), "%s: result is not a dict: %r" % (label, result))
    check(set(result) == RESULT_KEYS,
          "%s: unexpected keys %r" % (label, sorted(set(result) ^ RESULT_KEYS)))
    check(result["ok"] is False, "%s: expected failure, got ok=True" % label)
    check(result["code"] == code,
          "%s: code=%r, expected %r (message: %s)"
          % (label, result["code"], code, result["message"]))
    check(bool(result["message"]), "%s: empty message" % label)
    check(isinstance(result["suggestions"], list),
          "%s: suggestions is not a list" % label)
    for hint in result["suggestions"]:
        check(isinstance(hint, str) and hint, "%s: bad suggestion %r" % (label, hint))
    for text in contains:
        check(text in result["message"],
              "%s: message does not contain %r: %s" % (label, text, result["message"]))
    return result


# ---------------------------------------------------------------------------
# 1. affix effect labels / drop-down labels
# ---------------------------------------------------------------------------

def test_affix_effect_label():
    """Short effect names the GUI needs, all reused from affix_desc's wording."""
    cases = [
        ("prefix", "Ruby", "火焰抗性"),
        ("prefix", "Sapphire", "闪电抗性"),
        ("prefix", "Obsidian", "全抗性"),
        ("prefix", "Dragon's", "法力"),
        ("prefix", "Brutal", "伤害"),
        ("prefix", "Bronze", "命中"),
        ("prefix", "Glorious", "护甲"),
        ("prefix", "Plentiful", "充能"),
        ("suffix", "of the heavens", "所有属性"),
        ("suffix", "the fox", "生命"),
        ("suffix", "strength", "力量"),
        ("suffix", "dexterity", "敏捷"),
        ("suffix", "vitality", "体力"),
        ("suffix", "magic", "魔法"),
        ("suffix", "haste", "攻速"),
        ("suffix", "the leech", "吸血"),
    ]
    for kind, name, expected in cases:
        affix = T.affix_by_name(kind, name)
        check(affix is not None, "affix table row missing: %s %r" % (kind, name))
        got = I.affix_effect_label(affix)
        check(got == expected,
              "affix_effect_label(%s %r) = %r, expected %r"
              % (kind, name, got, expected))
        print("    %-6s %-16s -> %s" % (kind, name, got))

    # a bare ItemPower name is accepted too
    check(I.affix_effect_label("IPL_FIRERES") == "火焰抗性",
          "bare IPL_FIRERES should map to 火焰抗性")
    check(I.affix_effect_label({"name": "Ruby"}) == "",
          "a name-only dict has no power information")

    # every prefix/suffix row gets a usable, non-empty effect label
    unknown = []
    for kind in ("prefix", "suffix"):
        for affix in T.affix_list(kind):
            label = I.affix_effect_label(affix)
            if not label or label == "特殊效果" or "IPL_" in label:
                unknown.append((kind, affix["name"], affix["power_name"], label))
    check(not unknown, "affixes without a readable effect name: %r" % (unknown[:10],))
    print("    all %d prefix + %d suffix rows have a readable effect name"
          % (len(T.affix_list("prefix")), len(T.affix_list("suffix"))))


def test_affix_label_with_effect():
    """Dropdown text: 中文（English） 效果名 +min~max, fixed effects say 固定效果."""
    exact = [
        ("prefix", "Ruby", "红宝石（Ruby） 火焰抗性 +51~+60"),
        ("prefix", "Sapphire", "蓝宝石（Sapphire） 闪电抗性 +51~+60"),
        ("prefix", "Diamond", "钻石（Diamond） 魔法抗性 +51~+60"),
        ("prefix", "Dragon's", "翼龙的（Dragon's） 法力 +51~+60"),
        ("prefix", "Obsidian", "黑曜石（Obsidian） 全抗性 +31~+40"),
        ("suffix", "of the heavens", "天堂（of the heavens） 所有属性 +12~+15"),
    ]
    for kind, name, expected in exact:
        affix = T.affix_by_name(kind, name)
        got = I.affix_label(kind, affix, with_effect=True)
        check(got == expected,
              "affix_label(%s %r, with_effect=True) = %r, expected %r"
              % (kind, name, got, expected))
        # with_effect=False must stay byte-identical to the old 中文（English）
        plain = I.affix_label(kind, affix)
        check(plain == "%s（%s）" % (I.affix_name_cn(kind, name), name),
              "affix_label(%s %r) changed the old format: %r" % (kind, name, plain))
        print("    %-6s %-16s -> %s" % (kind, name, got))

    # fixed effects: no fake numbers, affix_desc's 固定效果 wording
    for kind, name, effect in (
        ("suffix", "haste", "攻速"),
        ("suffix", "the ages", "耐久"),
        ("prefix", "Plentiful", "充能"),
        ("suffix", "the leech", "吸血"),
    ):
        affix = T.affix_by_name(kind, name)
        check(G.affix_value_range(affix) is None,
              "%s %r should not accept a numeric value" % (kind, name))
        label = I.affix_label(kind, affix, with_effect=True)
        check("固定效果" in label, "fixed affix %r label missing 固定效果: %s"
              % (name, label))
        check(I.affix_effect_label(affix) == effect,
              "%s %r effect label = %r, expected %r"
              % (kind, name, I.affix_effect_label(affix), effect))
        print("    %-6s %-16s -> %s" % (kind, name, label))

    # a plain English name has no dict -> old 中文（English） only
    check(I.affix_label("prefix", "Ruby", with_effect=True) == "红宝石（Ruby）",
          "plain-name with_effect=True should fall back to 中文（English）")

    # full sweep: the shown range is exactly d1itemgen's accepted range
    checked = 0
    for kind in ("prefix", "suffix"):
        for affix in T.affix_list(kind):
            base = I.affix_label(kind, affix)
            label = I.affix_label(kind, affix, with_effect=True)
            check(label.startswith(base + " "),
                  "label %r does not extend %r" % (label, base))
            rng = G.affix_value_range(affix)
            if rng is None:
                continue
            lo, hi = rng
            span = ("%+d" % lo) if lo == hi else ("%+d~%+d" % (lo, hi))
            check(label.endswith(" %s %s" % (I.affix_effect_label(affix), span)),
                  "%s %r label %r should end with effect + %r"
                  % (kind, affix["name"], label, span))
            checked += 1
    print("    %d numeric affix rows show the generator's own range" % checked)


# ---------------------------------------------------------------------------
# 2. check_combination: the Ring + Obsidian + of the heavens example
# ---------------------------------------------------------------------------

def test_combination_ok():
    ring = _ring()
    for ilvl in (30, 40):
        result = G.check_combination(ring, ilvl, "magic",
                                     prefix="Obsidian", suffix="of the heavens")
        check(set(result) == RESULT_KEYS, "result keys: %r" % sorted(result))
        check(result["ok"] is True and result["code"] == "ok",
              "ilvl=%d should be legal: %s" % (ilvl, result))
        check(isinstance(result["prefix"], dict)
              and result["prefix"]["name"] == "Obsidian",
              "resolved prefix missing: %r" % (result["prefix"],))
        check(isinstance(result["suffix"], dict)
              and result["suffix"]["name"] == "the heavens",
              "resolved suffix missing: %r" % (result["suffix"],))
        check(result["suggestions"] == [], "ok result should have no suggestions")
        print("    Ring ilvl=%d Obsidian + of the heavens -> ok" % ilvl)

    # max_tries also runs the real seed search and reports the generated name
    result = G.check_combination(ring, 30, "magic", prefix="Obsidian",
                                 suffix="of the heavens", max_tries=200000)
    check(result["ok"] is True, "seeded pre-check should find the combo: %s" % result)
    check("Obsidian Ring of the heavens" in result["message"],
          "seeded pre-check message should name the item: %s" % result["message"])
    print("    max_tries=200000 -> %s" % result["message"])


def test_combination_level_window():
    ring = _ring()
    low = G.check_combination(ring, 20, "magic",
                              prefix="Obsidian", suffix="of the heavens")
    _expect_fail(low, "level_window", "ilvl=20", ("把 ilvl 提到 24",))
    check(any("提到 24" in s for s in low["suggestions"]),
          "suggestions should include ilvl>=24: %r" % (low["suggestions"],))
    check(any("25" in s for s in low["suggestions"]),
          "the suffix of the heavens (level 25) should be mentioned too: %r"
          % (low["suggestions"],))
    check(low["prefix"] is not None and low["prefix"]["name"] == "Obsidian",
          "resolved affixes should still be reported for GUI previews")
    print("    ilvl=20 -> %s" % low["message"])

    high = G.check_combination(ring, 50, "magic",
                               prefix="Obsidian", suffix="of the heavens")
    _expect_fail(high, "level_window", "ilvl=50", ("把 ilvl 降到 49",))
    check(any("降到 49" in s for s in high["suggestions"]),
          "suggestions should include ilvl<=49: %r" % (high["suggestions"],))
    print("    ilvl=50 -> %s" % high["message"])

    # prefix-only window failure keeps the same code
    only_prefix = G.check_combination(ring, 20, "magic", prefix="Obsidian")
    _expect_fail(only_prefix, "level_window", "prefix-only ilvl=20", ("提到 24",))


def test_combination_value_errors():
    sword, ring = _sword(), _ring()

    fixed = G.check_combination(sword, 40, "magic", suffix="the ages", suffix_value=1)
    _expect_fail(fixed, "fixed_affix_value", "fixed suffix + value",
                 ("不是可指定的数值效果", "IPL_INDESTRUCTIBLE"))
    print("    fixed suffix + value -> %s" % fixed["message"][:90])

    haste = G.check_combination(sword, 40, "magic", suffix="haste", suffix_value=1)
    _expect_fail(haste, "fixed_affix_value", "attack speed + value",
                 ("不是可指定的数值效果", "IPL_FASTATTACK"))

    high = G.check_combination(ring, 40, "magic", prefix="Ruby", prefix_value=100)
    _expect_fail(high, "value_out_of_range", "Ruby +100",
                 ("最接近 +60", "+51~+60"))
    check(any("+51~+60" in s for s in high["suggestions"]),
          "out-of-range suggestions should quote the range: %r" % (high["suggestions"],))
    print("    Ruby +100 -> %s" % high["message"])

    low = G.check_combination(ring, 40, "magic", prefix="Ruby", prefix_value=10)
    _expect_fail(low, "value_out_of_range", "Ruby +10", ("最接近 +51",))

    # in-range value stays legal (no seed search by default)
    ok = G.check_combination(ring, 40, "magic", prefix="Ruby", prefix_value=55)
    check(ok["ok"] is True, "Ruby +55 should be legal: %s" % ok)
    print("    Ruby +55 -> ok")

    # value without the affix
    missing = G.check_combination(sword, 30, "magic", suffix_value=4)
    _expect_fail(missing, "bad_affix", "value without affix", ("需要同时指定",))


# ---------------------------------------------------------------------------
# 3. check_combination: bases / affixes / GOE / staff
# ---------------------------------------------------------------------------

def test_combination_bad_base():
    starter = G.check_combination(166, 10, "normal")
    _expect_fail(starter, "bad_base", "starter item", ("初始装备",))
    print("    starter -> %s" % starter["message"][:80])

    cleaver = T.base_by_name("Cleaver", include_unique_only=True)
    check(cleaver is not None and cleaver["unique_only"], "Cleaver should be unique_only")
    unique_only = G.check_combination(cleaver["idx"], 20, "magic")
    _expect_fail(unique_only, "bad_base", "unique-only base", ("unique-only",))

    gold = T.base_by_name("Gold", include_non_equipment=True)
    check(gold is not None and not gold["equipment"], "Gold should be non-equipment")
    non_equip = G.check_combination(gold["idx"], 10, "normal")
    _expect_fail(non_equip, "bad_base", "non-equipment base", ("不是可装备底材",))

    unknown = G.check_combination("No Such Item", 10, "magic")
    _expect_fail(unknown, "bad_base", "unknown base", ("找不到底材",))


def test_combination_bad_affix():
    ring = _ring()
    wrong_type = G.check_combination(ring, 30, "magic", prefix="Brutal")
    _expect_fail(wrong_type, "bad_affix", "weapon prefix on a ring", ("不适用于",))
    print("    Brutal on Ring -> %s" % wrong_type["message"][:90])

    unknown = G.check_combination(ring, 30, "magic", suffix="of nonsense")
    _expect_fail(unknown, "bad_affix", "unknown suffix", ("找不到后缀",))

    onlygood = G.check_combination(ring, 10, "magic", suffix="the pit", onlygood=True)
    _expect_fail(onlygood, "bad_affix", "onlygood + bad affix", ("onlygood",))

    normal_affix = G.check_combination(ring, 10, "normal", prefix="Ruby")
    _expect_fail(normal_affix, "bad_affix", "normal + affix", ("不能带词缀",))

    unique_affix = G.check_combination("Plate Mail", 27, "unique",
                                       unique_id=77, suffix="of the giants")
    _expect_fail(unique_affix, "bad_affix", "unique + affix", ("不能指定前缀/后缀",))


def test_combination_goe_conflict():
    ring = _ring()
    gold = T.affix_by_name("prefix", "Gold")
    trouble = T.affix_by_name("suffix", "trouble")
    check(gold["goe"] == T.GOE_GOOD and trouble["goe"] == T.GOE_EVIL,
          "Gold (good) + trouble (evil) should be the GOE test pair")

    conflict = G.check_combination(ring, 24, "magic", prefix="Gold", suffix="trouble")
    _expect_fail(conflict, "goe_conflict", "Gold + of trouble", ("善良", "邪恶", "GOE"))
    check(conflict["prefix"]["name"] == "Gold"
          and conflict["suffix"]["name"] == "trouble",
          "conflicting affixes should still be resolved")
    check(any("中立" in s for s in conflict["suggestions"]),
          "GOE suggestions should propose neutral suffixes: %r"
          % (conflict["suggestions"],))
    print("    Gold + of trouble -> %s" % conflict["message"])

    # the same prefix with a neutral suffix is fine (no GOE filter for GOE_ANY)
    neutral = T.affix_by_name("suffix", "the wolf")
    check(neutral["goe"] == T.GOE_ANY, "of the wolf should be GOE_ANY")
    ok = G.check_combination(ring, 24, "magic", prefix="Gold", suffix="the wolf")
    check(ok["ok"] is True,
          "GOE_ANY suffix must not raise goe_conflict: %s" % ok)
    print("    Gold + of the wolf (neutral) -> ok")

    # the reverse direction: evil prefix + good suffix is impossible too
    check(T.affix_by_name("prefix", "Vicious")["goe"] == T.GOE_EVIL,
          "Vicious should be evil")
    check(T.affix_by_name("suffix", "vigor")["goe"] == T.GOE_GOOD,
          "of vigor should be good")
    reverse = G.check_combination(_sword(), 24, "magic",
                                 prefix="Vicious", suffix="vigor")
    _expect_fail(reverse, "goe_conflict", "Vicious + of vigor", ("GOE",))
    print("    Vicious + of vigor -> goe_conflict")


def test_combination_staff_and_inputs():
    staff = _staff()
    bad_staff = G.check_combination(staff, 60, "magic")
    _expect_fail(bad_staff, "staff_ilvl", "staff ilvl=60", ("ilvl", "法杖"))
    check(any("51" in s for s in bad_staff["suggestions"]),
          "staff suggestion should say ilvl<=51")
    print("    staff ilvl=60 -> %s" % bad_staff["message"][:90])

    # ilvl 51 is fine for a stat staff
    ok = G.check_combination(staff, 51, "magic", suffix="haste")
    check(ok["ok"] is True, "stat staff at ilvl=51 should be legal: %s" % ok)

    bad_rarity = G.check_combination(_ring(), 10, rarity="rare")
    _expect_fail(bad_rarity, "bad_rarity", "rarity=rare", ("normal",))

    bad_ilvl = G.check_combination(_ring(), 99, "magic")
    _expect_fail(bad_ilvl, "bad_ilvl", "ilvl=99", ("0..63",))

    unique_ok = G.check_combination("Plate Mail", 27, "unique", unique_id=77)
    check(unique_ok["ok"] is True, "unique check should pass: %s" % unique_ok)

    unique_low = G.check_combination("Plate Mail", 5, "unique", unique_id=77)
    _expect_fail(unique_low, "level_window", "unique below min_level", ("把 ilvl 提到 19",))


# ---------------------------------------------------------------------------
# 4. seed_not_found + generate() error codes
# ---------------------------------------------------------------------------

def test_combination_seed_not_found():
    sword, ring = _sword(), _ring()

    # the classic double-value target: legal, but 2000 seeds are not enough
    result = G.check_combination(sword, 30, "magic", prefix="Brutal",
                                 suffix="of the giants", prefix_value=85,
                                 suffix_value=18, max_tries=2000)
    _expect_fail(result, "seed_not_found", "double value, 2000 seeds", ("最接近",))
    check(any("max_tries" in s for s in result["suggestions"]),
          "seed failure should suggest max_tries: %r" % (result["suggestions"],))
    print("    double value, 2000 seeds -> %s" % result["message"][:100])

    # a plain (no numeric target) legal combo that the budget cannot find
    plain = G.check_combination(ring, 30, "magic", prefix="Obsidian",
                                suffix="of the heavens", max_tries=20)
    _expect_fail(plain, "seed_not_found", "plain combo, 20 seeds")
    check("预算" in plain["message"] and "最接近值" in plain["message"],
          "plain seed failure should explain the budget: %s" % plain["message"])

    # the same combo with a real budget is found
    found = G.check_combination(ring, 30, "magic", prefix="Obsidian",
                                suffix="of the heavens", max_tries=200000)
    check(found["ok"] is True and found["code"] == "ok",
          "200k seeds should find the combo: %s" % found)


def test_generate_error_codes():
    """generate() must raise ItemGenError with the same machine-readable code."""
    ring, sword, staff = _ring(), _sword(), _staff()
    cases = [
        ("starter", dict(base_idx=166, ilvl=10), "bad_base"),
        ("level window", dict(base_idx=ring, ilvl=20, prefix="Obsidian"), "level_window"),
        ("fixed value", dict(base_idx=sword, ilvl=40, suffix="haste",
                             suffix_value=1), "fixed_affix_value"),
        ("out of range", dict(base_idx=ring, ilvl=40, prefix="Ruby",
                              prefix_value=100), "value_out_of_range"),
        ("staff ilvl", dict(base_idx=staff, ilvl=60), "staff_ilvl"),
        ("no seed", dict(base_idx=sword, ilvl=30, prefix="Brutal",
                         suffix="of the giants", prefix_value=85,
                         suffix_value=18, max_tries=2000, seed=1),
         "seed_not_found"),
        ("bad affix", dict(base_idx=ring, ilvl=30, prefix="Brutal"), "bad_affix"),
        ("goe", dict(base_idx=ring, ilvl=24, prefix="Gold", suffix="trouble"),
         "goe_conflict"),
    ]
    for label, kwargs, expected in cases:
        rarity = "magic"
        try:
            G.generate(rarity=rarity, **kwargs)
        except G.ItemGenError as exc:
            check(exc.code == expected,
                  "%s: ItemGenError.code=%r, expected %r (%s)"
                  % (label, exc.code, expected, exc))
            check(bool(str(exc)), "%s: empty error message" % label)
            check(isinstance(exc.suggestions, tuple), "%s: suggestions not a tuple" % label)
            print("    %-12s -> code=%s | %s" % (label, exc.code, str(exc)[:70]))
        else:
            raise AssertionError("%s: generate() should have failed" % label)

    # default code keeps old-style raises working
    check(G.ItemGenError("legacy").code == "error", "default ItemGenError.code")

    # check_combination and generate agree for the same request
    for kwargs in (
        dict(base_idx=ring, ilvl=20, prefix="Obsidian"),
        dict(base_idx=ring, ilvl=24, prefix="Gold", suffix="trouble"),
        dict(base_idx=staff, ilvl=60),
    ):
        result = G.check_combination(rarity="magic", **kwargs)
        try:
            G.generate(rarity="magic", max_tries=1000, **kwargs)
        except G.ItemGenError as exc:
            check(exc.code == result["code"],
                  "pre-check code %r != generate code %r for %r"
                  % (result["code"], exc.code, kwargs))
        else:
            raise AssertionError("generate() unexpectedly accepted %r" % (kwargs,))
    print("    check_combination and generate() report the same codes")


def test_generate_after_check():
    """A passing pre-check followed by generate() yields a valid record."""
    ring = _ring()
    result = G.check_combination(ring, 30, "magic",
                                 prefix="Obsidian", suffix="of the heavens")
    check(result["ok"], "pre-check should pass: %s" % result)
    item = G.generate(ring, 30, "magic", prefix="Obsidian", suffix="of the heavens")
    check(item.prefix["name"] == result["prefix"]["name"], "prefix mismatch")
    check(item.suffix["name"] == result["suffix"]["name"], "suffix mismatch")
    check(not G.validate(item.record), "generated record failed validate(): %r"
          % (G.validate(item.record),))
    check(item.fields["iName"] == "Obsidian Ring of the heavens",
          "unexpected name %r" % (item.fields["iName"],))
    print("    generate() -> %s (validate=[])" % item.fields["iName"])


# ---------------------------------------------------------------------------
# 5. stash page semantics
# ---------------------------------------------------------------------------

def _stash_copy(name, grids):
    """A throw-away copy of tests/fixtures/saves/stash.sv with a fresh page map."""
    os.makedirs(TMP, exist_ok=True)
    dst = os.path.join(TMP, name)
    shutil.copy2(BACKUP_STASH, dst)
    stash = S.Stash(dst)
    stash.grids = {page: [row[:] for row in grid] for page, grid in grids.items()}
    return stash


def test_stash_pages():
    """page is 0-based; empty/existing/missing/full pages behave as documented."""
    check(os.path.isfile(BACKUP_STASH), "missing backup stash: %s" % BACKUP_STASH)

    s = _stash_copy("pages_0_1.sv", {0: EMPTY_GRID, 1: EMPTY_GRID})
    check(s.pages() == [0, 1], "fresh page map: %r" % (s.pages(),))
    record = s.records[0]
    w, h = S.Stash.record_size(record)
    count = s.item_count()

    check(s.add_record(record, page=0) == (0, 0, 0), "page=0 should be the first page")
    check(s.add_record(record, page=1) == (1, 0, 0), "page=1 should be the second page")
    check(s.item_count() == count + 2, "two records should have been appended")

    # an existing-but-empty non-contiguous page is a normal target
    check(s.add_record(record, page=5) == (5, 0, 0),
          "page=5 does not exist yet and should be created")
    check(5 in s.pages(), "page 5 should exist after add_record")

    # page 99 is the last legal page (0-based)
    check(s.add_record(record, page=99) == (99, 0, 0), "page=99 should be accepted")
    check(99 in s.pages(), "page 99 should exist")

    # out-of-range pages are refused instead of writing an illegal page number
    for bad_page in (-1, 100, 12345):
        try:
            s.add_record(record, page=bad_page)
        except S.StashError as exc:
            message = str(exc)
            check("页码越界" in message, "unclear out-of-range message: %s" % message)
            check("0..99" in message, "out-of-range message should quote 0..99: %s" % message)
        else:
            raise AssertionError("page=%r was accepted" % (bad_page,))
    print("    pages 0/1/5/99 placed; -1/100/12345 refused with 页码越界")

    # full requested page: default falls back, strict_page refuses
    fallback = _stash_copy("pages_full_fallback.sv", {0: FULL_GRID, 1: EMPTY_GRID})
    page, x, y = fallback.add_record(fallback.records[0], page=0)
    check(page == 1, "full page 0 should fall back to page 1, got %r" % (page,))
    check((x, y) == (0, 0), "fallback slot should be (0,0), got %r" % ((x, y),))

    strict = _stash_copy("pages_full_strict.sv", {0: FULL_GRID, 1: EMPTY_GRID})
    try:
        strict.add_record(strict.records[0], page=0, strict_page=True)
    except S.StashError as exc:
        message = str(exc)
        check("第 1 页" in message and "没有能放下" in message,
              "strict page message should say which page failed: %s" % message)
    else:
        raise AssertionError("strict_page=True accepted a full page")
    print("    full page: fallback -> page 1, strict_page=True -> clear error")

    # page=None starts at the lowest page with room
    auto = _stash_copy("pages_auto.sv", {0: FULL_GRID, 1: EMPTY_GRID})
    check(auto.add_record(auto.records[0])[0] == 1,
          "page=None should skip the full page 0")

    # a missing page is created at (0,0) even in strict mode ("指定空页")
    missing = _stash_copy("pages_missing.sv", {0: EMPTY_GRID})
    check(missing.add_record(missing.records[0], page=7, strict_page=True)
          == (7, 0, 0), "strict_page=True should create the requested empty page")
    print("    page=7 (missing) created at (0,0)")

    # 100 full pages -> the old, clear bin-full error still works
    full = _stash_copy("pages_bin_full.sv",
                       {p: FULL_GRID for p in range(S.MAX_STASH_PAGES)})
    try:
        full.add_record(full.records[0])
    except S.StashError as exc:
        check("储物箱已满" in str(exc), "bin-full message changed: %s" % exc)
    else:
        raise AssertionError("100 full pages should raise StashError")


def test_stash_page_save_reload():
    """Sparse page numbers survive save()/reload; the record lands where asked."""
    s = _stash_copy("pages_save.sv", {0: EMPTY_GRID, 1: EMPTY_GRID})
    record = s.records[0]
    placed = s.add_record(record, page=1)
    check(placed[0] == 1, "record should be placed on page 1")
    added = s.records[-1]
    count = s.item_count()

    out = os.path.join(TMP, "pages_save_out.sv")
    s.save(out, backup=False)
    reloaded = S.Stash(out)
    check(reloaded.item_count() == count, "item count changed after reload")
    check(reloaded.records == s.records, "records changed after save/reload")
    check(reloaded.grids == s.grids, "page/cell map changed after save/reload")
    check(reloaded.records[-1] == added, "the added record changed on disk")
    check(reloaded.pages() == s.pages(), "page list changed after reload")
    print("    save/reload kept %d pages %r and the new record"
          % (len(reloaded.pages()), reloaded.pages()))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("affix_effect_label() short effect names", test_affix_effect_label),
    ("affix_label(with_effect=True) drop-down text", test_affix_label_with_effect),
    ("check_combination: legal Ring + Obsidian + of the heavens", test_combination_ok),
    ("check_combination: level_window (ilvl 20 / 50)", test_combination_level_window),
    ("check_combination: fixed_affix_value / value_out_of_range",
     test_combination_value_errors),
    ("check_combination: bad_base", test_combination_bad_base),
    ("check_combination: bad_affix", test_combination_bad_affix),
    ("check_combination: goe_conflict", test_combination_goe_conflict),
    ("check_combination: staff_ilvl / bad_rarity / bad_ilvl",
     test_combination_staff_and_inputs),
    ("check_combination: seed_not_found", test_combination_seed_not_found),
    ("ItemGenError.code from generate()", test_generate_error_codes),
    ("generate() after a passing pre-check", test_generate_after_check),
    ("stash add_record(page=...) semantics", test_stash_pages),
    ("stash page save/reload", test_stash_page_save_reload),
]


def main():
    global LIVE_BEFORE
    print("Round 3 core tests (affix labels / combination pre-check / stash pages)")
    print("python:", sys.version.split()[0], "| lib:", LIB)

    if os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)

    LIVE_BEFORE = sha256(LIVE_STASH) if os.path.isfile(LIVE_STASH) else None
    backup_before = sha256(BACKUP_STASH) if os.path.isfile(BACKUP_STASH) else None

    failures = 0
    start = time.time()
    try:
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
    finally:
        live_after = sha256(LIVE_STASH) if os.path.isfile(LIVE_STASH) else None
        backup_after = sha256(BACKUP_STASH) if os.path.isfile(BACKUP_STASH) else None

    # -- safety: the real save and the read-only backup must be untouched ----
    print("\nsafety check")
    if LIVE_BEFORE is not None:
        if LIVE_BEFORE == live_after:
            print("    live stash unchanged: %s… (%d bytes)"
                  % (live_after[:16], os.path.getsize(LIVE_STASH)))
        else:
            failures += 1
            print("    FAILED: live stash changed! %s -> %s"
                  % (LIVE_BEFORE, live_after))
        if LIVE_BEFORE.upper().startswith(LIVE_BASELINE_SHA_PREFIX):
            if live_after.upper().startswith(LIVE_BASELINE_SHA_PREFIX):
                print("    live stash is still the 103-item %s… baseline"
                      % (LIVE_BASELINE_SHA_PREFIX,))
            else:
                failures += 1
                print("    FAILED: live stash left the %s… baseline"
                      % (LIVE_BASELINE_SHA_PREFIX,))
        else:
            print("    note: live stash is not the %s… baseline (user played); "
                  "only the no-write check applies" % (LIVE_BASELINE_SHA_PREFIX,))
    else:
        print("    live stash not found (skipped)")
    if backup_before == backup_after:
        print("    backup_saves/stash.sv unchanged: %s…" % backup_before[:16])
    else:
        failures += 1
        print("    FAILED: tests/fixtures/saves/stash.sv changed! %s -> %s"
              % (backup_before, backup_after))

    shutil.rmtree(TMP, ignore_errors=True)
    elapsed = time.time() - start
    total = len(TESTS)
    print("\n%d/%d tests passed in %.2fs" % (total - failures, total, elapsed))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
