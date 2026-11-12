#!/usr/bin/env python3
"""d1i18n.py -- Simplified-Chinese (zh_CN) localization for the Diablo 1 trainer.

The authoritative translation is the one the game itself ships with
(DevilutionX 1.5.5, ``Translations/zh_CN.po``)::

    ROOT/DevilutionX-1.5.5/Translations/zh_CN.po

That file is a gettext catalogue of 2043 entries covering every item name,
affix name, unique name, spell name and item-tooltip string.  Parsing a 380 KB
PO file on every launch is wasteful, so this module bakes it into a small JSON
cache (``work/lib/data/zh_CN.json``) and reads that first::

    source mode : work/lib/data/zh_CN.json
                  (fallback: read ROOT/DevilutionX-1.5.5/Translations/zh_CN.po)
    frozen mode : <sys._MEIPASS>/_d1lib/data/zh_CN.json   (PyInstaller --onefile)

Rebuild the cache after changing the PO::

    python lib/d1i18n.py --rebuild

Layout of the cache::

    {
      "meta": {"format": 1, "language": "zh_CN", "source": "...zh_CN.po",
               "source_sha256": "...", "entries": 1954, "ctx_entries": 279,
               "untranslated": 89, "fuzzy": 1,
               "zw_entries": 1337, "zw_removed": 4121},
      "tr":      {"Short Sword": "短剑", ...},
      "tr_ctx":  {"spell": {"Firebolt": "火球术"}, ...}
    }

Zero-width characters
---------------------
The Chinese PO uses U+200B ZERO WIDTH SPACE inside many msgstr values as a line
breaking hint for the game's font renderer (``"短\\u200b剑"``).  Tk cannot use
that hint: it would show up as a stray character and break string equality, so
``clean()`` strips U+200B/U+200C/U+200D/U+2060/U+FEFF/U+00AD from every string on
the way in *and* on the way out (the JSON cache already stores cleaned text).

Public API
----------
    tr(text, default=None, ctx=None)     -> str          generic lookup
    item_name_cn(en)                     -> str          base item name
    affix_name_cn(kind, en)              -> str          'prefix'/'suffix' name
    unique_name_cn(en)                   -> str          unique item name
    affix_label(kind, affix, with_effect=False)
                                         -> str          "中文（English）" [+ 效果名 +范围]
    affix_effect_label(affix)            -> str          short effect name ("火焰抗性")
    stat_label(key)                      -> str          "力量" / "火抗" ...
    spell_name_cn(spell_id)              -> str
    describe_power(power)                -> str          "力量 +10" / "固定效果：…"
    affix_desc(affix, value=None)        -> str          full Chinese sentence
    item_type_cn(name)                   -> str          AffixItemType -> 中文

    build_cache(po_path=None, out_path=None)            -> dict (meta)
    i18n_info()                          -> dict         where the data came from

Affix value semantics (important)
---------------------------------
The numbers shown to the player come from ``ItemPower{param1, param2}``: the
game rolls ``r = RndPL(param1, param2)`` in ``SaveItemPower()`` and adds the
signed result to the ``_iPL*`` field.  ``min_val``/``max_val`` in the same table
row are *only* used by ``CalcItemValue()`` (gold price) and must never be shown
as the effect value.  Example: suffix ``giants`` is ``IPL_STR 16..20`` with
``min_val=3200, max_val=5000`` -- the tooltip says "+16~20 力量", not 3200.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

__all__ = [
    "tr",
    "tr_ctx",
    "pgettext",
    "item_name_cn",
    "affix_name_cn",
    "unique_name_cn",
    "affix_label",
    "affix_effect_label",
    "affix_desc",
    "stat_label",
    "spell_name_cn",
    "describe_power",
    "item_type_cn",
    "clean",
    "parse_po",
    "build_cache",
    "i18n_info",
    "reload",
    "CACHE_FORMAT",
]

CACHE_FORMAT = 1
LANGUAGE = "zh_CN"
PO_RELPATH = Path("DevilutionX-1.5.5") / "Translations" / "zh_CN.po"

_HERE = Path(__file__).resolve().parent          # <repo>/lib（旧布局 <ROOT>/work/lib）
_REPO = _HERE.parent                             # <repo>（旧布局 <ROOT>/work）
_ROOT = _HERE.parents[1]                         # 旧布局的 <ROOT>
_MEIPASS = getattr(sys, "_MEIPASS", None)        # PyInstaller temp dir or None


# ---------------------------------------------------------------------------
# zero-width / invisible characters
# ---------------------------------------------------------------------------

#: U+200B is the one actually used by the zh_CN PO; the rest are cheap insurance
#: against hand-edited PO files (ZWNJ/ZWJ/word-joiner/BOM/soft hyphen).
_ZW_CHARS = "\u200b\u200c\u200d\u2060\ufeff\u00ad"
_ZW_RE = re.compile("[" + _ZW_CHARS + "]")


def clean(text):
    """Remove zero-width formatting characters (U+200B & friends) from *text*."""
    if not text:
        return text
    if not _ZW_RE.search(text):
        return text
    return _ZW_RE.sub("", text)


def _clean_meta(text):
    """Same as :func:`clean` but also returns how many characters were removed."""
    if not text:
        return text, 0
    matches = _ZW_RE.findall(text)
    if not matches:
        return text, 0
    return _ZW_RE.sub("", text), len(matches)


# ---------------------------------------------------------------------------
# gettext PO parser
# ---------------------------------------------------------------------------

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "?": "?",
}

_FIELD_RE = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+"(.*)"\s*$')
_STRING_RE = re.compile(r'^"(.*)"\s*$')


def _unescape(value):
    """Decode C-style escapes used inside PO string literals."""
    if "\\" not in value:
        return value
    out = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "\\" and i + 1 < n:
            nxt = value[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "x" and i + 3 < n:
                try:
                    out.append(chr(int(value[i + 2:i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            # unknown escape: keep the escaped character (gettext behaviour)
            out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_po(text):
    """Parse a gettext ``.po`` document.

    Returns a dict::

        {
          "tr":      {msgid: msgstr},                 # entries without msgctxt
          "tr_ctx":  {context: {msgid: msgstr}},      # entries with msgctxt
          "refs":    {msgid: ["Source/itemdat.cpp:249", ...]},
          "stats":   {"entries":…, "ctx_entries":…, "untranslated":…,
                      "fuzzy":…, "zw_entries":…, "zw_removed":…,
                      "multiline":…, "plurals":…}
        }

    Handles the parts of the format DevilutionX actually uses: ``msgctxt``
    (``P_()``), multi-line ``msgid``/``msgstr``, ``msgid_plural``/``msgstr[0]``
    (``ngettext``), ``#:`` source references, ``#, fuzzy`` flags, C escapes and
    U+200B inside translations.  Untranslated (empty msgstr) and fuzzy entries
    are skipped -- showing English is better than showing a stale guess.
    """
    table = {}
    ctx_table = {}
    refs = {}
    stats = {
        "entries": 0,
        "ctx_entries": 0,
        "untranslated": 0,
        "fuzzy": 0,
        "zw_entries": 0,
        "zw_removed": 0,
        "multiline": 0,
        "plurals": 0,
        "obsolete": 0,
    }

    cur = _new_entry()
    state = None  # which field continuation lines append to

    def flush():
        nonlocal cur, state
        msgid = cur["msgid"]
        msgstr = cur["msgstr"]
        is_header = cur["msgctxt"] is None and msgid == "" and msgstr == ""
        if not is_header and msgid:
            if cur["fuzzy"]:
                stats["fuzzy"] += 1
            elif msgstr == "":
                stats["untranslated"] += 1
            else:
                if cur["multiline"]:
                    stats["multiline"] += 1
                key = clean(msgid)
                value, removed = _clean_meta(msgstr)
                if removed:
                    stats["zw_entries"] += 1
                    stats["zw_removed"] += removed
                if cur["msgctxt"] is not None:
                    ctx = clean(cur["msgctxt"])
                    ctx_table.setdefault(ctx, {})[key] = value
                    stats["ctx_entries"] += 1
                else:
                    table[key] = value
                if cur["refs"]:
                    refs[key] = list(cur["refs"])
        cur = _new_entry()
        state = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            if line.startswith("#~"):
                stats["obsolete"] += 1
                continue
            if line.startswith("#,"):
                flags = [f.strip() for f in line[2:].split(",")]
                if "fuzzy" in flags:
                    cur["fuzzy"] = True
            elif line.startswith("#:"):
                cur["refs"].extend(line[2:].split())
            continue
        if line.startswith('"'):
            match = _STRING_RE.match(line)
            if match and state:
                cur[state] += _unescape(match.group(1))
                cur["multiline"] = True
            continue
        match = _FIELD_RE.match(line)
        if not match:
            continue
        field = match.group(1)
        value = _unescape(match.group(2))
        if field == "msgctxt":
            if cur["msgid"] or cur["msgstr"] or cur["msgctxt"] is not None:
                flush()
            cur["msgctxt"] = value
            state = "msgctxt"
        elif field == "msgid":
            if cur["msgid"] or cur["msgstr"]:
                flush()
            cur["msgid"] = value
            state = "msgid"
        elif field == "msgid_plural":
            cur["msgid_plural"] = value
            stats["plurals"] += 1
            state = "msgid_plural"
        else:  # msgstr / msgstr[N]
            index = 0
            bracket = field.find("[")
            if bracket >= 0:
                index = int(field[bracket + 1:-1])
            if index == 0:
                cur["msgstr"] = value
            state = "msgstr"
    flush()
    stats["entries"] = len(table)
    return {"tr": table, "tr_ctx": ctx_table, "refs": refs, "stats": stats}


def _new_entry():
    return {
        "msgctxt": None,
        "msgid": "",
        "msgid_plural": None,
        "msgstr": "",
        "refs": [],
        "fuzzy": False,
        "multiline": False,
    }


# ---------------------------------------------------------------------------
# data locations (source tree vs PyInstaller bundle)
# ---------------------------------------------------------------------------

def _json_candidates():
    """Candidate paths for the baked JSON cache, best first."""
    out = []
    env = os.environ.get("D1I18N_JSON")
    if env:
        out.append(Path(env))
    if _MEIPASS:
        base = Path(_MEIPASS)
        out.extend([
            base / "_d1lib" / "data" / "zh_CN.json",
            base / "_d1lib" / "py" / "data" / "zh_CN.json",
            base / "_d1lib" / "zh_CN.json",
            base / "data" / "zh_CN.json",
        ])
    out.extend([
        _HERE / "data" / "zh_CN.json",
        _HERE / "zh_CN.json",
    ])
    return out


def _po_candidates():
    """Candidate paths for the game's PO file, best first."""
    out = []
    env = os.environ.get("D1I18N_PO")
    if env:
        out.append(Path(env))
    if _MEIPASS:
        out.append(Path(_MEIPASS) / PO_RELPATH)
    out.append(_REPO / "data" / "game-tables" / PO_RELPATH)
    out.append(_REPO / PO_RELPATH)
    out.append(_ROOT / PO_RELPATH)  # 旧工作区布局
    return out


