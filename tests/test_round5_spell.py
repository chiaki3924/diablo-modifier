#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 5 spell tests: 1.5.5 whitelist + ``pMemSpells`` bitmap (``1 << (id-1)``).

Run with Python 3.12 from the repository root::

    python tests/test_round5_spell.py

If the current interpreter has no tkinter, the headless-UI check is executed in
a child process using the interpreter named by ``D1_PYTHON`` (default: the
current interpreter).  Running this file with a tkinter-enabled 3.12 also
works and runs every check in-process.  ``tkinter`` is probed **before**
``import d1env`` because d1env puts the PyInstaller ``PYZ.pyz_extracted`` dir on
``sys.path`` and that dir holds a partial ``tkinter`` package (no ``font``).
What this suite covers (see ``work/docs/ROUND5_BRIEF.md`` section 5):

* ``d1tables.learnable_spells()``: exactly the 22 original Diablo spells
  (1,2,3,4,6,7,8,10,11,12,13,14,15,20,21,23,29,30,31,33,35,36); multiplayer adds
  Heal Other (34).  Nova/Apocalypse, the unlearnable books, Resurrect, the three
  class skills and every Hellfire spell (37+) never show up.
* ``d1tables.spell_bitmask()``: spell 1 -> bit 0, spell 12 -> bit 11.
* ``HeroEdit`` on a **copy** of ``tests/fixtures/saves/single_2.sv``:
  - the pristine save already agrees with ``1 << (id-1)`` (no mismatches);
  - ``set_spell_level(12, 1)`` changes exactly one level and one bit (bit 11);
  - for every id 1..36 the other 46 levels and every other bit stay identical;
  - level 0 clears the bit, two different spells stay learned side by side;
  - save + reload round-trip keeps levels and bits;
  - ``learn_all(15)`` / ``forget_all()`` touch only the 22 visible spells and
    leave hidden Hellfire/class levels and their bits alone.
* headless ``CharTab`` (Tk): 22 rows, ``row->id`` mapping, applying one row
  leaves the other rows alone, "全部学会" sets only those 22 rows to 15.

