#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 5/7 drop tests: "guarantee droppable" (ilvl <= 34) protection.

Run with Python 3.12 from the repository root::

    python tests/test_round5_drop.py

If the current interpreter has no tkinter, the headless-UI checks are executed
in a child process using the interpreter named by ``D1_PYTHON`` (default: the
current interpreter).  Running this file with a tkinter-enabled 3.12 also
works.

Covers ``ROUND7_BRIEF.md`` (drop part):

* ``MAX_DROP_ILVL == 34`` / ``droppable_level_ok()`` / ``drop_plan()``;
* ilvl 31..34 go through the unique-monster route: the record stores
  ``ilvl-4`` (27..30) plus ``CF_UPER15|CF_ONLYGOOD``, which keeps the affix
  window identical (``GetItemBLevel`` adds 4) and passes
  ``IsUniqueMonsterItemValid()``;
* virtual level 31..34 reaches "Emerald" (all resist 41..50), the only affix
  that needs an affix level above 30;
* ``record_droppable()`` = game ``IsPItemValid()`` on the actual ``iCreateInfo``
  (plain ilvl 34 is rejected, 0x00DE is accepted, 0x02DE unique too);
* ilvl 35/50 rejected with ``ItemGenError(code="drop_ilvl")``;
* adapter ``generate/check_combination`` pass-through, ``drop_mode`` /
  ``record_ilvl`` / ``drop_note``, ``check_record()`` warning for old records;
* headless UI: character level 34 -> ilvl 34, spinner range 1..34, unchecked
  restores 1..50 and the preview warns in red; unique page auto-unchecks only
  when ``min_level > 34``;
* real saves: read-only hash check (nothing is written).

Nothing is written to disk: generation happens in memory and the only file
access is reading a backup save to hash it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

try:  # Chinese output must not crash on a GBK console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
APP = os.path.join(ROOT, "app")
VENV_PY = os.environ.get("D1_PYTHON") or sys.executable
FIXTURES = os.environ.get("D1_TEST_SAVES") or os.path.join(
    ROOT, "tests", "fixtures", "saves")
REAL_SAVE = os.path.join(FIXTURES, "single_2.sv")

for path in (LIB, APP):
    if path not in sys.path:
        sys.path.insert(0, path)

import d1tables as T          # noqa: E402
import d1itemgen as G         # noqa: E402

try:
    import tkinter  # noqa: F401,E402
    HAS_TK = True
except Exception:  # noqa: BLE001 - tkinter is optional
    HAS_TK = False

#: ``check_combination`` must keep returning exactly these keys (Round 3).
RESULT_KEYS = {"ok", "code", "message", "suggestions", "prefix", "suffix"}

#: The unique-monster route flags (CF_UPER15 | CF_ONLYGOOD).
ROUTE_FLAGS = 0xC0


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _base(name):
    rec = T.base_by_name(name)
    check(rec is not None, "base item %r not found" % (name,))
    return rec


def _expect_drop_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except G.ItemGenError as exc:
        check(exc.code == "drop_ilvl",
              "expected code 'drop_ilvl', got %r (%s)" % (exc.code, exc))
        text = str(exc)
        check("34" in text, "error message should mention ilvl 34: %s" % text)
        check(any("把 ilvl 降到 34" in s for s in (exc.suggestions or ())),
              "suggestions should include '把 ilvl 降到 34': %r" % (exc.suggestions,))
        return exc
    raise AssertionError("expected ItemGenError(code='drop_ilvl'), nothing raised")


# ---------------------------------------------------------------------------
# IsCreationFlagComboValid() / IsDungeonItemValid() equivalents (validation.cpp)
# ---------------------------------------------------------------------------

def _creation_flags_valid(create_info):
    """Port of items/validation.cpp IsCreationFlagComboValid() (1.5.5)."""
    flags = int(create_info) & 0xFFFF & ~0x3F
    is_town = (flags & 0x7C00) != 0                     # CF_TOWN
    is_pregen = (flags & 0x8000) != 0                   # CF_PREGEN
    is_useful = (flags & 0x180) == 0x180                # CF_UPER15 | CF_UPER1
    if is_pregen:
        return False
    if is_useful and (flags & ~0x180) != 0:
        return False
    if is_town and (flags & (flags - 1)) != 0:          # hasMultipleFlags
        return False
    return True


