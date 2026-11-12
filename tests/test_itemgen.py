#!/usr/bin/env python3
"""Item generation tests for the Diablo 1 (DevilutionX 1.5.5) trainer.

Run with Python 3.12 from the repository root::

    python tests/test_itemgen.py

The suite is split into small numbered tests; every test prints what it checked
and the script exits non-zero if any assertion failed.  It never writes to the
real save files (``stash.sv`` is only read via :mod:`d1stash2`).
"""

import importlib.util
import os
import random
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

FIXTURES = os.environ.get("D1_TEST_SAVES") or os.path.join(
    ROOT, "tests", "fixtures", "saves")
STASH = os.path.join(FIXTURES, "stash.sv")
PYC_DIR = os.path.join(ROOT, "_d1pyc")
if not os.path.isdir(PYC_DIR):
    PYC_DIR = os.path.join(
        ROOT, "暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted", "PYZ.pyz_extracted")
if not os.path.isfile(STASH) or not os.path.isfile(os.path.join(PYC_DIR, "d1save.pyc")):
    print("SKIP: 需要 tests/fixtures/saves/stash.sv 与 _d1pyc/d1save.pyc")
    raise SystemExit(0)

#: the one known non-reproducible field in the real stash (see report)
KNOWN_REPLAY_ANOMALIES = {(84, "AC")}

RESULTS = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def load_pyc(name):
    path = os.path.join(PYC_DIR, name + ".pyc")
    if not os.path.exists(path):
        return None
    if PYC_DIR not in sys.path:
        sys.path.insert(0, PYC_DIR)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_stash_records():
    try:
        import d1stash2
        return d1stash2.Stash(STASH).records
    except Exception:
        d1save = load_pyc("d1save")
        sf = d1save.StashFile(STASH)
        data = sf.data
        import struct
        pages = struct.unpack_from("<I", data, 5)[0]
        p = 9 + pages * 204
        count = struct.unpack_from("<I", data, p)[0]
        p += 4
        return [bytes(data[p + i * 368:p + (i + 1) * 368]) for i in range(count)]


# ---------------------------------------------------------------------------
# 1. tables
# ---------------------------------------------------------------------------

def test_tables():
    items = T.base_items()
    # Round 2: the default pool is "generatable equipment" only (no starter
    # items, no IMISC_UNIQUE rows, no gold/potions/scrolls/books).
    check(len(items) == 74, "expected 74 generatable equipment bases, got %d" % len(items))
    check(not any(b["starter"] or b["unique_only"] for b in items),
          "generatable pool must not contain starter/unique-only rows")
    all_rows = T.base_items(include_unavailable=True, include_starter=True,
                            include_unique_only=True, include_non_equipment=True)
    check(len(all_rows) == 169, "AllItemsList should have 169 rows, got %d" % len(all_rows))
    check(len(T.base_items(include_unavailable=False, include_starter=True,
                           include_unique_only=True, include_non_equipment=True)) == 141,
          "expected 141 available non-Hellfire rows")
    check(len(T.PREFIXES) == 86, "prefix count %d" % len(T.PREFIXES))
    check(len(T.SUFFIXES) == 98, "suffix count %d" % len(T.SUFFIXES))
    check(len(T.UNIQUES) == 110, "unique count %d" % len(T.UNIQUES))
    check(len(T.SPELLS) == 52, "spell count %d" % len(T.SPELLS))

    # starting ("IDROP_NEVER") vs droppable versions of the same name
    starter = T.base_by_idx(1)
    droppable = T.base_by_name("Short Sword")
    check(starter["name"] == "Short Sword" and starter["durability"] == 20 and starter["value"] == 50,
          "IDI_WARRIOR row changed: %r" % (starter,))
    check(not starter["droppable"], "IDI_WARRIOR should not be droppable")
    check(droppable["idx"] == 119 and droppable["durability"] == 24 and droppable["value"] == 120,
          "droppable Short Sword should be idx 119 (24/120), got %r" % (droppable,))
    check(droppable["saved_idx"] == 114, "droppable Short Sword saved idx should be 114")

    # index remapping against real save indices
    check(T.saved_to_runtime(154) == 159 and T.base_by_saved_idx(154)["name"] == "Amulet",
          "saved 154 should be the Amulet")
    check(T.saved_to_runtime(151) == 156 and T.base_by_saved_idx(151)["name"] == "Ring",
          "saved 151 should be a Ring")
    check(T.runtime_to_saved(159) == 154, "runtime 159 must map back to saved 154")

    # inventory sizes (verified against the real stash grid in the report)
    check(T.base_by_name("Leather Armor")["size"] == (2, 3), "Leather Armor should be 2x3")
    check(T.base_by_name("Long Sword")["size"] == (1, 3), "Long Sword should be 1x3")
    check(T.base_by_name("Full Plate Mail")["size"] == (2, 3), "Full Plate should be 2x3")
    check(T.base_by_name("Amulet")["size"] == (1, 1), "Amulet should be 1x1")

    # 1.6.0 TSV assets differ from the 1.5.5 tables -> must not be used
    comp = T.compare_with_tsv()
    check(comp["total_field_diffs"] > 0, "expected the 1.6.0 TSVs to differ from 1.5.5")
    print("    TSV cross-check: %d matched rows, %d differing fields %s"
          % (comp["matched_by_id_or_name"], comp["total_field_diffs"],
             {k: len(v) for k, v in comp["field_diffs"].items()}))


