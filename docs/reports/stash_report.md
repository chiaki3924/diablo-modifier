# 储物箱核心（stash-core）报告：改金币清空物品 bug 的根因、修法、测试与风险

> 交付物：`work/lib/d1stash2.py`、`work/tests/test_stash.py`、本文。
> 基准存档：`work/backup_saves/stash.sv`（90346 字节，96 件物品，gold=313108）。
> 真实存档目录 `%APPDATA%\diasurgical\devilution\` **全程只读**（见 §7 校验）。

---

## 1. 结论摘要

| 项目 | 结果 |
|---|---|
| 根因 | 已确认并**复现**：原 `d1save.StashFile.save()` 从 header offset **12**（`format_version`）读 `sector_size_shift`，应为 offset **14**。于是按 512 字节扇区写偏移表，块 flags 仍保留 `0x100`(IMPLODE)，游戏按 4096 读表 → 扇区解压失败 → `codec_decode` 失败 → `LoadStash()` 归零 → 箱子被清空 |
| 修法 | 按简报 §2.4 写**完全未压缩**块：`flags=0x80000000`、无扇区偏移表、`csize=usize=len(codec 密文)`；重加密回写块表、更新 `header.archive_size`、数据 16 字节对齐追加、哈希表不动 |
| 改金币 | ✔ gold 变化、**96 条 368 字节记录逐字节完全一致**、10 页/100 格完全一致、`currentPage` 不变 |
| 加物品 | ✔ `add_record` 按 `d1items.ITEM_SIZE[runtime_idx]` 找空位（支持多格、优先低页号、满则新建 `max(page)+1`），存盘重开记录数 +1 且新记录保真；`remove_record` 后能**逐字节回到原文件** |
| 自测 | `_py312\python.exe work\tests\test_stash.py` → **14 tests, OK**（4.4 s） |
| 遗留风险 | ① 未做游戏内加载验证（需 game-verify）；② 原修改器读取器读不了未压缩块（已证明是**它的**读取器 bug，见 §5.4）；③ 物品 `position` 字段必须修正（已默认处理，见 §6.2） |

---

## 2. 存档格式的实测事实（与简报一致，含新发现）

### 2.1 MPQ 外壳（真实 `stash.sv`）

```
signature           0x1A51504D ("MPQ\x1a")
header_size         32
archive_size        90346            (offset 8)
format_version      0                (offset 12)
sector_size_shift   3                (offset 14)  -> 512<<3 = 4096
hash_table_offset   32872
block_table_offset  104
hash_table_count    2048
block_table_count   2048
```

注意布局是「header(32) + 72 字节填充 → 块表(104) → 哈希表(32872) → 数据(65640)」，
即 **block 表在前、hash 表在后**，和 mpqfs 写入器的顺序相反，必须按 header 里的偏移读。

块表只有一项：

```
block[0] offset=65640  compressed_size=24706  file_size=37448  flags=0x80000100 (EXISTS|IMPLODE)
name = "spstashitems"，hash 槽位 845
```

### 2.2 关键：`file_size` 是 **codec 编码后** 的长度，不是 payload 长度

- payload（解密后）= **37385** 字节 = `1 + 4 + 4 + (4+200)*10 + 4 + 368*96 + 4`。
- codec 参数（`d1codec.BlockSize=16`、`BlockSizeBytes=64`、`SignatureSize=8`）：
  `codec_get_encoded_len(37385) = 37448`（37385 补齐到 64 的倍数 37440，再加 8 字节签名）。
- 游戏 `ReadArchive()` 读入 MPQ 块（37448 字节）后 `codec_decode()`，
  把**解码后长度 37385** 交给 `IsStashSizeValid()`（`loadsave.cpp:2298`）。
  所以块表里 `compressed_size == uncompressed_size == 37448` 才是对的。

### 2.3 payload 结构（实测解析，无未知尾部）

```
version      = 0
gold         = 313108
pageCount    = 10
pages        = 0,1,2,3,6,7,8,9,10,11   （按此顺序存放在文件里）
itemCount    = 96
currentPage  = 2
tail         = 空
```

96 条记录全部被网格引用且各引用一次（下标 0..95 无缺无重）。

### 2.4 网格落盘顺序是「x 在外、y 在内」（本次实测确认，很重要）

`Source/qol/stash.h`：

```cpp
using StashGrid = std::array<std::array<StashCell, 10>, 10>;   // [x][y]
```

`LoadStash/SaveStash` 用 `for (auto &row : grid) for (cell : row)` 遍历，
所以 payload 里第 `i` 个 `u16` 对应 **`x = i / 10, y = i % 10`**。
对外暴露 `grids[page][y][x]`（行优先）时，换算必须写成：

```python
grid[y][x] = cells[x * 10 + y]
```

> **踩坑记录**：第一版实现写成了 `cells[y*10+x]`（等于把网格转置了）。
> 因为解析和写盘互为转置，**自己的 roundtrip 测试完全通过**，
> 险些带着这个 bug 交付。后来用「记录里的 `position` 锚点」做独立校验才发现：
> 96 件里有 1 件（记录 7，position=(0,1)）对不上。
> 现在 `test_01` 会直接读 payload 的 100 个 u16 做交叉断言，`test_05` 也会
> 检查 2x3 物品落盘的 6 个格位，防止再次被「自洽」掩盖。

### 2.5 物品尺寸与网格锚点（用真实 96 件物品全量验证）

- 尺寸 = `d1items.ITEM_SIZE[d1save.saved_to_runtime(记录 offset 360 的 idx)]`，值为 `(w, h)`
  （`w` 沿 x，`h` 沿 y）。例：saved 154 → runtime 159 → `Amulet (1,1)`；saved 1 → `Short Sword (1,3)`。
- 验证结果：**96/96** 件物品的占格都是精确的 `w×h` 矩形，尺寸与上表完全吻合。
- 锚点：记录的 `position`（offset 12/16）必须等于 **左下角** `(x, y + h - 1)`。
  `stash.cpp:383` `if (item.position != slot) continue;` —— 只有锚点那一格才会被绘制。
  **96/96 件真实物品都满足这个规律。**

---

## 3. 根因确认（可复现的数字）

对真实存档副本执行原来的保存路径：

```python
sf = d1save.StashFile(copy)        # gold=313108, item_count()=96
sf.gold = 400000
sf.save()                          # ← 有 bug 的 save
```

结果（`work/tests/test_stash.py::test_02` 断言）：

| 项目 | 修好前（原修改器） |
|---|---|
| 文件大小 | 90346 → 128100 |
| block[0] offset | 90352（16 字节对齐追加，旧块保留） |
| block[0] flags | `0x80000100` = EXISTS\|IMPLODE（**仍声明压缩**） |
| compressed_size / file_size | 37748 / 37448（csize 多出 300 = 75×4） |
| 扇区偏移表首项 | **300** = `(37448/512 + 1) * 4` ← 按 **512** 字节扇区算出来的 |
| 4096 字节扇区应有的首项 | **44** = `(10 + 1) * 4` |

游戏/正确读取器的反应：
- 我们的读取器：`MPQError: 扇区偏移表首项 300 != 44（扇区大小 4096）`。
- 原修改器自己的读取器：`d1pkware.PkwareError: 字典大小非法: 237`
  （它把首项 300 当成扇区边界，切出来的一段被当 PKWARE 流 explode）。
- 游戏侧（`mpq_stream.c:102`）：`compSize(512) != expect(4096)` → 走 `pk_explode_sector()`，
  数据不是合法 implode 流 → `MPQFS_ERR_DECOMPRESS_FAILED` → `codec_decode` 返回 0
  → `LoadStash()` 里 `IsStashSizeValid()`/`file.IsValid()` 失败 → `Stash = {}`
  → 玩家一开箱或退出，游戏把空箱写回 → **物品永久丢失**。

> 附带发现：原 `save()` 并不是「就地覆盖」，而是把新块**追加**到 16 字节对齐的
> 文件尾部（90346→90352），旧压缩块留在文件里。所以修它只需正确写新的块表项。

---

## 4. 修法（`work/lib/d1stash2.py`）

### 4.1 写盘（简报 §2.4 的「未压缩无表」写法）

```
flags             = 0x80000000                # 只有 EXISTS
block_data        = codec_encode(payload)     # 37448 字节，无扇区偏移表
compressed_size   = uncompressed_size = 37448
offset            = align16(表区末尾或文件末尾)
archive_size      = 新文件长度
```

实现要点：

- 复用原 `d1save`/`d1mpq`/`d1codec`/`d1items`/`d1pkware`（Python 3.12 动态加载 `.pyc`，
  不反编译），块表加密用 `d1mpq.encrypt_block(..., hash_string("(block table)", 3))`，
  哈希表读取用 `hash_string("(hash table)", 3)`。
- **哈希表完全不改**（block index 不变），所以 `find()` 逻辑不受影响。
- 块表在原偏移处重新加密写回，长度不变（2048×16）。
- 数据区：如果归档里只有我们这一个块（stash.sv 就是），就**重建**文件
  （`raw[:data_start]` + 16 字节对齐 + 新块），丢掉旧压缩块；
  若还有别的块则退化为「保留原文件 + 追加」，绝不破坏其它文件的数据。
- 写盘是「写 `.tmp` → `fsync` → `os.replace()`」的原子替换，默认先备份 `<target>.bak`。

### 4.2 `implode_raw` 备选写法（代码里保留，默认不启用）

`Stash(path, write_mode="implode_raw")` 会写「**正确的 4096 字节**扇区偏移表 + 每扇区原样存储 +
`flags=0x80000100`」。mpqfs 对 `span == expect` 的扇区直接 memcpy，所以游戏同样能读。

保留它的价值：**双读取器交叉验证**（见 §5.4），以及万一游戏内验证发现未压缩路径有问题时的
一行切换逃生门。默认仍是简报指定的 `uncompressed`。

---

## 5. 测试（`work/tests/test_stash.py`）

### 5.1 运行

```powershell
cd F:\Qoder\暗黑1重制版
$env:PYTHONIOENCODING='utf-8'
.\_py312\python.exe work\tests\test_stash.py
```

结果：

```
Ran 14 tests in 4.376s
OK
exit=0
```

所有用例都在 `work\tmp\test_stash_<pid>\` 里对 `work/backup_saves/stash.sv` 的**副本**操作，
结束后自动清理；`%APPDATA%` 一个字节都没有碰。

### 5.2 用例清单

| # | 用例 | 断言要点 |
|---|---|---|
| 00 | `read_mpqfs_style_on_real_file` | 独立实现的 mpqfs 规则读取器读出真实文件，结果 == `d1save.StashFile().data`（37385 字节） |
| 01 | `real_baseline` | 96 条 / gold 313108 / 页 `[0,1,2,3,6,7,8,9,10,11]` / currentPage 2 / 无尾部；96 件占格矩形+尺寸+锚点全对；payload 与原始逐字节相同；**直接按 `cells[x*10+y]` 交叉验证行列顺序**（含记录 7 落在 `cells[1]`） |
| 02 | `original_bug_repro` | 原 `save()` 表首项=300、flags 仍 IMPLODE；我们的读取器报 `300 != 44`；原读取器报 `PkwareError` |
| 03 | `gold_fix_roundtrip` | 改 gold→save→重开：gold=196607、96 条记录逐字节一致（sha 相同）、页/格一致、currentPage 不变；payload 只有 offset **1,2,3** 变了；mpqfs 规则读取器读回同一 payload；块 `flags=0x80000000`、`csize=usize=37448`、offset 16 字节对齐、`archive_size==文件长度`；源文件 sha/mtime 保持不变 |
| 04 | `original_reader_limitation_evidence` | 证明原读取器读不了未压缩块（见 §5.4），并反证 `implode_raw` 写法它能读 |
| 05 | `add_record_roundtrip` | 复制记录 1（2×3 Short Sword）→ `(page,x,y)=(0,3,0)`、position 改为 (3,2)；存盘重开 97 条、`records[:96]` 不变、`records[96]` 保真、gold 不变、页/格一致；**直接按 `(x+dx)*10+(y+dy)` 核对落盘格位**；`remove_record(96)` 后 payload 与原始**完全逐字节相同** |
| 06 | `add_record_byte_identical_without_position_fix` | `fix_position=False` 时新记录与源记录**逐字节完全一致** |
| 07 | `new_page_when_full` | 现有页满→新建 `max(page)+1`；指定页优先；指定页满顺延；100 页全满抛 `StashError`；新页能存盘重开 |
| 08 | `backup_and_inplace_save` | 默认写回自身时生成 `.bak` 且内容=保存前；`backup=False` 不覆盖已有 `.bak` |
| 09 | `verify_roundtrip_both_modes` | 两种写法的 `verify_roundtrip()` 都 True；存盘后 mpqfs 规则读取器一致；两种写法的 flags/尺寸符合预期 |
| 10 | `unknown_tail_preserved` | `currentPage` 之后追加 4 字节 → 存盘重开后原样保留、`size_valid=False`、`size_mismatch=4`；不截断 |
| 11 | `multiplayer_name` | 多人模式找 `mpstashitems`，单人物品箱里没有 → 构造时 `MPQError` |
| 12 | `errors` | 记录长度不对/下标越界/未知写盘方式都抛清晰异常，不会静默写坏文件 |
| 13 | `missing_file` | 文件不存在 → `FileNotFoundError` |

### 5.3 修复效果的关键数字（改金币）

| 项目 | 值 |
|---|---|
| 输入 | `stash.sv` 90346 字节，gold=313108，96 条，10 页，currentPage=2 |
| 输出 | 103096 字节，gold=**196607**，96 条，10 页，currentPage=2 |
| 块表 | `offset=65648`（16 对齐）、`csize=usize=37448`、`flags=0x80000000` |
| header | `archive_size=103096`、`sector_size_shift=3`、`hash_off=32872`、`block_off=104`（不变） |
| payload 差异 | 仅 offset 1..3（gold 3 个有效字节；高位字节本来就都是 0） |
| 记录 sha | 修改前后 `sha256(records 拼接)` 完全相同 |
| 页/格 | `grids` 字典完全相等 |

加物品：payload 37385 → **37753**（+368），文件 103416 字节，重开 97 条；
`remove_record` 后 payload **逐字节等于原始 37385 字节**。

### 5.4 为什么原 `d1save.StashFile` 读不了我们保存的文件（证明是它的读取器限制）

这是任务里明确要求说明的一点，已用字节码 + 数据比对证实：

1. 反汇编 `d1mpq.MPQArchive.read_file` 可见未压缩分支（字节码行 363）：

   ```python
   body = raw[nsectors * 4:]      # 无条件把前 nsectors*4 字节当成“扇区偏移表”丢掉
   ...
   return body[:size]
   ```

   它假设「到了这个分支也一定存在扇区偏移表」，于是从**数据开头**多砍了
   `nsectors*4` 字节。我们的块是 37448 字节 @4096 → 10 个扇区 → 多砍 **40** 字节。

2. 实测证据（`test_04` 断言）：
   - `MPQArchive.read_raw(0)` 返回的块数据是**完整**的 37448 字节，且与
     `codec_encode(payload)` 逐字节相同（→ 文件里的块本身没问题）；
   - `MPQArchive.read_file("spstashitems")` 返回 **37408** 字节 = `37448 - 40`，
     且恰好等于 `codec_encode(payload)[40:]`；
   - 拿这 37408 字节去 `codec_decode` 必然失败（`(37408-8) % 64 = 24`，长度非法），
     于是 `StashFile.__init__` 报 `SaveError: stash 里没找到可读的储物箱内容`。

3. 反证（同一读取器、同一写入器）：
   - 原版 IMPLODE 文件它读得正常（96 条、gold 313108）；
   - 我们把它改成 `implode_raw` 写法（**正确的 4096 扇区表** + 原样扇区）后，
     `d1save.StashFile` 能读回 **gold=123456、96 条、payload 与我们逐字节相同**。
   ⇒ 说明我们写出的 MPQ 结构完全合法，只是它不支持「未压缩、无扇区表」这种块。

4. 游戏侧支持未压缩块，依据：
   - `mpq_stream.c:236-262` 的 `else` 分支就是「未压缩、多扇区、无偏移表」，
     直接 `fileAbs + sectorIdx * sector_size` 顺序读取；
   - `mpq_writer.c:354-369`：当没有任何扇区压缩有收益时，写入器**就是**产出
     `flags = MPQ_FILE_EXISTS`、无偏移表、`csize == file_size` 的块；
   - mpqfs 自己的单测 `tests/test_mpqfs.c` 覆盖了这两种情况：
     `TestSyntheticMpq`（手工构造未压缩文件并 `mpqfs_read_file` 读回）和
     `TestWriterCompression`（"Incompressible data is stored raw (no IMPLODE flag)"）。

---

## 6. 给 GUI / itemgen 的接口说明（务必按此对接）

### 6.1 接口（与简报 §6 一致，另有少量兼容扩展）

```python
from d1stash2 import Stash