def _dungeon_level_ok(create_info):
    """Non-Hellfire tail of IsDungeonItemValid(): level <= (16-1)*2."""
    return (int(create_info) & 0x3F) <= 30


def _assert_droppable_record(item, label):
    create_info = int(item.fields.get("iCreateInfo", item.create_info))
    level = create_info & 0x3F
    check(_dungeon_level_ok(create_info),
          "%s: record level %d > 30 (IsDungeonItemValid/unique-monster level)"
          % (label, level))
    check(_creation_flags_valid(create_info),
          "%s: illegal creation flag combo 0x%04X" % (label, create_info))
    check(G.record_droppable(create_info),
          "%s: record_droppable(0x%04X) is False" % (label, create_info))
    check(G.validate(item.record) == [],
          "%s: validate() = %r" % (label, G.validate(item.record)))
    check(len(item.record) == G.RECORD_SIZE, "%s: bad record length" % label)


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

def test_constants():
    check(G.MAX_DROP_ILVL == 34, "MAX_DROP_ILVL must be 34")
    check(G.UNIQUE_DROP_BONUS == 4, "UNIQUE_DROP_BONUS must be 4")
    for ok in (0, 20, 30, 31, 32, 33, 34):
        check(G.droppable_level_ok(ok), "ilvl %r must be droppable" % (ok,))
    for bad in (35, 50, 63, -1, "x"):
        check(not G.droppable_level_ok(bad),
              "ilvl %r must NOT be droppable" % (bad,))
    check("drop_ilvl" in G.COMBINATION_CODES, "drop_ilvl must be in COMBINATION_CODES")

    plan = G.drop_plan(30)
    check(plan["mode"] == "dungeon" and plan["record_ilvl"] == 30
          and plan["uper"] == 0 and plan["flags"] == 0,
          "ilvl 30 must stay a plain dungeon record: %r" % (plan,))
    for ilvl in (31, 32, 33, 34):
        plan = G.drop_plan(ilvl)
        check(plan["mode"] == "unique_monster",
              "ilvl %d must use the unique-monster route: %r" % (ilvl, plan))
        check(plan["record_ilvl"] == ilvl - 4,
              "ilvl %d record level must be %d: %r" % (ilvl, ilvl - 4, plan))
        check(plan["uper"] == 15 and plan["onlygood"] is True,
              "route must set uper=15/onlygood: %r" % (plan,))
        check(plan["flags"] == ROUTE_FLAGS,
              "route flags must be 0x%02X: %r" % (ROUTE_FLAGS, plan))
        check(1 <= plan["record_ilvl"] <= 30,
              "record level must be a real unique-monster level: %r" % (plan,))
    _expect_drop_error(G.drop_plan, 35)

    # record-level check (= IsPItemValid on the saved iCreateInfo)
    check(G.record_droppable(0x1E), "plain ilvl 30 must be droppable")
    check(not G.record_droppable(34), "plain ilvl 34 must NOT be droppable")
    check(G.record_droppable(0x00DE), "0x00DE (30|UPER15|ONLYGOOD) must be droppable")
    check(G.record_droppable(0x02DE), "0x02DE (CF_UNIQUE|route) must be droppable")
    check(not G.record_droppable(0x00E3), "level 35 with route flags must NOT be droppable")
    # CF_TOWN: single town flag + level <= 30 (Adria's elixirs are 0x400F)
    check(G.record_droppable(0x400F), "CF_HEALER ilvl 15 must be droppable")
    check(G.record_droppable(0x2010), "CF_WITCH ilvl 16 must be droppable")
    check(not G.record_droppable(0x4023), "CF_HEALER ilvl 35 must NOT be droppable")
    check(not G.record_droppable(0x600F), "two town flags must NOT be droppable")
    check(G.record_droppable(0x1011), "CF_BOY ilvl 17 must be droppable")
    # CF_USEFUL (UPER15|UPER1) is legal only on its own
    check(G.record_droppable(0x0180), "CF_USEFUL alone must be droppable")
    check(not G.record_droppable(0x01C0), "CF_USEFUL + ONLYGOOD must NOT be droppable")
    check(not G.record_droppable(0x01DE), "CF_USEFUL + route flags must NOT be droppable")
    check(not G.record_droppable(0x00C0 | 0x8000), "CF_PREGEN must NOT be droppable")
    print("    MAX_DROP_ILVL=34; dungeon 0..30, unique-monster 31..34, 35+ rejected")