# ---------------------------------------------------------------------------
# 2. record codec
# ---------------------------------------------------------------------------

def test_record_codec():
    records = read_stash_records()
    check(len(records) == 96, "stash should contain 96 records, got %d" % len(records))
    for i, rec in enumerate(records):
        check(len(rec) == 368, "record %d length %d" % (i, len(rec)))
        fields = G.record_to_fields(rec)
        check(fields["base_idx"] >= 0, "record %d idx %d does not map to a runtime item"
              % (i, fields["idx"]))
        rebuilt = G.fields_to_record(fields)
        check(rebuilt == rec, "record %d does not round-trip byte-for-byte" % i)

    # every byte of the padding is zero in the real records
    for i, rec in enumerate(records):
        for off in (6, 7, 24, 25, 26, 27, 44, 45, 46, 47, 49, 50, 51,
                    191, 306, 307, 334, 335, 355):
            check(rec[off] == 0, "record %d padding byte %d is 0x%02X" % (i, off, rec[off]))

    # name truncation is NUL terminated within 64 bytes
    f = dict(G.FIELD_DEFAULTS)
    f["name"] = "X" * 200
    f["iName"] = "Y" * 63
    rec = G.fields_to_record(f)
    check(rec[61:125].split(b"\0")[0] == b"X" * 63, "name should be truncated to 63 bytes")
    check(rec[125:189].split(b"\0")[0] == b"Y" * 63, "iName should keep 63 bytes")
    check(rec[61 + 63] == 0, "name must be NUL terminated")
    print("    96 real records round-trip byte-for-byte; padding is zero")


# ---------------------------------------------------------------------------
# 3. RNG
# ---------------------------------------------------------------------------

def test_rng():
    rng = G.Rng(12345)
    seq = [rng.rnd(100) for _ in range(7)]
    check(seq == [1, 71, 46, 90, 51, 81, 8], "RNG sequence mismatch: %r" % (seq,))
    rng = G.Rng(12345)
    check(rng.advance() == (12345 * 0x015A4E35 + 1) & 0xFFFFFFFF, "advance() mismatch")
    check(G.Rng(5).rnd(0) == 0 and G.Rng(5).rnd(-3) == 0, "GenerateRnd(<=0) must be 0")
    check(G._rnd_pl(G.Rng(99), 6, 10) in range(6, 11), "RndPL range")

    d1rng = load_pyc("d1rng")
    if d1rng is None:
        print("    d1rng.pyc not found - skipped cross-check")
        return
    rnd = random.Random(2024)
    mismatches = 0
    for _ in range(300):
        seed = rnd.getrandbits(32)
        ours = G.Rng(seed)
        theirs = d1rng.Rng(seed)
        for _ in range(20):
            v = rnd.choice([1, 2, 3, 4, 6, 10, 37, 100, 1000, 0x7FFF, 0x8000, 100000])
            a = ours.rnd(v)
            b = theirs.rnd(v)
            if a != b:
                mismatches += 1
                if mismatches < 5:
                    print("    RNG mismatch seed=%d v=%d ours=%d d1rng=%d" % (seed, v, a, b))
    check(mismatches == 0, "%d RNG values differ from the game's d1rng module" % mismatches)
    print("    RNG matches d1rng.pyc over 300 seeds x 20 draws")


