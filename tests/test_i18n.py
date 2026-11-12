#!/usr/bin/env python3
"""i18n tests for the Diablo 1 (DevilutionX 1.5.5) trainer.

Run with Python 3.12 from the repository root::

    python tests/test_i18n.py

What is covered
---------------
* PO parsing: ``msgctxt``, multi-line msgid/msgstr, C escapes, ``msgid_plural``
  / ``msgstr[0]``, ``#:`` references, ``#, fuzzy`` skipping and the U+200B zero
  width spaces the Chinese catalogue is full of.
* The baked JSON cache at ``lib/data/zh_CN.json``: it must exist, be valid
  UTF-8 JSON and match a fresh parse of the PO (so a stale cache fails loudly).
* Name lookups: base items, prefixes, suffixes, uniques (100% of the table rows
  the game actually uses).
* ``affix_desc()`` wording: value ranges from ``param1..param2`` (never
  ``min_val``/``max_val``), required level, applicable item types, pinned values
  and "fixed effect" affixes.
* ``describe_power()`` for the unique-item power lists.
* ``stat_label()`` for every label the GUI needs.
* Both data modes: JSON (normal + simulated PyInstaller ``_MEIPASS`` layout) and
  the PO fallback.

The suite never writes to a save file; the only file it creates is a temporary
JSON cache in ``%TEMP%``.
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import d1tables as T          # noqa: E402
import d1i18n as I            # noqa: E402

JSON_PATH = os.path.join(LIB, "data", "zh_CN.json")
ZW = "\u200b"                 # U+200B ZERO WIDTH SPACE used by zh_CN.po
CJK = lambda text: any("\u3400" <= ch <= "\u9fff" for ch in text or "")

#: engine placeholder rows, not real items: "Book of " is a template the game
#: fills with a spell name (spell_name == Null), "Non Item"/"Scroll of None" are
#: IDI_NONE placeholders and Arena Potion only exists in the Hellfire arena.
SENTINEL_ITEMS = {"Non Item", "Scroll of None", "Book of ", "Book of", "Arena Potion"}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------------------
# 1. JSON cache
# ---------------------------------------------------------------------------

def test_json_cache():
    info = I.i18n_info()
    check(info["mode"] == "json", "expected the JSON cache, got %r" % (info,))
    check(os.path.isfile(JSON_PATH), "missing cache: %s" % JSON_PATH)
    check(info["entries"] >= 1700, "cache has too few entries: %d" % info["entries"])
    check(info["ctx_entries"] == 279, "msgctxt entries: %d" % info["ctx_entries"])

    raw = open(JSON_PATH, "rb").read()
    payload = json.loads(raw.decode("utf-8"))
    check(payload["meta"]["language"] == "zh_CN", "cache language")
    check(payload["meta"]["format"] == I.CACHE_FORMAT, "cache format version")
    check(payload["meta"]["zw_entries"] > 1000,
          "cache should record the U+200B cleanup")
    sample = "".join(list(payload["tr"].values())[:500])
    check(ZW not in sample, "cache values still contain U+200B")
    check(payload["tr"]["Short Sword"] == "短剑", "cache value cleaning")
    print("    %s: %d entries, %d ctx, %d entries had U+200B (%d chars removed)"
          % (os.path.relpath(JSON_PATH, ROOT), info["entries"], info["ctx_entries"],
             payload["meta"]["zw_entries"], payload["meta"]["zw_removed"]))

    # the cache must not be stale: build a fresh one and compare
    po = I.find_po()
    check(po is not None, "zh_CN.po not found")
    tmpdir = tempfile.mkdtemp(prefix="d1i18n_")
    try:
        rebuilt_path = os.path.join(tmpdir, "zh_CN.json")
        meta = I.build_cache(po, rebuilt_path)
        rebuilt = json.loads(open(rebuilt_path, "r", encoding="utf-8").read())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    check(meta["entries"] == payload["meta"]["entries"],
          "rebuilt entry count differs: %d vs %d"
          % (meta["entries"], payload["meta"]["entries"]))
    check(rebuilt["tr"] == payload["tr"],
          "lib/data/zh_CN.json is stale -- run: python lib/d1i18n.py --rebuild")
    check(rebuilt["tr_ctx"] == payload["tr_ctx"], "stale msgctxt table in cache")
    check(meta["source_sha256"] == payload["meta"]["source_sha256"], "PO sha256 changed")
    print("    cache is identical to a fresh parse of %s" % os.path.basename(po))


# ---------------------------------------------------------------------------
# 2. PO parser
# ---------------------------------------------------------------------------

def test_po_parser():
    po = I.find_po()
    check(po is not None, "zh_CN.po not found")
    parsed = I.parse_po(open(po, "r", encoding="utf-8-sig", errors="replace").read())
    stats = parsed["stats"]
    tr = parsed["tr"]

    check(stats["entries"] >= 1700, "parsed entries: %d" % stats["entries"])
    check(stats["ctx_entries"] == 279, "parsed msgctxt entries: %d" % stats["ctx_entries"])
    check(stats["plurals"] == 9, "msgid_plural entries: %d" % stats["plurals"])
    check(stats["multiline"] > 200, "multi-line entries: %d" % stats["multiline"])
    check(stats["fuzzy"] == 1, "fuzzy entries: %d" % stats["fuzzy"])

    # multi-line msgstr really was concatenated (escaped \n included)
    check(any("\n" in value for value in tr.values()),
          "no multi-line msgstr was joined correctly")
    # C escapes decoded
    check(tr["Resist Fire: {:+d}%"] == "火焰抗性: {:+d}%",
          "escape/ZW handling: %r" % tr.get("Resist Fire: {:+d}%"))
    # U+200B stripped from stored values but present in the raw file
    check(tr["Short Sword"] == "短剑", "U+200B not stripped: %r" % tr.get("Short Sword"))
    check(I.clean("短" + ZW + "剑") == "短剑", "clean()")
    # msgctxt entries kept apart from plain entries
    check("spell" in parsed["tr_ctx"], "msgctxt 'spell' missing")
    check(parsed["tr_ctx"]["spell"]["Firebolt"] == "火焰弹",
          "spell context: %r" % parsed["tr_ctx"]["spell"].get("Firebolt"))
    check("Firebolt" not in tr, "msgctxt entry leaked into the plain table")
    # plural: ngettext msgstr[0]
    check(tr.get("{:d} Scroll") == "{:d}卷轴", "plural msgstr[0]: %r" % tr.get("{:d} Scroll"))
    # fuzzy entries are skipped on purpose
    check(I.parse_po('#, fuzzy\nmsgid "Offline"\nmsgstr "回环"\n')["tr"] == {},
          "fuzzy entry was not skipped")
    # untranslated entries are skipped
    check(I.parse_po('msgid "Untranslated"\nmsgstr ""\n')["tr"] == {},
          "empty msgstr was not skipped")
    # references are parsed (used for the coverage report)
    check(any("Source/itemdat.cpp" in ref
              for refs in parsed["refs"].values() for ref in refs),
          "#: source references were not parsed")
    print("    entries=%d ctx=%d plurals=%d multiline=%d fuzzy=%d U+200B_entries=%d"
          % (stats["entries"], stats["ctx_entries"], stats["plurals"],
             stats["multiline"], stats["fuzzy"], stats["zw_entries"]))


# ---------------------------------------------------------------------------
# 3. item names
# ---------------------------------------------------------------------------

def test_item_names():
    cases = {
        "Short Sword": "短剑",
        "Leather Armor": "皮甲",
        "Ring": "戒指",
        "Amulet": "护符",
        "Long Sword": "长剑",
        "Buckler": "圆盾",
    }
    for en, cn in cases.items():
        got = I.item_name_cn(en)
        check(got == cn, "item_name_cn(%r) = %r, expected %r" % (en, got, cn))
        check(ZW not in got, "zero-width space left in %r" % got)
    # input that still carries the U+200B (as it comes out of the PO)
    check(I.item_name_cn("Short" + ZW + " Sword") == "短剑",
          "item_name_cn did not strip U+200B from the input")
    # unknown names fall back to English, never to an empty string
    check(I.item_name_cn("Definitely Not An Item") == "Definitely Not An Item",
          "unknown item should fall back to English")
    check(I.item_name_cn(None) is None, "item_name_cn(None)")

    total = 0
    missing = []
    try:
        rows = T.base_items(include_unavailable=True, include_starter=True,
                            include_unique_only=True)
    except TypeError:  # older d1tables without the round-2 flags
        rows = T.base_items(include_unavailable=True)
    for rec in rows:
        name = rec["name"]
        if not name or name in SENTINEL_ITEMS:
            continue
        total += 1
        if not CJK(I.item_name_cn(name)):
            missing.append(name)
    check(not missing, "untranslated base items: %r" % missing)
    playable_missing = [
        rec["name"] for rec in T.base_items()
        if rec["name"] and rec["name"] not in SENTINEL_ITEMS
        and not CJK(I.item_name_cn(rec["name"]))
    ]
    check(not playable_missing,
          "playable base items without Chinese names: %r" % playable_missing)
    print("    %d/%d real base item rows have Chinese names; generatable rows: 100%%"
          % (total - len(missing), total))
    sentinels = sorted({rec["name"] for rec in rows
                        if rec["name"] in SENTINEL_ITEMS})
    print("    skipped engine placeholders: %s"
          % (", ".join(repr(s) for s in sentinels) or "none in this table view"))


# ---------------------------------------------------------------------------
# 4. affix names
# ---------------------------------------------------------------------------

def test_affix_names():
    cases = {
        ("prefix", "Brutal"): "残忍",
        ("prefix", "Sharp"): "锋利",
        ("prefix", "Tin"): "锡",
        ("prefix", "Godly"): "神佑",
        ("suffix", "the fox"): "狐狸",
        ("suffix", "of the Fox"): "狐狸",      # in-game spelling
        ("suffix", "of Haste"): "匆忙",
        ("suffix", "giants"): "巨人",
    }
    for (kind, en), cn in cases.items():
        got = I.affix_name_cn(kind, en)
        check(got == cn, "affix_name_cn(%r, %r) = %r, expected %r" % (kind, en, got, cn))

    for kind in ("prefix", "suffix"):
        rows = T.affix_list(kind)
        missing = [r["name"] for r in rows if not CJK(I.affix_name_cn(kind, r["name"]))]
        check(not missing, "%s rows without Chinese names: %r" % (kind, missing))
        print("    %s: %d/%d translated" % (kind, len(rows) - len(missing), len(rows)))

    label = I.affix_label("prefix", T.affix_by_name("prefix", "Brutal"))
    check(label == "残忍（Brutal）", "affix_label: %r" % label)
    label = I.affix_label("suffix", T.affix_by_name("suffix", "haste"))
    check(label == "匆忙（of haste）", "affix_label (suffix): %r" % label)
    print("    labels: %s | %s" % (
        I.affix_label("prefix", T.affix_by_name("prefix", "Brutal")),
        I.affix_label("suffix", T.affix_by_name("suffix", "the fox"))))


# ---------------------------------------------------------------------------
# 5. unique names
# ---------------------------------------------------------------------------

def test_unique_names():
    # a unique the game's own catalogue definitely translates
    naj = "Naj's Light Plate"
    cn = I.unique_name_cn(naj)
    check(CJK(cn), "unique_name_cn(%r) = %r is not Chinese" % (naj, cn))
    print("    %s -> %s" % (naj, cn))

    rows = T.unique_list(include_unavailable=True)
    missing = [u["name"] for u in rows if not CJK(I.unique_name_cn(u["name"]))]
    check(not missing, "uniques without Chinese names: %r" % missing)
    available = T.unique_list()
    print("    unique: %d/%d translated (%d playable in non-Hellfire)"
          % (len(rows) - len(missing), len(rows), len(available)))

    # a couple of well known ones, printed for the report
    for name in ("The Butcher's Cleaver", "The Undead Crown", "Arkaine's Valor",
                 "Griswold's Edge", "Veil of Steel", "Harlequin Crest",
                 "Naj's Light Plate", "Windforce"):
        print("      %-24s %s" % (name, I.unique_name_cn(name)))
    check(I.unique_name_cn("Totally Unknown Unique") == "Totally Unknown Unique",
          "unknown unique should fall back to English")


# ---------------------------------------------------------------------------
# 6. affix_desc
# ---------------------------------------------------------------------------

def _affix(kind, name):
    rec = T.affix_by_name(kind, name)
    check(rec is not None, "affix %r/%r not found" % (kind, name))
    return rec


def test_affix_desc():
    brutal = _affix("prefix", "Brutal")
    text = I.affix_desc(brutal)
    check("残忍" in text, "Brutal should be 残忍: %r" % text)
    check("伤害" in text, "Brutal description lacks 伤害: %r" % text)
    check("16" in text and "需要物品等级" in text, "Brutal level: %r" % text)
    check("适用" in text and "武器" in text, "Brutal item types: %r" % text)
    # 81~95 comes from param1/param2, NOT min_val/max_val (1500/1950)
    check("+81~95%" in text, "Brutal range must be param1..param2: %r" % text)
    check("1500" not in text and "1950" not in text,
          "Brutal leaked min_val/max_val (gold price range): %r" % text)
    print("    %s" % text)

    # The brief's example claimed "of the Fox -> 敏捷"; the 1.5.5 table says the
    # fox is IPL_LIFE (+10~15 生命).  Test the real table and also a real DEX one.
    fox = _affix("suffix", "of the Fox")
    text = I.affix_desc(fox)
    check(fox["power_name"] == "IPL_LIFE", "the fox is IPL_LIFE in 1.5.5")
    check("狐狸" in text and "生命" in text, "fox description: %r" % text)
    check("+10~15" in text, "fox range: %r" % text)
    check("需要物品等级 1" in text and "适用" in text, "fox level/types: %r" % text)
    print("    %s" % text)

    dex = _affix("suffix", "of Dexterity")
    text = I.affix_desc(dex)
    check("敏捷" in text, "dexterity description lacks 敏捷: %r" % text)
    print("    %s" % text)

    # percent resist prefix
    text = I.affix_desc(_affix("prefix", "Sapphire"))
    check("闪电抗性" in text and "+51~60%" in text,
          "Sapphire should be 闪电抗性 +51~60%%: %r" % text)
    print("    %s" % text)

    # fixed-effect affix: must say 固定效果 and not invent a range
    text = I.affix_desc(_affix("suffix", "haste"))
    check("固定效果" in text, "haste should be a fixed effect: %r" % text)
    check("最快攻击" in text, "haste should name the speed tier: %r" % text)
    check("~" not in text.split("：", 1)[1].split("；")[0],
          "fixed effect should not show a range: %r" % text)
    print("    %s" % text)

    # pinned value
    text = I.affix_desc(_affix("suffix", "giants"), value=15)
    check("力量 +15" in text, "pinned value: %r" % text)
    check("指定值" in text, "pinned value must be labelled 指定值: %r" % text)
    print("    %s" % text)

    text = I.affix_desc(_affix("prefix", "Sapphire"), value=30)
    check("闪电抗性 +30%" in text and "指定值" in text, "pinned resist: %r" % text)
    print("    %s" % text)

    # a fixed effect cannot be pinned -> explicit, not silently ignored
    text = I.affix_desc(_affix("suffix", "haste"), value=4)
    check("不能指定数值" in text, "fixed effect + value should be rejected: %r" % text)
    print("    %s" % text)

    # curse affixes keep the game's sign
    text = I.affix_desc(_affix("prefix", "Tin"))
    check("命中" in text and text.count("-") >= 2,
          "Tin is a curse (negative to-hit): %r" % text)
    print("    %s" % text)

    # every row must render without a placeholder or a missing label
    for kind in ("prefix", "suffix"):
        for rec in T.affix_list(kind):
            text = I.affix_desc(rec)
            check("（" in text and "）" in text, "label missing in %r" % text)
            check("需要物品等级" in text, "level missing in %r" % text)
            check("适用 " in text, "item types missing in %r" % text)
            check("None" not in text and "特殊效果" not in text,
                  "unresolved effect in %r" % text)
    print("    all 86 prefixes + 98 suffixes render a complete description")


# ---------------------------------------------------------------------------
# 7. describe_power / unique detail
# ---------------------------------------------------------------------------

def test_describe_power():
    # real unique powers straight from d1tables
    cleaver = T.unique_by_name("The Butcher's Cleaver")
    texts = [I.describe_power(p) for p in cleaver["powers"]]
    check(any("力量 +10" in t for t in texts), "STR power: %r" % texts)
    check(any("4-24" in t for t in texts), "SETDAM power: %r" % texts)
    print("    The Butcher's Cleaver: %s" % " / ".join(texts))

    # fixed effects take their wording from the PO
    crown = T.unique_by_name("The Undead Crown")
    texts = [I.describe_power(p) for p in crown["powers"]]
    check(any("生命偷取" in t for t in texts), "RNDSTEALLIFE: %r" % texts)
    print("    The Undead Crown: %s" % " / ".join(texts))

    # spell charges resolve through d1tables + msgctxt('spell')
    staff = T.unique_by_name("Gleamsong")
    texts = [I.describe_power(p) for p in staff["powers"]]
    check(any("充能" in t for t in texts), "SPELL charges: %r" % texts)
    check(any("术" in t for t in texts), "spell name not translated: %r" % texts)
    print("    Gleamsong: %s" % " / ".join(texts))

    haste_power = {"power_name": "IPL_FASTATTACK", "param1": 4, "param2": 4}
    check("固定效果" in I.describe_power(haste_power), "fixed power marker")
    check("最快攻击" in I.describe_power(haste_power), "attack speed tier")

    check(I.describe_power(("IPL_STR", 5, 5)) == "力量 +5", "tuple form")
    check(I.describe_power("IPL_INDESTRUCTIBLE").startswith("固定效果"),
          "bare power name form")

    # every power of every unique must produce Chinese text
    for uniq in T.unique_list(include_unavailable=True):
        for power in uniq["powers"]:
            text = I.describe_power(power)
            check(text and CJK(text),
                  "power %r of %r: %r" % (power["type_name"], uniq["name"], text))
    print("    all %d powers of %d uniques describe in Chinese"
          % (sum(len(u["powers"]) for u in T.unique_list(include_unavailable=True)),
             len(T.unique_list(include_unavailable=True))))

    # itemgen2 owns unique_detail(); use it when it exists (same powers)
    if hasattr(T, "unique_detail"):
        detail = T.unique_detail(cleaver["index"])
        check(detail, "unique_detail returned nothing")
        collected = detail.get("powers") or []
        check(collected, "unique_detail has no powers")
        rendered = [I.describe_power(p) for p in collected]
        check(all(CJK(t) for t in rendered), "unique_detail powers: %r" % rendered)
        print("    unique_detail(%d): %s" % (cleaver["index"], " / ".join(rendered)))
    else:
        print("    unique_detail() not in d1tables yet (itemgen2 agent); "
              "used unique_by_name()['powers'] instead")


# ---------------------------------------------------------------------------
# 8. stat labels
# ---------------------------------------------------------------------------

def test_stat_labels():
    expected = {
        "strength": "力量",
        "dexterity": "敏捷",
        "vitality": "体力",
        "magic": "魔法",
        "tohit": "命中",
        "damage": "伤害",
        "armor": "护甲",
        "fireres": "火焰抗性",
        "lightres": "闪电抗性",
        "magicres": "魔法抗性",
        "allres": "全抗性",
        "life": "生命",
        "mana": "法力",
        "light": "光照",
        "attack_speed": "攻击速度",
        "steal_life": "生命吸取",
        "steal_mana": "法力吸取",
        "durability": "耐久",
        "charges": "充能",
        "spell_level": "法术等级",
        "all_attributes": "所有属性",
    }
    for key, cn in expected.items():
        got = I.stat_label(key)
        check(got == cn, "stat_label(%r) = %r, expected %r" % (key, got, cn))
    # loose spellings
    check(I.stat_label("IPL_FIRERES") == "火焰抗性", "IPL_ prefix")
    check(I.stat_label("Fire Resist") == "火焰抗性", "spaces")
    check(I.stat_label("attack-speed") == "攻击速度", "hyphen")
    check(I.stat_label("力量") == "力量", "Chinese passthrough")
    check(I.stat_label("nonsense.key") == "nonsense.key", "unknown key fallback")
    print("    %d canonical labels + loose spellings OK" % len(expected))
    print("    " + " | ".join("%s=%s" % (k, I.stat_label(k)) for k in
                             ("strength", "dex", "vit", "magic", "fireres",
                              "allres", "life", "mana", "light")))


# ---------------------------------------------------------------------------
# 9. PO fallback
# ---------------------------------------------------------------------------

def test_po_fallback():
    po = I.find_po()
    check(po is not None, "zh_CN.po not found")
    saved_candidates = I._json_candidates
    saved_po = os.environ.get("D1I18N_PO")
    try:
        # pretend the JSON cache is absent (fresh checkout / broken bundle)
        I._json_candidates = lambda: []
        os.environ["D1I18N_PO"] = str(po)
        info = I.reload()
        check(info["mode"] == "po", "PO fallback mode: %r" % (info,))
        check(info["path"].endswith("zh_CN.po"), "PO fallback path: %r" % info["path"])
        check(I.tr("Short Sword") == "短剑", "PO-mode lookup")
        check(I.item_name_cn("Short" + ZW + " Sword") == "短剑",
              "PO-mode U+200B handling")
        check(I.affix_desc(T.affix_by_name("prefix", "Brutal")).startswith("残忍"),
              "PO-mode affix_desc")
        print("    fallback: mode=%s entries=%d after reading %s"
              % (info["mode"], info["entries"], os.path.basename(info["path"])))
    finally:
        I._json_candidates = saved_candidates
        if saved_po is None:
            os.environ.pop("D1I18N_PO", None)
        else:
            os.environ["D1I18N_PO"] = saved_po
        I.reload()
    check(I.i18n_info()["mode"] == "json", "did not return to JSON mode")


# ---------------------------------------------------------------------------
# 10. frozen (PyInstaller) layout
# ---------------------------------------------------------------------------

def test_frozen_layout():
    if not os.path.isfile(JSON_PATH):
        raise AssertionError("JSON cache missing, cannot simulate _MEIPASS")
    tmpdir = tempfile.mkdtemp(prefix="d1i18n_meipass_")
    saved_meipass = I._MEIPASS
    saved_env = {key: os.environ.get(key) for key in ("D1I18N_JSON", "D1I18N_PO")}
    try:
        layout = os.path.join(tmpdir, "_d1lib", "data")
        os.makedirs(layout)
        shutil.copy2(JSON_PATH, os.path.join(layout, "zh_CN.json"))
        os.environ.pop("D1I18N_JSON", None)
        os.environ.pop("D1I18N_PO", None)
        I._MEIPASS = tmpdir
        info = I.reload()
        check(info["mode"] == "json", "frozen mode: %r" % (info,))
        check("_d1lib" in info["path"] and "_MEIPASS" not in info["path"],
              "frozen path not resolved from _MEIPASS: %r" % info["path"])
        check(I.item_name_cn("Ring") == "戒指", "frozen-mode lookup")
        print("    simulated _MEIPASS: %s" % os.path.relpath(info["path"], tmpdir))
    finally:
        I._MEIPASS = saved_meipass
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmpdir, ignore_errors=True)
        I.reload()
    check(I.i18n_info()["mode"] == "json", "failed to restore JSON mode")


# ---------------------------------------------------------------------------
# 11. tr() edges / misc helpers
# ---------------------------------------------------------------------------

def test_misc():
    check(I.tr(None) is None, "tr(None)")
    check(I.tr("") == "", "tr('')")
    check(I.tr("Offline") == "Offline", "fuzzy entry must stay English")
    check(I.tr("Offline", "离线") == "离线", "tr default")
    check(I.tr("Resist Fire: {:+d}%") == "火焰抗性: {:+d}%", "PO template")
    check(I.tr("Firebolt", ctx="spell") == "火焰弹", "msgctxt lookup")
    check(I.pgettext("spell", "Firebolt") == "火焰弹", "pgettext")
    check(I.tr_ctx("spell", "Firebolt") == "火焰弹", "tr_ctx")
    check(I.pgettext("spell", "No Such Spell") == "No Such Spell", "pgettext fallback")
    check(I.has_tr("Short Sword") and not I.has_tr("Definitely Not An Item"), "has_tr")
    check(I.clean("  " + ZW + " ") == "   ", "clean keeps normal whitespace")
    check(I.item_type_cn("Misc") == "杂项", "item_type_cn")
    check(I.item_type_cn("Armor") == "防具", "item_type_cn armor")
    check(I.item_type_cn(["Bow", "Staff", "Weapon"]) == "弓/法杖/武器",
          "item_type_cn(list)")
    check(I.spell_name_cn(1) == "火焰弹", "spell_name_cn(1)")
    # "Gold" the item and "Gold" the prefix share one PO msgid (金币); the
    # prefix is special-cased to 金 so a "Gold Sword" is not labelled 金币.
    check(I.item_name_cn("Gold") == "金币", "Gold item stays 金币")
    check(I.affix_name_cn("prefix", "Gold") == "金", "Gold prefix should be 金")
    print("    tr/default/ctx, has_tr, clean, item_type_cn and spell_name_cn OK")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("JSON cache", test_json_cache),
    ("PO parser", test_po_parser),
    ("item names", test_item_names),
    ("affix names", test_affix_names),
    ("unique names", test_unique_names),
    ("affix descriptions", test_affix_desc),
    ("describe_power / uniques", test_describe_power),
    ("stat labels", test_stat_labels),
    ("PO fallback mode", test_po_fallback),
    ("frozen (_MEIPASS) layout", test_frozen_layout),
    ("tr() edges and helpers", test_misc),
]


def main():
    print("i18n tests (DevilutionX 1.5.5 zh_CN)")
    print("python:", sys.version.split()[0], "| cache:", JSON_PATH)
    print("po:", I.find_po())
    failures = 0
    for index, (name, fn) in enumerate(TESTS, start=1):
        print("\n[%d/%d] %s" % (index, len(TESTS), name))
        try:
            fn()
        except Exception as exc:
            failures += 1
            print("    FAILED: %s" % exc)
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print("    OK")
    print("\n%d/%d tests passed" % (len(TESTS) - failures, len(TESTS)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