def test_drop_plan_levels():
    """31..34 store level-4 and keep the same affix window."""
    emerald = T.affix_by_name("prefix", "Emerald")
    check(emerald is not None, "Emerald missing from the prefix table")
    check(int(emerald["min_level"]) == 31, "Emerald should be a level-31 affix")
    for ilvl in (31, 32, 33, 34):
        plan = G.drop_plan(ilvl)
        check(plan["affix_ilvl"] == ilvl,
              "affix window ilvl must stay %d: %r" % (ilvl, plan))
    lo, hi = G.affix_ilvl_band(emerald)
    check(lo == 31, "Emerald's legal ilvl band must start at 31, got %r" % (lo,))
    check(all(31 <= ilvl <= hi for ilvl in (31, 32, 33, 34)),
          "Emerald must be reachable at 31..34 (band %r..%r)" % (lo, hi))
    print("    drop_plan: record level -4, affix window unchanged (31..34)")


def test_normal_droppable():
    sword = _base("Long Sword")
    for ilvl in (20, 30):
        item = G.generate(sword["idx"], ilvl, "normal", seed=1, droppable=True)
        check((int(item.fields["iCreateInfo"]) & 0x3F) == ilvl,
              "normal ilvl %d was not stored" % ilvl)
        _assert_droppable_record(item, "normal ilvl %d" % ilvl)
        print("    normal Long Sword ilvl %d -> record ok" % ilvl)
    for ilvl in (31, 34):
        item = G.generate(sword["idx"], ilvl, "normal", seed=1, droppable=True)
        ci = int(item.fields["iCreateInfo"])
        check((ci & 0x3F) == ilvl - 4,
              "normal ilvl %d must store level %d, got %d" % (ilvl, ilvl - 4, ci & 0x3F))
        check((ci & ROUTE_FLAGS) == ROUTE_FLAGS,
              "normal ilvl %d must carry CF_UPER15|CF_ONLYGOOD: 0x%04X" % (ilvl, ci))
        _assert_droppable_record(item, "normal ilvl %d (unique route)" % ilvl)
        print("    normal Long Sword ilvl %d -> route record 0x%04X" % (ilvl, ci))


def test_magic_droppable():
    sword = _base("Long Sword")
    for ilvl in (20, 30):
        item = G.generate(sword["idx"], ilvl, "magic", seed=1, droppable=True)
        check(int(item.fields.get("magical", 0)) == 1,
              "magic ilvl %d did not come out magical" % ilvl)
        _assert_droppable_record(item, "magic ilvl %d" % ilvl)
        print("    magic Long Sword ilvl %d -> record ok" % ilvl)
    for ilvl in (31, 34):
        item = G.generate(sword["idx"], ilvl, "magic", seed=1, droppable=True)
        ci = int(item.fields["iCreateInfo"])
        check(int(item.fields.get("magical", 0)) == 1,
              "magic ilvl %d did not come out magical" % ilvl)
        check((ci & 0x3F) == ilvl - 4 and (ci & ROUTE_FLAGS) == ROUTE_FLAGS,
              "magic ilvl %d must use the route: 0x%04X" % (ilvl, ci))
        _assert_droppable_record(item, "magic ilvl %d (unique route)" % ilvl)
        print("    magic Long Sword ilvl %d -> route record 0x%04X" % (ilvl, ci))


def test_unique_droppable():
    uniq = T.unique_by_name("The Grandfather")
    check(uniq is not None, "The Grandfather missing from the unique table")
    for ilvl in (27, 30):
        item = G.generate(None, ilvl, "unique", unique_id=uniq["index"],
                          seed=1, droppable=True)
        check(int(item.fields.get("magical", 0)) == 2,
              "unique ilvl %d did not come out unique" % ilvl)
        _assert_droppable_record(item, "unique ilvl %d" % ilvl)
        print("    unique The Grandfather ilvl %d -> record ok" % ilvl)
    item = G.generate(None, 34, "unique", unique_id=uniq["index"],
                      seed=1, droppable=True)
    ci = int(item.fields["iCreateInfo"])
    check((ci & 0x3F) == 30, "unique ilvl 34 must store level 30: 0x%04X" % ci)
    check((ci & 0x200) != 0, "unique record must keep CF_UNIQUE: 0x%04X" % ci)
    check((ci & ROUTE_FLAGS) == ROUTE_FLAGS,
          "unique ilvl 34 must keep the route flags: 0x%04X" % ci)
    _assert_droppable_record(item, "unique ilvl 34 (unique route)")
    print("    unique The Grandfather ilvl 34 -> record 0x%04X" % ci)