def find_po():
    """Return the first existing ``zh_CN.po`` path, or ``None``."""
    for path in _po_candidates():
        if path.is_file():
            return path
    return None


def find_json():
    """Return the first existing ``zh_CN.json`` cache path, or ``None``."""
    for path in _json_candidates():
        if path.is_file():
            return path
    return None


DEFAULT_JSON = _HERE / "data" / "zh_CN.json"


# ---------------------------------------------------------------------------
# cache build / load
# ---------------------------------------------------------------------------

def build_cache(po_path=None, out_path=None, verbose=False):
    """Parse the PO file and (re)write the JSON cache.

    Returns the ``meta`` dict that was stored.  Raises ``FileNotFoundError``
    when no PO file can be found (frozen builds only ship the JSON).
    """
    po_path = Path(po_path) if po_path else find_po()
    if po_path is None or not po_path.is_file():
        raise FileNotFoundError("zh_CN.po not found (looked in %s)" % (
            ", ".join(str(p) for p in _po_candidates()),))
    out_path = Path(out_path) if out_path else DEFAULT_JSON

    raw_bytes = po_path.read_bytes()
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    parsed = parse_po(text)
    meta = {
        "format": CACHE_FORMAT,
        "language": LANGUAGE,
        "source": str(po_path),
        "source_relpath": str(PO_RELPATH),
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    meta.update(parsed["stats"])
    payload = {"meta": meta, "tr": parsed["tr"], "tr_ctx": parsed["tr_ctx"]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    data = (blob + "\n").encode("utf-8")
    out_path.write_bytes(data)
    if verbose:
        print("wrote %s (%d bytes, %d chars, %d entries, %d ctx entries, %d with U+200B)"
              % (out_path, len(data), len(blob) + 1, meta["entries"],
                 meta["ctx_entries"], meta["zw_entries"]))
    return meta


def _apply(table, ctx_table, source, meta=None):
    """Install a translation table into the module-level caches."""
    global _TR, _TR_CTX, _TR_LOWER, _INFO
    tr = {}
    removed = 0
    for key, value in table.items():
        clean_key = clean(key)
        clean_value, n = _clean_meta(value)
        removed += n
        tr[clean_key] = clean_value
    lower = {}
    for key, value in tr.items():
        folded = key.casefold()
        # First writer wins: the PO has both "Ring" (item) and stray lowercase
        # forms; keeping the first keeps item names authoritative.
        lower.setdefault(folded, value)
    ctx = {}
    for context, entries in (ctx_table or {}).items():
        ctx[clean(context)] = {clean(k): clean(v) for k, v in entries.items()}
    _TR = tr
    _TR_CTX = ctx
    _TR_LOWER = lower
    _INFO = {
        "mode": "json" if source.suffix.lower() == ".json" else "po",
        "path": str(source),
        "entries": len(tr),
        "ctx_entries": sum(len(v) for v in ctx.values()),
        "zw_removed": removed,
        "meta": meta or {},
    }
    return _INFO


def _load(force=False):
    if not force and _TR is not None:
        return
    errors = []
    for path in _json_candidates():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            _apply(payload.get("tr", {}), payload.get("tr_ctx", {}), path,
                   payload.get("meta"))
            return
        except Exception as exc:  # corrupt cache -> fall through to the PO
            errors.append("%s: %s" % (path, exc))
    po = find_po()
    if po is not None:
        parsed = parse_po(po.read_text(encoding="utf-8-sig", errors="replace"))
        _apply(parsed["tr"], parsed["tr_ctx"], po, parsed["stats"])
        return
    _apply({}, {}, Path("<none>"), {"errors": errors})


def reload():
    """Force re-reading the JSON cache / PO file (mainly for tests)."""
    _load(force=True)
    return i18n_info()


_TR = None
_TR_CTX = {}
_TR_LOWER = {}
_INFO = {}


def i18n_info():
    """Describe where the translations came from (mode/path/counts)."""
    _load()
    return dict(_INFO)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def _lookup_key(text):
    """Exact lookup, then case-insensitive, then stripped variants."""
    _load()
    value = _TR.get(text)
    if value:
        return value
    stripped = text.strip()
    if stripped != text:
        value = _TR.get(stripped)
        if value:
            return value
    return _TR_LOWER.get(stripped.casefold())


def tr(text, default=None, ctx=None):
    """Translate *text* to Chinese.

    Zero-width characters are stripped before the lookup.  When the PO has no
    entry, *default* is returned when given (the caller's own Chinese wording),
    else the original *text*.
    """
    if text is None:
        return default
    _load()
    source = str(text)
    key = clean(source)
    if ctx:
        value = _TR_CTX.get(ctx, {}).get(key)
        if value:
            return value
        value = _TR_CTX.get(ctx, {}).get(key.strip())
        if value:
            return value
    value = _lookup_key(key)
    if value:
        return value
    if default is not None:
        return default
    return source


def has_tr(text, ctx=None):
    """True if *text* has a Chinese translation."""
    if text is None:
        return False
    _load()
    key = clean(str(text))
    if ctx and _TR_CTX.get(ctx, {}).get(key):
        return True
    return _lookup_key(key) is not None


def pgettext(context, text, default=None):
    """gettext ``P_()`` style lookup: same msgid, explicit ``msgctxt``.

    The PO uses contexts for spell names (``P_("spell", "Firebolt")``) and a few
    UI strings; without the context those entries are not reachable.
    """
    return tr(text, default=default, ctx=context)


def tr_ctx(context, text, default=None):
    """Alias of :func:`pgettext` (reads better at some call sites)."""
    return tr(text, default=default, ctx=context)


def _variants(name):
    """Name spellings an affix table may use ('the fox' <-> 'of the fox')."""
    out = [name]
    low = name.lower()
    if low.startswith("of "):
        out.append(name[3:].strip())
    else:
        out.append("of " + name)
    out.append(name[:1].upper() + name[1:])
    out.append(name.lower())
    seen = set()
    unique = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _name_lookup(name):
    if name is None:
        return None
    source = clean(str(name)).strip()
    for candidate in _variants(source):
        value = _lookup_key(candidate)
        if value:
            return value
    return None


def item_name_cn(en, default=None):
    """Chinese name of a base item ('Short Sword' -> '短剑')."""
    if en is None:
        return default
    value = _name_lookup(en)
    if value:
        return value
    return default if default is not None else clean(str(en))


def unique_name_cn(en, default=None):
    """Chinese name of a unique item ('Naj's Light Plate' -> ...)."""
    return item_name_cn(en, default)


def affix_name_cn(kind, en, default=None):
    """Chinese name of a prefix/suffix.

    ``kind`` is ``'prefix'``/``'suffix'`` (only used for the fallback wording);
    ``en`` may be the raw table name (``'the fox'``) or the in-game form
    (``'of the Fox'``).

    ``Gold`` is special-cased: the PO has a single ``"Gold"`` entry translated
    as 金币 (the item/currency) because gettext cannot see that the prefix table
    reuses the same msgid.  The game therefore prints 金币 for a "Gold Sword";
    this module prints 金, which is what the prefix actually means.
    """
    if en is None:
        return default
    kind_key = str(kind or "").lower()
    name = clean(str(en)).strip()
    if kind_key.startswith("pre") and name in _PREFIX_OVERRIDES:
        return _PREFIX_OVERRIDES[name]
    value = _name_lookup(name)
    if value:
        return value
    if default is not None:
        return default
    if kind_key.startswith("suf"):
        return name if name.lower().startswith("of ") else "of " + name
    return name


#: affix names whose PO entry is shared with a different (unrelated) msgid
_PREFIX_OVERRIDES = {"Gold": "金"}


#: short, GUI-friendly effect names overriding the (longer) tooltip label.
#: Everything else comes from ``_POWER_SPEC`` / ``stat_label`` -- one single
#: translation table, no second wording.
_EFFECT_SHORT = {
    "IPL_FASTATTACK": "攻速",
    "IPL_STEALLIFE": "吸血",
}


def affix_effect_label(affix):
    """Short Chinese effect name of a prefix/suffix, for GUI drop-downs.

    ``affix`` is a ``d1tables`` affix dict (``power_name``/``param1``/``param2``);
    a bare ``ItemPower`` name (``"IPL_FIRERES"``) is accepted too.  The wording
    is the same one :func:`affix_desc` uses (``_POWER_SPEC`` / :func:`stat_label`),
    just without the numbers::

        >>> affix_effect_label(d1tables.affix_by_name('prefix', 'Ruby'))
        '火焰抗性'
        >>> affix_effect_label(d1tables.affix_by_name('suffix', 'of the heavens'))
        '所有属性'
        >>> affix_effect_label(d1tables.affix_by_name('suffix', 'haste'))
        '攻速'

    Returns ``""`` when *affix* carries no power information at all.
    """
    if isinstance(affix, dict):
        power = (affix.get("power_name") or affix.get("type_name") or "")
    else:
        power = affix
    power = clean(str(power or "")).strip()
    if not power:
        return ""
    if power in _EFFECT_SHORT:
        return _EFFECT_SHORT[power]
    spec = _POWER_SPEC.get(power)
    if spec is not None:
        return spec[0]
    if not power.upper().startswith("IPL_"):
        return ""
    label = stat_label(power, default="")
    if label and clean(label) != power:
        return label
    return "特殊效果"


def _itemgen_module():
    """Lazy import of :mod:`d1itemgen` (authoritative value ranges)."""
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import d1itemgen  # noqa: WPS433 (deliberate lazy import)
    return d1itemgen


def _affix_roll_range(affix):
    """Displayed ``(min, max)`` of an affix, or ``None`` for fixed effects.

    Uses :func:`d1itemgen.affix_value_range` (the generator's own rule: only
    ``_VALUE_POWERS`` rows are settable) so a label can never advertise a value
    the generator refuses.  A local ``_POWER_SPEC`` fallback keeps the label
    usable when ``d1itemgen`` is not bundled.
    """
    try:
        rng = _itemgen_module().affix_value_range(dict(affix))
        if rng is not None:
            return int(rng[0]), int(rng[1])
        return None
    except Exception:  # noqa: BLE001 - label must never explode
        spec = _POWER_SPEC.get(str(affix.get("power_name") or ""))
        if spec is None or spec[1] not in (_PCT, _FLAT, _TOHIT_DAMP):
            return None
        p1 = int(affix.get("param1") or 0)
        p2 = int(affix.get("param2") or 0)
        lo, hi = min(p1, p2), max(p1, p2)
        sign = spec[2]
        if sign > 0:
            return sign * lo, sign * hi
        return sign * hi, sign * lo


def _signed_range_text(lo, hi):
    """'+51~+60' / '+51' / '-10~-6' -- signs on both ends, no unit."""
    if lo == hi:
        return "%+d" % lo
    return "%+d~%+d" % (lo, hi)


def affix_label(kind, affix, with_effect=False):
    """``中文名（English）`` label for a prefix/suffix combo box.

    *affix* may be an ``d1tables`` affix dict or a plain English name.  With
    ``with_effect=True`` the short effect name and (for numeric powers) the
    roll range are appended, e.g.::

        >>> affix_label('prefix', d1tables.affix_by_name('prefix', 'Ruby'),
        ...             with_effect=True)
        '红宝石（Ruby） 火焰抗性 +51~+60'
        >>> affix_label('prefix', d1tables.affix_by_name('prefix', "Dragon's"),
        ...             with_effect=True)
        '翼龙的（Dragon's） 法力 +51~+60'
        >>> affix_label('suffix', d1tables.affix_by_name('suffix', 'haste'),
        ...             with_effect=True)
        '匆忙（of haste） 固定效果：最快攻击'

    Fixed-effect affixes (attack speed, charges, spells, life steal, ...) get
    the ``固定效果：…`` wording from :func:`affix_desc`; they never get a fake
    number.  A plain name (no dict) returns just ``中文名（English）``.
    """
    if isinstance(affix, dict):
        name = affix.get("name") or ""
        kind = affix.get("kind") or kind
        record = affix
    else:
        name = "" if affix is None else str(affix)
        record = None
    cn = affix_name_cn(kind, name, default="")
    english = clean(name).strip()
    if str(kind or "").lower().startswith("suf") and not english.lower().startswith("of "):
        english = "of " + english
    if not cn or cn == english:
        label = english
    else:
        label = "%s（%s）" % (cn, english)
    if not with_effect or record is None:
        return label

    power = str(record.get("power_name") or "")
    effect = affix_effect_label(record)
    rng = _affix_roll_range(record)
    if rng is not None:
        return "%s %s %s" % (label, effect, _signed_range_text(rng[0], rng[1]))
    detail = _effect_text(power, int(record.get("param1") or 0),
                          int(record.get("param2") or 0)) if power else ""
    if detail:
        return "%s %s" % (label, detail)
    return label



def _tables_module():
    """Import :mod:`d1tables` (works when this file is run as a script)."""
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import d1tables  # noqa: WPS433 (deliberate lazy import)
    return d1tables


def spell_name_cn(spell_id):
    """Chinese spell name for a ``SpellID`` value (uses d1tables)."""
    try:
        rec = _tables_module().spell_by_id(int(spell_id))
    except Exception:
        rec = None
    if not rec or not rec.get("name"):
        return "法术 #%s" % spell_id
    name = rec["name"]
    return tr(name, default=name, ctx="spell")


def item_type_cn(name):
    """Chinese label for an ``AffixItemType`` name (or a list of them)."""
    if isinstance(name, (list, tuple)):
        return _item_types_cn(name)
    return _ITEM_TYPE_CN.get(str(name), str(name))


def _item_types_cn(names):
    parts = []
    for name in names or ():
        cn = item_type_cn(name)
        if cn and cn not in parts:
            parts.append(cn)
    return "/".join(parts)


# ---------------------------------------------------------------------------
# stat labels
# ---------------------------------------------------------------------------

_ITEM_TYPE_CN = {
    "Misc": "杂项",
    "Bow": "弓",
    "Staff": "法杖",
    "Weapon": "武器",
    "Shield": "盾牌",
    "Armor": "防具",
}

#: canonical Chinese labels for the attributes this tool shows.
#: NOTE: the game itself translates "Vitality" as 活力; the trainer UI uses
#: 体力 (the wording the brief asks for) -- see docs/i18n_report.md.
_STAT_LABELS = {
    "strength": "力量",
    "str": "力量",
    "magic": "魔法",
    "mag": "魔法",
    "dexterity": "敏捷",
    "dex": "敏捷",
    "vitality": "体力",
    "vit": "体力",
    "all_attributes": "所有属性",
    "all_attribs": "所有属性",
    "attribs": "所有属性",
    "attributes": "所有属性",
    "tohit": "命中",
    "hit": "命中",
    "chance_to_hit": "命中率",
    "attack_rating": "命中",
    "damage": "伤害",
    "dam": "伤害",
    "damage_percent": "伤害%",
    "dammod": "伤害%",
    "armor": "护甲",
    "ac": "护甲",
    "armor_class": "护甲等级",
    "fireres": "火焰抗性",
    "fire_res": "火焰抗性",
    "fire_resist": "火焰抗性",
    "lightres": "闪电抗性",
    "lightning_res": "闪电抗性",
    "lightning_resist": "闪电抗性",
    "magicres": "魔法抗性",
    "magic_res": "魔法抗性",
    "magic_resist": "魔法抗性",
    "allres": "全抗性",
    "all_res": "全抗性",
    "all_resist": "全抗性",
    "life": "生命",
    "hp": "生命",
    "hit_points": "生命",
    "mana": "法力",
    "mp": "法力",
    "light": "光照",
    "light_radius": "光照范围",
    "attack_speed": "攻击速度",
    "ias": "攻击速度",
    "fastattack": "攻击速度",
    "hit_recovery": "硬直恢复",
    "fastrecover": "硬直恢复",
    "block": "格挡",
    "fastblock": "格挡速度",
    "cast_speed": "施法速度",
    "fastcast": "施法速度",
    "steal_life": "生命吸取",
    "lifesteal": "生命吸取",
    "steallife": "生命吸取",
    "steal_mana": "法力吸取",
    "manasteal": "法力吸取",
    "stealmana": "法力吸取",
    "durability": "耐久",
    "dur": "耐久",
    "indestructible": "不可破坏",
    "charges": "充能",
    "spell_level": "法术等级",
    "spllvladd": "法术等级",
    "spell": "法术",
    "fire_damage": "火焰伤害",
    "lightning_damage": "闪电伤害",
    "damage_from_enemies": "受击伤害",
    "gethit": "受击伤害",
    "level": "等级",
    "min_level": "需要等级",
    "item_level": "物品等级",
    "req_str": "需要力量",
    "req_mag": "需要魔法",
    "req_dex": "需要敏捷",
    "value": "价值",
    "gold": "金币",
    "prefix": "前缀",
    "suffix": "后缀",
    "unique": "暗金",
}

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def stat_label(key, default=None):
    """Chinese label for a stat/attribute key.

    Accepts loose spellings (``'fireres'``, ``'Fire Resist'``,
    ``'IPL_FIRERES'``, ``'strength'``, ...).  Strings that are already Chinese
    are returned unchanged.
    """
    if key is None:
        return default
    text = clean(str(key)).strip()
    if not text:
        return default
    if _CJK_RE.search(text):
        return text
    norm = re.sub(r"[\s\-/]+", "_", text).casefold().strip("_")
    for candidate in (norm, norm[4:] if norm.startswith("ipl_") else norm):
        if candidate in _STAT_LABELS:
            return _STAT_LABELS[candidate]
    # power-name fallback: IPL_TOHIT_DAMP -> "命中/伤害"
    spec = _POWER_SPEC.get("IPL_" + norm.upper().lstrip("IPL_"))
    if spec:
        return spec[0]
    return default if default is not None else text


# ---------------------------------------------------------------------------
# item powers -> Chinese
# ---------------------------------------------------------------------------
# value kind of each power
_PCT = "pct"        # signed percentage from param1..param2
_FLAT = "flat"      # signed plain number
_LIGHT = "light"    # param * 10 percent light radius
_DMG = "dmg"        # fixed damage range param1-param2
_TOHIT_DAMP = "td"  # damage range + CalculateToHitBonus(param1) hit bonus
_FIXED = "fixed"    # no numbers, fixed effect
_CHARGES = "charges"
_SPELL = "spell"

#: power name -> (Chinese label, value kind, sign)
_POWER_SPEC = {
    "IPL_TOHIT": ("命中", _PCT, 1),
    "IPL_TOHIT_CURSE": ("命中", _PCT, -1),
    "IPL_DAMP": ("伤害", _PCT, 1),
    "IPL_DAMP_CURSE": ("伤害", _PCT, -1),
    "IPL_TOHIT_DAMP": ("命中/伤害", _TOHIT_DAMP, 1),
    "IPL_TOHIT_DAMP_CURSE": ("命中/伤害", _TOHIT_DAMP, -1),
    "IPL_DOPPELGANGER": ("命中/伤害", _TOHIT_DAMP, 1),
    "IPL_ACP": ("护甲", _PCT, 1),
    "IPL_ACP_CURSE": ("护甲", _PCT, -1),
    "IPL_SETAC": ("护甲等级", _DMG, 1),
    "IPL_AC_CURSE": ("护甲等级", _FLAT, -1),
    "IPL_FIRERES": ("火焰抗性", _PCT, 1),
    "IPL_FIRERES_CURSE": ("火焰抗性", _PCT, -1),
    "IPL_LIGHTRES": ("闪电抗性", _PCT, 1),
    "IPL_LIGHTRES_CURSE": ("闪电抗性", _PCT, -1),
    "IPL_MAGICRES": ("魔法抗性", _PCT, 1),
    "IPL_MAGICRES_CURSE": ("魔法抗性", _PCT, -1),
    "IPL_ALLRES": ("全抗性", _PCT, 1),
    "IPL_ALLRESZERO": ("全抗性", _FIXED, 1),
    "IPL_SPLLVLADD": ("法术等级", _FLAT, 1),
    "IPL_CHARGES": ("充能", _CHARGES, 1),
    "IPL_SPELL": ("法术", _SPELL, 1),
    "IPL_FIREDAM": ("火焰伤害", _DMG, 1),
    "IPL_LIGHTDAM": ("闪电伤害", _DMG, 1),
    "IPL_ADDACLIFE": ("闪电伤害", _DMG, 1),
    "IPL_FIRE_ARROWS": ("火焰箭伤害", _DMG, 1),
    "IPL_LIGHT_ARROWS": ("闪电箭伤害", _DMG, 1),
    "IPL_FIREBALL": ("火球伤害", _DMG, 1),
    "IPL_SETDAM": ("固定伤害", _DMG, 1),
    "IPL_SETDUR": ("固定耐久", _DMG, 1),
    "IPL_STR": ("力量", _FLAT, 1),
    "IPL_STR_CURSE": ("力量", _FLAT, -1),
    "IPL_MAG": ("魔法", _FLAT, 1),
    "IPL_MAG_CURSE": ("魔法", _FLAT, -1),
    "IPL_DEX": ("敏捷", _FLAT, 1),
    "IPL_DEX_CURSE": ("敏捷", _FLAT, -1),
    "IPL_VIT": ("体力", _FLAT, 1),
    "IPL_VIT_CURSE": ("体力", _FLAT, -1),
    "IPL_ATTRIBS": ("所有属性", _FLAT, 1),
    "IPL_ATTRIBS_CURSE": ("所有属性", _FLAT, -1),
    "IPL_GETHIT": ("受击伤害", _FLAT, -1),
    "IPL_GETHIT_CURSE": ("受击伤害", _FLAT, 1),
    "IPL_LIFE": ("生命", _FLAT, 1),
    "IPL_LIFE_CURSE": ("生命", _FLAT, -1),
    "IPL_MANA": ("法力", _FLAT, 1),
    "IPL_MANA_CURSE": ("法力", _FLAT, -1),
    "IPL_DUR": ("耐久", _PCT, 1),
    "IPL_DUR_CURSE": ("耐久", _PCT, -1),
    "IPL_CRYSTALLINE": ("伤害", _FIXED, 1),
    "IPL_INDESTRUCTIBLE": ("耐久", _FIXED, 1),
    "IPL_LIGHT": ("光照范围", _LIGHT, 1),
    "IPL_LIGHT_CURSE": ("光照范围", _LIGHT, -1),
    "IPL_DAMMOD": ("伤害", _PCT, 1),
    "IPL_DECAY": ("伤害", _PCT, 1),
    "IPL_MULT_ARROWS": ("多重箭", _FIXED, 1),
    "IPL_THORNS": ("荆棘", _FIXED, 1),
    "IPL_NOMANA": ("无法力消耗", _FIXED, 1),
    "IPL_ABSHALFTRAP": ("陷阱伤害", _FIXED, 1),
    "IPL_KNOCKBACK": ("击退", _FIXED, 1),
    "IPL_3XDAMVDEM": ("对恶魔伤害", _FIXED, 1),
    "IPL_STEALMANA": ("法力吸取", _FIXED, 1),
    "IPL_STEALLIFE": ("生命吸取", _FIXED, 1),
    "IPL_TARGAC": ("穿透护甲", _FIXED, 1),
    "IPL_FASTATTACK": ("攻击速度", _FIXED, 1),
    "IPL_FASTRECOVER": ("硬直恢复", _FIXED, 1),
    "IPL_FASTBLOCK": ("格挡速度", _FIXED, 1),
    "IPL_FASTCAST": ("施法速度", _FIXED, 1),
    "IPL_RNDARROWVEL": ("箭速", _FIXED, 1),
    "IPL_ONEHAND": ("单手", _FIXED, 1),
    "IPL_DRAINLIFE": ("流失生命", _FIXED, 1),
    "IPL_RNDSTEALLIFE": ("生命偷取", _FIXED, 1),
    "IPL_NOMINSTR": ("无力量需求", _FIXED, 1),
    "IPL_INVCURS": ("特殊外观", _FIXED, 1),
    "IPL_DEVASTATION": ("毁灭", _FIXED, 1),
    "IPL_PERIL": ("危险", _FIXED, 1),
    "IPL_JESTERS": ("小丑", _FIXED, 1),
    "IPL_ACDEMON": ("对恶魔护甲", _FIXED, 1),
    "IPL_ACUNDEAD": ("对不死护甲", _FIXED, 1),
    "IPL_MANATOLIFE": ("法力转生命", _FIXED, 1),
    "IPL_LIFETOMANA": ("生命转法力", _FIXED, 1),
    "IPL_ADDMANAAC": ("充能弹", _FIXED, 1),
    "IPL_INVALID": ("无", _FIXED, 1),
}

#: fixed-effect powers -> (PO msgid, built-in Chinese fallback)
_FIXED_TEXT = {
    "IPL_INDESTRUCTIBLE": ("indestructible", "坚不可摧"),
    "IPL_FASTBLOCK": ("fast block", "快速格挡"),
    "IPL_FASTCAST": ("fast cast", "快速施法"),
    "IPL_MULT_ARROWS": ("multiple arrows per shot", "每次射出多支箭"),
    "IPL_NOMANA": ("user loses all mana", "使用者失去所有法力"),
    "IPL_ABSHALFTRAP": ("absorbs half of trap damage", "吸收一半陷阱伤害"),
    "IPL_KNOCKBACK": ("knocks target back", "击退目标"),
    "IPL_ALLRESZERO": ("All Resistance equals 0", "所有抗性归零"),
    "IPL_TARGAC": ("penetrates target's armor", "穿透目标护甲"),
    "IPL_RNDARROWVEL": ("fires random speed arrows", "射出随机速度的箭"),
    "IPL_ONEHAND": ("one handed sword", "单手武器"),
    "IPL_DRAINLIFE": ("constantly lose hit points", "持续流失生命"),
    "IPL_RNDSTEALLIFE": ("life stealing", "生命偷取"),
    "IPL_NOMINSTR": ("no strength requirement", "无力量需求"),
    "IPL_ADDMANAAC": ("charged bolts on hits", "命中时释放充能弹"),
    "IPL_DEVASTATION": ("occasional triple damage", "偶尔造成三倍伤害"),
    "IPL_PERIL": ("2x dmg to monst, 1x to you", "对怪物双倍伤害"),
    "IPL_JESTERS": ("Random 0 - 600% damage", "随机 0~600% 伤害"),
    "IPL_ACDEMON": ("extra AC vs demons", "对恶魔额外护甲"),
    "IPL_ACUNDEAD": ("extra AC vs undead", "对不死额外护甲"),
    "IPL_MANATOLIFE": ("50% Mana moved to Health", "50% 法力转化为生命"),
    "IPL_LIFETOMANA": ("40% Health moved to Mana", "40% 生命转化为法力"),
    "IPL_3XDAMVDEM": ("+200% damage vs. demons", "对恶魔伤害 +200%"),
    "IPL_INVCURS": ("", "改变物品外观（不影响属性）"),
}

#: CalculateToHitBonus(): to-hit bonus rolled for a TOHIT_DAMP prefix.
_TOHIT_POS = {
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
#: TOHIT_DAMP_CURSE passes -param1, i.e. the 25/50 keys of the same function.
_TOHIT_NEG = {25: (1, 5), 50: (6, 10)}

_ATTACK_SPEED = {
    1: ("quick attack", "快速攻击"),
    2: ("fast attack", "更快攻击"),
    3: ("faster attack", "极速攻击"),
    4: ("fastest attack", "最快攻击"),
}
_HIT_RECOVERY = {
    1: ("fast hit recovery", "快速打击回复"),
    2: ("faster hit recovery", "更快打击回复"),
    3: ("fastest hit recovery", "最快打击回复"),
}


def _fmt_range(low, high, unit=""):
    """'+81~95%' / '+100%' / '-10%~-6%' for a signed inclusive range."""
    if low > high:
        low, high = high, low
    if low == high:
        return "%+d%s" % (low, unit)
    if low < 0 and high < 0:
        return "%d%s~%d%s" % (low, unit, high, unit)
    if low >= 0 and high >= 0:
        return "+%d~%d%s" % (low, high, unit)
    return "%+d%s~%+d%s" % (low, unit, high, unit)


def _tohit_range(param1, sign):
    table = _TOHIT_POS if sign > 0 else _TOHIT_NEG
    base = table.get(param1)
    if base is None:
        return None
    return (sign * base[0], sign * base[1])


def _effect_text(power_name, param1, param2):
    """Chinese sentence fragment for one item power (no 'value' override)."""
    spec = _POWER_SPEC.get(power_name)
    if spec is None:
        label = stat_label(power_name)
        return label if label and label != power_name else "特殊效果"
    label, kind, sign = spec

    if kind == _PCT:
        return "%s %s" % (label, _fmt_range(sign * param1, sign * param2, "%"))
    if kind == _FLAT:
        return "%s %s" % (label, _fmt_range(sign * param1, sign * param2))
    if kind == _LIGHT:
        return "%s %s" % (label, _fmt_range(sign * param1 * 10, sign * param2 * 10, "%"))
    if kind == _DMG:
        low, high = sign * param1, sign * param2
        low, high = min(low, high), max(low, high)
        if low == high:
            return "%s %d" % (label, low)
        return "%s %d-%d" % (label, low, high)
    if kind == _TOHIT_DAMP:
        hit = _tohit_range(param1, sign)
        damage = _fmt_range(sign * param1, sign * param2, "%")
        if hit is None:
            return "%s %s" % (label, damage)
        return "命中 %s，伤害 %s" % (_fmt_range(hit[0], hit[1], "%"), damage)
    if kind == _CHARGES:
        return "固定效果：充能次数 ×%d" % param1
    if kind == _SPELL:
        return "固定效果：%s %d 次充能" % (spell_name_cn(param1), param2)
    # fixed effects
    if power_name == "IPL_THORNS":
        low, high = min(param1, param2), max(param1, param2)
        return "固定效果：攻击者受到 %d~%d 点伤害" % (low, high)
    if power_name == "IPL_FASTATTACK":
        msgid, fallback = _ATTACK_SPEED.get(param1, ("fastest attack", "最快攻击"))
        return "固定效果：" + tr(msgid, fallback)
    if power_name == "IPL_FASTRECOVER":
        msgid, fallback = _HIT_RECOVERY.get(param1, ("fastest hit recovery", "最快打击回复"))
        return "固定效果：" + tr(msgid, fallback)
    if power_name == "IPL_STEALMANA":
        amount = param1 or 3
        return "固定效果：" + tr("hit steals %d%% mana" % amount,
                               "命中时偷取 %d%% 法力" % amount)
    if power_name == "IPL_STEALLIFE":
        amount = param1 or 3
        return "固定效果：" + tr("hit steals %d%% life" % amount,
                               "命中时偷取 %d%% 生命" % amount)
    if power_name == "IPL_CRYSTALLINE":
        return "固定效果：低耐久，伤害 %s" % _fmt_range(140 + 2 * param1,
                                                    140 + 2 * param2, "%")
    msgid, fallback = _FIXED_TEXT.get(power_name, ("", "特殊效果"))
    return "固定效果：" + _localized(power_name, fallback, msgid)


def _localized(_key, fallback, msgid):
    if not msgid:
        return fallback
    return tr(msgid, fallback)


def _coerce_power(power):
    """Accept a dict / (name, p1, p2) tuple / bare power name."""
    if isinstance(power, dict):
        name = (power.get("power_name") or power.get("type_name")
                or power.get("name") or "")
        p1 = int(power.get("param1") or 0)
        p2 = int(power.get("param2") or 0)
        return str(name), p1, p2
    if isinstance(power, (tuple, list)):
        name = str(power[0]) if power else ""
        p1 = int(power[1]) if len(power) > 1 and power[1] is not None else 0
        p2 = int(power[2]) if len(power) > 2 and power[2] is not None else 0
        return name, p1, p2
    return str(power or ""), 0, 0


def describe_power(power):
    """Chinese one-liner for an ``ItemPower`` (unique item powers panel).

    ``describe_power({'power_name': 'IPL_STR', 'param1': 10, 'param2': 10})``
    -> ``'力量 +10'``.  Fixed effects become ``'固定效果：…'``.
    """
    name, p1, p2 = _coerce_power(power)
    if not name:
        return "特殊效果"
    return _effect_text(name, p1, p2)


def affix_desc(affix, value=None):
    """Full Chinese description of a prefix/suffix row.

    ``affix`` is a ``d1tables.affix_by_name()`` dict with the fields
    ``kind/name/power_name/param1/param2/min_level/item_types/
    item_type_names/min_val/max_val/mult_val/ok/goe``.  Only ``param1..param2``
    are real effect values (``min_val``/``max_val`` are gold-price inputs).

    >>> affix_desc(d1tables.affix_by_name('prefix', 'Brutal'))
    '残忍（Brutal）：伤害 +81~95%；需要物品等级 16；适用 弓/法杖/武器'
    >>> affix_desc(d1tables.affix_by_name('suffix', 'of the Fox'))
    '狐狸（of the fox）：生命 +10~15；需要物品等级 1；适用 杂项/盾牌/防具'
    >>> affix_desc(d1tables.affix_by_name('suffix', 'haste'))
    '匆忙（of haste）：固定效果：最快攻击；需要物品等级 27；适用 法杖/武器'

    *value* pins the roll: ``affix_desc(affix, 50)`` -> ``'伤害 +50%（指定值）'``.
    Numeric powers accept 0..255; fixed-effect powers ignore the value and say
    so, because there is nothing to pin.
    """
    if not isinstance(affix, dict):
        return clean(str(affix))
    kind = affix.get("kind") or "prefix"
    name = affix.get("name") or ""
    power_name = affix.get("power_name") or ""
    p1 = int(affix.get("param1") or 0)
    p2 = int(affix.get("param2") or 0)
    label = affix.get("label") or affix_label(kind, name)

    spec = _POWER_SPEC.get(power_name)
    numeric = spec is not None and spec[1] in (_PCT, _FLAT, _LIGHT, _DMG,
                                               _TOHIT_DAMP)
    if value is not None:
        if not numeric:
            effect = "%s（该词缀为固定效果，不能指定数值）" % _effect_text(power_name, p1, p2)
        else:
            effect = "%s（指定值）" % _effect_text(power_name, value, value)
    else:
        effect = _effect_text(power_name, p1, p2)

    parts = ["%s：%s" % (label, effect)]
    min_level = affix.get("min_level")
    if min_level is not None:
        parts.append("需要物品等级 %d" % int(min_level))
    types = _item_types_cn(affix.get("item_type_names") or [])
    if types:
        parts.append("适用 %s" % types)
    return "；".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _coverage():
    """Cross-check the PO against d1tables (used by --stats and the report)."""
    tables = _tables_module()
    result = {}

    # widest row set the installed d1tables can give us (the signature grew in
    # round 2 with include_starter/include_unique_only; stay compatible).
    try:
        rows = tables.base_items(include_unavailable=True, include_starter=True,
                                 include_unique_only=True)
    except TypeError:
        try:
            rows = tables.base_items(include_unavailable=True)
        except TypeError:
            rows = tables.base_items()
    items = [r["name"] for r in rows if r.get("name")]
    found = [n for n in items if _name_lookup(n)]
    result["items"] = (len(found), len(items),
                       [n for n in items if not _name_lookup(n)])

    for kind in ("prefix", "suffix"):
        rows = tables.affix_list(kind)
        hits = [r["name"] for r in rows if _name_lookup(r["name"])]
        missing = [r["name"] for r in rows if not _name_lookup(r["name"])]
        result[kind] = (len(hits), len(rows), missing)

    uniques = tables.unique_list(include_unavailable=True)
    hits = [u["name"] for u in uniques if _name_lookup(u["name"])]
    missing = [u["name"] for u in uniques if not _name_lookup(u["name"])]
    result["unique"] = (len(hits), len(uniques), missing)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--rebuild" in argv:
        meta = build_cache(verbose=True)
        print(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if "--stats" in argv or "--coverage" in argv:
        info = i18n_info()
        print("mode=%s path=%s entries=%d ctx=%d" % (
            info["mode"], info["path"], info["entries"], info["ctx_entries"]))
        for key, (hit, total, missing) in _coverage().items():
            print("%-8s %3d/%3d translated" % (key, hit, total))
            if missing and "--verbose" in argv:
                print("   missing:", ", ".join(missing))
        return 0
    # default: print a small smoke test
    print("d1i18n: %s" % json.dumps(i18n_info(), ensure_ascii=False, sort_keys=True))
    for sample in ("Short Sword", "Leather Armor", "Ring", "Amulet",
                   "Brutal", "Sharp", "Tin", "Naj's Light Plate"):
        print("  %-20s -> %s" % (sample, item_name_cn(sample)))
    print("  affix:", affix_desc({"kind": "prefix", "name": "Brutal",
                                  "power_name": "IPL_DAMP", "param1": 81,
                                  "param2": 95, "min_level": 16,
                                  "item_type_names": ["Bow", "Staff", "Weapon"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