# ---------------------------------------------------------------------------
# 4. regression against the real stash
# ---------------------------------------------------------------------------

def _replay_report():
    records = read_stash_records()
    ignore = {"durability"}  # mutable game state (wear/repair), not generation
    keys = [k for k in G._GENERATION_KEYS if k not in ignore]
    stats = {k: 0 for k in keys}
    replayable = 0
    vendor = []
    anomalies = []
    kinds = {0: 0, 1: 0, 2: 0}
    for i, rec in enumerate(records):
        f = G.record_to_fields(rec)
        kinds[f["magical"]] += 1
        if f["iCreateInfo"] & (T.CF_TOWN | T.CF_SMITH):
            vendor.append((i, f["name"], hex(f["iCreateInfo"])))
            continue
        rp = G.replay_item(rec).fields
        replayable += 1
        diffs = {}
        for k in keys:
            if rp.get(k) == f.get(k):
                stats[k] += 1
            else:
                diffs[k] = (rp.get(k), f.get(k))
        if diffs:
            anomalies.append((i, f["name"], diffs))
    return {
        "total": len(records),
        "kinds": kinds,
        "replayable": replayable,
        "vendor": vendor,
        "stats": stats,
        "keys": keys,
        "anomalies": anomalies,
    }


def test_stash_replay():
    rep = _replay_report()
    check(rep["total"] == 96, "expected 96 stash records")
    print("    records: normal=%d magic=%d unique=%d, vendor-skipped=%d"
          % (rep["kinds"][0], rep["kinds"][1], rep["kinds"][2], len(rep["vendor"])))
    for name, ci in [(v[1], v[2]) for v in rep["vendor"]]:
        print("    vendor item (RNG stream not replayable): %s ci=%s" % (name, ci))
    known_missing = {}
    for _i, field in KNOWN_REPLAY_ANOMALIES:
        known_missing[field] = known_missing.get(field, 0) + 1
    bad = []
    for field, count in rep["stats"].items():
        if count < rep["replayable"] - known_missing.get(field, 0):
            bad.append((field, count))
    seen_anomalies = set()
    for i, name, diffs in rep["anomalies"]:
        for field in diffs:
            if (i, field) not in KNOWN_REPLAY_ANOMALIES:
                bad.append((i, name, field, diffs[field]))
            else:
                seen_anomalies.add((i, field))
    if bad:
        raise AssertionError("unexpected replay differences: %r" % (bad,))
    check(seen_anomalies == KNOWN_REPLAY_ANOMALIES,
          "known anomaly set changed: %r" % (seen_anomalies,))
    print("    replayed %d/%d records: every generation field matches "
          "(durability excluded: items get worn/repaired)"
          % (rep["replayable"], rep["total"] - len(rep["vendor"])))
    for i, name, diffs in rep["anomalies"]:
        print("    known anomaly: #%d %s %r" % (i, name, diffs))


def test_stash_validate():
    records = read_stash_records()
    kinds = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
    bad = []
    for i, rec in enumerate(records):
        f = G.record_to_fields(rec)
        problems = G.validate(rec)
        kinds[f["magical"]][0] += 1
        if problems:
            kinds[f["magical"]][1] += 1
            bad.append((i, f["name"], problems[:3]))
    for label, magic in (("normal", 0), ("magic", 1), ("unique", 2)):
        print("    %-6s %2d/%2d valid" % (label, kinds[magic][0] - kinds[magic][1], kinds[magic][0]))
    # the only failing record is the AC anomaly documented above
    unexpected = [b for b in bad if b[0] != 84]
    check(not unexpected, "validate rejected legal records: %r" % (unexpected,))
    check(len(bad) <= 1, "expected at most one known AC anomaly")
    print("    96 real records: %d accepted by validate()" % (96 - len(bad)))


# ---------------------------------------------------------------------------
# 5. random magic generation
# ---------------------------------------------------------------------------

EQUIP_TYPES = ("Sword", "Axe", "Mace", "Bow", "Shield", "LightArmor", "Helm",
               "MediumArmor", "HeavyArmor", "Staff", "Ring", "Amulet")


def _equipment_bases():
    return [b for b in T.base_items(droppable_only=True)
            if b["itype_name"] in EQUIP_TYPES and not b["unique_only"]]