def test_emerald_route():
    """Emerald (affix level 31) is the reason the cap moved to 34."""
    sword = _base("Long Sword")
    item = G.generate(sword["idx"], 34, "magic", prefix="Emerald",
                      droppable=True, max_tries=2000000)
    fields = item.fields
    check(str(fields.get("iName", "")).startswith("Emerald"),
          "ilvl 34 should allow Emerald: %r" % (fields.get("iName"),))
    check(int(fields.get("PLFR") or 0) == int(fields.get("PLLR") or 0)
          == int(fields.get("PLMR") or 0) > 0,
          "Emerald should give equal all-res: FR=%r LR=%r MR=%r"
          % (fields.get("PLFR"), fields.get("PLLR"), fields.get("PLMR")))
    _assert_droppable_record(item, "Emerald ilvl 34")
    res = G.check_combination(sword["idx"], 34, "magic", prefix="Emerald",
                              droppable=True)
    check(res["ok"], "check_combination(Emerald@34) must pass: %r" % (res,))
    # At ilvl 30 the affix window stops at 30, so Emerald is unreachable.
    res30 = G.check_combination(sword["idx"], 30, "magic", prefix="Emerald",
                                droppable=True)
    check(not res30["ok"] and res30["code"] == "level_window",
          "Emerald@30 must be a level_window error: %r" % (res30,))
    print("    Emerald@34 -> all-res %d, validate ok; Emerald@30 -> level_window"
          % int(fields["PLFR"]))


def test_reject_above_34():
    sword = _base("Long Sword")
    uniq = T.unique_by_name("The Grandfather")
    for ilvl in (35, 50):
        _expect_drop_error(G.generate, sword["idx"], ilvl, "normal",
                           seed=1, droppable=True)
        _expect_drop_error(G.generate, sword["idx"], ilvl, "magic",
                           seed=1, droppable=True)
        _expect_drop_error(G.generate, None, ilvl, "unique",
                           unique_id=uniq["index"], seed=1, droppable=True)
        check(G.generate(sword["idx"], ilvl, "normal", seed=1, strict=False,
                         droppable=True) is None,
              "strict=False must return None for ilvl %d" % ilvl)
        print("    ilvl %d rejected (normal/magic/unique)" % ilvl)


def test_check_combination_droppable():
    sword = _base("Long Sword")
    for ilvl in (20, 30, 31, 34):
        res = G.check_combination(sword["idx"], ilvl, "normal", droppable=True)
        check(set(res) == RESULT_KEYS, "result keys changed: %r" % sorted(res))
        check(res["ok"] and res["code"] == "ok",
              "ilvl %d should pass: %r" % (ilvl, res))
    for ilvl in (35, 50):
        res = G.check_combination(sword["idx"], ilvl, "normal",
                                  droppable=True)
        check(set(res) == RESULT_KEYS, "result keys changed: %r" % sorted(res))
        check(not res["ok"] and res["code"] == "drop_ilvl",
              "ilvl %d should be drop_ilvl: %r" % (ilvl, res))
        check("34" in res["message"], "message must mention 34: %r" % (res,))
        check(any("把 ilvl 降到 34" in s for s in res["suggestions"]),
              "suggestions must mention '把 ilvl 降到 34': %r" % (res,))
    # unique path too
    uniq = T.unique_by_name("The Grandfather")
    res = G.check_combination(None, 35, "unique", unique_id=uniq["index"],
                              droppable=True)
    check(res["code"] == "drop_ilvl", "unique ilvl 35 should be drop_ilvl: %r" % (res,))
    res34 = G.check_combination(None, 34, "unique", unique_id=uniq["index"],
                                droppable=True)
    check(res34["ok"], "unique ilvl 34 should pass: %r" % (res34,))
    print("    check_combination: 20/30/31/34 ok; 35/50 -> drop_ilvl")


