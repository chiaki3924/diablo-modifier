#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""test_stash.py — 「储物箱核心」的回归测试（DevilutionX 1.5.5 stash.sv）。

跑法（必须用 Python 3.12，因为要加载原修改器的 3.12 pyc）::

    python tests/test_stash.py

覆盖内容
--------
0. ``read_mpqfs_style()``：严格按 mpqfs ``src/mpq_stream.c`` 规则独立实现的读取器
   （扇区偏移表 / span==expect 原样 / 否则 PKWARE explode / 未压缩无表）。
1. 真实存档基线：96 条记录、gold=313108、10 页、currentPage=2，
   96 件物品的占格矩形/尺寸/锚点全部与 ``d1items.ITEM_SIZE`` 吻合。
2. **原 bug 复现**：用原 ``d1save.StashFile.save()`` 保存副本 → 写出 512 字节扇区表
   （首项 300，而 4096 字节扇区应为 44）→ 我们的读取器精确报错，原修改器自己
   也读不回来（``PkwareError 字典大小非法``）。
3. **修复验证**：改 gold → ``Stash.save()`` → 重开：gold 正确、96 条记录逐字节
   完全一致、页/格一致；mpqfs 规则读取器也能读回。
4. **原读取器限制证明**：原 ``d1mpq.MPQArchive.read_file()`` 对未压缩块会无条件
   丢掉 ``nsectors*4`` 字节（字节码 ``body = raw[nsectors*4:]``），所以它读不了我们
   的文件；用 ``read_raw()`` 证明块数据本身是完整的。
5. ``add_record`` / ``remove_record``：加一件→存盘→重开（记录数 +1、新记录保持
   逐字节一致、原有记录与 gold 不变）→ 删掉→恢复成与原文件一致的字节。
6. ``.bak`` 备份、``verify_roundtrip()``、空页回收、100 页上限、未知尾部字节保留、
   多人模式找不到文件、``implode_raw`` 兼容写法的双读取器交叉验证。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import sys
import tempfile
import unittest

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
SAVES = os.environ.get("D1_TEST_SAVES") or os.path.join(
    ROOT, "tests", "fixtures", "saves")
MODIFIER = os.path.join(ROOT, "暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted")
PYZ = os.path.join(ROOT, "_d1pyc")
if not os.path.isdir(PYZ):
    PYZ = os.path.join(MODIFIER, "PYZ.pyz_extracted")
REAL_STASH = os.path.join(SAVES, "stash.sv")
if not os.path.isfile(REAL_STASH) or not os.path.isfile(os.path.join(PYZ, "d1save.pyc")):
    print("SKIP: 需要 tests/fixtures/saves/stash.sv 与 _d1pyc/d1save.pyc")
    raise SystemExit(0)

if LIB not in sys.path:
    sys.path.insert(0, LIB)
if PYZ not in sys.path:
    sys.path.insert(0, PYZ)

import d1stash2 as S  # noqa: E402


def _load_pyc(name):
    import importlib.util
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, os.path.join(PYZ, name + ".pyc"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


d1save = _load_pyc("d1save")
d1mpq = _load_pyc("d1mpq")
d1codec = _load_pyc("d1codec")
d1pkware = _load_pyc("d1pkware")

PASSWORD = "xrgyrkj1"

# 基准数字（2026-11-11 的真实 stash.sv）
BASE_GOLD = 313108
BASE_ITEMS = 96
BASE_PAGES = [0, 1, 2, 3, 6, 7, 8, 9, 10, 11]
BASE_CURRENT_PAGE = 2

TMP = None


def setUpModule():
    global TMP
    TMP = os.path.join(ROOT, "tests", "tmp", "test_stash_%d" % os.getpid())
    if os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)


def tearDownModule():
    if TMP and os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)


def copy_real(name="stash.sv"):
    dst = os.path.join(TMP, name)
    shutil.copy2(REAL_STASH, dst)
    return dst


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------- #
# 严格按 mpqfs src/mpq_stream.c 规则实现的独立读取器
# --------------------------------------------------------------------------- #

MPQ_SIGNATURE = 0x1A51504D
MPQ_FILE_EXISTS = 0x80000000
MPQ_FILE_IMPLODE = 0x00000100
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_ENCRYPTED = 0x00010000
MPQ_FILE_SINGLE_UNIT = 0x01000000
HASH_ENTRY_EMPTY = 0xFFFFFFFF
HASH_ENTRY_DELETED = 0xFFFFFFFE


class MpqfsReadError(Exception):
    pass


def _mpq_find_header(raw):
    """mpqfs MpqFindHeader(): 在 512 字节边界上扫描签名（最多 128 MiB）。"""
    limit = min(len(raw) - 4, 128 * 1024 * 1024)
    off = 0
    while off <= limit:
        if struct.unpack_from("<I", raw, off)[0] == MPQ_SIGNATURE:
            return off
        off += 512
    raise MpqfsReadError("找不到 MPQ 签名")