def test_generate_random():
    rnd = random.Random(20261111)
    bases = _equipment_bases()
    check(len(bases) > 60, "expected many equipment bases, got %d" % len(bases))
    names = set()
    start = time.time()
    for i in range(100):
        base = rnd.choice(bases)
        ilvl = rnd.randint(1, 50)
        item = G.generate(base["idx"], ilvl, "magic")
        check(len(item.record) == 368, "generated record is not 368 bytes")
        problems = G.validate(item.record)
        check(not problems, "generated %s ilvl %d invalid: %r" % (base["name"], ilvl, problems))
        check(item.fields["magical"] == 1, "rarity magic produced magical=%d" % item.fields["magical"])
        check(item.fields["iCreateInfo"] & 0x3F == ilvl, "iCreateInfo level bits != ilvl")
        check(G.fields_to_record(G.record_to_fields(item.record)) == item.record,
              "generated record does not round-trip")
        check(item.fields["iName"], "empty iName")
        names.add(item.fields["iName"])
        item.describe()
    elapsed = time.time() - start
    check(len(names) > 60, "expected varied names, got %d" % len(names))
    print("    100 random magic items valid in %.2fs (%d distinct names)" % (elapsed, len(names)))


def test_generate_named_affixes():
    # (base, ilvl, prefix, suffix).  The affix level must fall inside the game's
    # window [ilvl//2 (max 25), ilvl], so low-level affixes need a low ilvl.
    cases = [
        ("Long Sword", 2, "Sharp", "quality"),             # both low level, weapon
        ("Buckler", 2, "Fine", "of the Fox"),              # armor/shield affixes
        ("Short Sword", 30, "Brutal", "slaying"),          # 16 / 15
        ("Leather Armor", 60, "Godly", "of the Whale"),    # 60 / 60
        ("Buckler", 24, "Saintly", "of absorption"),       # 24 / 12
        ("Amulet", 30, "Drake's", "of the Zodiac"),        # 21 / 30
        ("War Staff", 50, "King's", "of haste"),           # 28 / 27
    ]
    for base_name, ilvl, prefix_name, suffix_name in cases:
        base = T.base_by_name(base_name)
        item = G.generate(base["idx"], ilvl, "magic", prefix=prefix_name, suffix=suffix_name)
        problems = G.validate(item.record)
        check(not problems, "%s + %s/%s invalid: %r" % (base_name, prefix_name, suffix_name, problems))
        check(item.prefix is not None and item.suffix is not None,
              "%s: affixes not reported" % base_name)
        check(item.prefix["name"].lower() == prefix_name.lower().removeprefix("of "),
              "%s: prefix %r != %r" % (base_name, item.prefix["name"], prefix_name))
        check(item.suffix["name"].lower() == suffix_name.lower().removeprefix("of "),
              "%s: suffix %r != %r" % (base_name, item.suffix["name"], suffix_name))
        iname = item.fields["iName"].lower()
        check(item.prefix["name"].lower() in iname, "%s: prefix missing from iName" % base_name)
        check(item.suffix["name"].lower() in iname, "%s: suffix missing from iName" % base_name)
        print("    %-14s ilvl %2d -> %-40s pre#%-3d suf#%-3d"
              % (base_name, ilvl, item.fields["iName"], item.prefix["index"], item.suffix["index"]))

    # deterministic search: same requested seed -> same record
    base = T.base_by_name("Long Sword")
    a = G.generate(base["idx"], 2, "magic", seed=987654321, prefix="Sharp", suffix="quality")
    b = G.generate(base["idx"], 2, "magic", seed=987654321, prefix="Sharp", suffix="quality")
    check(a.record == b.record, "seed search is not deterministic")
    print("    seed search is deterministic (seed=987654321 -> seed %d)" % a.seed)

    # impossible request is rejected with a reason
    try:
        G.generate(base["idx"], 5, "magic", prefix="King's")
    except G.ItemGenError as exc:
        print("    rejection works: %s" % str(exc)[:120])
    else:
        raise AssertionError("King's at ilvl 5 should have been rejected")
    check(G.generate(base["idx"], 5, "magic", prefix="King's", strict=False) is None,
          "strict=False should return None")