def test_old_api_unchanged():
    """Default droppable=False keeps the historical ilvl 1..63 API."""
    sword = _base("Long Sword")
    for ilvl in (31, 34, 50):
        item = G.generate(sword["idx"], ilvl, "normal", seed=1)
        ci = int(item.fields["iCreateInfo"])
        check((ci & 0x3F) == ilvl,
              "old API must still generate ilvl %d, got %d" % (ilvl, ci & 0x3F))
        check((ci & 0xC0) == 0,
              "old API must not add drop flags at ilvl %d: 0x%04X" % (ilvl, ci))
        res = G.check_combination(sword["idx"], ilvl, "normal")
        check(res["ok"] and res["code"] == "ok",
              "old check_combination must accept ilvl %d: %r" % (ilvl, res))
    print("    default droppable=False still accepts 31/34/50 without flags")


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------

def _adapter():
    from d1itemgen_adapter import ItemGen
    gen = ItemGen()
    check(gen.ready, "adapter ItemGen is not ready (d1itemgen missing)")
    return gen


def test_adapter_generate_and_check():
    gen = _adapter()
    sword = _base("Long Sword")
    check(gen.max_drop_ilvl == 34, "adapter max_drop_ilvl must be 34")
    res = gen.generate(sword["idx"], 20, "normal", seed=1, droppable=True)
    check(res.droppable and "可丢地上" in res.drop_note,
          "adapter result should report droppable: %r / %r"
          % (res.droppable, res.drop_note))
    ok = gen.check_combination(sword["idx"], 20, "normal", droppable=True)
    check(ok.ok and ok.code == "", "adapter check should pass: %r" % (ok,))
    good = gen.check_combination(sword["idx"], 34, "normal", droppable=True)
    check(good.ok, "adapter check should accept ilvl 34: %r" % (good,))
    bad = gen.check_combination(sword["idx"], 35, "normal", droppable=True)
    check(not bad.ok and bad.code == "drop_ilvl",
          "adapter check should return drop_ilvl: %r" % (bad,))
    _expect_drop_error(gen.generate, sword["idx"], 35, "normal", seed=1,
                       droppable=True)

    route = gen.generate(sword["idx"], 34, "normal", seed=1, droppable=True)
    check(route.droppable, "adapter ilvl-34 route must be droppable")
    check(route.drop_mode == "unique_monster",
          "adapter drop_mode must be unique_monster: %r" % (route.drop_mode,))
    check(route.record_ilvl == 30 and route.ilvl == 34,
          "adapter record_ilvl/ilvl mismatch: %r/%r"
          % (route.record_ilvl, route.ilvl))
    check("暗金怪" in route.drop_note,
          "adapter drop_note should mention the route: %r" % (route.drop_note,))

    old = gen.generate(sword["idx"], 34, "normal", seed=1)
    check(not old.droppable, "plain ilvl 34 record must NOT be droppable")
    check("储物箱" in old.drop_note,
          "adapter should warn about the stash: %r" % (old.drop_note,))
    print("    adapter: 20/34 pass, 35 -> drop_ilvl, route flags reported")


def test_adapter_check_record_warn():
    gen = _adapter()
    sword = _base("Long Sword")
    high = G.generate(sword["idx"], 34, "normal", seed=1)
    issues = gen.check_record(high.record, deep=True)
    warned = [(sev, msg) for sev, msg in issues
              if "储物箱" in msg and "无效的数据包" in msg]
    check(warned, "check_record must warn about a plain ilvl-34 record: %r" % (issues,))
    check(all(sev == "warn" for sev, _ in warned),
          "the drop message must be a warn, never fatal: %r" % (issues,))
    check(any("物品等级 34" in msg for _sev, msg in warned),
          "the warning must name the level: %r" % (warned,))
    route = G.generate(sword["idx"], 34, "normal", seed=1, droppable=True)
    route_issues = gen.check_record(route.record, deep=False)
    check(not any("物品等级" in msg and "储物箱" in msg
                  for _sev, msg in route_issues),
          "the unique-monster route must not get the drop warning: %r"
          % (route_issues,))
    low = G.generate(sword["idx"], 30, "normal", seed=1, droppable=True)
    low_issues = gen.check_record(low.record, deep=False)
    check(not any("物品等级" in msg and "储物箱" in msg for _sev, msg in low_issues),
          "ilvl 30 must not get the drop warning: %r" % (low_issues,))
    print("    check_record: plain ilvl 34 warn (non-fatal), route/30 clean")


# ---------------------------------------------------------------------------
# headless UI
# ---------------------------------------------------------------------------