s = Stash(path, multiplayer=False, write_mode="uncompressed")
s.gold                      # int，可直接赋值
s.records                   # list[bytes]，每项 368 字节，下标 = stashList 下标
s.grids                     # dict[page] -> list[list[int]]，grid[y][x]，cell = itemIndex+1
s.current_page              # currentPage
s.pages()                   # 升序页号
s.item_count()              # len(records)
s.add_record(rec, page=None, fix_position=True)  -> (page, x, y)
s.remove_record(index, prune_empty_pages=True)   -> bytes
s.save(out_path=None, backup=True)               -> 实际写入路径
s.verify_roundtrip()        -> bool
Stash.record_size(rec)      -> (w, h)     # 静态方法，itemgen 可用来校验
Stash.record_saved_index(rec) / record_runtime_index(rec)
```

- `add_record`：按 `w×h` 在**已有页**按页号升序找空位（行优先扫描）；`page=` 指定时优先该页，
  满了顺延；全满则新建 `max(page)+1`（≥100 抛 `StashError`）。不改 `gold`。
- `save()` 成功后会**把 `self.path` 更新为实际写入路径**（之后 `save()` 默认写那个文件）。
- `save()` 默认生成 `<target>.bak`（覆盖式，只保留一份）。
- `write_mode`：默认 `"uncompressed"`（简报指定）；`"implode_raw"` 是兼容备选（见 §4.2）。

### 6.2 两个必须知道的坑

1. **`grids` 是 `grid[y][x]`（行优先），但文件里是 x 在外**。自己解析 payload 时别搞反。
2. **`position` 字段必须改成左下角锚点 `(x, y + h - 1)`**。
   `add_record` 默认 `fix_position=True` 会做这件事；**不要传 False**，
   否则物品在游戏里不会被绘制（`DrawStash` 只在 `item.position` 那一格画）。
   如果确实需要「记录逐字节原样」，用 `fix_position=False` 并自行承担不可见的风险。

---

## 7. 遗留风险与后续建议

| 风险 | 说明 | 建议 |
|---|---|---|
| **未做游戏内验证（最高优先级）** | 单元测试只证明「按 mpqfs 源码规则能读回」。未启动 `devilutionx.exe` 实测 | 由 game-verify 用现成样机做：`work\tmp\stash_gold400000.sv`（未压缩）与 `work\tmp\stash_gold400000_implode.sv`（兼容写法）。放进 `%APPDATA%\diasurgical\devilution\`（先备份！）后开箱看金币与 96 件物品 |
| 未压缩块是游戏的「冷路径」 | 真实存档里所有块都是 IMPLODE（数据可压缩），所以游戏从没在真存档里走过未压缩分支。代码明确支持（§5.4），但缺少实战样本 | 若游戏内验证异常，一行切换 `write_mode="implode_raw"`（已被原读取器+我们两个读取器验证） |
| 原修改器读取器读不了新文件 | 是**它的** bug（§5.4）。GUI 若还要用 `d1save` 读自己写的 stash 会报 `SaveError` | GUI 统一用 `d1stash2.Stash` 读；`d1save` 只用于角色存档（`SaveFile`） |
| 多人存档未实测 | 只验证了 `multiplayer=True` 会去找 `mpstashitems`（当前没有该文件）。多人存档口令是 `szqnlsk1`，逻辑一致 | 有 `mpstashitems` 样本时再补一条测试 |
| Hellfire（`.hsv` / 372 字节记录）不支持 | 本库固定 368 字节记录、`IsStashSizeValid` 公式按非 Hellfire。物品编号映射 saved 156+ 也非双射（`ITEM_SIZE` 只到 runtime 168） | 明确不支持；需要时另开分支 |
| 空页会被回收 | `remove_record` 默认 `prune_empty_pages=True`（游戏的 `SaveStash` 本来也不保存空页）。若调用方手工塞了「空的占位页」，删除操作会把它清掉 | 需要保留空页时传 `prune_empty_pages=False` |
| 文件会变大 | 未压缩写法 37448 字节 vs 原压缩 24706；改一次金币后文件 90346 → 103096 | 可接受（存档本来就 ~90KB）。若在意，可后续接入 PKWARE implode 压缩（mpqfs 有 `pk_implode_sector`，但 pyc 里没有对应实现） |
| 反复保存 | 单文件归档走「重建」，不会累积垃圾；多文件归档走「追加」，会保留旧块 | 目前 stash.sv 只有 1 个文件 |

### 7.1 真实存档只读校验（本次已做）

```
stash.sv    real=4E4648DF1998 backup=4E4648DF1998 same=True
single_0.sv real=6B6A8FBF738E backup=6B6A8FBF738E same=True
single_1.sv real=2DEE3F41B990 backup=2DEE3F41B990 same=True
single_2.sv real=1C172A2E14F3 backup=1C172A2E14F3 same=True
diablo.ini  real=5DBDF2192DE3 backup=5DBDF2192DE3 same=True
```

---

## 8. 参考（源码定位）

| 内容 | 位置 |
|---|---|
| stash payload 读写、`IsStashSizeValid` | `DevilutionX-1.5.5\Source\loadsave.cpp:1966`、`:2265`、`:2547` |
| `stashGrids` 类型与 `grid[x][y]` 访问 | `DevilutionX-1.5.5\Source\qol\stash.h:20,47` |
| 落盘遍历顺序、`position` 锚点、放置扫描 | `DevilutionX-1.5.5\Source\qol\stash.cpp:70,383,711-727` |
| 物品尺寸 `GetInventorySize` | `DevilutionX-1.5.5\Source\inv.cpp:2150`、`cursor.cpp:168` |
| codec 编码长度/解码返回值 | `DevilutionX-1.5.5\Source\codec.cpp:92-135`、`loadsave.cpp:568`（`ReadArchive`） |
| MPQ 读取（未压缩分支） | `mpqfs-...\src\mpq_stream.c:236-262` |
| MPQ 写入（无收益则原样存） | `mpqfs-...\src\mpq_writer.c:354-369` |
| 未压缩块的单测 | `mpqfs-...\tests\test_mpqfs.c:456`、`:1220` |

---

## 9. 样机文件（给 game-verify）

`work\tmp\` 下（由 `work\tmp\make_samples.py` 生成，可重复生成）：

| 文件 | 写法 | 大小 | 内容 |
|---|---|---|---|
| `stash_gold400000.sv` | uncompressed（默认） | 103096 | gold=400000，96 件，10 页 |
| `stash_gold400000_implode.sv` | implode_raw（备选） | 103140 | gold=400000，96 件，10 页 |

两者都已用本库 + （后者）原 `d1save` 双读取器验证；`records`/`grids` 与真实存档完全一致。
