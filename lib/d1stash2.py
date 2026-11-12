r"""d1stash2 — DevilutionX 1.5.5 储物箱 (stash.sv) 读写库（修正版）。

背景 / 根因
-----------
原修改器 ``d1save.StashFile.save()`` 在重建 MPQ 时把 ``sector_size_shift``
从 ``raw[12]`` 读（应为 ``raw[14]``，``raw[12]`` 是 ``format_version``），
于是按 512 字节扇区写扇区偏移表，而块 flags 仍带 ``0x100`` (IMPLODE)。
游戏 (mpqfs) 按 4096 字节扇区读表 → 第 0 扇区 ``span(512) != expect(4096)``
→ 把原始数据当 PKWARE 压缩流 explode → 解压失败 → ``codec_decode`` 失败
→ ``LoadStash()`` 放弃 → 箱子显示为空 → 玩家一开箱/退出游戏就用空箱覆盖存档。

本库的写法（简报 §2.4）
-----------------------
写出**完全未压缩**的 MPQ 块::

    flags = 0x80000000  (只有 EXISTS，没有 IMPLODE / COMPRESS / SINGLE_UNIT)
    block_data = codec 编码后的字节   # 没有扇区偏移表
    compressed_size = uncompressed_size = len(block_data)

然后更新块表（重新加密写回）、header 的 ``archive_size``（offset 8），
追加的数据按 16 字节对齐，哈希表保持不变（block index 不变）。

格式备忘
--------
``stash.sv`` = MPQ v1，单文件 ``spstashitems``（单人）/ ``mpstashitems``（多人）。
文件内容再套一层 Diablo codec 加密（口令 ``xrgyrkj1`` / ``szqnlsk1``）。
解码后的 payload::

    u8   version (0)
    u32  gold
    u32  pageCount
      pageCount × { u32 page; u16 cells[100] }   # cells 顺序为 x 在外、y 在内
    u32  itemCount
      itemCount × 368 字节 Item 记录
    u32  currentPage
    ...（未知尾部字节，若有，原样保留）

重要：MPQ 块的 ``uncompressed_size`` 是 **codec 编码后的长度**
（``codec_get_encoded_len(payload)``，等于 payload 补齐到 64 字节倍数 + 8 字节签名），
而不是 payload 长度。游戏 ``ReadArchive()`` 读入该长度后再 ``codec_decode``，
把 **解码后长度** 交给 ``IsStashSizeValid()``。

网格约定（与游戏 ``Source/qol/stash.cpp`` 一致）
----------------------------------------------
* ``grids[page]`` 是 ``10x10`` 的 ``list[list[int]]``，索引为 ``grid[y][x]``
  （``y`` = 行 / 竖直，``x`` = 列 / 水平）。
* 格子值 = ``itemIndex + 1``，``0`` 表示空。
* 物品左上角为 ``(x, y)``，按 ``w × h`` 占格（``w`` 沿 x 方向，``h`` 沿 y 方向）。
* **落盘顺序是 x 在外、y 在内**：C++ 里 ``StashGrid = array<array<StashCell,10>,10>``
  且用 ``stashGrids[page][x][y]`` 访问，``LoadStash/SaveStash`` 按 ``for x { for y }``
  顺序读写这 100 个 u16。所以 payload 里的第 ``i`` 个 cell 对应
  ``x = i // 10, y = i % 10``；本库对外暴露行优先的 ``grid[y][x]``，
  内部换算是 ``grid[y][x] = cells[x*10 + y]``。
* 记录里 ``position`` 字段（offset 12/16）必须等于 **左下角锚点**
  ``(x, y + h - 1)``——游戏 ``DrawStash()`` 只在该格绘制物品
  （``if (item.position != slot) continue;``）。``add_record()`` 默认会帮你修正它。

物品尺寸来自 ``d1items.ITEM_SIZE[runtime_idx]``（运行时物品编号索引，值为 ``(w, h)``）。
已用真实存档 96 件物品验证：全部 96 件的占格矩形、尺寸、锚点都与之完全吻合。

用法
----
>>> from d1stash2 import Stash
>>> s = Stash(r"...\stash.sv")
>>> s.gold, s.item_count()
(313108, 96)
>>> s.gold = 400000
>>> s.save()                       # 先写 .bak 再原子替换
>>> s.add_record(s.records[0])     # 复制一件物品，自动找空位
(12, 0, 0)
"""

from __future__ import annotations

import importlib.util
import os
import struct
import sys

__all__ = [
    "Stash",
    "StashError",
    "MPQError",
    "load_stash",
    "ITEM_RECORD_SIZE",
    "STASH_GRID_W",
    "STASH_GRID_H",
    "MAX_STASH_PAGES",
    "WRITE_MODE_UNCOMPRESSED",
    "WRITE_MODE_IMPLODE_RAW",
    "WRITE_MODES",
]

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