def test_eligible_affixes():
    sword = T.base_by_name("Long Sword")
    names = {a["name"] for a in G.eligible_affixes(sword["idx"], 30, "prefix")}
    # window at ilvl 30 is [15, 30]: level-16..28 weapon prefixes are in,
    # level-1 affixes such as "Sharp" are correctly out.
    check("Brutal" in names and "King's" in names,
          "expected mid/high weapon prefixes at ilvl 30: %r" % (names,))
    check("Sharp" not in names, "Sharp (level 1) must not be available at ilvl 30")
    check("Hydra's" not in names, "Hydra's is staff-only")
    low = {a["name"] for a in G.eligible_affixes(sword["idx"], 2, "prefix")}
    check("Sharp" in low and "King's" not in low,
          "ilvl 2 window [1,2] should offer Sharp but not King's: %r" % (low,))
    ring = T.base_by_name("Ring")
    ring_names = {a["name"] for a in G.eligible_affixes(ring["idx"], 30, "prefix")}
    check("Sharp" not in ring_names and "Drake's" in ring_names,
          "ring prefix pool looks wrong: %r" % (ring_names,))
    suffixes = {a["name"] for a in G.eligible_affixes(sword["idx"], 30, "suffix")}
    check("slaying" in suffixes and "gore" in suffixes,
          "weapon suffix pool wrong at ilvl 30: %r" % (suffixes,))
    check("the fox" not in suffixes,
          "'the fox' is a life affix (armor/shield/misc), not a weapon affix")
    # unique-only base rows never advertise affixes
    check(G.eligible_affixes(T.base_by_name("Cleaver", include_unique_only=True)["idx"], 30, "prefix") == [],
          "unique-only base should have no affixes")
    print("    eligible pools: sword %d prefixes / %d suffixes, ring %d prefixes"
          % (len(names), len(suffixes), len(ring_names)))


# ---------------------------------------------------------------------------
# 6. normal and unique items
# ---------------------------------------------------------------------------

def test_generate_normal():
    for base_name in ("Long Sword", "Leather Armor", "Buckler", "Ring", "Amulet",
                      "Short Bow", "Long Staff", "War Staff", "Scroll of Identify"):
        base = (T.base_by_name(base_name)
                or T.base_by_name(base_name, include_non_equipment=True))
        # Round 2: non-equipment bases (scrolls/books/potions) need the explicit
        # opt-in; the flag is harmless for equipment.
        item = G.generate(base["idx"], 20, "normal", allow_non_equipment=True)
        check(item.fields["magical"] == 0, "%s normal item is magical" % base_name)
        check(item.fields["PrePower"] == -1 and item.fields["SufPower"] == -1,
              "%s normal item has affix powers" % base_name)
        problems = G.validate(item.record)
        check(not problems, "%s normal invalid: %r" % (base_name, problems))
        check(item.fields["name"].startswith(base["name"].split(" of ")[0]) or base["misc_id"] == T.IMISC_BOOK,
              "%s: unexpected base name %r" % (base_name, item.fields["name"]))
    staff = G.generate(T.base_by_name("Long Staff")["idx"], 30, "normal")
    check(staff.fields["spell"] != 0 and staff.fields["charges"] > 0,
          "a normal staff should still roll a spell and charges")
    check(" of " in staff.fields["iName"], "normal staff name should be '<base> of <spell>'")
    print("    normal items valid; staff example: %s (%d charges)"
          % (staff.fields["iName"], staff.fields["charges"]))


def test_generate_unique():
    generated = 0
    skipped = []
    for uniq in T.unique_list():
        base = G.unique_base(uniq)
        if base is None or not base["available"]:
            skipped.append(uniq["name"])  # e.g. Bovine Plate (IDI_LGTFORGE)
            continue
        check(uniq["base_item_id"] == base["item_id"],
              "%s: uniques_for_base mapping is inconsistent" % uniq["name"])
        ilvl = max(uniq["min_level"], 1)
        item = G.generate(None, ilvl, "unique", unique_id=uniq["index"])
        check(item.fields["magical"] == 2, "%s is not unique" % uniq["name"])
        check(item.fields["iName"] == uniq["name"],
              "%s: iName %r" % (uniq["name"], item.fields["iName"]))
        check(item.fields["Uid"] == uniq["index"], "%s: wrong Uid" % uniq["name"])
        problems = G.validate(item.record)
        check(not problems, "%s unique invalid: %r" % (uniq["name"], problems))
        check(item.fields["iCreateInfo"] & T.CF_UNIQUE, "%s: missing CF_UNIQUE" % uniq["name"])
        generated += 1
    check(generated >= 85, "expected 85+ generated uniques, got %d" % generated)
    print("    %d unique items generated and validated (skipped %d unavailable bases: %s)"
          % (generated, len(skipped), ", ".join(skipped[:4])))

    # the 5 unique records from the real stash replay exactly (AC aside for quest uniques)
    records = read_stash_records()
    uniques = 0
    for i, rec in enumerate(records):
        f = G.record_to_fields(rec)
        if f["magical"] != 2:
            continue
        uniques += 1
        rp = G.replay_item(rec).fields
        for key in G._GENERATION_KEYS:
            if key == "durability":
                continue
            if key == "AC" and f["iCreateInfo"] == T.CF_UNIQUE:
                continue
            check(rp[key] == f[key], "unique record #%d field %s: %r != %r"
                  % (i, key, rp[key], f[key]))
    print("    %d real unique records replay field-exactly" % uniques)