Safety: **nothing** is written to the real save directory; every test uses a
copy under ``tests/tmp/round5_spell`` and ``d1env.ALLOW_PROTECTED_WRITES`` is
forced to ``False``.  The real ``%APPDATA%\diasurgical\devilution`` directory is
SHA256-snapshotted before/after the run.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
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
ROOT = Path(HERE).parent
APP = ROOT / "app"
LIB = ROOT / "lib"
VENV_PY = Path(os.environ.get("D1_PYTHON") or sys.executable)
for _p in (str(APP), str(LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: tkinter is optional; detect it *before* ``import d1env`` so
#: the PyInstaller ``PYZ.pyz_extracted`` directory (which also holds a partial
#: ``tkinter`` package without ``tkinter.font``) cannot shadow the real one.
try:
    import tkinter  # noqa: F401
    from tkinter import font, ttk  # noqa: F401
    HAS_TK = True
except Exception:  # noqa: BLE001 - tkinter is optional
    HAS_TK = False

import d1env  # noqa: E402

d1env.ALLOW_PROTECTED_WRITES = False       # 自动测试：禁止写真实存档

import d1tables as T                        # noqa: E402
import d1hero as H                          # noqa: E402
from d1env import settings_dir              # noqa: E402
from d1hero import HeroEdit                 # noqa: E402

FIXTURES = Path(os.environ.get("D1_TEST_SAVES") or ROOT / "tests" / "fixtures" / "saves")
SRC_SAVE = FIXTURES / "single_2.sv"
TMPDIR = ROOT / "tests" / "tmp" / "round5_spell"

#: The 22 spells the 1.5.5 single-player spell book can teach.
WHITELIST = [1, 2, 3, 4, 6, 7, 8, 10, 11, 12, 13, 14, 15, 20, 21, 23,
             29, 30, 31, 33, 35, 36]

#: ids that must never be offered (unlearnable / class skill / Hellfire).
HIDDEN_IDS = [5, 9, 16, 17, 18, 19, 22, 24, 25, 26, 27, 28, 32, 34]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _bits(hero: HeroEdit) -> int:
    mem = int(H._offsets()["pMemSpells"])
    return struct.unpack_from("<Q", hero.pack.buf, mem)[0]


def _fresh_hero(name: str = "hero.sv") -> HeroEdit:
    TMPDIR.mkdir(parents=True, exist_ok=True)
    dest = TMPDIR / name
    shutil.copy2(SRC_SAVE, dest)
    return HeroEdit(dest)


def _level_diff(before: list[int], after: list[int]) -> list[tuple[int, int, int]]:
    return [(i, before[i], after[i]) for i in range(len(before)) if before[i] != after[i]]


def _bit_diff(before: int, after: int) -> list[int]:
    return [i for i in range(64) if ((before >> i) & 1) != ((after >> i) & 1)]


def _set_bit(hero: HeroEdit, sid: int, on: bool = True) -> None:
    """直接改缓冲里的 pMemSpells 位（模拟游戏授予的职业技能）。"""
    mem = int(H._offsets()["pMemSpells"])
    bits = struct.unpack_from("<Q", hero.pack.buf, mem)[0]
    mask = 1 << (sid - 1)
    bits = (bits | mask) if on else (bits & ~mask)
    struct.pack_into("<Q", hero.pack.buf, mem, bits)


def _set_level_byte(hero: HeroEdit, sid: int, level: int) -> None:
    """只写一个 pSplLvl 字节，不动位图（用来伪造「有等级没位」的坏存档）。"""
    off = H._offsets()
    if sid < 37:
        pos = int(off["pSplLvl"]) + sid
    else:
        pos = int(off.get("pSplLvl2", 1222)) + (sid - 37)
    hero.pack.buf[pos] = max(0, min(255, int(level)))


# ---------------------------------------------------------------------------
# whitelist / bitmask
# ---------------------------------------------------------------------------

def test_learnable_whitelist():
    """learnable_spells(): exactly the 22 original spells, no hidden ones."""
    rows = T.learnable_spells()
    ids = [int(row["index"]) for row in rows]
    check(len(rows) == 22, "expected 22 single-player spells, got %d: %r" % (len(rows), ids))
    check(ids == WHITELIST, "unexpected spell ids: %r" % (ids,))
    check(ids == sorted(ids), "learnable_spells() must be in spell-id order")
    for row in rows:
        for key in ("index", "name", "cn", "book_lvl"):
            check(key in row, "row %r is missing %r" % (row, key))
        check(int(row["book_lvl"]) >= 1,
              "spell %d has book_lvl %r" % (row["index"], row["book_lvl"]))
        check(bool(row["name"]), "spell %d has no English name" % row["index"])
        check(bool(row["cn"]), "spell %d has no Chinese name" % row["index"])
        check(not str(row["cn"]).startswith("法术 #"),
              "spell %d has no translation: %r" % (row["index"], row["cn"]))

    for sid in HIDDEN_IDS:
        check(sid not in ids, "hidden spell %d leaked into learnable_spells()" % sid)
    for sid in range(37, 52):
        check(sid not in ids, "Hellfire spell %d leaked into learnable_spells()" % sid)
        check(T.spell_book_level(sid) == -1,
              "GetSpellBookLevel(%d) must be -1 in 1.5.5" % sid)
    for sid in (18, 24, 5, 9, 16, 17, 19, 22, 25, 26, 27, 28, 32):
        check(T.spell_book_level(sid) == -1,
              "GetSpellBookLevel(%d) must be -1" % sid)
    check(T.spell_book_level(36) == 9, "Bone Spirit keeps its book level 9")
    check(T.spell_book_level(34) == 1, "Heal Other still has a table book level")

    multi = [int(row["index"]) for row in T.learnable_spells(multiplayer=True)]
    check(len(multi) == 23, "multiplayer whitelist should have 23 rows, got %d" % len(multi))
    check(set(multi) == set(WHITELIST) | {34},
          "multiplayer whitelist ids are wrong: %r" % (multi,))
    check([int(row["index"]) for row in H.learnable_spells()] == WHITELIST,
          "d1hero.learnable_spells() must match d1tables")
    print("    22 single-player spells, 23 with Heal Other, 37+ rejected")


def test_spell_bitmask():
    """spell_bitmask(): the game starts at Firebolt(1) -> bit 0."""
    check(T.spell_bitmask(1) == 1, "Firebolt must be bit 0")
    check(T.spell_bitmask(2) == 2, "Healing must be bit 1")
    check(T.spell_bitmask(12) == 1 << 11, "Fireball must be bit 11")
    check(T.spell_bitmask(36) == 1 << 35, "Bone Spirit must be bit 35")
    check(T.spell_bitmask(47) == 1 << 46, "Hellfire ids shift to bit id-1 as well")
    check(T.spell_bitmask(0) == 0, "spell 0 (Null) owns no bit")
    check(T.spell_bitmask(-3) == 0, "negative ids own no bit")
    check(H.spell_bitmask(12) == 1 << 11, "d1hero.spell_bitmask() must match")
    print("    1 -> 1, 12 -> 0x800, 0 -> 0")


# ---------------------------------------------------------------------------
# HeroEdit: bitmap + atomic single-spell writes
# ---------------------------------------------------------------------------

def test_pristine_save_bits():
    """The untouched save already uses bit = 1 << (id-1) (the old code broke it)."""
    hero = _fresh_hero("pristine.sv")
    levels = hero.spell_levels
    check(len(levels) == 47, "spell_levels should expose 47 slots, got %d" % len(levels))
    check(hero.spell_bit_mismatches() == [],
          "pristine save has bitmap mismatches: %r" % (hero.spell_bit_mismatches(),))
    bits = _bits(hero)
    check(bool(bits & 1) == (levels[1] > 0), "Firebolt must be bit 0")
    check(bool(bits & (1 << 11)) == (levels[12] > 0), "Fireball must be bit 11")
    check(bool(bits & (1 << 35)) == (levels[36] > 0), "Bone Spirit must be bit 35")
    print("    offsets %r, 0 mismatches, %d known spells" % (
        {k: H._offsets()[k] for k in ("pSplLvl", "pMemSpells", "pSplLvl2")},
        len(hero.known_spells)))


def test_single_spell_12():
    """set_spell_level(12, 1): only level 12 and bit 11 change."""
    hero = _fresh_hero("single12.sv")
    before_levels = hero.spell_levels
    before_bits = _bits(hero)
    hero.set_spell_level(12, 1)
    after_levels = hero.spell_levels
    after_bits = _bits(hero)
    check(_level_diff(before_levels, after_levels) == [(12, 0, 1)],
          "only spell 12 may change: %r" % (_level_diff(before_levels, after_levels),))
    check(_bit_diff(before_bits, after_bits) == [11],
          "only bit 11 may change: %r" % (_bit_diff(before_bits, after_bits),))
    check(bool(after_bits & (1 << 11)), "bit 11 must be set")
    check(not (after_bits & (1 << 12)), "bit 12 (spell 13) must stay clear")
    check(after_levels[13] == before_levels[13], "spell 13 level must not move")
    check(hero.spell_bit_mismatches() == [], "bitmap must stay self-consistent")
    print("    one level, one bit (bit 11), no collateral changes")


def test_every_spell_1_to_36():
    """Every id 1..36: other 46 levels and all other bits stay identical."""
    hero = _fresh_hero("each.sv")
    for sid in range(1, 37):
        before_levels = hero.spell_levels
        before_bits = _bits(hero)
        target = (before_levels[sid] % 15) + 1
        hero.set_spell_level(sid, target)
        after_levels = hero.spell_levels
        after_bits = _bits(hero)
        check(after_levels[sid] == target,
              "spell %d should be %d, got %d" % (sid, target, after_levels[sid]))
        diff = [i for i in range(47) if i != sid and before_levels[i] != after_levels[i]]
        check(not diff, "spell %d disturbed levels %r" % (sid, diff))
        mask = 1 << (sid - 1)
        check(bool(after_bits & mask), "spell %d bit %d must be set" % (sid, sid - 1))
        expected = before_bits | mask
        check(after_bits == expected,
              "spell %d changed other bits: before %#x after %#x" % (
                  sid, before_bits, after_bits))
        check(hero.spell_bit_mismatches() == [],
              "spell %d left mismatches: %r" % (sid, hero.spell_bit_mismatches()))
    check(hero.spell_levels[37:] == [0] * 10, "Hellfire slots 37..46 must stay untouched")
    print("    36 spells written, no level/bit collateral, bitmap 1<<(id-1)")


def test_zero_clears_bit():
    """Level 0 forgets the spell and clears exactly its own bit."""
    hero = _fresh_hero("zero.sv")
    hero.set_spell_level(12, 1)
    check(bool(_bits(hero) & (1 << 11)), "precondition: bit 11 set")
    before_levels = hero.spell_levels
    before_bits = _bits(hero)
    hero.set_spell_level(12, 0)
    after_levels = hero.spell_levels
    after_bits = _bits(hero)
    check(after_levels[12] == 0, "spell 12 must be forgotten")
    check(_level_diff(before_levels, after_levels) == [(12, 1, 0)],
          "only spell 12 may change: %r" % (_level_diff(before_levels, after_levels),))
    check(_bit_diff(before_bits, after_bits) == [11],
          "only bit 11 may change: %r" % (_bit_diff(before_bits, after_bits),))
    check(not (after_bits & (1 << 11)), "bit 11 must be cleared")
    check(hero.spell_bit_mismatches() == [], "bitmap must stay self-consistent")
    print("    level 0 clears the bit, other spells untouched")


def test_hidden_class_bits_preserved():
    """Class-skill bits (bit set, level 0) survive edits and save/reload."""
    hero = _fresh_hero("hidden.sv")
    _set_bit(hero, 26, True)          # Item Repair: game-granted, level 0
    _set_bit(hero, 27, True)          # Staff Recharge
    check(hero.spell_levels[26] == 0 and hero.spell_levels[27] == 0,
          "precondition: class skills have no level")
    check(hero.spell_bit_mismatches() == [],
          "a granted class-skill bit must not be reported as a mismatch: %r"
          % (hero.spell_bit_mismatches(),))

    before_bits = _bits(hero)
    hero.set_spell_level(12, 1)
    bits = _bits(hero)
    check(bits & (1 << 25), "Item Repair bit 25 must survive editing spell 12")
    check(bits & (1 << 26), "Staff Recharge bit 26 must survive editing spell 12")
    check(bits == (before_bits | (1 << 11)),
          "editing spell 12 may only add bit 11: %#x vs %#x" % (before_bits, bits))
    check(hero.spell_bit_mismatches() == [], "class-skill bits must stay unreported")

    hero.save(clear_progress=False)
    again = HeroEdit(hero.path)
    check(_bits(again) == bits, "class-skill bits changed across save/reload")
    check(again.spell_levels[26] == 0 and again.spell_levels[27] == 0,
          "class-skill levels must stay 0 across save/reload")
    check(again.spell_bit_mismatches() == [], "reloaded class-skill bits reported")

    # 反向不一致（隐藏法术有等级、没位）仍要报出来
    _set_level_byte(hero, 34, 4)
    mism = hero.spell_bit_mismatches()
    check((34, 4, 0) in mism, "a hidden level without its bit must be reported: %r" % (mism,))

    # 显式把职业技能设为 0 才清它自己的位（这是用户主动操作）
    hero.set_spell_level(26, 0)
    check(not (_bits(hero) & (1 << 25)), "explicit level 0 clears that spell's bit")
    print("    class-skill bit=1/level=0 kept; only explicit edits touch a bit")


def test_two_spells_and_bulk():
    """Learn A then B: both stay; set_spell_levels({...}) touches only its ids."""
    hero = _fresh_hero("two.sv")
    before_levels = hero.spell_levels
    before_bits = _bits(hero)
    hero.set_spell_level(12, 1)
    hero.set_spell_level(23, 2)
    levels = hero.spell_levels
    bits = _bits(hero)
    check(levels[12] == 1 and levels[23] == 2, "both spells must stay learned")
    diff = [(i, before_levels[i], levels[i]) for i in range(47)
            if i not in (12, 23) and before_levels[i] != levels[i]]
    check(not diff, "learning two spells disturbed %r" % (diff,))
    check(bits == (before_bits | (1 << 11) | (1 << 22)),
          "bits should be exactly +bit11 +bit22: %#x" % bits)
    check(hero.spell_bit_mismatches() == [], "bitmap must stay self-consistent")

    hero2 = _fresh_hero("bulk.sv")
    before_levels = hero2.spell_levels
    hero2.set_spell_levels({1: 1, 36: 2})
    levels = hero2.spell_levels
    diff = [(i, before_levels[i], levels[i]) for i in range(47)
            if i not in (1, 36) and before_levels[i] != levels[i]]
    check(not diff, "set_spell_levels() disturbed %r" % (diff,))
    check(levels[1] == 1 and levels[36] == 2, "set_spell_levels() values")
    print("    A + B coexist, set_spell_levels() is scoped")


def test_save_reload():
    """Save + reload keeps every level and bit (incl. the Hellfire slot 37)."""
    hero = _fresh_hero("reload.sv")
    hero.set_spell_level(12, 5)
    hero.set_spell_level(37, 6)            # pSplLvl2 @ offset 1222
    levels = hero.spell_levels
    bits = _bits(hero)
    check(levels[37] == 6, "Hellfire slot 37 must be writable (pSplLvl2)")
    check(bool(bits & (1 << 36)), "spell 37 -> bit 36")
    hero.save(clear_progress=False)
    again = HeroEdit(hero.path)
    check(again.spell_levels == levels, "levels changed across save/reload: %r vs %r"
          % (levels, again.spell_levels))
    check(_bits(again) == bits, "bitmap changed across save/reload")
    check(again.spell_bit_mismatches() == [], "reloaded save has mismatches")
    print("    save/reload keeps 47 levels and the bitmap")


def _game_view(path):
    """``game`` 块（已解码明文）里的玩家记录与 ``_pSplLvl`` 起点。"""
    d1save = d1env.MODULES.d1save
    sf = d1save.SaveFile(str(path))
    data, _pw = sf.read_named_file("game")
    rec = sf._locate_player_record(data)
    check(rec is not None, "game 块里找不到角色记录")
    return data, rec - H.GAME_SPELLS_BEFORE_NAME, sf


def test_game_block_spell_sync():
    """进游戏用的是 game 块里的 ``_pSplLvl[64]``（名字前 127 字节），必须同步。

    旧版编辑器按 ``_pSplLvl[52]`` 写成“名字-115”，法术等级整体错位 12 字节，
    表现为：法术列表补全但已有法术不升级、新法术显示 0 级不可用。
    """
    hero = _fresh_hero("gamesync.sv")
    check(hero.spell_levels[1] > 0, "precondition: 该存档应已有 Firebolt")
    hero.set_spell_level(37, 7)                 # pSplLvl2 也要进 game 块
    hero.learn_all(15)
    want = hero.spell_levels
    hero.save(clear_progress=False)

    data, start, _ = _game_view(hero.path)
    check(start > 0, "game 块 _pSplLvl 起点异常：%d" % start)
    got = list(data[start:start + H.GAME_SPELL_SLOTS])
    check(got[:47] == want[:47],
          "game 块 _pSplLvl[0:47] 与 hero 不一致：%r" % (got[:47],))
    check(got[47:] == [0] * (H.GAME_SPELL_SLOTS - 47),
          "game 块 47~51 应为空：%r" % (got[47:],))
    for sid in WHITELIST:
        check(got[sid] == 15, "game 块法术 %d 应为 15 级，实际 %d" % (sid, got[sid]))
    check(got[37] == 7, "game 块 Hellfire 法术 37 应为 7 级，实际 %d" % got[37])
    check(got[5] == 0 and got[34] == 0,
          "game 块不可学习法术应为 0：5=%d 34=%d" % (got[5], got[34]))

    hero_bits = _bits(hero)
    game_bits = struct.unpack_from("<Q", data, start + 71)[0]   # name-56
    check(game_bits == hero_bits,
          "game 块 _pMemSpells 与 hero 不一致：%#x vs %#x" % (game_bits, hero_bits))

    # 单法术修改也要同步
    again = HeroEdit(hero.path)
    again.set_spell_level(12, 3)
    again.save(clear_progress=False)
    data2, start2, _ = _game_view(again.path)
    check(start2 == start, "game 记录位置不应变化")
    check(data2[start2 + 12] == 3, "game 块 Fireball 应为 3 级")
    check(data2[start2 + 2] == 15, "其它法术不应被单法术修改影响")
    print("    game 块 _pSplLvl[0:47] + _pMemSpells 与 hero 包一致（单改/全学）")


def test_clear_non_original():
    """clear_non_original_spells(): Hellfire/unlearnable -> 0, class skills kept."""
    hero = _fresh_hero("clear.sv")
    hero.set_spell_level(37, 15)      # Hellfire slot (pSplLvl2)
    hero.set_spell_level(5, 15)       # Identify (unlearnable book)
    _set_bit(hero, 26, True)          # Item Repair: game-granted, level 0
    check(hero.spell_levels[5] == 15 and hero.spell_levels[37] == 15,
          "precondition: 5 and 37 must be set")
    white_before = {sid: hero.spell_levels[sid] for sid in WHITELIST}

    removed = hero.clear_non_original_spells()
    levels = hero.spell_levels
    bits = _bits(hero)
    check(removed == T.non_original_spells(),
          "clear_non_original_spells() should target %r, got %r"
          % (T.non_original_spells(), removed))
    for sid in (5, 9, 16, 17, 18, 19, 22, 24, 25, 32, 34, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46):
        check(levels[sid] == 0, "spell %d should be cleared, got %d" % (sid, levels[sid]))
        check(not (bits & (1 << (sid - 1))), "spell %d bit should be cleared" % sid)
    for sid in (26, 27, 28):
        check(sid not in removed, "class skill %d must not be targeted" % sid)
        check(levels[sid] == 0, "class skill %d level must stay 0" % sid)
    check(bool(bits & (1 << 25)), "Item Repair bit 25 must survive the cleanup")
    for sid in WHITELIST:
        check(levels[sid] == white_before[sid],
              "whitelist spell %d changed (%d -> %d)"
              % (sid, white_before[sid], levels[sid]))
    check(hero.spell_bit_mismatches() == [], "cleanup left bitmap mismatches")

    hero.save(clear_progress=False)
    again = HeroEdit(hero.path)
    check(again.spell_levels[5] == 0 and again.spell_levels[37] == 0,
          "cleanup must survive save/reload")
    check(bool(_bits(again) & (1 << 25)), "class-skill bit must survive save/reload")
    print("    21 non-original spells cleared; class skills + 22 original kept")


def test_learn_all_forget_all():
    """learn_all/forget_all only touch the 22 visible spells, hidden stay intact."""
    hero = _fresh_hero("all.sv")
    hidden_seed = {26: 5, 27: 3, 28: 2, 32: 4, 34: 6, 37: 7}
    for sid, lvl in hidden_seed.items():
        hero.set_spell_level(sid, lvl)
    check(len(hero.hidden_spell_levels) == len(hidden_seed),
          "expected %d hidden spells, got %r" % (len(hidden_seed), hero.hidden_spell_levels))

    hero.learn_all(15)
    levels = hero.spell_levels
    for row in T.learnable_spells():
        sid = int(row["index"])
        check(levels[sid] == 15, "learn_all left spell %d at %d" % (sid, levels[sid]))
    for sid, lvl in hidden_seed.items():
        check(levels[sid] == lvl, "learn_all changed hidden spell %d to %d" % (sid, levels[sid]))
    bits = _bits(hero)
    for sid in hidden_seed:
        check(bool(bits & (1 << (sid - 1))), "hidden spell %d lost its bit" % sid)
    check(hero.spell_bit_mismatches() == [], "learn_all left mismatches")

    hero.forget_all()
    levels = hero.spell_levels
    for row in T.learnable_spells():
        sid = int(row["index"])
        check(levels[sid] == 0, "forget_all left spell %d at %d" % (sid, levels[sid]))
    for sid, lvl in hidden_seed.items():
        check(levels[sid] == lvl, "forget_all changed hidden spell %d to %d" % (sid, levels[sid]))
    bits = _bits(hero)
    for sid in hidden_seed:
        check(bool(bits & (1 << (sid - 1))), "hidden spell %d lost its bit" % sid)
    check(hero.spell_bit_mismatches() == [], "forget_all left mismatches")
    print("    only the 22 visible spells flip to 15 / 0; 6 hidden levels + bits kept")


# ---------------------------------------------------------------------------
# headless UI
# ---------------------------------------------------------------------------

class _FakeApp:
    """CharTab 只需要这几个 App 接口（不建主窗口）。"""

    game_running = False

    def __init__(self):
        self.logs: list[str] = []

    def log(self, msg, tag=None):
        self.logs.append(str(msg))

    def quick_name(self, path):
        return ""

    def on_char_loaded(self, path):
        pass

    def refresh_all(self, keep_char=False):
        pass

    def require_game_closed(self):
        return True


def _widget_texts(widget):
    """All ``text=`` values in a widget tree (to assert buttons/labels exist)."""
    out = []
    for child in widget.winfo_children():
        try:
            if "text" in child.keys():
                out.append(str(child.cget("text")))
        except Exception:  # noqa: BLE001
            pass
        out.extend(_widget_texts(child))
    return out


def _ui_checks():
    """CharTab lists 22 rows; one edit / 全部学会 leave the other rows alone."""
    import tkinter as tk

    import ui_common as uic
    import ui_char

    uic.HEADLESS = True
    TMPDIR.mkdir(parents=True, exist_ok=True)
    dest = TMPDIR / "ui.sv"
    shutil.copy2(SRC_SAVE, dest)

    hero = HeroEdit(dest)
    hidden_seed = {26: 5, 32: 4, 37: 7}
    for sid, lvl in hidden_seed.items():
        hero.set_spell_level(sid, lvl)
    hero.save(clear_progress=False)

    root = tk.Tk()
    root.withdraw()
    try:
        uic.make_style(root)
        app = _FakeApp()
        tab = ui_char.CharTab(root, app)
        tab.load(dest)

        rows = tab.spell_tree.get_children()
        check(len(rows) == 22, "spell tree should show 22 rows, got %d" % len(rows))
        check([tab._row_spell[r] for r in rows] == WHITELIST,
              "row->id mapping is wrong: %r" % ([tab._row_spell[r] for r in rows],))
        for iid in rows:
            label = tab.spell_tree.item(iid, "values")[0]
            check(" · " in label, "row label should be 'index · 中文名': %r" % (label,))
            check(int(iid) == int(label.split(" · ")[0]), "label id mismatch: %r" % (label,))
        check("只显示 1.5.5 原版可学习法术" in tab.lbl_spell_note.cget("text"),
              "missing whitelist hint label")
        texts = _widget_texts(tab)
        check(any("清理非原版法术" in t for t in texts),
              "missing「清理非原版法术」button: %r" % ([t for t in texts if "法术" in t],))
        check("隐藏 3" in tab.lbl_spell_hidden.cget("text"),
              "hidden-spell hint should mention 3: %r" % tab.lbl_spell_hidden.cget("text"))

        before = tab.hero.spell_levels
        before_text = {r: tab.spell_tree.item(r, "values")[1] for r in rows}
        tab.spell_tree.selection_set("12")
        tab.var_spell_lv.set("3")
        tab._apply_spell()
        after = tab.hero.spell_levels
        diff = [(i, before[i], after[i]) for i in range(47)
                if i != 12 and before[i] != after[i]]
        check(not diff, "applying spell 12 changed other levels: %r" % (diff,))
        check(after[12] == 3, "spell 12 should be 3, got %d" % after[12])
        rows2 = tab.spell_tree.get_children()
        check(len(rows2) == 22, "row count changed after apply: %d" % len(rows2))
        for rid in rows2:
            if rid == "12":
                continue
            check(tab.spell_tree.item(rid, "values")[1] == before_text[rid],
                  "row %r level changed after applying spell 12" % rid)

        tab._learn_all()
        rows3 = tab.spell_tree.get_children()
        check(len(rows3) == 22, "row count changed after 全部学会: %d" % len(rows3))
        for rid in rows3:
            value = str(tab.spell_tree.item(rid, "values")[1])
            check(value in ("15", "15.0"), "row %r should be 15, got %r" % (rid, value))
        levels = tab.hero.spell_levels
        for sid, lvl in hidden_seed.items():
            check(levels[sid] == lvl, "全部学会 changed hidden spell %d" % sid)
        check(tab.hero.spell_bit_mismatches() == [], "全部学会 left bitmap mismatches")

        tab._forget_all()
        rows4 = tab.spell_tree.get_children()
        check(len(rows4) == 22, "row count changed after 遗忘全部: %d" % len(rows4))
        for rid in rows4:
            check(str(tab.spell_tree.item(rid, "values")[1]) in ("", "0", "0.0"),
                  "row %r should be empty/0, got %r" % (rid, tab.spell_tree.item(rid, "values")))
        levels = tab.hero.spell_levels
        for sid, lvl in hidden_seed.items():
            check(levels[sid] == lvl, "遗忘全部 changed hidden spell %d" % sid)

        tab._clear_non_original()
        levels = tab.hero.spell_levels
        check(levels[32] == 0, "清理非原版 should clear Resurrect (32)")
        check(levels[37] == 0, "清理非原版 should clear Hellfire slot 37")
        check(levels[26] == hidden_seed[26],
              "清理非原版 must keep class skill 26 (%d -> %d)"
              % (hidden_seed[26], levels[26]))
        check(tab.hero.spell_bit_mismatches() == [], "清理非原版 left bitmap mismatches")
        check(len(tab.spell_tree.get_children()) == 22,
              "清理非原版 must not change the 22 visible rows")
        check("隐藏 1" in tab.lbl_spell_hidden.cget("text"),
              "hidden hint should shrink to 1 (class skill only): %r"
              % tab.lbl_spell_hidden.cget("text"))
        print("    22 rows, row->id mapping, scoped apply / learn-all / "
              "forget-all / clear-non-original")
    finally:
        root.destroy()


def test_ui_headless():
    """Headless UI checks; delegates to the tkinter-enabled venv when needed."""
    if HAS_TK:
        _ui_checks()
        print("    CharTab runs in-process (this interpreter has tkinter)")
        return
    if not VENV_PY.is_file():
        print("    SKIP: 当前解释器没有 tkinter，且未找到可用的 Python"
              "（可用环境变量 D1_PYTHON 指定带 tkinter 的解释器）")
        return
    proc = subprocess.run(
        [str(VENV_PY), os.path.abspath(__file__), "--ui-child"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(ROOT))
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    if proc.returncode != 0:
        raise AssertionError(
            "headless UI child failed (exit %d):\n%s\n%s"
            % (proc.returncode, tail, (proc.stderr or "").strip()))
    print("    headless UI passed in the app venv (%s)" % VENV_PY.name)
    if tail:
        print("    " + tail.replace("\n", "\n    "))


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------

def _saves_snapshot() -> dict:
    out = {}
    try:
        base = settings_dir()
    except Exception:  # noqa: BLE001
        return out
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if p.is_file():
            try:
                out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                pass
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("learnable_spells() whitelist", test_learnable_whitelist),
    ("spell_bitmask() 1<<(id-1)", test_spell_bitmask),
    ("pristine save already uses 1<<(id-1)", test_pristine_save_bits),
    ("set_spell_level(12, 1) touches one level/bit", test_single_spell_12),
    ("each spell 1..36 keeps the other 46 levels", test_every_spell_1_to_36),
    ("level 0 clears the bit", test_zero_clears_bit),
    ("class-skill bits survive edits", test_hidden_class_bits_preserved),
    ("two spells + set_spell_levels()", test_two_spells_and_bulk),
    ("save/reload round-trip", test_save_reload),
    ("game block _pSplLvl sync", test_game_block_spell_sync),
    ("learn_all/forget_all keep hidden spells", test_learn_all_forget_all),
    ("clear_non_original_spells keeps class skills", test_clear_non_original),
    ("headless CharTab 22 rows", test_ui_headless),
]


def _run_ui_child():
    print("Round 5 UI child (tkinter available: %s)" % HAS_TK)
    _ui_checks()
    print("UI-CHILD-OK")
    return 0


def main():
    if "--ui-child" in sys.argv:
        return _run_ui_child()
    print("Round 5 spell tests (whitelist + pMemSpells 1<<(id-1))")
    print("python:", sys.version.split()[0], "| tkinter:", HAS_TK, "| lib:", LIB)
    if not SRC_SAVE.is_file():
        print("SKIP: 缺少测试用存档副本：%s" % SRC_SAVE)
        return 0
    before_saves = _saves_snapshot()

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

    after_saves = _saves_snapshot()
    if before_saves == after_saves:
        print("\nOK: 真实存档目录未被写入（%d 个文件 SHA256 一致）" % len(before_saves))
    else:
        failures += 1
        changed = sorted(set(before_saves) | set(after_saves))
        changed = [n for n in changed if before_saves.get(n) != after_saves.get(n)]
        print("\nFAILED: 真实存档目录被修改：%r" % (changed,))

    shutil.rmtree(TMPDIR, ignore_errors=True)

    elapsed = time.time() - start
    total = len(TESTS)
    print("\n%d/%d tests passed in %.2fs" % (total - failures, total, elapsed))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
