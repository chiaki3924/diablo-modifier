#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 7 tests: two-number affixes (King's = damage + to-hit).

Run with::

    F:\Qoder\暗黑1重制版\work\build\venv312\Scripts\python.exe work\tests\test_round7_values.py

Covers the "一个词缀两条属性" fix:

* :func:`d1itemgen.affix_value_slots` / ``affix_value_slot_range`` /
  ``_normalize_value_target`` for the 12 TOHIT_DAMP-style prefixes (King's,
  Knight's, Master's, Champion's, Lord's, Soldier's, Warrior's, Fine, Sharp,
  Clumsy, Dull, Doppelganger's) and ordinary one-number affixes;
* ``generate(prefix_value=[151, 93])``, ``"151/93"`` and the legacy single int
  (slot 0 only, second roll stays random);
* the cursed variant (Clumsy/Dull) with negative damage **and** negative
  to-hit, matching ``CalculateToHitBonus(-50) == -RndPL(6, 10)``;
* ``check_combination`` multi-slot validation (message names 「命中」);
* adapter ``Affix.value_slots`` / ``GenResult.prefix_values`` / Chinese text
  "伤害 +151%，命中 +93%";
* ``d1zh.power_value(..., tohit=...)`` display;
* replay/validate round-trip of the two-value record.

Nothing is written to disk.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

try:  # Chinese output must not crash on a GBK console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
APP = os.path.join(ROOT, "app")
for path in (LIB, APP):
    if path not in sys.path:
        sys.path.insert(0, path)

import d1tables as T          # noqa: E402
import d1itemgen as G         # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _base(name):
    rec = T.base_by_name(name)
    check(rec is not None, "base item %r not found" % (name,))
    return rec


def _prefix(name):
    rec = T.affix_by_name("prefix", name)
    check(rec is not None, "prefix %r not found" % (name,))
    return rec


def _fields(item):
    return item.fields


# ---------------------------------------------------------------------------
# slot description
# ---------------------------------------------------------------------------

def test_slots():
    king = _prefix("King's")
    slots = G.affix_value_slots(king)
    check(len(slots) == 2, "King's must have 2 slots: %r" % (slots,))
    check([s["key"] for s in slots] == ["value", "tohit"],
          "slot keys must be value/tohit: %r" % (slots,))
    check([s["label"] for s in slots] == ["伤害", "命中"],
          "slot labels must be 伤害/命中: %r" % (slots,))
    check(slots[0]["range"] == (151, 175), "damage range: %r" % (slots[0],))
    check(slots[1]["range"] == (76, 100), "to-hit range: %r" % (slots[1],))
    check(G.affix_value_slot_range(king, 0) == (151, 175), "slot 0 range")
    check(G.affix_value_slot_range(king, 1) == (76, 100), "slot 1 range")

    knight = _prefix("Knight's")
    check([s["range"] for s in G.affix_value_slots(knight)] == [(96, 110), (31, 40)],
          "Knight's ranges: %r" % (G.affix_value_slots(knight),))

    clumsy = _prefix("Clumsy")
    cslots = G.affix_value_slots(clumsy)
    check([s["range"] for s in cslots] == [(-75, -50), (-10, -6)],
          "Clumsy must expose negative damage/to-hit: %r" % (cslots,))

    # a plain one-number affix
    ruby = T.affix_by_name("prefix", "Ruby")
    check(ruby is not None, "Ruby missing")
    check(len(G.affix_value_slots(ruby)) == 1, "Ruby must have one slot")
    check(G.is_value_affix(ruby), "Ruby must be a value affix")

    # fixed-effect affix -> no slots
    haste = T.affix_by_name("suffix", "haste")
    check(haste is not None, "suffix 'haste' missing")
    check(G.affix_value_slots(haste) == [], "haste must have no value slots")
    print("    King's/Knight's/Clumsy 2 slots, Ruby 1, haste 0")


def test_normalize():
    king = _prefix("King's")
    check(G._normalize_value_target(151, king, "prefix") == [151, None],
          "int -> slot 0 only")
    check(G._normalize_value_target("151/93", king, "prefix") == [151, 93],
          "string form")
    check(G._normalize_value_target("151,93", king, "prefix") == [151, 93],
          "comma form")
    check(G._normalize_value_target([151, 93], king, "prefix") == [151, 93],
          "list form")
    check(G._normalize_value_target((None, 93), king, "prefix") == [None, 93],
          "None slot 0 leaves damage free")
    ruby = T.affix_by_name("prefix", "Ruby")
    check(G._normalize_value_target(55, ruby, "prefix") == [55], "single slot")
    for bad in (151.5, "abc"):
        try:
            G._normalize_value_target(bad, king, "prefix")
        except G.ItemGenError as exc:
            check(exc.code == "bad_value",
                  "expected bad_value for %r, got %r" % (bad, exc.code))
        else:
            raise AssertionError("%r must be rejected" % (bad,))
    check(G._normalize_value_target(None, king, "prefix") == [None, None],
          "None must leave both slots free")
    print("    int/str/list/tuple normalize; bad input -> bad_value")


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

def test_kings_exact():
    sword = _base("Long Sword")
    item = G.generate(sword["idx"], 30, "magic", prefix="King's",
                      prefix_value=[151, 93], seed=1)
    f = _fields(item)
    check(int(f["PLDam"]) == 151, "King's damage must be 151, got %r" % (f["PLDam"],))
    check(int(f["PLToHit"]) == 93, "King's to-hit must be 93, got %r" % (f["PLToHit"],))
    check(int(f["magical"]) == 1, "must stay magical")
    check(G.validate(item.record) == [], "validate: %r" % (G.validate(item.record),))
    check(str(f["iName"]).startswith("King's"), "name: %r" % (f["iName"],))
    print("    King's [151,93] -> PLDam=151 PLToHit=93, validate ok")

    # string form produces the same record fields
    item2 = G.generate(sword["idx"], 30, "magic", prefix="King's",
                       prefix_value="151/93", seed=1)
    check(int(_fields(item2)["PLDam"]) == 151 and int(_fields(item2)["PLToHit"]) == 93,
          "string form must behave like the list")
    # list with None slot 0: damage random, to-hit fixed
    item3 = G.generate(sword["idx"], 30, "magic", prefix="King's",
                       prefix_value=[None, 93], seed=1)
    check(151 <= int(_fields(item3)["PLDam"]) <= 175,
          "free damage must stay in range: %r" % (_fields(item3)["PLDam"],))
    check(int(_fields(item3)["PLToHit"]) == 93, "to-hit must be 93")
    print("    '151/93' and [None,93] also work")


def test_single_int_backward_compatible():
    sword = _base("Long Sword")
    item = G.generate(sword["idx"], 30, "magic", prefix="King's",
                      prefix_value=160, seed=1)
    f = _fields(item)
    check(int(f["PLDam"]) == 160, "single int must target damage: %r" % (f["PLDam"],))
    check(76 <= int(f["PLToHit"]) <= 100,
          "to-hit must stay a legal random roll: %r" % (f["PLToHit"],))
    check(G.validate(item.record) == [], "validate: %r" % (G.validate(item.record),))
    print("    single int 160 -> damage 160, to-hit %d (random)" % int(f["PLToHit"]))


def test_other_two_value_affixes():
    sword = _base("Long Sword")
    cases = [
        ("Knight's", 30, [96, 31]),
        ("Master's", 30, [111, 41]),
        ("Lord's", 30, [81, 21]),
        ("Champion's", 40, [126, 51]),
    ]
    for name, ilvl, want in cases:
        aff = T.affix_by_name("prefix", name)
        if aff is None:
            print("    (%s missing, skipped)" % name)
            continue
        item = G.generate(sword["idx"], ilvl, "magic", prefix=name,
                          prefix_value=want, seed=1, max_tries=400000)
        f = _fields(item)
        check(int(f["PLDam"]) == want[0] and int(f["PLToHit"]) == want[1],
              "%s -> PLDam=%r PLToHit=%r (want %r)"
              % (name, f["PLDam"], f["PLToHit"], want))
        check(G.validate(item.record) == [], "%s validate: %r"
              % (name, G.validate(item.record)))
        print("    %s [%d,%d] -> ok (ilvl %d)" % (name, want[0], want[1], ilvl))


def test_cursed_variant():
    sword = _base("Long Sword")
    item = G.generate(sword["idx"], 9, "magic", prefix="Clumsy",
                      prefix_value=[-50, -8], seed=1)
    f = _fields(item)
    check(int(f["PLDam"]) == -50, "Clumsy damage must be -50: %r" % (f["PLDam"],))
    check(int(f["PLToHit"]) == -8,
          "Clumsy to-hit must be -8 (CalculateToHitBonus(-50) is negative): %r"
          % (f["PLToHit"],))
    check(G.validate(item.record) == [], "validate: %r" % (G.validate(item.record),))
    rep = G.replay_item(item.record)
    check(int(rep.fields["PLToHit"]) == -8 and int(rep.fields["PLDam"]) == -50,
          "replay must reproduce the cursed values")
    dull = G.generate(sword["idx"], 3, "magic", prefix="Dull",
                      prefix_value=[-25, -2], seed=1)
    check(int(_fields(dull)["PLToHit"]) == -2,
          "Dull to-hit must be -2: %r" % (_fields(dull)["PLToHit"],))
    check(G.validate(dull.record) == [], "Dull validate")
    print("    Clumsy [-50,-8], Dull [-25,-2] -> negative rolls, replay ok")


def test_suffix_value_together():
    import d1itemgen_adapter as A
    gen = A.ItemGen()
    check(gen.ready, "adapter not ready")
    sword = _base("Long Sword")
    suffix = None
    for aff in gen.eligible_affixes(sword["idx"], 30, "suffix"):
        slots = aff.value_slots
        if len(slots) == 1 and aff.numeric:
            lo, hi = slots[0]["range"]
            if lo <= 9 <= hi:
                suffix = aff
                break
    check(suffix is not None, "no numeric suffix with 9 in range at ilvl 30")
    res = gen.generate(sword["idx"], 30, "magic", prefix="King's",
                       suffix=suffix.en, prefix_value=[None, 93],
                       suffix_value=9, max_tries=3000000)
    check(not res.error and not res.validation,
          "generate failed: %r / %r" % (res.error, res.validation))
    check(res.prefix_values and res.prefix_values[1] == 93,
          "prefix to-hit 93 not applied: %r" % (res.prefix_values,))
    check(151 <= int(res.prefix_values[0]) <= 175,
          "free damage slot out of range: %r" % (res.prefix_values,))
    check(res.suffix_values and res.suffix_values[0] == 9,
          "suffix value 9 not applied (%s): %r" % (suffix.en, res.suffix_values))
    print("    King's [-,93] + %s +9 -> both affixes exact" % suffix.en)


def test_out_of_range():
    sword = _base("Long Sword")
    res = G.check_combination(sword["idx"], 30, "magic", prefix="King's",
                              prefix_value=[151, 120])
    check(not res["ok"] and res["code"] == "value_out_of_range",
          "to-hit 120 must be out of range: %r" % (res,))
    check("命中" in res["message"],
          "message must name the 命中 slot: %r" % (res["message"],))
    try:
        G.generate(sword["idx"], 30, "magic", prefix="King's",
                   prefix_value=[151, 120], seed=1, max_tries=1000)
    except G.ItemGenError as exc:
        check(exc.code == "value_out_of_range", "generate error code: %r" % (exc.code,))
        check("命中" in str(exc), "generate message must name 命中: %s" % exc)
    else:
        raise AssertionError("generate must reject to-hit 120")
    print("    King's [151,120] -> value_out_of_range naming 「命中」")


# ---------------------------------------------------------------------------
# view layer
# ---------------------------------------------------------------------------

def test_d1zh_display():
    import d1zh
    king = _prefix("King's")
    text = d1zh.power_value(king, 151, tohit=93)["text"]
    check("伤害 +151%" in text and "命中 +93%" in text,
          "d1zh must show both values: %r" % (text,))
    range_text = d1zh.power_value(king)["text"]
    check("151" in range_text and "76" in range_text,
          "range text must keep both ranges: %r" % (range_text,))
    clumsy = _prefix("Clumsy")
    ctext = d1zh.power_value(clumsy)["text"]
    check("-10" in ctext and "-6" in ctext,
          "Clumsy to-hit range must be negative: %r" % (ctext,))
    custom = _base("Long Sword")
    adapter_text = None
    try:
        import d1itemgen_adapter as A
        gen = A.ItemGen()
        if gen.ready:
            aff = [a for a in gen.eligible_affixes(custom["idx"], 30, "prefix")
                   if a.en == "King's"][0]
            text2 = d1zh.power_value(aff.raw, 151, tohit=93)["text"]
            adapter_text = text2
    except Exception:  # noqa: BLE001
        adapter_text = None
    if adapter_text:
        check("命中 +93%" in adapter_text,
              "adapter affix display must show the to-hit: %r" % (adapter_text,))
    print("    d1zh shows 伤害 +151%，命中 +93%；Clumsy range is negative")


def test_adapter():
    import d1itemgen_adapter as A
    gen = A.ItemGen()
    check(gen.ready, "adapter not ready")
    sword = _base("Long Sword")
    check(gen.supports_value_slots(), "adapter must expose value slots")
    aff = [a for a in gen.eligible_affixes(sword["idx"], 30, "prefix")
           if a.en == "King's"][0]
    slots = aff.value_slots
    check([s["label"] for s in slots] == ["伤害", "命中"],
          "Affix.value_slots labels: %r" % (slots,))
    res = gen.generate(sword["idx"], 30, "magic", prefix="King's",
                       prefix_value=[151, 93], seed=1)
    check(res.error == "" and res.validation == [],
          "adapter generate failed: %r / %r" % (res.error, res.validation))
    check(res.prefix_values == [151, 93],
          "GenResult.prefix_values must be [151, 93]: %r" % (res.prefix_values,))
    check(res.prefix_value == 151, "GenResult.prefix_value = slot 0")
    check("伤害 +151%" in res.text and "命中 +93%" in res.text,
          "adapter text must show both values:\n%s" % res.text)
    print("    adapter: slots [伤害,命中], prefix_values [151,93], text ok")


# ---------------------------------------------------------------------------
# headless UI
# ---------------------------------------------------------------------------

def _gen_tab():
    """Build the real Tk UI headless and return the 装备生成 tab."""
    try:
        import tkinter  # noqa: F401
        import tkinter.font  # noqa: F401
        import tkinter.ttk  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise AssertionError("tkinter unavailable: %r" % (exc,))
    import ui_common as uic
    uic.HEADLESS = True
    from d1editor2 import App
    app = App(headless=True)
    app.withdraw()
    tab = app.tab_gen
    gen = tab.gen
    check(gen.ready, "adapter not ready: %s" % gen.status_text())
    tab._items_loaded(gen.base_items())
    app.update_idletasks()
    return app, tab


def _pick_base(tab, name):
    for i, b in enumerate(tab._filtered):
        if b.name == name and getattr(b, "kind", "") in ("武器", "防具", "戒指护符"):
            tab.listbox.selection_clear(0, "end")
            tab.listbox.selection_set(i)
            tab.listbox.see(i)
            tab._on_item_select()
            return b
    raise AssertionError("base %r not selectable" % (name,))


def _pick_affix(tab, which, needle):
    mapping = tab._pre_map if which == "pre" else tab._suf_map
    for key, aff in mapping.items():
        if needle in str(key):
            var = tab.var_pre if which == "pre" else tab.var_suf
            var.set(key)
            tab._on_affix_pick(which)
            tab.update_idletasks()
            tab.update()
            return aff
    raise AssertionError("affix containing %r not offered: %r"
                         % (needle, list(mapping)[:12]))


def test_ui_two_value_entries():
    app, tab = _gen_tab()
    try:
        _pick_base(tab, "Long Sword")
        tab.var_rarity.set("magic")
        tab._on_rarity()
        tab.var_ilvl.set("34")
        app.update_idletasks()

        aff = _pick_affix(tab, "pre", "King's")
        check(len(aff.value_slots) == 2, "King's needs two value slots")
        check(tab.lbl_pre_value2.winfo_ismapped(),
              "second value entry (命中) must be visible for King's")
        title2 = str(tab.lbl_pre_value2.cget("text"))
        check("命中" in title2 and "76" in title2,
              "second entry must be labelled 命中 with its range: %r" % (title2,))
        title1 = str(tab.lbl_pre_value.cget("text"))
        check("伤害" in title1 and "151" in title1,
              "first entry must be labelled 伤害 with its range: %r" % (title1,))
        check("disabled" not in tab.ent_pre_value2.state(),
              "second entry must be editable")

        tab.var_pre_value.set("151")
        tab.var_pre_value2.set("93")
        tab.update_idletasks()
        pre, _suf, _tol, err = tab._preview_values()
        check(err == "", "unexpected value error: %r" % (err,))
        check(list(pre) == [151, 93],
              "two entries must produce [151, 93], got %r" % (pre,))
        params = tab._params_dict()
        check(list(params["pre_value"]) == [151, 93],
              "_params_dict pre_value: %r" % (params["pre_value"],))

        # only the to-hit filled -> [None, 93] (damage stays random)
        tab.var_pre_value.set("")
        tab.update_idletasks()
        pre, _suf, _tol, err = tab._preview_values()
        check(err == "" and list(pre) == [None, 93],
              "empty damage + 命中 93 must give [None, 93]: %r / %r" % (pre, err))
        tab.var_pre_value.set("151")

        # out-of-range to-hit names 「命中」 in the message
        tab.var_pre_value2.set("120")
        tab.update_idletasks()
        pre, _suf, _tol, err = tab._preview_values()
        check("命中" in err and "120" in err,
              "out-of-range must name 命中: %r" % (err,))
        tab.var_pre_value2.set("93")

        # switching to a single-slot affix hides the second entry
        single_key = None
        for key, cand in tab._pre_map.items():
            if cand is None:
                continue
            if len(cand.value_slots) == 1 and getattr(cand, "numeric", False):
                single_key = key
                break
        check(single_key is not None, "no single-slot numeric prefix offered")
        tab.var_pre.set(single_key)
        tab._on_affix_pick("pre")
        tab.update_idletasks()
        check(not tab.lbl_pre_value2.winfo_ismapped(),
              "single-slot affix must hide the 命中 entry")

        # fixed-effect affix: disabled entry showing 固定效果
        _pick_base(tab, "Long Sword")
        aff_fixed = None
        for key, cand in tab._suf_map.items():
            if cand is None:
                continue
            # 真正的「固定效果」= 没有任何可填槽（攻速/吸血/耐久…）
            if len(cand.value_slots) == 0:
                aff_fixed = cand
                break
        check(aff_fixed is not None, "no fixed-effect suffix available")
        tab.var_suf.set([k for k, v in tab._suf_map.items() if v is aff_fixed][0])
        tab._on_affix_pick("suf")
        tab.update_idletasks()
        check(str(tab.var_suf_value.get()) == "固定效果",
              "fixed-effect affix must show 固定效果, got %r"
              % (tab.var_suf_value.get(),))
        check("disabled" in tab.ent_suf_value.state(),
              "fixed-effect entry must be disabled")
        print("    King's -> 2 entries (伤害/命中), single-slot hides 命中, "
              "fixed effect disabled")
    finally:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


def test_ui_preview_shows_both_ranges():
    """The live preview must describe both rolls of a two-value affix."""
    app, tab = _gen_tab()
    try:
        _pick_base(tab, "Long Sword")
        tab.var_rarity.set("magic")
        tab._on_rarity()
        tab.var_ilvl.set("34")
        _pick_affix(tab, "pre", "King's")
        app.update_idletasks()
        # _on_affix_pick only schedules the debounced preview; force it now
        tab.refresh_preview()
        app.update_idletasks()
        text = str(tab.preview.get("1.0", "end"))
        check("命中" in text, "preview must mention 命中:\n%s" % text[:800])
        check("151" in text and "100" in text,
              "preview must show both value ranges:\n%s" % text[:800])
        print("    preview lists 伤害 and 命中 ranges")
    finally:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("affix_value_slots for two-value affixes", test_slots),
    ("_normalize_value_target int/str/list", test_normalize),
    ("King's exact [151,93] + string/None forms", test_kings_exact),
    ("single int stays slot 0 (backward compatible)", test_single_int_backward_compatible),
    ("Knight's/Master's/Lord's/Champion's", test_other_two_value_affixes),
    ("cursed Clumsy/Dull negative rolls", test_cursed_variant),
    ("prefix value + suffix value together", test_suffix_value_together),
    ("out-of-range message names 「命中」", test_out_of_range),
    ("d1zh display with tohit", test_d1zh_display),
    ("adapter value_slots / prefix_values / text", test_adapter),
    ("UI: two value entries (伤害 / 命中)", test_ui_two_value_entries),
    ("UI: preview shows both ranges", test_ui_preview_shows_both_ranges),
]


def main():
    print("Round 7 two-value affix tests (King's = 伤害 + 命中)")
    print("python:", sys.version.split()[0])
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