# ---------------------------------------------------------------------------
# 7. names
# ---------------------------------------------------------------------------

def test_display_name_replay():
    """The game recomputes magic item names from seed+createInfo for display."""
    records = read_stash_records()
    checked = 0
    for i, rec in enumerate(records):
        f = G.record_to_fields(rec)
        if f["magical"] != 1:
            continue
        shown = G.translated_item_name_magical(f)
        check(shown is not None, "record #%d: the game could not build a name" % i)
        check(shown == f["iName"], "record #%d: display %r != stored %r" % (i, shown, f["iName"]))
        checked += 1
    check(checked == 37, "expected 37 magic records, got %d" % checked)

    generated = 0
    for base in _equipment_bases():
        for ilvl in (2, 20, 45, 63):
            if base["itype_name"] == "Staff" and ilvl > 51:
                # Round 2: magical staves are generated as stat-affix staves by
                # default; above ilvl 51 the game's own name replay disagrees
                # with the generation path (1.5.5 quirk, report section 7).
                continue
            item = G.generate(base["idx"], ilvl, "magic")
            shown = G.translated_item_name_magical(item.fields)
            check(shown is None or shown == item.fields["iName"],
                  "%s ilvl %d: display %r != stored %r"
                  % (base["name"], ilvl, shown, item.fields["iName"]))
            generated += 1
    print("    %d real + %d generated magic items: game display name == stored iName"
          % (checked, generated))


def test_inventory_sizes():
    """Inventory cell sizes must match the real stash grid (10x10 cells/page)."""
    try:
        import d1stash2
    except Exception:
        print("    d1stash2 not available - skipped")
        return
    stash = d1stash2.Stash(STASH)
    bbox = {}
    for page, grid in stash.grids.items():
        for y, row in enumerate(grid):
            for x, value in enumerate(row):
                if not value:
                    continue
                i = value - 1
                if i not in bbox:
                    bbox[i] = [x, y, x, y]
                b = bbox[i]
                b[0] = min(b[0], x)
                b[1] = min(b[1], y)
                b[2] = max(b[2], x)
                b[3] = max(b[3], y)
    mismatches = []
    for i, rec in enumerate(stash.records):
        f = G.record_to_fields(rec)
        base = T.base_by_saved_idx(f["idx"])
        size = (bbox[i][2] - bbox[i][0] + 1, bbox[i][3] - bbox[i][1] + 1)
        if size != base["size"]:
            mismatches.append((i, base["name"], size, base["size"]))
    check(not mismatches, "inventory size mismatches: %r" % (mismatches[:5],))
    print("    96/96 stash items occupy exactly their table size (cursor.cpp/GetInventorySize)")


def test_names():
    check(T.base_by_name("Leather Armor")["name"] == "Leather Armor", "base name")
    check(T.unique_by_name("Leather of Aut")["name"] == "Leather of Aut", "unique name")
    check(T.affix_by_name("prefix", "Sharp")["name"] == "Sharp", "prefix name")
    # suffix names are lower case in the game table ("of the fox")
    check(T.affix_by_name("suffix", "of the fox")["name"] == "the fox", "suffix name")
    check(T.affix_by_name("suffix", "the Fox")["name"] == "the fox", "suffix name without 'of'")

    # exact panel-width behaviour (the game stores the short-name fallback)
    check(G.string_in_panel("Ivory Two-Handed Sword of the stars") is False,
          "long name should not fit the 254px panel")
    check(G.string_in_panel("Ivory Sword of the stars") is True, "short name should fit")
    check(G.string_in_panel("Master's Two-Handed Sword") is True,
          "this name just fits (the game keeps the long form)")
    check(G.line_width("Leather of Aut") == 133, "panel width of 'Leather of Aut' changed")

    # the real stash contains the short-name fallback: "Ivory Sword of the stars"
    records = read_stash_records()
    found = False
    for rec in records:
        f = G.record_to_fields(rec)
        if f["iName"] == "Ivory Sword of the stars":
            found = True
            check(f["name"] == "Two-Handed Sword", "expected base name Two-Handed Sword")
    check(found, "expected the short-name fallback item in the stash")
    print("    names match the game's font-width fallback (e.g. 'Ivory Sword of the stars')")


