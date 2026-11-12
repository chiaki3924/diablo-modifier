#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Round 7 tests: Chinese item names in the stash (储物箱) list.

Run with::

    F:\Qoder\暗黑1重制版\work\build\venv312\Scripts\python.exe work\tests\test_round7_stash_names.py

Covers user request #3 ("储物箱界面，物品列表也用中文显示"):

* ``d1stash_adapter.record_name_cn()`` / ``record_label_cn()`` resolve a record
  to a Chinese name via ``d1itemgen.replay_item`` + ``d1zh`` (unique / prefix /
  suffix / staff spell / spell book), with a never-raising fallback;
* the stash UI's ``_fill_list`` shows the Chinese label (``中文名（English）``)
  for every row, ``scan_issues`` and the delete confirmation use the same name;
* unknown/corrupt records degrade to the Chinese base name or English iName
  instead of raising.

Only the copy ``tests/fixtures/saves/stash.sv`` is read; nothing is written.
The UI part runs in this venv process (tkinter is available) with
``uic.HEADLESS = True``.
"""

from __future__ import annotations

import os
import re
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
FIXTURES = os.environ.get("D1_TEST_SAVES") or os.path.join(
    ROOT, "tests", "fixtures", "saves")
STASH = os.path.join(FIXTURES, "stash.sv")
if not os.path.isfile(STASH):
    print("SKIP: 需要 tests/fixtures/saves/stash.sv")
    raise SystemExit(0)

for path in (LIB, APP):
    if path not in sys.path:
        sys.path.insert(0, path)

# Import the real stdlib tkinter *before* the app package: d1zh/d1env may prepend
# the original editor's PYZ dump (which has a stripped tkinter without
# `tkinter.font`) to sys.path, and a later `import tkinter` would pick that one.
try:  # pragma: no cover - depends on the host
    import tkinter  # noqa: F401
    import tkinter.font  # noqa: F401
    import tkinter.ttk  # noqa: F401
    import tkinter.filedialog  # noqa: F401
    import tkinter.messagebox  # noqa: F401
    HAS_TK = True
except Exception:  # noqa: BLE001
    HAS_TK = False

import d1stash_adapter as S    # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")

#: Tests operate on a throw-away copy: nothing may ever delete fixtures.
_TMPDIR = None
_FIXTURE = None


def _fixture() -> str:
    global _TMPDIR, _FIXTURE
    if _FIXTURE is None:
        import shutil
        import tempfile
        _TMPDIR = tempfile.mkdtemp(prefix="d1stash_cn_")
        _FIXTURE = os.path.join(_TMPDIR, "stash.sv")
        shutil.copyfile(STASH, _FIXTURE)
    return _FIXTURE


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _has_cn(text: str) -> bool:
    return bool(CJK.search(str(text or "")))


def _records():
    check(os.path.exists(STASH), "missing %s" % STASH)
    stash = S.open_stash(_fixture(), multiplayer=False)
    return stash, list(stash.records)


# ---------------------------------------------------------------------------
# adapter level
# ---------------------------------------------------------------------------

def test_adapter_names():
    stash, records = _records()
    check(len(records) >= 50, "expected a populated stash, got %d records" % len(records))
    names = [S.record_name_cn(rec) for rec in records]
    labels = [S.record_label_cn(rec) for rec in records]
    cn = sum(1 for n in names if _has_cn(n))
    check(cn >= len(records) * 0.95,
          "only %d/%d records got a Chinese name; first misses: %r"
          % (cn, len(records),
             [(i, S.record_fields(r).get("name"))
              for i, n in enumerate(names) if not _has_cn(n)][:5]))
    check(all(lbl for lbl in labels), "some rows would be empty: %r"
          % [i for i, lbl in enumerate(labels) if not lbl][:10])
    # The known unique "Arkaine's Valor" is in the sample stash.
    joined = "\n".join(labels)
    check("阿凯尼" in joined, "Arkaine's Valor should be 阿凯尼的荣耀:\n%s"
          % "\n".join(labels[:12]))
    check("（" in labels[3] or "（" in labels[0],
          "label should append the English name in parentheses: %r" % (labels[:4],))
    # Labels differing from the raw English name prove the translation is used.
    same = 0
    for rec, lbl in zip(records, labels):
        english = S.record_display_name(rec)
        if lbl == english:
            same += 1
    check(same <= len(records) * 0.1,
          "%d/%d labels are unchanged English" % (same, len(records)))
    print("    %d/%d Chinese names; sample: %s"
          % (cn, len(records), " | ".join(labels[:4])))


def test_fallbacks_never_raise():
    # all-zero and all-0xFF records must degrade, not raise
    for raw in (b"\x00" * 368, b"\xff" * 368, b"\x00" * 10):
        try:
            name = S.record_name_cn(raw)
            label = S.record_label_cn(raw)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError("record_name_cn(%r) raised %r" % (raw[:4], exc))
        check(isinstance(name, str) and isinstance(label, str),
              "fallbacks must return strings: %r / %r" % (name, label))
    print("    zero/0xFF/short records degrade without raising")


def test_spell_and_staff_names():
    _, records = _records()
    labels = [S.record_label_cn(rec) for rec in records]
    joined = "\n".join(labels)
    # staff / spell book records in the sample stash
    for want in ("法术书", "长杖"):
        if want in joined:
            print("    found %r: %s" % (want, [l for l in labels if want in l][:2]))
    check("法术书" in joined or "杖" in joined,
          "expected at least one translated staff/spell book name:\n%s"
          % "\n".join(labels[:20]))


# ---------------------------------------------------------------------------
# UI level
# ---------------------------------------------------------------------------

def test_ui_rows():
    check(HAS_TK, "tkinter is not available in this interpreter")
    import ui_common as uic
    uic.HEADLESS = True
    from d1editor2 import App

    app = App(headless=True)
    app.withdraw()
    app.geometry("1260x920")
    try:
        app.update_idletasks()
        tab = app.tab_stash
        tab.load(Path(_fixture()))
        app.update_idletasks()
        rows = tab.tree.get_children()
        check(rows, "stash tree is empty after load()")
        check(len(rows) == tab.stash.item_count(),
              "tree has %d rows but stash has %d items"
              % (len(rows), tab.stash.item_count()))
        names = [tab.tree.item(row, "values")[2] for row in rows]
        cn = sum(1 for name in names if _has_cn(name))
        check(cn >= len(names) * 0.95,
              "tree shows only %d/%d Chinese names: %r" % (cn, len(names), names[:5]))
        # English name is preserved in parentheses for recognisability.
        check(any("（" in name and "）" in name for name in names),
              "rows should show 中文名（English）: %r" % (names[:5],))
        # scan_issues uses the same Chinese names.
        issues = tab.scan_issues(deep=False)
        for _index, name, severity, reason in issues:
            check(_has_cn(name) or not name, "issue name is not Chinese: %r" % (name,))
            check(severity in ("warn", "error"), "bad severity: %r" % (severity,))
        print("    tree rows %d, Chinese %d, issues %d, sample: %s"
              % (len(rows), cn, len(issues), " | ".join(names[:3])))
        if issues:
            print("    issue sample: #%s %s [%s] %s"
                  % (issues[0][0], issues[0][1], issues[0][2], issues[0][3][:60]))
    finally:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


def test_delete_confirmation_is_chinese():
    """The delete confirmation text must carry the Chinese label (no real write)."""
    check(HAS_TK, "tkinter is not available in this interpreter")
    import ui_common as uic
    uic.HEADLESS = True
    from d1editor2 import App

    app = App(headless=True)
    app.withdraw()
    captured = {}

    def fake_confirm(title=None, msg=None, **kw):
        captured["title"] = title
        captured["message"] = msg
        return False          # -> nothing is deleted

    original = uic.confirm
    uic.confirm = fake_confirm
    try:
        app.update_idletasks()
        tab = app.tab_stash
        tab.load(Path(_fixture()))
        app.update_idletasks()
        rows = tab.tree.get_children()
        check(rows, "stash tree is empty")
        tab.tree.selection_set(rows[0])
        tab.delete_selected()
        text = "%s %s" % (captured.get("title"), captured.get("message"))
        check("确定" in text and "删除" in text,
              "unexpected confirmation text: %r" % (text,))
        check(_has_cn(text), "confirmation text has no Chinese name: %r" % (text,))
        check(len(tab.tree.get_children()) == len(rows),
              "nothing may be deleted when the user answers No")
        print("    confirm: %s" % text.strip().replace("\n", " ")[:120])
    finally:
        uic.confirm = original
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = [
    ("record_name_cn/record_label_cn for the sample stash", test_adapter_names),
    ("zero/0xFF/short records degrade safely", test_fallbacks_never_raise),
    ("staff / spell book names", test_spell_and_staff_names),
    ("stash tree rows show Chinese labels", test_ui_rows),
    ("delete confirmation uses the Chinese name", test_delete_confirmation_is_chinese),
]


def main():
    print("Round 7 stash Chinese-name tests")
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