def _ui_checks():
    """Runs in a process that has tkinter (see test_headless_ui)."""
    import ui_common as uic
    uic.HEADLESS = True
    from d1editor2 import App

    app = App(headless=True)
    app.withdraw()
    app.geometry("1260x920")
    try:
        app.update_idletasks()
        tab = app.tab_gen
        tab._items_loaded(tab.gen.base_items())

        class _Hero:
            level = 34
            name = "Round7Fake"

        app.tab_char.hero = _Hero()
        app.on_char_loaded(Path("round7_fake.sv"))
        app.update_idletasks()

        check(tab.var_drop_safe.get() is True,
              "equipment page must default to 保证可丢地上 = checked")
        check(tab.var_ilvl.get() == "34",
              "hero level 34 must clamp default ilvl to 34, got %r"
              % tab.var_ilvl.get())
        check(int(tab.sp_ilvl.cget("to")) == 34,
              "equipment ilvl Spinbox upper bound must be 34")
        check(tab._ilvl_or_none() == 34, "_ilvl_or_none must accept 34")
        params = tab._params_dict()
        check(params["ilvl"] == 34, "params ilvl should be 34: %r" % (params,))
        check(params.get("droppable") is True,
              "params must carry droppable=True: %r" % (params,))
        # The fixed bar must fit the 640px left column at 1260x920 (Round 5).
        tab._update_recommend_button()
        app.update_idletasks()
        app.update()
        row0_req = tab._gen_row0.winfo_reqwidth()
        bar_req = tab._action_bar.winfo_reqwidth()
        print("    fixed bar reqwidth = %dpx (row0 %dpx, left column 640px)"
              % (bar_req, row0_req))
        check(row0_req <= 640,
              "equipment fixed-bar row0 needs %dpx (> 640px left column)" % row0_req)
        check(bar_req <= 640,
              "equipment fixed bar needs %dpx (> 640px left column)" % bar_req)

        # Uncheck -> 1..50 again, and ilvl 40 is allowed but flagged red.
        tab.var_drop_safe.set(False)
        app.update_idletasks()
        check(tab._max_ilvl() == 50, "unchecked max ilvl must be 50")
        check(int(tab.sp_ilvl.cget("to")) == 50,
              "unchecked Spinbox upper bound must be 50")
        tab.set_ilvl(40)
        text = tab.preview_text()
        check("可丢地上：否" in text,
              "preview must say 可丢地上：否 at ilvl 40:\n%s" % text)
        check("只能放储物箱" in text,
              "preview must warn about the stash at ilvl 40:\n%s" % text)
        check("无效的数据包" in text,
              "preview must mention 无效的数据包:\n%s" % text)
        try:
            color = tab.preview.tag_cget("setcolor", "foreground")
        except Exception:  # noqa: BLE001
            color = ""
        check(str(color).lower() in ("#c62828", "red"),
              "the ilvl>34 preview must be red, got %r" % (color,))

        # Re-checking clamps back to 34 and restores the 1..34 range.
        tab.var_drop_safe.set(True)
        app.update_idletasks()
        check(tab.var_ilvl.get() == "34",
              "re-checking 保证可丢地上 must clamp ilvl 40 -> 34, got %r"
              % tab.var_ilvl.get())
        check(int(tab.sp_ilvl.cget("to")) == 34,
              "re-checking must restore the 1..34 Spinbox range")
        check(tab._params_dict()["droppable"] is True,
              "params droppable must become True again")

        # ---- unique page ----
        utab = app.tab_unique
        check(utab.var_drop_safe.get() is True,
              "unique page must default to 保证可丢地上 = checked")
        check(int(utab.sp_ilvl.cget("to")) == 34,
              "unique ilvl Spinbox upper bound must be 34")
        opts_req = utab._opts.winfo_reqwidth()
        check(opts_req <= 640,
              "unique options row needs %dpx (> 640px right column)" % opts_req)

        class _FakeUnique:
            uid = 999
            cn = "测试暗金"
            en = "Fake Unique"
            base_available = True
            base_cn = "Plate Mail"
            base_en = "Plate Mail"
            base_idx = 68
            min_level = 40
            value = 100
            base_unique_only = False
            note = ""

            def to_rows(self):
                return []

        utab._current = lambda: _FakeUnique()
        utab._on_select()
        app.update_idletasks()
        check(utab.var_drop_safe.get() is False,
              "unique min_level 40 must auto-uncheck 保证可丢地上")
        check(int(utab.sp_ilvl.cget("to")) == 50,
              "after auto-uncheck the unique ilvl range must be 1..50")
        hint = str(utab.lbl_drop_hint.cget("text"))
        check("只能放储物箱" in hint and "不能丢地上" in hint,
              "unique hint must explain the stash-only rule: %r" % hint)
        utext = uic.get_text(utab.preview)
        check("可丢地上：否" in utext,
              "unique preview must say 可丢地上：否:\n%s" % utext)
        check("只能放储物箱" in utext,
              "unique preview must warn about the stash:\n%s" % utext)
        # Re-checking is refused: it auto-unchecks again.
        utab.var_drop_safe.set(True)
        app.update_idletasks()
        check(utab.var_drop_safe.get() is False,
              "checking 保证可丢地上 for a min_level>34 unique must be refused")
        # Generation is allowed into the stash with droppable=False.
        u, ilvl, count = utab._params()
        check(ilvl >= 40 and count >= 1,
              "unique params should keep ilvl >= min_level: %r" % ((u, ilvl, count),))
    finally:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


