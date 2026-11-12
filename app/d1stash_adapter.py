"""储物箱适配层。

优先使用 work/lib/d1stash2.py（修正版 MPQ 写入，绝不会丢物品）；
如果该库缺失或加载失败，退回只读模式（用 d1save.StashFile 解密 payload 显示，
但禁止保存），保证界面仍能查看而不会用原版有 bug 的 save() 写坏文件。
"""
from __future__ import annotations

import struct
from pathlib import Path

from d1env import MODULES, assert_writable, lib_module, safe_name

ITEM_REC_SIZE = 368


class StashUnavailable(RuntimeError):
    pass


class GuardedStash:
    """自动测试模式（ALLOW_PROTECTED_WRITES=False）下包住真实储物箱：

    读操作全部放行，**任何写操作直接抛 ProtectedWriteError**。
    这样即使代码路径出错（例如刷新后误载入真实 stash），也不会改坏用户存档。
    """

    WRITE_METHODS = ("save", "add_record", "remove_record", "set_item", "flush")

    def __init__(self, inner, path):
        self._inner = inner
        self.path = str(path)
        self.is_readonly = True
        self.writes_blocked = True

    def __getattr__(self, name):
        if name in self.WRITE_METHODS:
            def blocked(*a, **kw):
                assert_writable(self.path)   # 一定抛（自动测试模式 + 真实路径）
                raise StashUnavailable(
                    f"自动测试模式禁止写真实储物箱：{self.path}")
            return blocked
        return getattr(self._inner, name)

    def __repr__(self):
        return f"<GuardedStash {self.path}>"


def _patch_d1stash2(mod) -> None:
    """让 d1stash2 复用我们已经加载好的 pyc 模块（打包后没有 ROOT 目录）。"""
    if MODULES.load():
        for name, obj in MODULES.modules.items():
            try:
                mod._MODULES[name] = obj
            except Exception:  # noqa: BLE001
                pass


def load_stash_module():
    """返回 (module, error)。"""
    mod, err = lib_module("d1stash2")
    if mod is None:
        return None, err
    _patch_d1stash2(mod)
    return mod, None


# ---------------------------------------------------------------- 只读后备

class ReadOnlyStash:
    """d1stash2 不可用时的只读后备实现（禁止保存）。"""

    is_readonly = True

    def __init__(self, path: str, multiplayer: bool = False):
        self.path = str(Path(path).resolve())
        self.multiplayer = bool(multiplayer)
        d1save = MODULES.d1save
        self._sf = d1save.StashFile(self.path, multiplayer=self.multiplayer)
        data = bytes(self._sf.data)
        self.version = data[0]
        self.gold = struct.unpack_from("<I", data, 1)[0]
        page_count = struct.unpack_from("<I", data, 5)[0]
        off = 9
        self.grids: dict[int, list[list[int]]] = {}
        for _ in range(page_count):
            page = struct.unpack_from("<I", data, off)[0]
            off += 4
            cells = struct.unpack_from("<100H", data, off)
            off += 200
            self.grids[page] = [list(cells[y * 10:(y + 1) * 10]) for y in range(10)]
        item_count = struct.unpack_from("<I", data, off)[0]
        off += 4
        self.records = [bytes(data[off + i * ITEM_REC_SIZE: off + (i + 1) * ITEM_REC_SIZE])
                        for i in range(item_count)]
        off += item_count * ITEM_REC_SIZE
        self.current_page = struct.unpack_from("<I", data, off)[0] if off + 4 <= len(data) else 0

    def item_count(self) -> int:
        return len(self.records)

    def pages(self) -> list[int]:
        return sorted(self.grids)

    def grid_at(self, page: int) -> list[list[int]]:
        return self.grids.get(page) or [[0] * 10 for _ in range(10)]

    def save(self, out_path=None, backup=True):
        raise StashUnavailable(
            "d1stash2 未就绪，为避免写坏储物箱，已禁止保存（当前为只读浏览模式）。"
        )

    def add_record(self, record, page=None, **kw):
        raise StashUnavailable("d1stash2 未就绪，不能加物品")

    def remove_record(self, index):
        raise StashUnavailable("d1stash2 未就绪，不能删物品")

    def verify_roundtrip(self) -> bool:
        return False