# ---------------------------------------------------------------------------
# 8. validate() must reject broken records
# ---------------------------------------------------------------------------

def test_validate_rejects():
    base = T.base_by_name("Long Sword")
    good = G.generate(base["idx"], 30, "magic", seed=13579)
    check(G.validate(good.record) == [], "baseline item should validate")

    def mutate(**changes):
        f = G.record_to_fields(good.record)
        f.update(changes)
        return G.fields_to_record(f)

    cases = {
        "truncated": good.record[:360],
        "empty name": mutate(name=""),
        "wrong type": mutate(iType=T.ITEM_TYPE["Axe"]),
        "hellfire power": mutate(PrePower=T.ITEM_EFFECT_TYPE["IPL_ACDEMON"]),
        "wrong iName": mutate(iName="Definitely Not The Same Name"),
        "no affix values": mutate(VAdd1=0, VMult1=0, VAdd2=0, VMult2=0),
        "bad idx": mutate(idx=160),
    }
    for label, rec in cases.items():
        problems = G.validate(rec)
        check(problems, "validate() accepted a broken record: %s" % label)
        print("    rejected %-16s -> %s" % (label, problems[0][:80]))

    uniq = G.generate(None, 30, "unique", unique_id="Griswold's Edge")
    f = G.record_to_fields(uniq.record)
    f["Uid"] = 0  # The Butcher's Cleaver is a different base
    problems = G.validate(G.fields_to_record(f))
    check(problems, "validate() accepted a unique with the wrong Uid")
    print("    rejected %-16s -> %s" % ("wrong unique Uid", problems[0][:80]))


# ---------------------------------------------------------------------------
# 9. describe / misc
# ---------------------------------------------------------------------------

def test_describe_and_limits():
    item = G.generate(T.base_by_name("Long Sword")["idx"], 30, "magic", seed=24680)
    text = item.describe()
    check("Long Sword" in text and "seed=" in text, "describe() output looks wrong")
    check(len(item.record) == 368, "record size")

    # ilvl is the value stored in iCreateInfo (6 bits)
    try:
        G.generate(1, 64, "magic")
    except G.ItemGenError:
        pass
    else:
        raise AssertionError("ilvl 64 should be rejected")

    # unknown base item
    try:
        G.generate("No Such Item", 10, "magic")
    except G.ItemGenError:
        pass
    else:
        raise AssertionError("unknown base should be rejected")

    # unique-only bases cannot become normal/magic items
    cleaver = T.base_by_name("Cleaver", include_unique_only=True)
    check(cleaver["unique_only"], "Cleaver should be flagged unique_only")
    try:
        G.generate(cleaver["idx"], 20, "magic")
    except G.ItemGenError:
        pass
    else:
        raise AssertionError("unique-only base accepted as a magic item")
    print("    limits and error paths behave (ilvl 0..63, unknown base, unique-only base)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("tables", test_tables),
    ("record codec", test_record_codec),
    ("rng", test_rng),
    ("stash replay (96 real records)", test_stash_replay),
    ("stash validate", test_stash_validate),
    ("generate 100 random magic items", test_generate_random),
    ("generate named affixes (seed search)", test_generate_named_affixes),
    ("eligible affixes", test_eligible_affixes),
    ("normal items", test_generate_normal),
    ("unique items", test_generate_unique),
    ("game display-name replay", test_display_name_replay),
    ("inventory sizes", test_inventory_sizes),
    ("names / font fallback", test_names),
    ("validate rejects broken records", test_validate_rejects),
    ("describe / limits", test_describe_and_limits),
]


def main():
    print("item generation tests (DevilutionX 1.5.5, non-Hellfire)")
    print("python:", sys.version.split()[0], "| stash:", STASH)
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