ITEM_RECORD_SIZE = 368          # 1.5.5 非 Hellfire (HellfireItemSaveSize = 372)
STASH_GRID_W = 10
STASH_GRID_H = 10
GRID_CELLS = STASH_GRID_W * STASH_GRID_H
MAX_STASH_PAGES = 100           # StashStruct / CountStashPages

STASH_VERSION = 0

MPQ_SIGNATURE = 0x1A51504D      # b"MPQ\x1a" 小端
MPQ_HEADER_SIZE = 32

MPQ_FILE_EXISTS = 0x80000000
MPQ_FILE_IMPLODE = 0x00000100
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_ENCRYPTED = 0x00010000
MPQ_FILE_FIX_KEY = 0x00020000
MPQ_FILE_SINGLE_UNIT = 0x01000000

HASH_TABLE_INDEX = 0
HASH_NAME_A = 1
HASH_NAME_B = 2
HASH_FILE_KEY = 3

HASH_ENTRY_EMPTY = 0xFFFFFFFF
HASH_ENTRY_DELETED = 0xFFFFFFFE

SINGLE_STASH_FILE = "spstashitems"
MULTI_STASH_FILE = "mpstashitems"

DEFAULT_PASSWORD_SINGLE = "xrgyrkj1"
DEFAULT_PASSWORD_MULTI = "szqnlsk1"

# 写盘方式（见模块文档 / stash_report.md）
#   uncompressed ：flags = 0x80000000，无扇区表，csize == usize == len(block)  ← 简报 §2.4 指定，默认
#   implode_raw  ：flags = 0x80000100，带**正确的 4096 字节**扇区偏移表，每个扇区原样存储
#                  （span == expect，mpqfs 直接 memcpy）。兼容性对照用：
#                  原修改器的 d1mpq 读取器也能读回（实测），游戏同样支持。
WRITE_MODE_UNCOMPRESSED = "uncompressed"
WRITE_MODE_IMPLODE_RAW = "implode_raw"
WRITE_MODES = (WRITE_MODE_UNCOMPRESSED, WRITE_MODE_IMPLODE_RAW)

# 记录里的字段偏移（见 PROJECT_BRIEF §4.1 / loadsave.cpp SaveItem）
OFF_POSITION = 12               # i32 position.x, i32 position.y
OFF_IDX = 360                   # i32 存档编号（Diablo 映射号）


class StashError(Exception):
    """储物箱语义错误（格式非法、页满、记录长度不对等）。"""


class MPQError(Exception):
    """MPQ 结构错误。"""


# --------------------------------------------------------------------------- #
# 原修改器 pyc 模块的动态加载（Python 3.12）
# --------------------------------------------------------------------------- #

_MODULES: dict[str, object] = {}
_ROOT_CACHE: str | None = None


def _find_root() -> str:
    """定位工作区根 ROOT（含 ``暗黑破坏神1存档修改器-...exe_extracted`` 的目录）。"""
    global _ROOT_CACHE
    if _ROOT_CACHE:
        return _ROOT_CACHE

    candidates: list[str] = []
    env = os.environ.get("D1_ROOT")
    if env:
        candidates.append(env)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(here)                                   # <repo>/lib
    candidates.append(os.path.dirname(here))                  # <repo>
    candidates.append(os.path.dirname(os.path.dirname(here)))  # 旧布局 ROOT
    candidates.append(os.getcwd())

    for cand in candidates:
        if not cand:
            continue
        if os.path.isdir(os.path.join(cand, "暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted")):
            _ROOT_CACHE = os.path.abspath(cand)
            return _ROOT_CACHE
        if os.path.isfile(os.path.join(cand, "_d1pyc", "d1mpq.pyc")):
            _ROOT_CACHE = os.path.abspath(cand)
            return _ROOT_CACHE

    raise StashError(
        "找不到 3.12 pyc 模块目录（_d1pyc/d1mpq.pyc）或原修改器解包目录。"
        "可用环境变量 D1_ROOT 指定工作区根目录。尝试过: %r" % (candidates,)
    )


def _pyz_dir() -> str:
    root = _find_root()
    pyc_dir = os.path.join(root, "_d1pyc")
    if os.path.isdir(pyc_dir):
        return pyc_dir
    return os.path.join(
        root, "暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted", "PYZ.pyz_extracted"
    )