def open_stash(path: str | Path, multiplayer: bool = False):
    """打开储物箱；返回对象带 .gold/.records/.grids/.save()/.add_record()。

    自动测试模式（``d1env.ALLOW_PROTECTED_WRITES = False``）下，如果路径在真实存档
    目录里，返回的是一层**只读保护壳**（写操作直接抛异常），防止测试误写用户存档。
    """
    from d1env import ALLOW_PROTECTED_WRITES, is_protected_path
    mod, err = load_stash_module()
    if mod is None:
        try:
            return ReadOnlyStash(str(path), multiplayer)
        except Exception as exc:  # noqa: BLE001
            raise StashUnavailable(f"{err}；且后备读取失败：{exc}") from exc
    try:
        st = mod.Stash(str(path), multiplayer=multiplayer)
    except TypeError:
        st = mod.Stash(str(path), multiplayer)
    except Exception as exc:  # noqa: BLE001
        raise StashUnavailable(f"打开储物箱失败：{exc}") from exc
    if not ALLOW_PROTECTED_WRITES and is_protected_path(path):
        return GuardedStash(st, path)
    return st


def stash_backend_ready() -> tuple[bool, str]:
    mod, err = load_stash_module()
    if mod is None:
        return False, err or "d1stash2 不可用"
    return True, f"d1stash2 已就绪（{Path(mod.__file__).name}）"


# ---------------------------------------------------------------- 记录解析

def record_fields(rec: bytes) -> dict:
    """解析 368 字节 Item 记录的几个常用字段（1.5.5 布局）。"""
    def u(off, fmt="<i"):
        try:
            return struct.unpack_from(fmt, rec, off)[0]
        except Exception:
            return 0

    def s(off, n=64):
        raw = rec[off:off + n].split(b"\x00")[0]
        return raw.decode("utf-8", "ignore").strip()

    return {
        "seed": u(0, "<I"),
        "create_info": u(4, "<h"),
        "type": u(8),
        "x": u(12), "y": u(16),
        "identified": u(56, "<I"),
        "magical": u(60, "<b"),
        "name": s(61, 64),
        "iName": s(125, 64),
        "loc": u(189, "<b"),
        "curs": u(192),
        "ivalue": u(196),
        "iIvalue": u(200),
        "minDam": u(204), "maxDam": u(208), "AC": u(212),
        "durability": u(236), "maxDur": u(240),
        "pre": u(332, "<b"), "suf": u(333, "<b"),
        "saved_idx": u(360),
    }


def record_runtime_idx(rec: bytes) -> int:
    try:
        saved = struct.unpack_from("<i", rec, 360)[0]
        return int(MODULES.d1save.saved_to_runtime(saved))
    except Exception:
        try:
            return struct.unpack_from("<i", rec, 360)[0]
        except Exception:
            return -1


def record_display_name(rec: bytes) -> str:
    f = record_fields(rec)
    return safe_name(f.get("iName") or f.get("name") or "")


def record_is_unique(rec: bytes) -> bool:
    f = record_fields(rec)
    return bool(f.get("magical") == 2 or f.get("create_info") and (int(f["create_info"]) & 0x200))


# ---------------------------------------------------------------- 中文名称
#: (saved_idx, iSeed, iCreateInfo) -> 中文名。同一件物品在列表里会被反复取名字
#: （列表 / 体检 / 删除确认），这里缓存一份，96 件物品只需各重放一次。
_CN_CACHE: dict[tuple[int, int, int], str] = {}
_CN_GEN = None          # d1itemgen 模块；False = 加载失败
_CN_ZH = None           # d1zh 模块；False = 加载失败


def _cn_itemgen():
    """延迟加载 d1itemgen（缺失时返回 None，不影响界面启动）。"""
    global _CN_GEN
    if _CN_GEN is None:
        try:
            mod, _err = lib_module("d1itemgen")
        except Exception:  # noqa: BLE001
            mod = None
        _CN_GEN = mod or False
    return _CN_GEN or None


def _cn_zh():
    """延迟加载 d1zh（内部已对 d1i18n 做守卫，缺失时退回内置表）。"""
    global _CN_ZH
    if _CN_ZH is None:
        try:
            import d1zh as mod
        except Exception:  # noqa: BLE001
            mod = None
        _CN_ZH = mod or False
    return _CN_ZH or None


def _record_cn_key(rec: bytes) -> tuple:
    try:
        f = record_fields(rec)
        return (int(f.get("saved_idx") or 0), int(f.get("seed") or 0),
                int(f.get("create_info") or 0))
    except Exception:  # noqa: BLE001
        return ()