def _mpq_header(raw):
    base = _mpq_find_header(raw)
    (sig, hsize, asize, fmt, shift,
     hash_off, block_off, hash_cnt, block_cnt) = struct.unpack_from("<IIIHHIIII", raw, base)
    if fmt != 0:
        raise MpqfsReadError("format_version=%d 不支持" % fmt)
    return {
        "base": base,
        "header_size": hsize,
        "archive_size": asize,
        "format_version": fmt,
        "sector_size_shift": shift,
        "sector_size": 512 << shift,
        "hash_off": base + hash_off,
        "block_off": base + block_off,
        "hash_cnt": hash_cnt,
        "block_cnt": block_cnt,
    }


def _mpq_tables(raw, hdr):
    key_h = d1mpq.hash_string("(hash table)", 3)
    key_b = d1mpq.hash_string("(block table)", 3)
    hash_table = bytes(d1mpq.crypt_block(
        bytearray(raw[hdr["hash_off"]:hdr["hash_off"] + hdr["hash_cnt"] * 16]), key_h))
    block_table = bytes(d1mpq.crypt_block(
        bytearray(raw[hdr["block_off"]:hdr["block_off"] + hdr["block_cnt"] * 16]), key_b))
    return hash_table, block_table


def _mpq_lookup(raw, hdr, name):
    hash_table, block_table = _mpq_tables(raw, hdr)
    ha = d1mpq.hash_string(name, 1)
    hb = d1mpq.hash_string(name, 2)
    start = d1mpq.hash_string(name, 0) % hdr["hash_cnt"]
    for probe in range(hdr["hash_cnt"]):
        i = (start + probe) % hdr["hash_cnt"]
        a, b, _loc_plat, bi = struct.unpack_from("<IIII", hash_table, i * 16)
        if bi == HASH_ENTRY_EMPTY:
            raise MpqfsReadError("文件 %r 不存在（探查到空槽）" % name)
        if bi == HASH_ENTRY_DELETED:
            continue
        if a == ha and b == hb:
            if bi >= hdr["block_cnt"]:
                raise MpqfsReadError("block index %d 越界" % bi)
            return struct.unpack_from("<IIII", block_table, bi * 16)
    raise MpqfsReadError("文件 %r 不存在（探查链绕回）" % name)


