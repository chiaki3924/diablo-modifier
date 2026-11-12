"""从 DevilutionX 1.5.5 的 zh_CN.po 生成 GUI 用的中文兜底表。

产物：app/zh_fallback.json
  { "meta": {...}, "tr": {msgid: msgstr}, "ctx": {"ctx\u0004msgid": msgstr} }

只保留单行条目（物品名/词缀名/暗金名/属性文案），去掉 U+200B 零宽空格。
lib/d1i18n.py 可用时 GUI 会优先用它；本表只是兜底。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PO = ROOT / "data" / "game-tables" / "DevilutionX-1.5.5" / "Translations" / "zh_CN.po"
OUT = ROOT / "app" / "zh_fallback.json"

ZWSP = "\u200b"


def unquote(s: str) -> str:
    s = s.strip()
    assert s.startswith('"') and s.endswith('"'), s
    body = s[1:-1]
    return (body.replace("\\n", "\n").replace("\\t", "\t")
            .replace('\\"', '"').replace("\\\\", "\\"))


def parse_po(text: str):
    entries = []
    cur: dict = {"ctxt": None, "id": None, "str": None, "plural": None}
    mode = None

    def flush():
        nonlocal cur
        if cur["id"] is not None:
            entries.append(dict(cur))
        cur = {"ctxt": None, "id": None, "str": None, "plural": None}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line:
                flush()
                mode = None
            continue
        if line.startswith("msgctxt "):
            if cur["id"] is not None:
                flush()
            cur["ctxt"] = unquote(line[8:])
            mode = "ctxt"
        elif line.startswith("msgid_plural "):
            cur["plural"] = unquote(line[13:])
            mode = "plural"
        elif line.startswith("msgid "):
            if cur["id"] is not None:
                flush()
            cur["id"] = unquote(line[6:])
            mode = "id"
        elif line.startswith("msgstr[0] "):
            cur["str"] = unquote(line[10:])
            mode = "str"
        elif line.startswith("msgstr "):
            cur["str"] = unquote(line[7:])
            mode = "str"
        elif line.startswith('"'):
            frag = unquote(line)
            if mode == "id":
                cur["id"] = (cur["id"] or "") + frag
            elif mode == "str":
                cur["str"] = (cur["str"] or "") + frag
            elif mode == "ctxt":
                cur["ctxt"] = (cur["ctxt"] or "") + frag
            elif mode == "plural":
                cur["plural"] = (cur["plural"] or "") + frag
    flush()
    return entries


def clean(s: str) -> str:
    return s.replace(ZWSP, "").strip()


def main() -> int:
    text = PO.read_text(encoding="utf-8")
    entries = parse_po(text)
    tr: dict[str, str] = {}
    ctx: dict[str, str] = {}
    skipped = 0
    for e in entries:
        mid = e["id"]
        mstr = e["str"]
        if not mid or not mstr:
            skipped += 1
            continue
        mid_c = clean(mid)
        mstr_c = clean(mstr)
        if not mid_c or not mstr_c:
            skipped += 1
            continue
        if "\n" in mid or "\n" in mstr or len(mid) > 90:
            skipped += 1
            continue
        key = f"{clean(e['ctxt'])}\x04{mid_c}" if e["ctxt"] else mid_c
        (ctx if e["ctxt"] else tr)[key] = mstr_c
    data = {
        "meta": {"source": str(PO), "entries": len(tr) + len(ctx), "skipped": skipped},
        "tr": tr,
        "ctx": ctx,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}  tr={len(tr)} ctx={len(ctx)} skipped={skipped} size={OUT.stat().st_size}")
    for probe in ("Short Sword", "Brutal", "Sharp", "Harlequin Crest", "Arkaine's Valor",
                  "chance to hit: {:+d}%", "Resist Fire: {:+d}%", "the fox"):
        print(f"  {probe!r} -> {tr.get(probe)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