def _name_cn_uncached(rec: bytes) -> str:
    """按 seed 重放出物品，用 d1zh 拼中文名；失败时用底材名（+ 品质标记）。"""
    fields = record_fields(rec)
    idx = record_runtime_idx(rec)
    base_cn = ""
    if idx >= 0:
        try:
            from d1names import item_cn
            base_cn = item_cn(idx)
        except Exception:  # noqa: BLE001
            base_cn = ""
    zh = _cn_zh()
    gen = _cn_itemgen()
    if gen is not None and zh is not None:
        try:
            return _replayed_name_cn(rec, gen, zh, base_cn)
        except Exception:  # noqa: BLE001
            pass          # 重放失败（损耗/未知记录）→ 用底材中文名 + 品质标记
    # 重放不可用时也别只剩英文
    quality = int(fields.get("magical") or 0)
    tag = "（暗金）" if quality >= 2 else ("（魔法）" if quality == 1 else "")
    return f"{base_cn}{tag}" if base_cn else ""


def _replayed_name_cn(rec: bytes, gen, zh, base_cn: str) -> str:
    """用 d1itemgen 重放 + d1zh 中文模板拼名；重放失败时抛异常由上层兜底。"""
    it = gen.replay_item(bytes(rec))
    base = getattr(it, "base", None) or {}
    base_en = str(base.get("name") or "")
    if base_en:
        base_cn = zh.item_name_cn(base_en, base_cn) or base_cn
    uniq = getattr(it, "unique", None)
    if isinstance(uniq, dict) and uniq.get("name"):
        uniq_cn = zh.unique_name(str(uniq["name"]))
        if uniq_cn:
            return uniq_cn
    pre = getattr(it, "prefix", None)
    suf = getattr(it, "suffix", None)
    pre_cn = zh.affix_name("prefix", pre) if isinstance(pre, dict) else ""
    suf_cn = zh.affix_name("suffix", suf) if isinstance(suf, dict) else ""
    # 法术编号用记录里的（offset 224）：游戏显示/施放用的就是它，
    # 而且重放对法术书可能取到不同的法术（RNG 顺序差异）。
    try:
        spell_id = int(struct.unpack_from("<i", rec, 224)[0])
    except Exception:  # noqa: BLE001
        spell_id = -1
    if spell_id <= 0:
        spell_id = int((getattr(it, "fields", None) or {}).get("spell") or -1)
    spell_cn = zh.spell_name(spell_id) if spell_id > 0 else ""
    # 底材名里已经带了同一个法术（如 ILL_166 "Short Staff of Charged Bolt"）
    # 时不要再拼一次
    spell_en = ""
    try:
        tbl = getattr(gen, "T", None)
        rec_spell = tbl.spell_by_id(spell_id) if tbl is not None else None
        spell_en = str((rec_spell or {}).get("name") or "")
    except Exception:  # noqa: BLE001
        spell_en = ""
    if spell_en and spell_en.lower() in base_en.lower():
        spell_cn = ""
    # 法术书：底材名只有 "Book of "，游戏里是「法术书： 传送」
    if spell_cn and base_en.strip().lower().startswith("book of"):
        return f"{zh.item_name_cn('Spell book', '法术书')}：{spell_cn}"
    # 法杖：底材 + " of 法术"（英文 Long Staff of Firebolt）
    staff_spell_cn = spell_cn if str(base.get("itype_name") or "") == "Staff" else ""
    if pre_cn or suf_cn or staff_spell_cn:
        # 中文模板：后缀 + 前缀 + 底材（d1zh.item_full_name_cn）
        return zh.item_full_name_cn(base_cn, pre_cn,
                                    "" if staff_spell_cn else suf_cn,
                                    staff_spell_cn)
    return base_cn


def record_name_cn(rec: bytes) -> str:
    """储物箱一条记录的**中文名**（暗金 / 魔法 / 法杖法术按游戏中文模板）。

    绝不抛异常：d1itemgen 重放失败、d1zh 或 d1names 缺失时逐级退回英文 iName。
    """
    key = _record_cn_key(rec)
    if key:
        hit = _CN_CACHE.get(key)
        if hit is not None:
            return hit
    try:
        cn = _name_cn_uncached(rec) or ""
    except Exception:  # noqa: BLE001
        cn = ""
    if not cn:
        cn = record_display_name(rec)
    if key:
        if len(_CN_CACHE) > 4096:
            _CN_CACHE.clear()
        _CN_CACHE[key] = cn
    return cn


def record_label_cn(rec: bytes) -> str:
    """『中文名（English）』——英文名与中文不同才加括号，供列表/确认框显示。"""
    cn = record_name_cn(rec)
    eng = record_display_name(rec)
    if not cn:
        return eng
    if eng and eng != cn:
        return f"{cn}（{eng}）"
    return cn