def mpq_block_info(path, name):
    """返回块元信息 dict（用于断言 flags/尺寸）。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    hdr = _mpq_header(raw)
    off, csize, usize, flags = _mpq_lookup(raw, hdr, name)
    return {
        "offset": off, "compressed_size": csize, "file_size": usize,
        "flags": flags, "header": hdr,
    }


def read_mpqfs_style(path, name):
    """严格按 mpqfs ``src/mpq_stream.c`` 读取 + codec 解码，返回 stash payload。"""
    with open(path, "rb") as fh:
        raw = fh.read()

    hdr = _mpq_header(raw)
    off, csize, usize, flags = _mpq_lookup(raw, hdr, name)

    if not (flags & MPQ_FILE_EXISTS):
        raise MpqfsReadError("块没有 EXISTS")
    if flags & MPQ_FILE_ENCRYPTED:
        raise MpqfsReadError("本辅助函数不支持逐块加密（stash.sv 不会加密）")
    if off + csize > len(raw):
        raise MpqfsReadError("块越界")

    sector_size = hdr["sector_size"]
    blob = raw[off:off + csize]
    if usize == 0:
        block = b""
    elif (flags & (MPQ_FILE_IMPLODE | MPQ_FILE_COMPRESS)) and not (flags & MPQ_FILE_SINGLE_UNIT):
        nsec = (usize + sector_size - 1) // sector_size
        table_bytes = (nsec + 1) * 4
        table = struct.unpack_from("<%dI" % (nsec + 1), blob, 0)
        if table[0] != table_bytes:
            raise MpqfsReadError(
                "扇区偏移表首项 %d != %d（sector_size=%d）" % (table[0], table_bytes, sector_size))
        out = bytearray()
        for s in range(nsec):
            expect = min(sector_size, usize - s * sector_size)
            start, end = table[s], table[s + 1]
            if end < start:
                raise MpqfsReadError("扇区 %d 偏移倒挂" % s)
            span = end - start
            chunk = blob[start:end]
            if span == 0:
                out += b"\x00" * expect
            elif span == expect:
                out += chunk                                  # 原样存储
            elif flags & MPQ_FILE_IMPLODE:
                out += d1pkware.explode(chunk, expect)
            elif flags & MPQ_FILE_COMPRESS:
                method = chunk[0]
                if method & 0x08:
                    out += d1pkware.explode(chunk[1:], expect)
                elif method & 0x02:
                    import zlib
                    out += zlib.decompress(chunk[1:])[:expect]
                elif method & 0x10:
                    import bz2
                    out += bz2.decompress(chunk[1:])[:expect]
                else:
                    raise MpqfsReadError("不支持的多方法压缩 0x%02X" % method)
        if len(out) < usize:
            out += b"\x00" * (usize - len(out))
        block = bytes(out[:usize])
    elif flags & MPQ_FILE_SINGLE_UNIT:
        block = blob[:usize]
    else:
        # 未压缩、多扇区：无偏移表，直接顺序读取（mpq_stream.c 的 else 分支）
        if len(blob) < usize:
            raise MpqfsReadError("未压缩块长度不足 %d < %d" % (len(blob), usize))
        block = blob[:usize]

    return bytes(d1codec.codec_decode(block, PASSWORD))


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def raw_page_cells(payload):
    """从 stash payload 里**直接**解析出 ``{page: [100 个 u16]}``（不做任何重排）。

    用来独立验证落盘顺序：第 i 个 cell 对应游戏坐标 ``x = i // 10, y = i % 10``。
    """
    pos = 0
    assert payload[pos] == 0
    pos += 1
    pos += 4                                   # gold
    page_count = struct.unpack_from("<I", payload, pos)[0]
    pos += 4
    pages = {}
    for _ in range(page_count):
        page = struct.unpack_from("<I", payload, pos)[0]
        pos += 4
        pages[page] = list(struct.unpack_from("<100H", payload, pos))
        pos += 200
    return pages


def check_grids_consistent(tc, stash):
    """校验每个页的占格：每件物品是精确的 w×h 矩形，且 position 是左下角锚点。"""
    referenced = set()
    for page, grid in stash.grids.items():
        tc.assertEqual(len(grid), 10, "第 %d 页不是 10 行" % page)
        for row in grid:
            tc.assertEqual(len(row), 10, "第 %d 页某行不是 10 列" % page)
        cells = {}
        for y in range(10):
            for x in range(10):
                v = grid[y][x]
                if v:
                    cells.setdefault(v - 1, []).append((x, y))
        for idx, coords in cells.items():
            tc.assertLess(idx, len(stash.records), "第 %d 页格子引用了不存在的记录 %d" % (page, idx))
            referenced.add(idx)
            rec = stash.records[idx]
            w, h = S.Stash.record_size(rec)
            xs = sorted({c[0] for c in coords})
            ys = sorted({c[1] for c in coords})
            tc.assertEqual(len(coords), w * h,
                           "记录 %d 的占格数 %d != %dx%d" % (idx, len(coords), w, h))
            tc.assertEqual(xs, list(range(xs[0], xs[0] + w)),
                           "记录 %d 的 x 范围不连续" % idx)
            tc.assertEqual(ys, list(range(ys[0], ys[0] + h)),
                           "记录 %d 的 y 范围不连续" % idx)
            px, py = struct.unpack_from("<ii", rec, 12)
            tc.assertEqual((px, py), (xs[0], ys[-1]),
                           "记录 %d 的 position %s 不是左下角锚点 (%d,%d)"
                           % (idx, (px, py), xs[0], ys[-1]))
    tc.assertEqual(referenced, set(range(len(stash.records))),
                   "有记录没有被网格引用，或有重复引用")


# --------------------------------------------------------------------------- #
# 测试
# --------------------------------------------------------------------------- #

class TestStashCore(unittest.TestCase):

    # -- 0. 读取器辅助函数 -------------------------------------------------- #

    def test_00_read_mpqfs_style_on_real_file(self):
        """独立实现的 mpqfs 规则读取器能读出真实存档，且与原修改器的 data 一致。"""
        payload = read_mpqfs_style(REAL_STASH, "spstashitems")
        expected = bytes(d1save.StashFile(REAL_STASH).data)
        self.assertEqual(len(payload), 37385)
        self.assertEqual(payload, expected, "mpqfs 规则读取结果 != d1save.StashFile.data")

        info = mpq_block_info(REAL_STASH, "spstashitems")
        self.assertEqual(info["header"]["sector_size_shift"], 3)
        self.assertEqual(info["header"]["sector_size"], 4096)
        self.assertEqual(info["flags"], 0x80000100, "真实文件是 EXISTS|IMPLODE")
        self.assertEqual(info["file_size"], 37448, "uncompressed_size = codec 编码后长度")
        self.assertEqual(info["compressed_size"], 24706)

    # -- 1. 基线 ------------------------------------------------------------ #

    def test_01_real_baseline(self):
        """真实 stash.sv：96 条记录、gold=313108、10 页、currentPage=2、占格自洽。"""
        path = copy_real("baseline.sv")
        s = S.Stash(path)

        self.assertEqual(s.version, 0)
        self.assertEqual(s.gold, BASE_GOLD)
        self.assertEqual(s.item_count(), BASE_ITEMS)
        self.assertEqual(len(s.records), BASE_ITEMS)
        self.assertEqual(s.pages(), BASE_PAGES)
        self.assertEqual(s.current_page, BASE_CURRENT_PAGE)
        self.assertEqual(s.tail, b"")
        self.assertTrue(s.size_valid)
        self.assertEqual(s.expected_payload_size, 37385)

        for i, rec in enumerate(s.records):
            self.assertIsInstance(rec, bytes)
            self.assertEqual(len(rec), 368, "第 %d 条记录不是 368 字节" % i)

        check_grids_consistent(self, s)

        # 与原始 payload 逐字节一致（证明解析无损）
        payload = s._build_payload()
        self.assertEqual(payload, bytes(d1save.StashFile(path).data))
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         hashlib.sha256(bytes(d1save.StashFile(path).data)).hexdigest())

        # 物品尺寸来自 d1items.ITEM_SIZE[runtime_idx]
        item0 = s.records[0]
        saved_idx = struct.unpack_from("<i", item0, 360)[0]
        runtime = d1save.saved_to_runtime(saved_idx)
        self.assertEqual(S.Stash.record_size(item0), tuple(d1items_size(runtime)))

        # 独立验证：直接看 payload 里的 100 个 u16，落盘顺序必须是 x 在外、y 在内
        # （C++ StashGrid[x][y] 的遍历顺序），即第 i 个 cell = (x=i//10, y=i%10)。
        raw_pages = raw_page_cells(payload)
        self.assertEqual(sorted(raw_pages), BASE_PAGES)
        for page, flat in raw_pages.items():
            for y in range(10):
                for x in range(10):
                    # s.grids[page][y][x] 必须等于 payload 里的 cells[x*10 + y]
                    self.assertEqual(s.grids[page][y][x], flat[x * 10 + y],
                                     "page %d (x=%d,y=%d) 的行列顺序与落盘顺序不符" % (page, x, y))
        # 再验证第 7 条记录（position=(0,1)、1x1）确实落在 cells[0*10+1] 上
        rec7_flat = 0 * 10 + 1
        self.assertEqual(raw_pages[0][rec7_flat], 8, "记录 7 应在 (x=0,y=1)，cell 值应为 8")
        self.assertEqual(struct.unpack_from("<ii", s.records[7], 12), (0, 1))

    # -- 2. 原 bug 复现 ----------------------------------------------------- #

    def test_02_original_bug_repro(self):
        """原 StashFile.save() 按 512 字节扇区写表 → 我们的读取器精确报错、原读取器也读不回。"""
        path = copy_real("buggy.sv")
        before = sha(path)

        sf = d1save.StashFile(path)
        self.assertEqual(sf.gold, BASE_GOLD)
        self.assertEqual(sf.item_count(), BASE_ITEMS)
        sf.gold = 400000
        try:
            sf.save()
        except Exception as exc:                       # pragma: no cover - 环境异常
            self.skipTest("原修改器 save() 自己就失败了：%r" % (exc,))

        self.assertNotEqual(sha(path), before, "原修改器没有改写文件？")

        info = mpq_block_info(path, "spstashitems")
        self.assertEqual(info["flags"] & 0x300, 0x100, "原修改器仍写着 IMPLODE")
        hdr = info["header"]
        nsec_4096 = (info["file_size"] + hdr["sector_size"] - 1) // hdr["sector_size"]
        table_bytes = (nsec_4096 + 1) * 4
        with open(path, "rb") as fh:
            raw = fh.read()
        first = struct.unpack_from("<I", raw, info["offset"])[0]
        # 512 字节扇区 → 表首项 = (74+1)*4 = 300；4096 字节扇区 → 44
        self.assertEqual(first, 300, "原修改器写出的扇区表首项应为 300（512 字节扇区）")
        self.assertNotEqual(first, table_bytes,
                            "首项恰好等于 4096 扇区的表长，bug 没有复现")

        with self.assertRaises(S.MPQError) as ctx:
            S.Stash(path)
        self.assertIn("扇区偏移表首项", str(ctx.exception))
        self.assertIn("300", str(ctx.exception))
        self.assertIn("44", str(ctx.exception))

        with self.assertRaises(Exception):
            read_mpqfs_style(path, "spstashitems")

        # 原修改器自己的读取器也读不回来（与简报 §2.3 描述一致）
        with self.assertRaises(Exception) as ctx2:
            d1save.StashFile(path)
        self.assertIn("PkwareError", repr(type(ctx2.exception).__name__) + str(ctx2.exception))

        # 游戏侧的后果：LoadStash 拿不到数据 → 箱子显示空 → 存档被清空
        # （这里用“读取失败”代表这一后果）

    # -- 3. 修复验证 -------------------------------------------------------- #

    def test_03_gold_fix_roundtrip(self):
        """改 gold → save → 重开：gold 正确、96 条记录逐字节一致、页/格一致。"""
        src = copy_real("gold_src.sv")
        src_sha = sha(src)
        src_mtime = os.path.getmtime(src)

        s = S.Stash(src)
        base_records = list(s.records)
        base_grids = {p: [row[:] for row in g] for p, g in s.grids.items()}
        base_payload = s._build_payload()
        self.assertEqual(s.gold, BASE_GOLD)

        NEW_GOLD = 196607
        s.gold = NEW_GOLD
        out = os.path.join(TMP, "gold_fixed.sv")
        written = s.save(out, backup=False)
        self.assertEqual(written, out)
        self.assertTrue(os.path.isfile(out))
        self.assertFalse(os.path.exists(out + ".bak"), "backup=False 不应产生 .bak")

        # 原文件一个字节都没动
        self.assertEqual(sha(src), src_sha)
        self.assertEqual(os.path.getmtime(src), src_mtime)

        s2 = S.Stash(out)
        self.assertEqual(s2.gold, NEW_GOLD, "gold 没写对")
        self.assertEqual(s2.item_count(), BASE_ITEMS)
        self.assertEqual(s2.records, base_records, "96 条记录没有逐字节保持一致")
        self.assertEqual(s2.grids, base_grids, "页/格变了")
        self.assertEqual(s2.pages(), BASE_PAGES)
        self.assertEqual(s2.current_page, BASE_CURRENT_PAGE)
        self.assertEqual(s2.tail, b"")
        self.assertTrue(s2.size_valid)
        check_grids_consistent(self, s2)

        # payload 只允许 gold 那 4 个字节变化
        new_payload = s2._build_payload()
        self.assertEqual(len(new_payload), len(base_payload))
        diff = [i for i in range(len(base_payload)) if base_payload[i] != new_payload[i]]
        self.assertEqual(diff, [1, 2, 3], "除 gold 外还有字节被改动：%r" % (diff,))
        self.assertEqual(struct.unpack_from("<I", new_payload, 1)[0], NEW_GOLD)

        # 记录整体 sha（逐字节）
        self.assertEqual(
            hashlib.sha256(b"".join(base_records)).hexdigest(),
            hashlib.sha256(b"".join(s2.records)).hexdigest(),
        )

        # mpqfs 规则读取器交叉验证
        payload = read_mpqfs_style(out, "spstashitems")
        self.assertEqual(payload, new_payload, "mpqfs 规则读取器读不出同样的 payload")

        # 块头：未压缩、无扇区表、csize == usize == codec 编码后长度
        info = mpq_block_info(out, "spstashitems")
        encoded = bytes(d1codec.codec_encode(new_payload, PASSWORD))
        self.assertEqual(info["flags"], 0x80000000,
                         "flags 应为 0x80000000（只有 EXISTS）")
        self.assertEqual(info["compressed_size"], len(encoded))
        self.assertEqual(info["file_size"], len(encoded))
        self.assertEqual(info["file_size"], d1codec.codec_get_encoded_len(len(new_payload)))
        self.assertEqual(info["offset"] % 16, 0, "数据区没有 16 字节对齐")

        # header.archive_size == 文件长度
        self.assertEqual(info["header"]["archive_size"], os.path.getsize(out))
        self.assertEqual(info["header"]["sector_size_shift"], 3)

        # 哈希表没有被动过：仍能在原槽位找到它
        self.assertEqual(info["header"]["hash_off"], 32872)
        self.assertEqual(info["header"]["block_off"], 104)

        self.assertTrue(s2.verify_roundtrip())

    # -- 4. 原读取器的限制（证明不是文件非法） ------------------------------ #

    def test_04_original_reader_limitation_evidence(self):
        """原 d1mpq 读取器对“未压缩块”无条件丢掉 nsectors*4 字节 → 读不了我们的文件。"""
        s = S.Stash(copy_real("lim_src.sv"))
        s.gold = 123456
        out = os.path.join(TMP, "lim_fixed.sv")
        s.save(out, backup=False)

        payload = s._build_payload()
        encoded = bytes(d1codec.codec_encode(payload, PASSWORD))

        archive = d1mpq.MPQArchive(out)
        raw_block = archive.read_raw(0)
        # read_raw(bidx) -> (raw_bytes, file_size, flags)
        self.assertEqual(len(raw_block[0]), len(encoded), "read_raw 拿到的块数据是完整的")
        self.assertEqual(bytes(raw_block[0]), encoded, "块里就是完整的 codec 密文")
        self.assertEqual(raw_block[1], len(encoded))
        self.assertEqual(raw_block[2] & 0x300, 0, "块没有任何压缩标志")

        data = archive.read_file("spstashitems")
        hdr = mpq_block_info(out, "spstashitems")["header"]
        nsec = (len(encoded) + hdr["sector_size"] - 1) // hdr["sector_size"]
        self.assertEqual(nsec, 10, "37448 字节 @4096 = 10 个扇区")
        self.assertEqual(len(data), len(encoded) - nsec * 4,
                         "原读取器正好丢掉了 nsectors*4 字节")
        self.assertEqual(len(data), 37408)
        self.assertEqual(bytes(data), encoded[nsec * 4:],
                         "原读取器返回的就是“块数据去掉前 nsectors*4 字节”")

        # 因此它的 codec 解码必然失败（长度不是 64 的倍数）
        with self.assertRaises(Exception) as ctx:
            d1codec.codec_decode(bytes(data), PASSWORD)
        self.assertIn("64", str(ctx.exception))

        # 反证：同一读取器能正常读原版 IMPLODE 文件 → 说明它只是不支持未压缩块
        real_payload = bytes(d1save.StashFile(REAL_STASH).data)
        self.assertEqual(len(real_payload), 37385)
        self.assertTrue(d1save.StashFile(REAL_STASH).item_count() == BASE_ITEMS)

        # 反证 2：换成 implode_raw 写法（正确 4096 扇区表 + 原样扇区），
        # 原修改器就能读回来 —— 证明我们的 MPQ 结构完全合法，只是对方读不了未压缩块。
        s.write_mode = S.WRITE_MODE_IMPLODE_RAW
        out2 = os.path.join(TMP, "lim_implode_raw.sv")
        s.save(out2, backup=False)
        sf2 = d1save.StashFile(out2)
        self.assertEqual(sf2.gold, 123456)
        self.assertEqual(sf2.item_count(), BASE_ITEMS)
        self.assertEqual(bytes(sf2.data), payload, "原修改器读出的 payload 与我们的完全一致")

    # -- 5. add_record / remove_record -------------------------------------- #

    def test_05_add_record_roundtrip(self):
        """复制一条现有记录加入 → 存盘 → 重开（+1 条、新记录一致、老记录与 gold 不变）→ 删除恢复。"""
        src = copy_real("add_src.sv")
        s = S.Stash(src)
        base_records = list(s.records)
        base_grids = {p: [row[:] for row in g] for p, g in s.grids.items()}
        base_payload = s._build_payload()
        base_gold = s.gold
        self.assertEqual(len(base_records), BASE_ITEMS)

        # 挑一条 2x3 的多格物品（index 1，Short Sword），覆盖多格占位逻辑
        pick = 1
        rec = base_records[pick]
        w, h = S.Stash.record_size(rec)
        self.assertEqual((w, h), (2, 3))

        page, x, y = s.add_record(rec)
        self.assertIn(page, base_grids, "应该优先放进已有页")
        self.assertEqual(s.item_count(), BASE_ITEMS + 1)
        new_index = BASE_ITEMS

        # 新记录：除 position（12..20）外与源记录逐字节一致
        added = s.records[new_index]
        self.assertEqual(added[:12], rec[:12])
        self.assertEqual(added[20:], rec[20:])
        self.assertEqual(struct.unpack_from("<ii", added, 12), (x, y + h - 1),
                         "position 必须是左下角锚点，否则游戏不绘制该物品")
        # 原有记录一条都没变
        self.assertEqual(s.records[:BASE_ITEMS], base_records)
        self.assertEqual(s.gold, base_gold)

        # 占格正确
        grid = s.grids[page]
        for dy in range(h):
            for dx in range(w):
                self.assertEqual(grid[y + dy][x + dx], new_index + 1,
                                 "占格 (%d,%d) 不对" % (x + dx, y + dy))
        # 除了这块矩形，其它格子没变
        changed = set()
        for yy in range(10):
            for xx in range(10):
                if grid[yy][xx] != base_grids[page][yy][xx]:
                    changed.add((xx, yy))
        expected_changed = {(x + dx, y + dy) for dy in range(h) for dx in range(w)}
        self.assertEqual(changed, expected_changed, "额外动到了别的格子")

        check_grids_consistent(self, s)

        # 存盘 + 重开
        out = os.path.join(TMP, "add_out.sv")
        s.save(out, backup=False)
        s2 = S.Stash(out)
        self.assertEqual(s2.gold, base_gold, "add_record 不该改 gold")
        self.assertEqual(s2.item_count(), BASE_ITEMS + 1)
        self.assertEqual(s2.records[:BASE_ITEMS], base_records, "原有记录被改了")
        self.assertEqual(s2.records[BASE_ITEMS], added, "新记录写盘后不一致")
        self.assertEqual(s2.grids, s.grids, "页/格写盘后不一致")
        self.assertEqual(s2.pages(), s.pages())
        self.assertEqual(read_mpqfs_style(out, "spstashitems"), s2._build_payload())
        check_grids_consistent(self, s2)

        # 独立验证：直接看落盘的 100 个 u16，确认 2x3 的矩形确实写在
        # (x+dx)*10 + (y+dy) 这些位置上（防止“解析/写盘互为转置”掩盖错误）
        flat = raw_page_cells(read_mpqfs_style(out, "spstashitems"))[page]
        for dy in range(h):
            for dx in range(w):
                self.assertEqual(flat[(x + dx) * 10 + (y + dy)], new_index + 1,
                                 "落盘位置 (x=%d,y=%d) 不对" % (x + dx, y + dy))
        self.assertEqual(sum(1 for v in flat if v == new_index + 1), w * h,
                         "落盘后新物品的格子数不等于 w*h")

        # 删掉它 → 恢复原样
        removed = s2.remove_record(BASE_ITEMS)
        self.assertEqual(removed, added)
        self.assertEqual(s2.item_count(), BASE_ITEMS)
        self.assertEqual(s2.records, base_records)
        self.assertEqual(s2.grids, base_grids, "删除后没有恢复到原来的页/格")
        self.assertEqual(s2.pages(), BASE_PAGES)
        self.assertEqual(s2._build_payload(), base_payload,
                         "加一件再删掉应该回到与原始 payload 完全一致的字节")

        out2 = os.path.join(TMP, "add_removed.sv")
        s2.save(out2, backup=False)
        s3 = S.Stash(out2)
        self.assertEqual(s3.records, base_records)
        self.assertEqual(s3.grids, base_grids)
        self.assertEqual(s3.gold, base_gold)
        self.assertEqual(read_mpqfs_style(out2, "spstashitems"), base_payload)

    def test_06_add_record_byte_identical_without_position_fix(self):
        """fix_position=False 时新记录与源记录逐字节完全一致（position 保持原值）。"""
        s = S.Stash(copy_real("nofix_src.sv"))
        rec = s.records[5]
        w, h = S.Stash.record_size(rec)
        old_pos = struct.unpack_from("<ii", rec, 12)
        page, x, y = s.add_record(rec, fix_position=False)
        self.assertEqual(s.records[-1], rec, "fix_position=False 时不应改动任何字节")
        self.assertEqual(struct.unpack_from("<ii", s.records[-1], 12), old_pos,
                         "position 应保持记录里的原值")
        self.assertIn(page, s.grids)
        # 注意：position 与新的左上角 (x, y) 不匹配时，游戏只会按 position 那一格绘制，
        # 物品可能“看不见”。这正是默认 fix_position=True 的原因。
        if old_pos != (x, y + h - 1):
            self.assertNotEqual(old_pos, (x, y + h - 1))

    # -- 6. 页分配 ---------------------------------------------------------- #

    def test_07_new_page_when_full(self):
        """现有页都满时新建 max(page)+1 页；页号达到 100 时抛错。"""
        s = S.Stash(copy_real("pages_src.sv"))
        # 人为把第 0 页塞满（用 999 当“占位”），模拟“没空位”
        s.grids = {0: [[999] * 10 for _ in range(10)]}
        page, x, y = s.add_record(s.records[0])
        self.assertEqual((page, x, y), (1, 0, 0), "应该新建第 1 页")
        self.assertEqual(s.grids[1][0][0], len(s.records))
        self.assertEqual(len(s.grids[0]), 10)
        self.assertTrue(all(c == 999 for row in s.grids[0] for c in row),
                        "旧页的格子不应该被动过")

        # 指定页优先
        s2 = S.Stash(copy_real("pages_src2.sv"))
        s2.grids = {0: [[0] * 10 for _ in range(10)], 3: [[0] * 10 for _ in range(10)]}
        page2, _, _ = s2.add_record(s2.records[0], page=3)
        self.assertEqual(page2, 3, "指定页有空位时应放在指定页")

        # 指定页满 → 顺延到下一个有空位的页
        s3 = S.Stash(copy_real("pages_src3.sv"))
        s3.grids = {3: [[999] * 10 for _ in range(10)], 5: [[0] * 10 for _ in range(10)]}
        page3, _, _ = s3.add_record(s3.records[0], page=3)
        self.assertEqual(page3, 5)

        # 100 页都满 → StashError
        s4 = S.Stash(copy_real("pages_src4.sv"))
        s4.grids = {p: [[999] * 10 for _ in range(10)] for p in range(100)}
        with self.assertRaises(S.StashError) as ctx:
            s4.add_record(s4.records[0])
        self.assertIn("储物箱已满", str(ctx.exception))

        # 新建的页能正常存盘/重开
        out = os.path.join(TMP, "newpage.sv")
        s.save(out, backup=False)
        s5 = S.Stash(out)
        self.assertEqual(s5.pages(), [0, 1])
        self.assertEqual(s5.item_count(), BASE_ITEMS + 1)
        self.assertEqual(s5.grids, s.grids)
        self.assertEqual(s5.grids[1][0][0], BASE_ITEMS + 1)
        self.assertEqual(read_mpqfs_style(out, "spstashitems"), s5._build_payload())

    # -- 7. 备份 / 自检 / 边界 ---------------------------------------------- #

    def test_08_backup_and_inplace_save(self):
        """save() 默认在写回自身前生成 .bak；backup=False 不生成。"""
        path = copy_real("inplace.sv")
        original = sha(path)

        s = S.Stash(path)
        s.gold = 777777
        written = s.save()                       # 写回自身，默认 backup=True
        self.assertEqual(written, path)
        self.assertTrue(os.path.isfile(path + ".bak"), "没有生成 .bak")
        self.assertEqual(sha(path + ".bak"), original, ".bak 不是保存前的内容")
        self.assertEqual(S.Stash(path).gold, 777777)

        # 再存一次，backup=False → .bak 保持第一次的内容
        s.gold = 888888
        s.save(backup=False)
        self.assertEqual(sha(path + ".bak"), original)
        self.assertEqual(S.Stash(path).gold, 888888)

    def test_09_verify_roundtrip_both_modes(self):
        for mode in S.WRITE_MODES:
            with self.subTest(mode=mode):
                s = S.Stash(copy_real("verify_%s.sv" % mode), write_mode=mode)
                self.assertTrue(s.verify_roundtrip())
                s.gold = 424242
                s.add_record(s.records[2])
                self.assertTrue(s.verify_roundtrip())
                out = os.path.join(TMP, "verify_%s_out.sv" % mode)
                s.save(out, backup=False)
                s2 = S.Stash(out)
                self.assertEqual(s2.gold, 424242)
                self.assertEqual(s2.records, s.records)
                self.assertEqual(s2.grids, s.grids)
                self.assertEqual(read_mpqfs_style(out, "spstashitems"), s2._build_payload(),
                                 "mpqfs 规则读取器读不出 %s 写法的文件" % mode)
                info = mpq_block_info(out, "spstashitems")
                if mode == S.WRITE_MODE_UNCOMPRESSED:
                    self.assertEqual(info["flags"], 0x80000000)
                    self.assertEqual(info["compressed_size"], info["file_size"])
                else:
                    self.assertEqual(info["flags"], 0x80000100)
                    self.assertGreater(info["compressed_size"], info["file_size"])
                    nsec = (info["file_size"] + 4096 - 1) // 4096
                    self.assertEqual(info["compressed_size"], info["file_size"] + (nsec + 1) * 4,
                                     "扇区偏移表长度应为 (nsec+1)*4")

    def test_10_unknown_tail_preserved(self):
        """currentPage 之后的未知字节必须原样保留，不能截断。"""
        s = S.Stash(copy_real("tail_src.sv"))
        s.tail = b"\xde\xad\xbe\xef"
        self.assertFalse(s.verify_roundtrip() is None)
        out = os.path.join(TMP, "tail.sv")
        s.save(out, backup=False)
        s2 = S.Stash(out)
        self.assertEqual(s2.tail, b"\xde\xad\xbe\xef", "尾部字节被丢了")
        self.assertEqual(len(s2._build_payload()), 37385 + 4)
        self.assertFalse(s2.size_valid, "尾部存在时 size_valid 应为 False")
        self.assertEqual(s2.size_mismatch, 4)
        self.assertEqual(s2.records, s.records)
        self.assertEqual(s2.grids, s.grids)

    def test_11_multiplayer_name(self):
        """多人模式找的是 mpstashitems；单人箱里没有它，应在构造时报错。"""
        path = copy_real("mp_src.sv")
        with self.assertRaises(S.MPQError) as ctx:
            S.Stash(path, multiplayer=True)
        self.assertIn("mpstashitems", str(ctx.exception))
        # 单人模式能读，说明只是文件名不同
        s = S.Stash(path)
        self.assertEqual(s.item_count(), BASE_ITEMS)

    def test_12_errors(self):
        """非法输入要报清晰的错误，而不是静默写坏文件。"""
        with self.assertRaises(S.StashError):
            S.Stash(REAL_STASH, write_mode="bogus")

        s = S.Stash(copy_real("err_src.sv"))
        with self.assertRaises(S.StashError):
            s.add_record(b"\x00" * 100)
        with self.assertRaises(S.StashError):
            s.remove_record(999)

        # records 里塞长度不对的记录 → 写盘前就报错
        s.records.append(b"\x00" * 10)
        with self.assertRaises(S.StashError):
            s._build_payload()

    def test_13_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            S.Stash(os.path.join(TMP, "does_not_exist.sv"))


def d1items_size(runtime_idx):
    """``d1items.ITEM_SIZE[runtime_idx]``（运行时编号索引的 (w, h)）。"""
    return S._d1items().ITEM_SIZE[runtime_idx]


if __name__ == "__main__":
    if not os.path.isfile(REAL_STASH):
        print("缺少基准存档：%s" % REAL_STASH, file=sys.stderr)
        sys.exit(2)
    if sys.version_info[:2] != (3, 12):
        print("警告：当前 Python 是 %s，加载 3.12 pyc 可能失败（请使用 Python 3.12）"
              % (sys.version.split()[0],), file=sys.stderr)

    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
