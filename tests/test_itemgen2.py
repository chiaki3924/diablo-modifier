#!/usr/bin/env python3
"""Round 2 tests: starter/unique_only filtering, numeric value search, uniques.

Run with Python 3.12 from the repository root::

    python tests/test_itemgen2.py

What this suite covers (see work/docs/itemgen_report.md, Round 2 section):

* the crash fix: ``IDI_SORCERER_DIABLO`` (= saved idx 5 / runtime 166, the
  Sorcerer's starter "Short Staff of Charged Bolt") and the other three class
  starting items are excluded from the base pool and rejected by ``generate()``;
* ``unique_only`` base rows are excluded from the base pool (no more unique
  names in the base dropdown) while ``base + unique_id`` still works;
* gold/potions/scrolls/books are excluded from the default base pool;
* the numeric affix search: ``prefix_value`` / ``suffix_value`` (exact roll
  values, LIFE/MANA in points, cursed affixes negative);
* ``unique_detail()`` / ``affix_value_range()`` helpers for the GUI.

The suite never writes to a save file; it only generates 368-byte records in
memory (``validate()`` is always run on them).
"""

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
import d1itemgen as G         # noqa: E402

#: runtime indices of the class starting items (id -> runtime idx)
STARTER_RUNTIME = {
    "IDI_WARRIOR": 1,
    "IDI_ROGUE": 4,
    "IDI_SORCERER": 5,
    "IDI_SORCERER_DIABLO": 166,
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _record_fields(item):
    """Decode the generated record (what will be written) -- not the cached dict."""
    return G.record_to_fields(item.record)


def _assert_valid(item, label):
    problems = G.validate(item.record)
    check(not problems, "%s: validate() = %r" % (label, problems))
    check(len(item.record) == 368, "%s: record is not 368 bytes" % label)
    check(G.fields_to_record(G.record_to_fields(item.record)) == item.record,
          "%s: record does not round-trip" % label)


# ---------------------------------------------------------------------------
# 1. base pool filtering
# ---------------------------------------------------------------------------

def test_base_pool_filters():
    pool = T.base_items()
    check(len(pool) == 74,
          "default base pool should be the 74 generatable equipment rows, got %d" % len(pool))
    check(len(pool) >= 70, "expected at least 70 generatable bases, got %d" % len(pool))

    # no starter rows, by IDI name *and* by saved/runtime index
    starter_ids = set(STARTER_RUNTIME)
    for rec in pool:
        check(not rec["starter"], "starter row leaked into base_items(): %r" % (rec,))
        check(rec["id"] not in starter_ids,
              "starter id %r leaked into base_items()" % (rec["id"],))
        check(not rec["unique_only"],
              "unique-only base leaked into base_items(): %r" % (rec["name"],))
        check(rec["equipment"], "non-equipment base leaked into base_items(): %r" % (rec["name"],))
        check(rec["available"], "unavailable base leaked into base_items(): %r" % (rec["name"],))
        check(rec["generatable"], "base_items() returned a non-generatable row: %r" % (rec["name"],))
    # the four starters exist but are flagged
    for item_id, idx in STARTER_RUNTIME.items():
        rec = T.base_by_idx(idx)
        check(rec is not None, "missing starter row %d" % idx)
        check(rec["id"] == item_id, "starter row %d should be %s, got %r"
              % (idx, item_id, rec["id"]))
        check(rec["starter"], "%s should be flagged starter" % item_id)
        check(not rec["generatable"], "%s must not be generatable" % item_id)
    # IDI_SORCERER and IDI_SORCERER_DIABLO share saved idx 5 -> the loader picks 166
    check(T.base_by_idx(5)["saved_idx"] == 5 and T.base_by_idx(166)["saved_idx"] == 5,
          "IDI_SORCERER/IDI_SORCERER_DIABLO must both map to saved idx 5")
    check(T.base_by_saved_idx(5)["idx"] == 166,
          "saved idx 5 must be loaded as IDI_SORCERER_DIABLO (runtime 166)")

    # the ordinary Long Staff (152) is the pool, the starter staff is not
    check(any(b["idx"] == 152 for b in pool), "Long Staff (152) missing from the base pool")
    check(not any(b["idx"] == 166 for b in pool), "IDI_SORCERER_DIABLO (166) in the base pool")
    check(T.base_by_name("Long Staff")["idx"] == 152, "Long Staff should resolve to 152")
    check(T.base_by_name("Short Staff of Charged Bolt") is None,
          "base_by_name() must not return the starter staff by default")
    check(T.base_by_name("Short Staff of Charged Bolt", include_starter=True)["idx"] == 166,
          "include_starter=True should still be able to inspect it")

    # the 5 ordinary staffs and the ring/amulet rows are all present
    pool_idx = {b["idx"] for b in pool}
    for idx in (151, 152, 153, 154, 155):
        check(idx in pool_idx, "ordinary staff %d missing from base_items()" % idx)
    for idx in (156, 157, 158, 159, 160):
        check(idx in pool_idx, "ring/amulet row %d missing from base_items()" % idx)
    check(len(T.base_items(droppable_only=True)) == 72,
          "droppable equipment pool should be 72, got %d"
          % len(T.base_items(droppable_only=True)))

    # explicit debugging flags restore the full table
    check(len(T.base_items(include_unavailable=True, include_starter=True,
                           include_unique_only=True, include_non_equipment=True)) == 169,
          "AllItemsList should have 169 rows")
    check(len(T.base_items(include_starter=True, include_unique_only=True,
                           include_non_equipment=True)) == 141,
          "expected 141 available non-Hellfire rows")
    # unique_only rows are 10 in total, 9 of them available
    uniq_only = T.base_items(include_unique_only=True, include_starter=True,
                             include_non_equipment=True, include_unavailable=True)
    uniq_only = [r for r in uniq_only if r["unique_only"]]
    check(len(uniq_only) == 10, "expected 10 unique_only rows, got %d" % len(uniq_only))
    check(any(r["name"] == "Arkaine's Valor" for r in uniq_only),
          "Arkaine's Valor should be unique_only")
    check(T.base_by_name("Arkaine's Valor") is None,
          "base_by_name() must not return a unique-only row by default")

    # the flag is exactly the documented formula
    for rec in T.base_items(include_unavailable=True, include_starter=True,
                            include_unique_only=True, include_non_equipment=True):
        want = (rec["available"] and rec["equipment"]
                and not rec["starter"] and not rec["unique_only"])
        check(rec["generatable"] == want,
              "generatable flag mismatch for %r" % (rec["name"],))
    print("    base pool: %d generatable equipment / %d available / 169 rows; "
          "4 starters + 10 unique-only excluded" % (len(pool), 141))


# ---------------------------------------------------------------------------
# 2. the crash guard: starter base items are refused
# ---------------------------------------------------------------------------

def test_starter_generation_refused():
    requests = [
        (166, {}),
        (166, {"rarity": "magic"}),
        (166, {"rarity": "normal"}),
        (166, {"rarity": "unique", "unique_id": 0}),
        ("Short Staff of Charged Bolt", {}),
        ("IDI_SORCERER_DIABLO", {}),
        (1, {}),          # IDI_WARRIOR (Short Sword 20/50)
        (4, {}),          # IDI_ROGUE (Short Bow)
        (5, {}),          # IDI_SORCERER -> saved 5 resolves to 166
    ]
    for request, kwargs in requests:
        try:
            item = G.generate(request, 10, **kwargs)
        except G.ItemGenError as exc:
            message = str(exc)
            check("初始装备" in message,
                  "rejection of %r should mention 初始装备: %s" % (request, message))
            check("IDI_" in message, "rejection of %r should name the IDI id: %s"
                  % (request, message))
            print("    refused %-32r -> %s" % (request, message[:70]))
        else:
            raise AssertionError("%r was accepted as a base item: %r"
                                 % (request, item.fields["iName"]))

    # strict=False still returns None instead of raising
    check(G.generate(166, 10, strict=False) is None,
          "strict=False should return None for a starter base")

    # the droppable version of the same name is still allowed
    short_sword = T.base_by_name("Short Sword")
    check(short_sword["idx"] == 119, "droppable Short Sword should be 119")
    item = G.generate("Short Sword", 30, "magic")
    _assert_valid(item, "droppable Short Sword")
    print("    droppable 'Short Sword' still generates: %s" % item.fields["iName"])


# ---------------------------------------------------------------------------
# 3. staff safety: no random spell staves unless explicitly allowed
# ---------------------------------------------------------------------------

def test_staff_generation_safe():
    staff = T.base_by_name("Long Staff")
    check(staff["idx"] == 152, "Long Staff should be 152")

    item = G.generate(152, 30, "magic", seed=12345)
    _assert_valid(item, "Long Staff magic")
    f = _record_fields(item)
    check(f["spell"] == 0, "stat staff should not roll a spell (spell=%d)" % f["spell"])
    check(f["charges"] == 0 and f["maxCharges"] == 0,
          "stat staff should not roll charges (%d/%d)" % (f["charges"], f["maxCharges"]))
    check(f["iType"] == T.ITEM_TYPE["Staff"], "staff iType")
    print("    Long Staff ilvl30 magic -> %-34s spell=%d charges=%d"
          % (f["iName"], f["spell"], f["charges"]))

    item = G.generate(152, 30, "magic", prefix="King's", suffix="haste", seed=99)
    _assert_valid(item, "King's Long Staff of haste")
    f = _record_fields(item)
    check(f["spell"] == 0 and f["charges"] == 0 and f["maxCharges"] == 0,
          "affix staff must stay spell/charge free, got spell=%d charges=%d"
          % (f["spell"], f["charges"]))
    check(f["iName"] == "King's Long Staff of haste",
          "unexpected name %r" % (f["iName"],))
    check(f["PrePower"] >= 0 and f["SufPower"] >= 0, "both affixes should be present")
    print("    King's Long Staff of haste: validate=%r spell=0 charges=0"
          % (G.validate(item.record),))

    # every generated magic staff (all 5 ordinary staff bases) is spell-free
    staffs = [b for b in T.base_items() if b["itype_name"] == "Staff"]
    check(len(staffs) == 5, "expected 5 ordinary staff bases, got %d" % len(staffs))
    for base in staffs:
        for ilvl in (1, 10, 30, 45, 51):
            staff_item = G.generate(base["idx"], ilvl, "magic")
            _assert_valid(staff_item, "%s ilvl %d" % (base["name"], ilvl))
            sf = _record_fields(staff_item)
            check(sf["spell"] == 0 and sf["charges"] == 0,
                  "%s ilvl %d rolled a spell staff" % (base["name"], ilvl))
    print("    5 staff bases x ilvl {1,10,30,45,51}: all stat staves, validate=[]")

    # above ilvl 51 stat staves are not representable -> clear error
    try:
        G.generate(152, 60, "magic")
    except G.ItemGenError as exc:
        check("ilvl" in str(exc) and "法杖" in str(exc),
              "staff ilvl>51 error should explain the quirk: %s" % (exc,))
        print("    staff ilvl 60 refused: %s" % str(exc)[:70])
    else:
        raise AssertionError("staff magic at ilvl 60 should be refused")

    # spell staves remain available as an explicit opt-in (game-native path)
    spell_staff = None
    for seed in range(1, 40):
        candidate = G.generate(152, 30, "magic", seed=seed, allow_staff_spells=True)
        sf = _record_fields(candidate)
        if sf["spell"] != 0 and sf["charges"] > 0:
            spell_staff = candidate
            break
    check(spell_staff is not None,
          "allow_staff_spells=True never produced a spell staff in 40 seeds")
    _assert_valid(spell_staff, "spell staff opt-in")
    sf = _record_fields(spell_staff)
    check(sf["spell"] != 0 and 0 < sf["charges"] <= sf["maxCharges"],
          "opt-in spell staff must have a valid spell/charges (%d/%d)"
          % (sf["charges"], sf["maxCharges"]))
    print("    allow_staff_spells=True -> %s (spell=%d charges=%d)"
          % (sf["iName"], sf["spell"], sf["charges"]))


# ---------------------------------------------------------------------------
# 4. unique-only bases and the unique catalogue
# ---------------------------------------------------------------------------

def test_unique_only_and_unique_generation():
    # unique names must not be usable as normal/magic bases
    for name in ("Cleaver", "Arkaine's Valor", "Griswold's Edge", "Veil of Steel"):
        check(T.base_by_name(name) is None, "%r leaked into base_by_name()" % name)
        try:
            G.generate(name, 30, "magic")
        except G.ItemGenError as exc:
            check("unique-only" in str(exc),
                  "%r should be rejected as unique-only: %s" % (name, exc))
        else:
            raise AssertionError("%r was accepted as a magic base" % name)
    print("    unique_only names refused as magic bases (4 checked)")

    # the correct way: ordinary base + unique_id (Plate Mail + uid 77)
    plate = T.base_by_name("Plate Mail")
    check(plate is not None and plate["idx"] == 67, "Plate Mail should be runtime 67")
    item = G.generate("Plate Mail", 27, "unique", unique_id=77)
    _assert_valid(item, "Naj's Light Plate")
    f = _record_fields(item)
    check(f["magical"] == 2, "unique item quality")
    check(f["Uid"] == 77, "Uid should be 77, got %d" % f["Uid"])
    check(f["iName"] == "Naj's Light Plate", "iName %r" % (f["iName"],))
    check(f["idx"] == plate["saved_idx"], "saved idx should be %d" % plate["saved_idx"])
    print("    Plate Mail + uid 77 -> %s (validate=%r)" % (f["iName"], G.validate(item.record)))

    # quest uniques still use their own IMISC_UNIQUE base row
    quest = G.generate(None, 30, "unique", unique_id="Griswold's Edge")
    _assert_valid(quest, "Griswold's Edge")
    check(quest.base["unique_only"], "quest uniques are built on a unique_only row")
    print("    quest unique Griswold's Edge -> %s (base %s)"
          % (quest.fields["iName"], quest.base["name"]))

    # every available unique can be generated from its (normal) base + uid
    generated = 0
    for uniq in T.unique_list():
        detail = G.unique_detail(uniq["index"])
        if not detail["available"]:
            continue
        it = G.generate(None, max(uniq["min_level"], 1), "unique", unique_id=uniq["index"])
        check(it.fields["iName"] == uniq["name"], "%s: iName" % uniq["name"])
        _assert_valid(it, uniq["name"])
        generated += 1
    check(generated >= 85, "expected 85+ generated uniques, got %d" % generated)
    print("    %d uniques generated from base+uid and validated" % generated)


# ---------------------------------------------------------------------------
# 5. numeric value search: suffix +STR (of the giants)
# ---------------------------------------------------------------------------

def test_value_search_str():
    sword = T.base_by_name("Short Sword")
    check(G.is_value_affix("of the giants", "suffix"), "'of the giants' should be numeric")
    check(G.affix_value_range("of the giants", "suffix") == (16, 20),
          "of the giants range should be (16, 20), got %r"
          % (G.affix_value_range("of the giants", "suffix"),))

    seeds = [1000, 2000, 3000, 4000, 5000]
    used_seeds = set()
    count = 0
    start = time.time()
    for want in range(16, 21):  # 16..20 = the whole IPL_STR roll range of giants
        hits = 0
        for seed in seeds:
            item = G.generate(sword["idx"], 30, "magic", suffix="of the giants",
                              suffix_value=want, seed=seed)
            f = _record_fields(item)
            check(f["PLStr"] == want,
                  "suffix_value=%d produced PLStr=%d (seed %d)" % (want, f["PLStr"], item.seed))
            check(item._extra["suffix_value"] == want,
                  "GenItem._extra suffix_value=%r != %d" % (item._extra["suffix_value"], want))
            check(item.suffix is not None and item.suffix["name"] == "giants",
                  "wrong suffix selected: %r" % (item.suffix,))
            check("giants" in f["iName"], "iName should contain 'giants': %r" % (f["iName"],))
            _assert_valid(item, "giants +%d seed %d" % (want, seed))
            used_seeds.add(item.seed)
            count += 1
            hits += 1
        check(hits == len(seeds), "expected %d hits for +%d, got %d" % (len(seeds), want, hits))
    elapsed = time.time() - start
    check(len(used_seeds) >= 10,
          "expected distinct seeds, got %d distinct for %d items" % (len(used_seeds), count))
    print("    of the giants +16..+20 x %d seeds: %d items, PLStr exact, %.2fs"
          % (len(seeds), count, elapsed))

    # out-of-range targets -> clear Chinese failure with the closest value
    for want, closest in ((15, "+16"), (21, "+20"), (10, "+16")):
        try:
            G.generate(sword["idx"], 30, "magic", suffix="of the giants", suffix_value=want)
        except G.ItemGenError as exc:
            message = str(exc)
            check("未找到" in message and "最接近" in message and "差距" in message,
                  "value failure message should contain 未找到/最接近/差距: %s" % (message,))
            check(closest in message, "closest value should be %s: %s" % (closest, message))
            print("    +%d refused: %s" % (want, message[:80]))
        else:
            raise AssertionError("+%d should not be reachable for 'of the giants'" % want)

    # tolerance widens the target
    item = G.generate(sword["idx"], 30, "magic", suffix="of the giants",
                      suffix_value=15, value_tolerance=1, seed=777)
    check(_record_fields(item)["PLStr"] == 16,
          "tolerance 1 should accept PLStr=16 for target 15")
    _assert_valid(item, "giants tolerance")
    print("    value_tolerance=1 accepted +16 for target +15")

    # a target inside the range that needs a longer search still resolves
    slow = G.generate(sword["idx"], 30, "magic", suffix="of the giants",
                      suffix_value=17, seed=424242)
    check(_record_fields(slow)["PLStr"] == 17, "PLStr should be 17")
    _assert_valid(slow, "giants +17")


# ---------------------------------------------------------------------------
# 6. numeric value search: LIFE/MANA display values, damage%, double requests
# ---------------------------------------------------------------------------

def test_value_search_life_and_damage():
    armor = T.base_by_name("Leather Armor")
    check(G.affix_value_range("the fox", "suffix") == (10, 15),
          "of the fox range should be (10, 15)")

    item = G.generate(armor["idx"], 1, "magic", suffix="the fox", suffix_value=12, seed=31)
    f = _record_fields(item)
    check(f["PLHP"] == 12 << 6,
          "LIFE display value 12 must be stored as PLHP=%d, got %d" % (12 << 6, f["PLHP"]))
    check(f["PLHP"] >> 6 == 12, "PLHP>>6 should be the displayed value")
    _assert_valid(item, "of the fox +12")
    print("    of the fox +12 life -> PLHP=%d (%d<<6), validate=[]" % (f["PLHP"], 12))

    ring = T.base_by_name("Ring")
    mana = G.generate(ring["idx"], 30, "magic", prefix="Dragon's", prefix_value=55, seed=4242)
    f = _record_fields(mana)
    check(f["PLMana"] == 55 << 6, "MANA 55 -> PLMana=%d, got %d" % (55 << 6, f["PLMana"]))
    _assert_valid(mana, "mana +55")
    print("    Dragon's +55 mana -> PLMana=%d" % f["PLMana"])

    # damage% (Brutal, IPL_DAMP 81..95)
    sword = T.base_by_name("Short Sword")
    check(G.affix_value_range("Brutal", "prefix") == (81, 95),
          "Brutal range should be (81, 95)")
    item = G.generate(sword["idx"], 30, "magic", prefix="Brutal", prefix_value=85, seed=606)
    f = _record_fields(item)
    check(f["PLDam"] == 85, "Brutal +85%% should give PLDam=85, got %d" % f["PLDam"])
    check("Brutal" in f["iName"], "iName should contain Brutal: %r" % (f["iName"],))
    _assert_valid(item, "Brutal +85")
    print("    Brutal +85%% damage -> PLDam=%d, validate=[]" % f["PLDam"])

    # two affixes, one numeric target: prefix Brutal value 81..95 + suffix slaying
    # (IPL_DAMMOD).  The hit rate is ~1 per 25k..130k seeds, so give it 1M tries.
    for want in (81, 90, 95):
        item = G.generate(sword["idx"], 30, "magic", prefix="Brutal", suffix="slaying",
                          prefix_value=want, seed=8080 + want, max_tries=1000000)
        f = _record_fields(item)
        check(f["PLDam"] == want, "Brutal +%d with suffix slaying: PLDam=%d" % (want, f["PLDam"]))
        check(item._extra["suffix_value"] is not None,
              "suffix 'slaying' should report a numeric value (IPL_DAMMOD)")
        _assert_valid(item, "Brutal+%d of slaying" % want)
    print("    Brutal +81/+90/+95 with suffix 'slaying': PLDam exact, validate=[]")


def test_value_search_double():
    ring = T.base_by_name("Ring")
    check(ring["idx"] == 156, "Ring should be 156")

    start = time.time()
    for seed in (100, 7919, 15838):
        item = G.generate(ring["idx"], 2, "magic", prefix="Bronze", suffix="of strength",
                          prefix_value=3, suffix_value=4, seed=seed)
        f = _record_fields(item)
        check(f["PLToHit"] == 3, "prefix Bronze +3 -> PLToHit=%d" % f["PLToHit"])
        check(f["PLStr"] == 4, "suffix strength +4 -> PLStr=%d" % f["PLStr"])
        check(item._extra["prefix_value"] == 3 and item._extra["suffix_value"] == 4,
              "per-slot values: %r" % (item._extra,))
        check(item.prefix["name"] == "Bronze" and item.suffix["name"] == "strength",
              "wrong affixes: %r / %r" % (item.prefix, item.suffix))
        _assert_valid(item, "Bronze Ring of strength")
    print("    double value Bronze +3 / strength +4 x3: exact fields, %.2fs"
          % (time.time() - start))

    # The worst realistic case: two affixes AND two values (Brutal +85%, giants
    # +18 STR).  The hit rate is ~1 per 137k seeds, so 200000 tries is only
    # ~77% reliable; the GUI must raise max_tries (2,000,000 -> >99.99%).
    # 5 different start seeds must all succeed within that budget.
    sword = T.base_by_name("Short Sword")
    start = time.time()
    found = 0
    for attempt in range(5):
        item = G.generate(sword["idx"], 30, "magic", prefix="Brutal", suffix="of the giants",
                          prefix_value=85, suffix_value=18, max_tries=2000000,
                          seed=attempt * 777777 + 1)
        f = _record_fields(item)
        check(f["PLDam"] == 85, "Brutal +85: PLDam=%d" % f["PLDam"])
        check(f["PLStr"] == 18, "giants +18: PLStr=%d" % f["PLStr"])
        check(item.prefix["name"] == "Brutal" and item.suffix["name"] == "giants",
              "wrong affixes: %r / %r" % (item.prefix, item.suffix))
        _assert_valid(item, "Brutal+85 of giants+18")
        found += 1
    elapsed = time.time() - start
    check(found >= 4, "expected at least 4/5 double-value searches to succeed, got %d" % found)
    print("    Brutal +85%% + giants +18: %d/5 seeded searches succeeded in %.2fs"
          % (found, elapsed))

    # the same search with the default 200k budget is not reliable (that is why
    # the GUI passes a larger max_tries) -- it must fail with a clear message
    # when it runs out of seeds instead of returning a wrong item.
    try:
        G.generate(sword["idx"], 30, "magic", prefix="Brutal", suffix="of the giants",
                   prefix_value=85, suffix_value=18, max_tries=2000, seed=1)
    except G.ItemGenError as exc:
        check("未找到" in str(exc) and "已尝试" in str(exc),
              "budget failure should be explicit: %s" % (exc,))
        print("    small max_tries -> clear failure: %s" % str(exc)[:70])
    else:
        raise AssertionError("a 2000-seed budget should not find the double target")

    # impossible double target -> ItemGenError mentioning both requirement parts
    try:
        G.generate(ring["idx"], 2, "magic", prefix="Bronze", suffix="of strength",
                   prefix_value=3, suffix_value=99, max_tries=5000)
    except G.ItemGenError as exc:
        check("未找到" in str(exc), "double value failure should be explicit: %s" % (exc,))
        print("    impossible double target refused: %s" % str(exc)[:80])
    else:
        raise AssertionError("suffix_value=99 is impossible but was accepted")


# ---------------------------------------------------------------------------
# 7. value search error handling
# ---------------------------------------------------------------------------

def test_value_errors():
    sword = T.base_by_name("Short Sword")
    staff = T.base_by_name("Long Staff")

    # non-numeric effects
    for request, kwargs in (
        ({"suffix": "haste", "suffix_value": 1}, "IPL_FASTATTACK"),
        ({"suffix": "the ages", "suffix_value": 1}, "IPL_INDESTRUCTIBLE"),
        ({"prefix": "Plentiful", "prefix_value": 2}, "IPL_CHARGES"),
        ({"suffix": "the leech", "suffix_value": 3}, "IPL_STEALLIFE"),
    ):
        try:
            G.generate(sword["idx"], 40, "magic", **request)
        except G.ItemGenError as exc:
            check("不是可指定的数值效果" in str(exc),
                  "non-numeric affix should explain itself: %s" % (exc,))
            check(kwargs in str(exc), "error should name %s: %s" % (kwargs, exc))
        else:
            raise AssertionError("%r should not accept a numeric value" % (request,))
    print("    4 non-numeric affixes refused with a clear message")

    # value without the affix
    for kwargs in ({"suffix_value": 4}, {"prefix_value": 4}):
        try:
            G.generate(sword["idx"], 30, "magic", **kwargs)
        except G.ItemGenError as exc:
            check("需要同时指定" in str(exc), "missing affix error: %s" % (exc,))
        else:
            raise AssertionError("value without affix should be refused")
    print("    value without affix refused")

    # value on normal/unique rarities
    for rarity, extra in (("normal", {}), ("unique", {"unique_id": 77})):
        try:
            G.generate(sword["idx"] if rarity == "normal" else "Plate Mail", 27, rarity,
                       suffix="of the giants", suffix_value=16, **extra)
        except G.ItemGenError as exc:
            check("只适用于" in str(exc), "rarity+value error: %s" % (exc,))
        else:
            raise AssertionError("value on rarity=%s should be refused" % rarity)
    print("    value on normal/unique rarity refused")

    # cursed affix uses a negative target
    check(G.affix_value_range("Tin", "prefix") == (-10, -6),
          "Tin (TOHIT_CURSE) range should be (-10, -6)")
    tin = G.generate(sword["idx"], 6, "magic", prefix="Tin", prefix_value=-8, seed=20)
    tf = _record_fields(tin)
    check(tf["PLToHit"] == -8, "Tin -8%% should give PLToHit=-8, got %d" % tf["PLToHit"])
    _assert_valid(tin, "Tin -8")
    print("    cursed prefix Tin -8%% -> PLToHit=%d" % tf["PLToHit"])

    # affix_value_range is None for fixed/flag effects
    for name in ("haste", "the ages", "the bear", "blocking"):
        check(G.affix_value_range(name, "suffix") is None,
              "%r should have no numeric range" % name)
    print("    affix_value_range() returns None for fixed/flag affixes")


# ---------------------------------------------------------------------------
# 8. unique_detail()
# ---------------------------------------------------------------------------

def test_unique_detail():
    detail = G.unique_detail(77)
    expect_keys = ("uid", "index", "name", "name_en", "base_idx", "base_saved_idx",
                   "base_name", "base_name_en", "base_id", "base_itype",
                   "min_level", "value", "num_powers", "powers", "available")
    for key in expect_keys:
        check(key in detail, "unique_detail(77) missing key %r" % key)
    check(detail["uid"] == 77 and detail["index"] == 77, "uid/index")
    check(detail["name"] == "Naj's Light Plate", "name: %r" % (detail["name"],))
    check(detail["base_name"] == "Plate Mail", "base: %r" % (detail["base_name"],))
    check(detail["base_idx"] == T.base_by_name("Plate Mail")["idx"],
          "base_idx should be the runtime idx of Plate Mail")
    check(detail["base_saved_idx"] == T.base_by_name("Plate Mail")["saved_idx"],
          "base_saved_idx")
    check(detail["min_level"] == 19, "min_level: %r" % (detail["min_level"],))
    check(detail["value"] == 78700, "value: %r" % (detail["value"],))
    check(len(detail["powers"]) == detail["num_powers"] == 6,
          "powers: %d vs num_powers %d" % (len(detail["powers"]), detail["num_powers"]))
    for power in detail["powers"]:
        check(set(power) == {"type", "type_name", "param1", "param2"},
              "power keys: %r" % (power,))
        check(isinstance(power["type"], int) and power["type_name"].startswith("IPL_"),
              "power type: %r" % (power,))
    names = [p["type_name"] for p in detail["powers"]]
    check("IPL_MAG" in names and "IPL_ALLRES" in names, "powers look wrong: %r" % (names,))
    print("    unique_detail(77): %s on %s, lvl %d, %d powers"
          % (detail["name"], detail["base_name"], detail["min_level"], len(detail["powers"])))

    # every unique has a complete detail record; unavailable ones (Bovine Plate)
    # are still listed with available=False so the GUI can grey them out
    checked = 0
    unavailable = []
    for uniq in T.unique_list():
        d = G.unique_detail(uniq["name"])
        check(d["uid"] == uniq["index"], "%s: uid" % uniq["name"])
        check(d["name"] == uniq["name"], "%s: name" % uniq["name"])
        check(d["base_idx"] >= 0, "%s: base_idx %r" % (uniq["name"], d["base_idx"]))
        check(d["base_name"], "%s: base_name" % uniq["name"])
        check(d["base_itype"] not in ("Misc", "Gold", "None"),
              "%s: base should be equipment, got %r" % (uniq["name"], d["base_itype"]))
        check(d["num_powers"] == len(d["powers"]) and len(d["powers"]) >= 1,
              "%s: powers" % uniq["name"])
        check(isinstance(d["available"], bool), "%s: available" % uniq["name"])
        if not d["available"]:
            unavailable.append(d["name"])
        checked += 1
    check(checked == 90, "expected 90 unique details, got %d" % checked)
    check(unavailable == ["Bovine Plate"],
          "only Bovine Plate should be unavailable, got %r" % (unavailable,))
    bovine = G.unique_detail("Bovine Plate")
    check(bovine["available"] is False and bovine["base_itype"] == "HeavyArmor",
          "Bovine Plate detail should be a complete but unavailable entry: %r" % (bovine,))
    print("    90 unique_detail() records complete; 1 unavailable (Bovine Plate)")
    print("      Bovine Plate -> base %s (runtime %d), available=False"
          % (bovine["base_name"], bovine["base_idx"]))

    # unknown id -> clear error
    try:
        G.unique_detail(999)
    except G.ItemGenError:
        pass
    else:
        raise AssertionError("unique_detail(999) should fail")


# ---------------------------------------------------------------------------
# 9. record integrity + timing summary
# ---------------------------------------------------------------------------

def test_record_integrity():
    """Every value-searched record must still be a self-consistent 368 bytes.

    ``(base name, ilvl, generate kwargs, affix name, kind)`` -- each affix is a
    numeric one (see ``_VALUE_POWERS``) whose range contains the requested value.
    """
    cases = [
        ("Short Sword", 30, dict(suffix="of the giants", suffix_value=19, seed=111), "giants", "suffix"),
        ("Plate Mail", 30, dict(prefix="Obsidian", prefix_value=35, seed=222), "Obsidian", "prefix"),
        ("Ring", 10, dict(prefix="Silver", prefix_value=18, seed=333), "Silver", "prefix"),
        ("Leather Armor", 1, dict(suffix="the fox", suffix_value=12, seed=444), "the fox", "suffix"),
        ("Long Staff", 30, dict(suffix="of sorcery", suffix_value=18, seed=555), "sorcery", "suffix"),
    ]
    for base_name, ilvl, kwargs, affix_name, kind in cases:
        base = T.base_by_name(base_name)
        item = G.generate(base["idx"], ilvl, "magic", **kwargs)
        _assert_valid(item, "%s %r" % (base_name, kwargs))

        # what the game will display must equal the stored name
        shown = G.translated_item_name_magical(item.fields)
        check(shown is None or shown == item.fields["iName"],
              "display name %r != stored %r" % (shown, item.fields["iName"]))

        # re-read the written bytes: the mapped fields really carry the target
        f = G.record_to_fields(item.record)
        affix = item.prefix if kind == "prefix" else item.suffix
        check(affix is not None and affix["name"] == T.affix_by_name(kind, affix_name)["name"],
              "%s: wrong affix %r" % (base_name, affix))
        target = kwargs["prefix_value"] if kind == "prefix" else kwargs["suffix_value"]
        check(item._extra["%s_value" % kind] == target,
              "%s: slot value %r != %d" % (base_name, item._extra["%s_value" % kind], target))
        power_name = affix["power_name"]
        check(power_name in G._VALUE_POWERS, "%s: %s is not a numeric power" % (base_name, power_name))
        for field, _sign, shift in G._VALUE_POWERS[power_name]:
            expected = target * (1 << shift)
            check(f[field] == expected,
                  "%s: record %s=%d, expected %d for target %d"
                  % (item.fields["iName"], field, f[field], expected, target))
        print("    %-14s ilvl %2d %-10s %+4d -> %-32s fields ok"
              % (base_name, ilvl, power_name, target, item.fields["iName"]))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("base pool filters (starter/unique_only/non-equipment)", test_base_pool_filters),
    ("starter base items refused (crash guard)", test_starter_generation_refused),
    ("staff generation stays spell-free by default", test_staff_generation_safe),
    ("unique_only bases + unique generation", test_unique_only_and_unique_generation),
    ("value search: +STR (of the giants)", test_value_search_str),
    ("value search: LIFE/MANA/damage%", test_value_search_life_and_damage),
    ("value search: two values at once", test_value_search_double),
    ("value search: error handling", test_value_errors),
    ("unique_detail()", test_unique_detail),
    ("record integrity of value-searched items", test_record_integrity),
]


def main():
    print("Round 2 item generation tests (DevilutionX 1.5.5, non-Hellfire)")
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
    print("\n%d/%d tests passed in %.2fs" % (len(TESTS) - failures, len(TESTS),
                                             time.time() - start))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