def test_ui_headless():
    """Headless UI checks; delegates to the tkinter-enabled venv when needed."""
    if HAS_TK:
        _ui_checks()
        print("    equipment/unique pages: defaults, clamp, range, red warning")
        return
    check(os.path.exists(VENV_PY),
          "tkinter is unavailable and no tkinter-enabled Python was found: %r "
          "(set D1_PYTHON)" % VENV_PY)
    proc = subprocess.run(
        [VENV_PY, os.path.abspath(__file__), "--ui-child"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=ROOT)
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    if proc.returncode != 0:
        raise AssertionError(
            "headless UI child failed (exit %d):\n%s\n%s"
            % (proc.returncode, tail, (proc.stderr or "").strip()))
    print("    headless UI passed in %s" % os.path.basename(VENV_PY))
    if tail:
        print("    " + tail.replace("\n", "\n    "))


# ---------------------------------------------------------------------------
# real saves: read-only
# ---------------------------------------------------------------------------

def test_real_save_readonly():
    if not os.path.exists(REAL_SAVE):
        print("    (skipped: %s not found)" % REAL_SAVE)
        return
    before = _sha256(REAL_SAVE)
    gen = _adapter()
    sword = _base("Long Sword")
    G.generate(sword["idx"], 34, "normal", seed=1, droppable=True)
    G.generate(sword["idx"], 40, "normal", seed=1)
    G.check_combination(sword["idx"], 35, "normal", droppable=True)
    gen.check_record(G.generate(sword["idx"], 34, "normal", seed=1).record, deep=False)
    after = _sha256(REAL_SAVE)
    check(before == after,
          "real save was modified! %s -> %s" % (before, after))
    print("    real save untouched: %s" % before[:16])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("MAX_DROP_ILVL / droppable_level_ok / drop_plan", test_constants),
    ("drop_plan keeps the affix window (31..34)", test_drop_plan_levels),
    ("normal ilvl 20/30/31/34 with droppable=True", test_normal_droppable),
    ("magic ilvl 20/30/31/34 with droppable=True", test_magic_droppable),
    ("unique ilvl 27/30/34 with droppable=True", test_unique_droppable),
    ("Emerald (affix 31) reachable at ilvl 34", test_emerald_route),
    ("ilvl 35/50 rejected (drop_ilvl)", test_reject_above_34),
    ("check_combination droppable contract", test_check_combination_droppable),
    ("default droppable=False keeps the old API", test_old_api_unchanged),
    ("adapter generate/check_combination pass-through", test_adapter_generate_and_check),
    ("adapter check_record drop warning", test_adapter_check_record_warn),
    ("headless UI drop-safe controls", test_ui_headless),
    ("real save is read-only", test_real_save_readonly),
]


def _run_ui_child():
    print("Round 7 UI child (tkinter available: %s)" % HAS_TK)
    _ui_checks()
    print("UI-CHILD-OK")
    return 0


def main():
    if "--ui-child" in sys.argv:
        return _run_ui_child()
    print("Round 5/7 drop tests (ilvl<=34 / 保证可丢地上)")
    print("python:", sys.version.split()[0], "| tkinter:", HAS_TK)

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