def _load_pyc(name: str):
    """按简报 §7 的方式从 PYZ.pyz_extracted 加载 3.12 pyc。"""
    mod = _MODULES.get(name)
    if mod is not None:
        return mod

    pyz = _pyz_dir()
    path = os.path.join(pyz, name + ".pyc")
    if not os.path.isfile(path):
        raise StashError("缺少模块 %s（%s）" % (name, path))

    if pyz not in sys.path:
        sys.path.insert(0, pyz)

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StashError("无法加载模块 %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


def _d1save():
    return _load_pyc("d1save")


def _d1mpq():
    return _load_pyc("d1mpq")


def _d1codec():
    return _load_pyc("d1codec")


def _d1items():
    return _load_pyc("d1items")


def _d1pkware():
    return _load_pyc("d1pkware")


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def _u32(buf, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _align16(n: int) -> int:
    return (n + 15) & ~15


def _read_block_entry(block_table: bytes | bytearray, index: int) -> tuple[int, int, int, int]:
    off, csize, usize, flags = struct.unpack_from("<IIII", block_table, index * 16)
    return off, csize, usize, flags


def _write_block_entry(block_table: bytearray, index: int, off: int, csize: int, usize: int, flags: int):
    struct.pack_into("<IIII", block_table, index * 16, off, csize, usize, flags)


# --------------------------------------------------------------------------- #
# Stash
# --------------------------------------------------------------------------- #

class Stash:
    """DevilutionX 1.5.5 储物箱（stash.sv）。

    Attributes
    ----------
    path : str
        当前文件路径（``save(out_path)`` 后会更新）。
    gold : int
        箱子里的金币。
    records : list[bytes]
        每条 368 字节的 Item 记录；列表下标即 stashList 下标。
    grids : dict[int, list[list[int]]]
        ``page -> grid[y][x]``，10x10，``cell = itemIndex + 1``，0 为空。
    current_page : int
        ``currentPage`` 字段（游戏打开箱子时显示的页）。
    """

    def __init__(self, path: str, multiplayer: bool = False,
                 write_mode: str = WRITE_MODE_UNCOMPRESSED):
        if write_mode not in WRITE_MODES:
            raise StashError("未知写盘方式 %r（可选 %r）" % (write_mode, WRITE_MODES))
        self.path = os.path.abspath(path)
        self.multiplayer = bool(multiplayer)
        self.write_mode = write_mode
        self.name = MULTI_STASH_FILE if self.multiplayer else SINGLE_STASH_FILE
        self.password = self._password()

        # 逻辑状态（由 _parse_payload 填充）
        self.version: int = STASH_VERSION
        self.gold: int = 0
        self.records: list[bytes] = []
        self.grids: dict[int, list[list[int]]] = {}
        self.current_page: int = 0
        self.tail: bytes = b""          # currentPage 之后的未知字节，原样保留
        self.expected_payload_size: int = 0
        self.size_valid: bool = True
        self.size_mismatch: int = 0

        # MPQ 层状态（由 _load_archive_bytes 填充）
        self._raw: bytes = b""
        self._header: dict[str, int] = {}
        self._hash_table: bytearray = bytearray()
        self._block_table: bytearray = bytearray()
        self._block_index: int = -1

        self._read_file()

    # -- 口令 ------------------------------------------------------------- #

    def _password(self) -> str:
        try:
            d1save = _d1save()
            return d1save.PASSWORD_MULTI if self.multiplayer else d1save.PASSWORD_SINGLE
        except Exception:
            return DEFAULT_PASSWORD_MULTI if self.multiplayer else DEFAULT_PASSWORD_SINGLE

    # -- MPQ 解析 ---------------------------------------------------------- #

    def _read_file(self):
        with open(self.path, "rb") as fh:
            data = fh.read()
        self._load_archive_bytes(data)

    def _load_archive_bytes(self, raw: bytes):
        """解析 MPQ 外壳，并把解密后的 stash payload 解出来。"""
        self._load_tables(raw)
        block_raw = self._read_block_data(self._block_index)
        d1codec = _d1codec()
        try:
            payload = bytes(d1codec.codec_decode(block_raw, self.password))
        except Exception as exc:  # noqa: BLE001 - codec 的异常类型是 CodecError
            raise MPQError(
                "codec 解码失败（%s）。文件可能被原修改器的 bug 写坏了。" % (exc,)
            ) from exc
        self._parse_payload(payload)

    def _load_tables(self, raw: bytes):
        """解析 header、解密哈希表/块表、定位 ``self.name`` 的 block index。"""
        if len(raw) < MPQ_HEADER_SIZE:
            raise MPQError("文件太小，不是 MPQ：%s" % self.path)

        (sig, hsize, asize, fmt, shift,
         hash_off, block_off, hash_cnt, block_cnt) = struct.unpack_from("<IIIHHIIII", raw, 0)
        if sig != MPQ_SIGNATURE:
            raise MPQError("MPQ 签名不匹配（0x%08X）：%s" % (sig, self.path))
        if fmt != 0:
            raise MPQError("不支持的 MPQ 格式版本 %d（本库只处理 v1）" % fmt)
        if shift > 15:
            raise MPQError("sector_size_shift 异常：%d" % shift)
        if hash_cnt == 0 or block_cnt == 0:
            raise MPQError("MPQ 表为空")
        for off, count, label in ((hash_off, hash_cnt, "hash"), (block_off, block_cnt, "block")):
            if off + count * 16 > len(raw):
                raise MPQError("%s 表越界（off=%d cnt=%d 文件=%d）" % (label, off, count, len(raw)))

        d1mpq = _d1mpq()
        k_hash = d1mpq.hash_string("(hash table)", HASH_FILE_KEY)
        k_block = d1mpq.hash_string("(block table)", HASH_FILE_KEY)

        self._raw = raw
        self._header = {
            "signature": sig,
            "header_size": hsize,
            "archive_size": asize,
            "format_version": fmt,
            "sector_size_shift": shift,
            "sector_size": 512 << shift,
            "hash_off": hash_off,
            "block_off": block_off,
            "hash_cnt": hash_cnt,
            "block_cnt": block_cnt,
        }
        self._hash_table = bytearray(
            bytes(d1mpq.crypt_block(bytearray(raw[hash_off:hash_off + hash_cnt * 16]), k_hash))
        )
        self._block_table = bytearray(
            bytes(d1mpq.crypt_block(bytearray(raw[block_off:block_off + block_cnt * 16]), k_block))
        )

        index = self._find_block(self.name)
        if index is None:
            raise MPQError("归档里找不到文件 %r：%s" % (self.name, self.path))
        self._block_index = index

    def _find_block(self, name: str):
        """按 MPQ v1 线性探测规则查哈希表，返回 block index。"""
        d1mpq = _d1mpq()
        hash_cnt = self._header["hash_cnt"]
        block_cnt = self._header["block_cnt"]
        ha = d1mpq.hash_string(name, HASH_NAME_A)
        hb = d1mpq.hash_string(name, HASH_NAME_B)
        start = d1mpq.hash_string(name, HASH_TABLE_INDEX) % hash_cnt
        ht = self._hash_table
        for probe in range(hash_cnt):
            i = (start + probe) % hash_cnt
            a, b, _locale_platform, bi = struct.unpack_from("<IIII", ht, i * 16)
            if bi == HASH_ENTRY_EMPTY:
                return None
            if bi == HASH_ENTRY_DELETED:
                continue
            if a == ha and b == hb and bi < block_cnt:
                return bi
        return None

    def _read_block_data(self, index: int) -> bytes:
        """按 mpqfs ``mpq_stream.c`` 的规则取出块的**未解码**字节（codec 密文）。"""
        raw = self._raw
        sector_size = self._header["sector_size"]
        off, csize, usize, flags = _read_block_entry(self._block_table, index)

        if not (flags & MPQ_FILE_EXISTS):
            raise MPQError("块 %d 没有 EXISTS 标志" % index)
        if flags & MPQ_FILE_ENCRYPTED:
            raise MPQError(
                "块 %d 带 ENCRYPTED 标志，本库未实现逐块加密（stash.sv 不会这样）" % index
            )
        if off + csize > len(raw):
            raise MPQError("块 %d 越界（off=%d csize=%d 文件=%d）" % (index, off, csize, len(raw)))
        if usize == 0:
            return b""

        blob = raw[off:off + csize]

        if (flags & (MPQ_FILE_IMPLODE | MPQ_FILE_COMPRESS)) and not (flags & MPQ_FILE_SINGLE_UNIT):
            nsec = (usize + sector_size - 1) // sector_size
            table_bytes = (nsec + 1) * 4
            if len(blob) < table_bytes:
                raise MPQError("扇区偏移表越界（块 %d）" % index)
            table = struct.unpack_from("<%dI" % (nsec + 1), blob, 0)
            if table[0] != table_bytes:
                raise MPQError(
                    "扇区偏移表首项 %d != %d（扇区大小 %d）。"
                    "典型的「原修改器把 shift 读成 0 写成 512 扇区」症状。"
                    % (table[0], table_bytes, sector_size)
                )
            d1pkware = _d1pkware()
            out = bytearray()
            for s in range(nsec):
                expect = min(sector_size, usize - s * sector_size)
                start, end = table[s], table[s + 1]
                if end < start or end > len(blob):
                    raise MPQError("扇区 %d 偏移非法（%d..%d）" % (s, start, end))
                span = end - start
                if span == 0:
                    out += b"\x00" * expect
                elif span == expect:
                    out += blob[start:end]                    # 原样存储
                elif flags & MPQ_FILE_IMPLODE:
                    out += d1pkware.explode(blob[start:end], expect)
                elif flags & MPQ_FILE_COMPRESS:
                    out += self._decompress_multi(blob[start:end], expect)
                else:  # pragma: no cover - 逻辑上不可能
                    raise MPQError("扇区 %d 无法解压" % s)
            if len(out) < usize:
                out += b"\x00" * (usize - len(out))
            return bytes(out[:usize])

        if flags & MPQ_FILE_SINGLE_UNIT:
            return blob[:usize]

        # 未压缩、多扇区：数据直接从块起始处顺序排布，无偏移表
        if len(blob) < usize:
            raise MPQError("未压缩块长度不足（%d < %d）" % (len(blob), usize))
        return blob[:usize]

    @staticmethod
    def _decompress_multi(blob: bytes, expect: int) -> bytes:
        """MPQ_FILE_COMPRESS 的多方法压缩（首字节是方法掩码）。"""
        if not blob:
            raise MPQError("空的多方法压缩扇区")
        method = blob[0]
        src = blob[1:]
        if method & 0x08:  # PKWARE
            return _d1pkware().explode(src, expect)
        if method & 0x02:  # zlib
            import zlib
            return zlib.decompress(src)[:expect]
        if method & 0x10:  # bzip2
            import bz2
            return bz2.decompress(src)[:expect]
        raise MPQError("不支持的多方法压缩掩码 0x%02X" % method)

    # -- 逻辑结构 ---------------------------------------------------------- #

    def _parse_payload(self, payload: bytes):
        if len(payload) < 1 + 4 + 4 + 4 + 4:
            raise StashError("stash payload 太短（%d 字节）" % len(payload))

        pos = 0
        version = payload[pos]
        pos += 1
        gold = _u32(payload, pos)
        pos += 4

        page_count = _u32(payload, pos)
        pos += 4
        if page_count > MAX_STASH_PAGES:
            raise StashError("pageCount=%d 超过上限 %d" % (page_count, MAX_STASH_PAGES))

        grids: dict[int, list[list[int]]] = {}
        for _ in range(page_count):
            page = _u32(payload, pos)
            pos += 4
            cells = struct.unpack_from("<%dH" % GRID_CELLS, payload, pos)
            pos += GRID_CELLS * 2
            if page in grids:
                raise StashError("页号 %d 重复出现" % page)
            # 落盘顺序是 x 在外、y 在内（C++: array<array<cell,10>,10> 用 grid[x][y]，
            # 序列化时先遍历外层 x）。这里对外暴露 grid[y][x]（行优先），
            # 所以 grid[y][x] 取 cells[x * 10 + y]。
            grids[page] = [
                [cells[x * STASH_GRID_W + y] for x in range(STASH_GRID_W)]
                for y in range(STASH_GRID_H)
            ]

        item_count = _u32(payload, pos)
        pos += 4
        need = item_count * ITEM_RECORD_SIZE
        if pos + need + 4 > len(payload):
            raise StashError(
                "itemCount=%d 需要 %d 字节记录，但剩余只有 %d 字节"
                % (item_count, need, len(payload) - pos - 4)
            )
        records = [
            bytes(payload[pos + i * ITEM_RECORD_SIZE: pos + (i + 1) * ITEM_RECORD_SIZE])
            for i in range(item_count)
        ]
        pos += need

        current_page = _u32(payload, pos)
        pos += 4

        tail = bytes(payload[pos:])

        # 尺寸自检：与游戏 IsStashSizeValid() 完全一致的公式。
        # 多出来的字节（若有）原样保留在 self.tail，重新写盘时按原样追加，绝不截断。
        expected = (
            1 + 4 + 4
            + (4 + GRID_CELLS * 2) * page_count
            + 4
            + ITEM_RECORD_SIZE * item_count
            + 4
        )
        self.expected_payload_size = expected
        self.size_valid = (expected == len(payload))
        if not self.size_valid:
            # 游戏侧 IsStashSizeValid() 要求严格相等；这里只记录，不抛异常。
            self.size_mismatch = len(payload) - expected
        else:
            self.size_mismatch = 0

        self.version = version
        self.gold = gold
        self.grids = grids
        self.records = records
        self.current_page = current_page
        self.tail = tail

    def _build_payload(self) -> bytes:
        out = bytearray()
        out.append(self.version & 0xFF)
        out += struct.pack("<I", int(self.gold) & 0xFFFFFFFF)
        out += struct.pack("<I", len(self.grids))
        for page, grid in self.grids.items():
            out += struct.pack("<I", int(page) & 0xFFFFFFFF)
            flat = [0] * GRID_CELLS
            for y in range(STASH_GRID_H):
                row = grid[y]
                for x in range(STASH_GRID_W):
                    flat[x * STASH_GRID_W + y] = int(row[x]) & 0xFFFF
            out += struct.pack("<%dH" % GRID_CELLS, *flat)
        out += struct.pack("<I", len(self.records))
        for i, rec in enumerate(self.records):
            if len(rec) != ITEM_RECORD_SIZE:
                raise StashError(
                    "records[%d] 长度 %d，应为 %d" % (i, len(rec), ITEM_RECORD_SIZE)
                )
            out += rec
        out += struct.pack("<I", int(self.current_page) & 0xFFFFFFFF)
        out += self.tail
        return bytes(out)

    # -- 只读属性 ---------------------------------------------------------- #

    def item_count(self) -> int:
        return len(self.records)

    def pages(self) -> list[int]:
        """已有的页号（升序）。"""
        return sorted(self.grids)

    def grid_at(self, page: int) -> list[list[int]]:
        """取某页的 10x10 网格（``grid[y][x]``），不存在则创建空页。"""
        if page not in self.grids:
            self.grids[page] = [[0] * STASH_GRID_W for _ in range(STASH_GRID_H)]
        return self.grids[page]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Stash %s gold=%d items=%d pages=%s>" % (
            os.path.basename(self.path), self.gold, self.item_count(), self.pages(),
        )

    # -- 物品尺寸 ---------------------------------------------------------- #

    @staticmethod
    def record_saved_index(record: bytes) -> int:
        return struct.unpack_from("<i", record, OFF_IDX)[0]

    @staticmethod
    def record_runtime_index(record: bytes) -> int:
        saved = Stash.record_saved_index(record)
        try:
            return int(_d1save().saved_to_runtime(saved))
        except Exception:  # noqa: BLE001
            return saved

    @staticmethod
    def record_size(record: bytes) -> tuple[int, int]:
        """返回 (w, h)：w 沿 x，h 沿 y。来自 ``d1items.ITEM_SIZE[runtime_idx]``。"""
        runtime = Stash.record_runtime_index(record)
        size = _d1items().ITEM_SIZE.get(runtime)
        if not size:
            raise StashError(
                "查不到物品尺寸：saved_idx=%d runtime_idx=%d"
                % (Stash.record_saved_index(record), runtime)
            )
        w, h = int(size[0]), int(size[1])
        if not (1 <= w <= STASH_GRID_W and 1 <= h <= STASH_GRID_H):
            raise StashError("物品尺寸异常：%r (runtime_idx=%d)" % ((w, h), runtime))
        return w, h

    # -- 网格操作 ---------------------------------------------------------- #

    def _find_free_slot(self, page: int, w: int, h: int):
        """在一页里找能放下 w×h 的左上角 (x, y)，行优先扫描。"""
        grid = self.grids.get(page)
        if grid is None:
            return (0, 0) if (w <= STASH_GRID_W and h <= STASH_GRID_H) else None
        for y in range(0, STASH_GRID_H - h + 1):
            for x in range(0, STASH_GRID_W - w + 1):
                free = True
                for dy in range(h):
                    row = grid[y + dy]
                    for dx in range(w):
                        if row[x + dx]:
                            free = False
                            break
                    if not free:
                        break
                if free:
                    return (x, y)
        return None

    def _occupy(self, page: int, x: int, y: int, w: int, h: int, cell: int):
        grid = self.grid_at(page)
        for dy in range(h):
            row = grid[y + dy]
            for dx in range(w):
                row[x + dx] = cell

    def _remap_cells(self, fn):
        for grid in self.grids.values():
            for row in grid:
                for i, cell in enumerate(row):
                    row[i] = fn(cell)

    def add_record(self, record: bytes, page: int | None = None,
                   fix_position: bool = True, strict_page: bool = False) -> tuple[int, int, int]:
        """把一条 368 字节记录加入储物箱，返回 ``(page, x, y)``（左上角坐标）。

        参数
        ----
        record : bytes
            368 字节 Item 记录（原样加入，除 ``fix_position`` 修正的 position 字段）。
        page : int | None
            指定优先页（**0-based**，第 1 页 = ``page=0``，有效范围 0..99）。
            ``None`` 表示从最低页号开始找。
            指定页还有空位 → 就放该页；指定页不存在 → 新建该页（放在 (0,0)）；
            指定页已满且 ``strict_page=False`` → 按页号升序顺延到别的页。
            页号越界（<0 或 >99）一律抛 :class:`StashError`，不会写出非法页号。
        fix_position : bool
            默认 True：把记录里的 ``position`` 改成游戏要求的左下角锚点
            ``(x, y + h - 1)``。**必须保留 True**，否则游戏不会绘制该物品
            （``DrawStash`` 只在 ``item.position`` 那一格画）。
        strict_page : bool
            默认 False（保持老行为：指定页满时顺延）。True 时指定页放不下就抛
            :class:`StashError`，方便 GUI 的“写入第 N 页”给出明确提示。

        返回
        ----
        (page, x, y) —— 左上角格坐标；x 沿 x 轴（列），y 沿 y 轴（行）。
        """
        rec = bytes(record)
        if len(rec) != ITEM_RECORD_SIZE:
            raise StashError("记录长度 %d，应为 %d" % (len(rec), ITEM_RECORD_SIZE))

        w, h = self.record_size(rec)

        requested = None
        if page is not None:
            try:
                requested = int(page)
            except (TypeError, ValueError):
                raise StashError("页码必须是整数（0-based，第 1 页 = 0），收到 %r" % (page,))
            if not (0 <= requested < MAX_STASH_PAGES):
                raise StashError(
                    "页码越界：%d。page 是 0-based，有效范围 0..%d（第 1 页 = page 0，"
                    "第 %d 页 = page %d）"
                    % (requested, MAX_STASH_PAGES - 1, MAX_STASH_PAGES,
                       MAX_STASH_PAGES - 1))

        target_page = None
        slot = None
        if requested is not None:
            found = self._find_free_slot(requested, w, h)
            if found is not None:
                target_page, slot = requested, found
            elif strict_page:
                raise StashError(
                    "第 %d 页（page=%d）没有能放下 %dx%d 物品的空位；"
                    "请换一页、新建一页，或允许自动顺延（strict_page=False）"
                    % (requested + 1, requested, w, h))
            else:
                for p in sorted(self.grids):
                    if p == requested:
                        continue
                    found = self._find_free_slot(p, w, h)
                    if found is not None:
                        target_page, slot = p, found
                        break
        else:
            for p in sorted(self.grids):
                found = self._find_free_slot(p, w, h)
                if found is not None:
                    target_page, slot = p, found
                    break

        if target_page is None:
            new_page = (max(self.grids) + 1) if self.grids else 0
            if new_page >= MAX_STASH_PAGES:
                raise StashError("储物箱已满（%d 页且都没有空位）" % len(self.grids))
            self.grids[new_page] = [[0] * STASH_GRID_W for _ in range(STASH_GRID_H)]
            target_page = new_page
            slot = (0, 0)

        x, y = slot
        index = len(self.records)
        self.records.append(rec)
        self._occupy(target_page, x, y, w, h, index + 1)

        if fix_position:
            anchor = struct.pack("<ii", x, y + h - 1)
            cur = self.records[index]
            self.records[index] = cur[:OFF_POSITION] + anchor + cur[OFF_POSITION + 8:]

        return (target_page, x, y)

    def remove_record(self, index: int, prune_empty_pages: bool = True) -> bytes:
        """删掉 ``records[index]``，清掉它的格子并把更大的下标前移一位。

        与游戏 ``StashStruct::RemoveStashItem()`` 语义一致（下标紧凑）。
        ``prune_empty_pages=True`` 时顺手回收变空的页（游戏的 ``SaveStash()``
        本来也不保存空页），这样“加一件再删掉”能恢复成与原来完全一致的字节。
        返回被删掉的记录。
        """
        n = len(self.records)
        if not (0 <= index < n):
            raise StashError("记录下标越界：%d（共 %d 条）" % (index, n))

        removed = self.records.pop(index)
        cell = index + 1

        def remap(value: int) -> int:
            if value == cell:
                return 0
            if value > cell:
                return value - 1
            return value

        self._remap_cells(remap)

        if prune_empty_pages:
            empty = [p for p, g in self.grids.items() if not any(any(row) for row in g)]
            for p in empty:
                del self.grids[p]

        return removed

    # -- 写盘 -------------------------------------------------------------- #

    def _build_block_data(self, encoded: bytes) -> tuple[bytes, int]:
        """把 codec 密文包成 MPQ 块数据，返回 (block_data, flags)。"""
        if self.write_mode == WRITE_MODE_UNCOMPRESSED:
            # 未压缩、无扇区偏移表、无 IMPLODE
            return encoded, MPQ_FILE_EXISTS

        if self.write_mode == WRITE_MODE_IMPLODE_RAW:
            # 正确的扇区偏移表 + 每扇区原样存储（span == expect）。
            # 注意 sector_size 必须按 header offset 14 的 shift 计算，
            # 即 512 << shift（真实存档 shift=3 → 4096）。原修改器 bug 就是把它当成了 0。
            sector_size = self._header["sector_size"]
            nsec = (len(encoded) + sector_size - 1) // sector_size
            table = [0] * (nsec + 1)
            body = bytearray()
            cursor = (nsec + 1) * 4
            for s in range(nsec):
                table[s] = cursor
                chunk = encoded[s * sector_size:(s + 1) * sector_size]
                body += chunk
                cursor += len(chunk)
            table[nsec] = cursor
            blob = struct.pack("<%dI" % (nsec + 1), *table) + bytes(body)
            return blob, MPQ_FILE_EXISTS | MPQ_FILE_IMPLODE

        raise StashError("未知写盘方式 %r" % (self.write_mode,))  # pragma: no cover

    def _build_file_bytes(self) -> bytes:
        """生成完整的 ``stash.sv`` 字节串（不改动磁盘）。"""
        d1codec = _d1codec()
        d1mpq = _d1mpq()

        payload = self._build_payload()
        encoded = bytes(d1codec.codec_encode(payload, self.password))
        block_data, new_flags = self._build_block_data(encoded)

        h = self._header
        raw = self._raw
        block_cnt = h["block_cnt"]
        hash_cnt = h["hash_cnt"]
        block_off = h["block_off"]
        bidx = self._block_index

        block_table = bytearray(self._block_table)
        off, csize, usize, old_flags = _read_block_entry(block_table, bidx)
        if old_flags & (MPQ_FILE_ENCRYPTED | MPQ_FILE_FIX_KEY):
            raise MPQError("原块带 ENCRYPTED/FIX_KEY，本库不支持改写（stash.sv 不会这样）")

        used = [
            i for i in range(block_cnt)
            if _read_block_entry(block_table, i)[3] & MPQ_FILE_EXISTS
        ]

        # 表区之后就是文件数据区；如果只有我们这一个文件，可以重建（丢掉旧压缩块），
        # 否则保留原文件并追加，绝不破坏其它块的数据。
        data_start = max(
            MPQ_HEADER_SIZE,
            h["hash_off"] + hash_cnt * 16,
            block_off + block_cnt * 16,
        )
        if used == [bidx] and data_start <= len(raw):
            base = raw[:data_start]
        else:
            base = raw

        new_off = _align16(len(base))
        new_raw = bytearray(base)
        if new_off > len(new_raw):
            new_raw += b"\x00" * (new_off - len(new_raw))
        new_raw += block_data

        # compressed_size / uncompressed_size 都必须是 **codec 编码后** 的长度：
        # 游戏 ReadArchive() 读这么多个字节后再 codec_decode，
        # 把解码后的长度交给 IsStashSizeValid()。
        _write_block_entry(block_table, bidx, new_off, len(block_data), len(encoded), new_flags)

        # 块表重新加密写回（哈希表不动，block index 不变）
        k_block = d1mpq.hash_string("(block table)", HASH_FILE_KEY)
        enc_block_table = bytes(d1mpq.encrypt_block(bytes(block_table), k_block))
        if len(enc_block_table) != block_cnt * 16:  # pragma: no cover
            raise MPQError("块表加密后长度异常")
        new_raw[block_off:block_off + block_cnt * 16] = enc_block_table

        # header.archive_size (offset 8)
        struct.pack_into("<I", new_raw, 8, len(new_raw))

        return bytes(new_raw)

    def save(self, out_path: str | None = None, backup: bool = True) -> str:
        """写回磁盘，返回实际写入路径。

        ``out_path`` 为空时写回 ``self.path``。``backup=True``（默认）时先把
        目标文件复制成 ``<target>.bak``。
        """
        target = os.path.abspath(out_path) if out_path else self.path
        data = self._build_file_bytes()

        if backup and os.path.isfile(target):
            try:
                import shutil
                shutil.copy2(target, target + ".bak")
            except OSError as exc:  # pragma: no cover
                raise StashError("备份失败：%s" % exc) from exc

        tmp = target + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

        # 刷新 MPQ 层状态（逻辑字段保持不变，避免让调用方持有的引用失效）
        self.path = target
        self._load_archive_reuse(data)
        return target

    def _load_archive_reuse(self, raw: bytes):
        """只刷新 MPQ 外壳状态（records/grids/gold 保持调用方手里的对象）。"""
        try:
            self._load_tables(raw)
        except MPQError as exc:  # pragma: no cover - 我们自己刚写的文件
            raise MPQError("写盘后重新解析失败（内部错误）：%s" % exc) from exc

    # -- 自检 -------------------------------------------------------------- #

    def verify_roundtrip(self) -> bool:
        """把当前状态写成临时文件、重新打开并逐项比对，返回是否完全一致。"""
        import tempfile

        payload = self._build_payload()
        data = self._build_file_bytes()

        fd, tmp = tempfile.mkstemp(suffix=".sv", prefix="d1stash_verify_")
        os.close(fd)
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            other = Stash(tmp, multiplayer=self.multiplayer, write_mode=self.write_mode)
            ok = (
                other.gold == self.gold
                and other.version == self.version
                and other.current_page == self.current_page
                and other.tail == self.tail
                and other.pages() == self.pages()
                and other.records == self.records
                and other.grids == self.grids
                and other._build_payload() == payload
            )
            return bool(ok)
        finally:
            try:
                os.unlink(tmp)
            except OSError:  # pragma: no cover
                pass


def load_stash(path: str, multiplayer: bool = False) -> Stash:
    """``Stash(path, multiplayer)`` 的便捷写法。"""
    return Stash(path, multiplayer=multiplayer)
