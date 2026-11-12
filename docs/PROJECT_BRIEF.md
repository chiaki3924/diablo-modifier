# 项目简报：暗黑破坏神1（DevilutionX 1.5.5）存档修改器修复 + 合规装备生成

> 本文件是给子代理的总简报。请先完整读完再动手。所有路径均已在本机验证。
> 工作区根：`F:\Qoder\暗黑1重制版`（下称 ROOT）

## 0. 用户诉求（原文要点）

1. 现有修改器改「角色公用储物箱金币」时，会把储物箱里其他所有物品清空。要修好。
2. 希望能自由生成带各种词条的装备，且生成物要「合规」（符合游戏规则、不会坏档、不会被游戏判非法删除）。
3. 用户外出，尽量少让他做选择；给最高权限；多用子代理；子代理用与本会话相同的 DeepSeek 官方模型（provider `deepseek-account`，model `deepseek-flash`）。主会话只做总指挥。

## 1. 环境与关键路径

| 用途 | 路径 |
|---|---|
| 游戏本体（已汉化，DevilutionX **1.5.5**） | `ROOT\暗黑破坏神1重构游戏本体和修改器\devilutionx\` |
| 游戏 exe | 上述目录下 `devilutionx.exe`（版本字符串 1.5.5） |
| 真实存档目录 | `C:\Users\39247\AppData\Roaming\diasurgical\devilution\` |
| 真实存档 | `single_0.sv`、`single_1.sv`、`single_2.sv`、`stash.sv`、`diablo.ini` |
| **存档备份（只读，绝对不要改）** | `ROOT\work\backup_saves\` |
| 原修改器 exe | `ROOT\暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-by蓝色大肥鱼.exe` |
| 原修改器解包目录 | `ROOT\暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted\` |
| 原修改器 pyc 模块 | 上述目录 `PYZ.pyz_extracted\d1save.pyc`、`d1mpq.pyc`、`d1codec.pyc`、`d1rng.pyc`、`d1items.pyc`、`d1spells.pyc`；主程序 `d1save_editor.pyc` |
| Python 3.12（可跑上述 3.12 pyc） | `ROOT\_py312\python.exe`（3.12.10 embeddable） |
| 系统 Python 3.15 | `python`（PATH 中，不能 unmarshal 3.12 pyc） |
| DevilutionX **1.5.5** 完整源码 | `ROOT\DevilutionX-1.5.5\`（从 GitHub tag 1.5.5 下载，权威） |
| DevilutionX 1.6.0-dev 源码（参考） | `ROOT\devilutionX\`（sparse checkout，含 `assets/txtdata`） |
| mpqfs 源码（游戏 MPQ 读写实现，权威） | `ROOT\mpqfs-1dc2407a9cd97eb7aaf8a0c184c70436871b7e5a\` |
| 工作目录 | `ROOT\work\`（lib/app/tests/docs） |

注意：真实存档只能复制到 `work\` 下的临时路径做实验。**不要直接写 `%APPDATA%` 里的文件**，除非最终交付阶段明确要应用到用户存档（届时先再备份）。

## 2. 已确诊的 bug（储物箱金币导致物品清空）

### 2.1 存档/储物箱格式（1.5.5）

`stash.sv` 是 MPQ v1 档案，里面通常只有一个文件：`spstashitems`（单人）或 `mpstashitems`（多人）。文件内容再套一层 Diablo codec 加密（口令：单人 `xrgyrkj1`，多人 `szqnlsk1`；spawn 另有口令）。解密后格式（`Source/loadsave.cpp` `LoadStash/SaveStash`）：

```
u8   version (0)
u32  gold                      <- 只改这里
u32  pageCount
  pageCount × { u32 page; u16 cells[100] }   // 10x10，cell = itemIndex+1，0 为空
u32  itemCount
  itemCount × 368 字节 Item 记录
u32  currentPage
```

真实 `stash.sv`（2026-11-11）：`gold=313108`，10 页（页号 0,1,2,3,6,7,8,9,10,11），96 件物品。

### 2.2 MPQ 写入规则（游戏侧，见 mpqfs `src/mpq_writer.c`）

- 文件数据若**有任一分区压缩**：块 flags = `0x80000000|0x100`（EXISTS|IMPLODE），数据 = 扇区偏移表 + 各扇区（可压缩或原样）。扇区大小 = `512 << sector_size_shift`，游戏写的是 shift=3 → **4096 字节**。
- 文件若**没有任何分区值得压缩**：块 flags = `0x80000000`（仅 EXISTS），数据 = **原始字节，没有扇区偏移表**，`compressed_size == uncompressed_size == 文件长度`。
- 读取侧（`mpqfs/src/mpq_stream.c`）：只有 flags 含 IMPLODE/COMPRESS 才读扇区表；每扇区 `span == 期望解压长度` 时按原样拷贝，否则 PKWARE explode。

### 2.3 根因

原修改器 `d1save.StashFile.save()`（pyc 行 1565 起）在重建 MPQ 时：

- 从 `raw[12]` 读 `<H` 再 `512 << x` 计算扇区大小 —— **偏移错了**。header 里 `sector_size_shift` 在 **offset 14**，offset 12 是 `format_version`（0）。所以它算出扇区大小 = 512，而不是 4096。
- 于是它写出的扇区偏移表是 512 字节一格的（74 个扇区），但 flags 仍保留 `0x100`（IMPLODE），`uncompressed_size=37448`。游戏按 4096 扇区读表：第 0 扇区 span=512 ≠ 4096，于是把原始数据当 PKWARE 压缩流去 explode → 失败/乱码。
- `LoadStash()` 里 `IsStashSizeValid` 或 codec 校验失败 → `Stash = {}` → 游戏内储物箱显示空；玩家一开箱/退出，游戏把空箱写回，物品永久丢失。

原修改器自己的 `d1mpq` 读取器也不支持“IMPLODE 但扇区原样存储”，所以连它自己保存后的文件都读不回来（实测 `d1pkware.PkwareError: 字典大小非法: 45`）。

### 2.4 正确修法（推荐，最简单且 100% 合法）

写**未压缩**文件：

```python
flags = 0x80000000              # EXISTS，无 IMPLODE/COMPRESS
block_data = payload            # 不加扇区偏移表
compressed_size = uncompressed_size = len(payload)
```

并更新块表（加密写回）、header 的 archive_size（offset 8）、按 16 字节对齐追加数据。不要改哈希表（block index 不变）。这符合 mpqfs 写入器“压缩无收益时原样存”的分支。

> 备选：修正 offset 14 后保留现有“扇区表 + 原样扇区 + IMPLODE”写法，游戏也能读（mpqfs 支持 span==expect 的原样扇区），但原修改器的读取器读不了，且更容易出错。**统一用未压缩无表写法。**

### 2.5 角色存档的 `_stage` 是否也有 bug？

`SaveFile._stage()` 实测写出的 game 块：`csize=76376, usize=76296, flags=0x80000100`，80 字节表 = 20 项 ×4 → 扇区 4096，正确。角色存档往返可读。暂不动它，但**必须做游戏内加载验证**（见 §5）。

## 3. 原修改器 pyc 模块的可用 API（黑盒复用）

用 Python 3.12 从 `PYZ.pyz_extracted` 动态加载即可，不必反编译。`d1save` 暴露：

- `ItemPack`：19 字节紧凑物品（PlayerPack 内背包/装备/腰带用），属性 `idx/seed/create_info/bId/identified/magical/durability/...`，`idx` setter 接受运行时编号并自动转存档编号。
- `HeroPack`：1266 字节 PlayerPack。属性 `level/hero_class/name/gold/...`；方法 `set_level(lvl, exp=None)`、`set_stats(...)`、`set_experience`、`set_gold(amount, make_piles=True)`、`learn_spells`、`bump_all_spell_levels`、`forget_all_spells`、`inventory_slots()`、`rebuild_inv_grid()`、`add_item(idx, seed=0, create_info=0, value=0)`（加到背包，idx 为运行时编号）、`add_spell_book(...)`、`to_bytes()`。
- `SaveFile(path)`：属性 `pack`（HeroPack）、`raw/block_table/...`；方法 `save(out_path=None, backup=True, sync_game=False, clear_progress=False, drop_heroitems=False)`；`_find_block(name)`。实测 `pack.set_level(30)` 后 `save()` 再打开可读回。
- `StashFile(path, multiplayer=False)`：`gold` 属性（getter/setter，setter 只写 data[1:5]）、`item_count()`、`save()`。**save 有上述 bug，必须替换。**
- `d1codec.codec_encode(data, password)` / `codec_decode(data, password)`；`d1mpq.crypt_block(data, key)` / `hash_string(name, type)`；常量 `FLAG_EXISTS=0x80000000` 等。
- `d1items.ITEM_NAMES` / `ITEM_SIZE`（运行时编号索引）；`d1rng` 是游戏同款 RNG。

实测（Python 3.12）：
```python
sf = d1save.SaveFile(path); sf.pack.name  # 剑来
sf.pack.level  # 24
sf.pack.set_level(30); sf.save(backup=False)
sf2 = d1save.SaveFile(path); sf2.pack.level  # 30
```

## 4. 物品生成（任务 2）的核心资料

### 4.1 存档里的物品记录 = 368 字节（非 Hellfire），字段顺序严格按 `DevilutionX-1.5.5\Source\loadsave.cpp:1042 SaveItem()`

已按该顺序核对出的偏移（小端；名字字段各 **64** 字节，1.5.5 与 1.6.0 不同！1.6.0 改成 32）：

```
0    u32 iSeed
4    i16 iCreateInfo
6    pad2
8    i32 iType
12   i32 position.x
16   i32 position.y
20   u32 animFlag
24   pad4
28   i32 numFrames
32   i32 currentFrame
36   i32 animWidth
40   i32 animWidth2
44   pad4
48   u8  selFlag (+3 pad)
52   u32 postDraw
56   u32 identified
60   i8  magical
61   char name[64]
125  char iName[64]
189  i8  loc
190  u8  class
191  pad1
192  i32 curs
196  i32 ivalue
200  i32 iIvalue
204  i32 minDam
208  i32 maxDam
212  i32 AC
216  u32 flags
220  i32 miscId
224  i32 spell
228  i32 charges
232  i32 maxCharges
236  i32 durability
240  i32 maxDur
244  i32 PLDam
248  i32 PLToHit
252  i32 PLAC
256  i32 PLStr
260  i32 PLMag
264  i32 PLDex
268  i32 PLVit
272  i32 PLFR
276  i32 PLLR
280  i32 PLMR
284  i32 PLMana
288  i32 PLHP
292  i32 PLDamMod
296  i32 PLGetHit
300  i32 PLLight
304  i8  SplLvlAdd
305  i8  Request
306  pad2
308  i32 Uid
312  i32 FMinDam
316  i32 FMaxDam
320  i32 LMinDam
324  i32 LMaxDam
328  i32 PLEnAc
332  i8  PrePower
333  i8  SufPower
334  pad2
336  i32 VAdd1
340  i32 VMult1
344  i32 VAdd2
348  i32 VMult2
352  i8  MinStr
353  u8  MinMag
354  i8  MinDex
355  pad1
356  u32 StatFlag
360  i32 idx          // 存档编号（Diablo 映射号）
364  u32 dwBuff
= 368
```

已从真实 stash 解出示例：`idx=154` 的 Amulet，`name=b'Amulet'`、`iName=b'Gold Amulet'`、`magical=1`、`pre=0`、`VAdd1=3000`、`VMult1=9`。物品名是**英文**存盘（现有存档如此），显示由游戏处理。

`iCreateInfo` 语义、`PrePower/SufPower`、`VAdd/VMult` 的取值规则见 `items.cpp` 的 `SetupAllItems/GetItemAttrs/GetItemBonus/GetItemPower/SaveItemAffix/PLVal`。`idx` 是 `RemapItemIdxToDiablo` 后的存档编号，`d1save.runtime_to_saved/saved_to_runtime` 可互转。

### 4.2 游戏生成流程（1.5.5，非 Hellfire）

- `SetupAllItems`（items.cpp:1529）：`_iSeed=iseed; SetRndSeed(iseed); GetItemAttrs(item, idx, lvl/2); _iCreateInfo=lvl;` 然后 `CheckUnique` / `GetItemBonus` / `GetUniqueItem` / `ItemRndDur`。
- `GetItemAttrs`（items.cpp:3163）：基础伤害/AC/需求/耐久/价值/名称；`iMinAC + rnd(iMaxAC-iMinAC+1)` 用 RNG。
- `GetItemBonus`（items.cpp:1345）：按 `_iCreateInfo` 的标志决定词缀数量/等级区间，调用 `GetItemPower` 选前缀/后缀，再 `SaveItemAffix` 应用数值。
- 词缀表：`ROOT\devilutionX\assets\txtdata\items\item_prefixes.tsv` / `item_suffixes.tsv` / `unique_itemdat.tsv` / `itemdat.tsv`（1.6.0 的 assets，数值大概率与 1.5.5 一致；**必须用真实存档的 96 件物品做回归校验**，不一致再想办法取游戏 MPQ 里的表）。
- 1.5.5 源码里 `GetItemAttrs/GetItemBonus/SetupAllItems` 可直接逐行对照移植。

### 4.3 「合规」定义（验收标准）

- 基础物品、词缀、暗金都来自游戏表；词缀适用于该物品类型（`PLStruct.itemType`/`AffixItemType`），物品等级/词缀等级满足游戏规则。
- 词缀数量不超过游戏允许（普通 0，魔法 1~2，暗金固定词条），数值在 `PLVal` 范围内。
- 需求（力量/敏捷/魔法）、耐久、价值等自洽；`_iStatFlag` 合理。
- 生成的 368 字节记录能被游戏读入且**不会触发 `RemoveInvalidItem` 删除**。
- 最终以“游戏内实际打开储物箱/背包看到物品”为准（见 §5）。

## 5. 验证要求（最重要，不能只看代码）

1. **回合制单元测试**：改金币前后，stash 的 96 条 368 字节记录逐字节相等；gold 改变；文件能被“mpqfs 规则读取器”读回；再被 `d1save.StashFile`（原读取器）读回也尽量通过（若原读取器不支持原样扇区，可只要求我们自己的读取器 + 游戏验证）。
2. **游戏内验证**：复制存档到临时目录/真实目录（先备份），启动 `devilutionx.exe`，用键鼠自动化或人工截图确认：
   - 载入角色正常，不弹“存档损坏/版本无效”；
   - 储物箱金币变化，且原有物品还在；
   - 生成的装备出现在储物箱，图标/名称/词条正常，可拾取/装备，保存退出再进仍在。
3. 任何会改动真实存档的测试，必须先备份，测试后恢复原样（最终交付时除外）。
4. 交付物：修好的修改器 exe（新名字，保留原版）、使用说明（中文）、源码、测试脚本、测试报告。

## 6. 子代理分工与文件所有权（避免冲突）

| 代理 | 负责 | 只写这些文件 |
|---|---|---|
| stash-core | 修正版 StashFile 写盘、stash 解析/加物品/网格布局、测试 | `work/lib/d1stash2.py`、`work/tests/test_stash*.py` |
| itemgen | 1.5.5 物品生成移植、词缀/暗金、合法性校验、368 字节序列化、测试 | `work/lib/d1itemgen.py`、`work/lib/d1tables.py`、`work/tests/test_itemgen*.py` |
| gui | 新修改器 GUI（tkinter，中文）、整合 core/itemgen、PyInstaller 打包 | `work/app/*`、`work/build/*` |
| game-verify | 游戏启动/截图/自动化验证脚本与报告 | `work/tests/game_*.py`、`work/docs/verify_*.md` |
| 总指挥（主会话） | 接口定义、集成、最终验收 | 其它 |

接口契约（先按此实现，允许向后兼容地扩展）：

```python
# work/lib/d1stash2.py
class Stash:
    def __init__(self, path: str, multiplayer: bool = False): ...
    gold: int
    records: list[bytes]          # 每项 368 字节
    grids: dict[int, list[list[int]]]  # page -> 10x10，cell = index+1
    def item_count(self) -> int: ...
    def add_record(self, record: bytes, page: int | None = None) -> tuple[int,int,int]: ...
        # 返回 (page, x, y)；自动找空位/新建页；不改 gold
    def save(self, out_path: str | None = None, backup: bool = True) -> str: ...
    def verify_roundtrip(self) -> bool: ...
```
```python
# work/lib/d1itemgen.py
@dataclass
class GenItem:
    record: bytes
    fields: dict
    def describe(self) -> str: ...
def base_items() -> list[dict]          # name, idx, type, size, ...
def eligible_affixes(base_idx, ilvl, kind='prefix'|'suffix') -> list[dict]
def generate(base_idx, ilvl, rarity='magic', seed=None, prefix=None, suffix=None, unique=None) -> GenItem
def validate(rec: bytes) -> list[str]   # 空列表 = 合规
def record_to_fields(rec: bytes) -> dict
def fields_to_record(f: dict) -> bytes
```

## 7. 常用命令

```powershell
# 用 3.12 跑脚本（重要：pyc 只认 3.12）
ROOT\_py312\python.exe work\tests\test_stash.py

# 动态加载原修改器模块
$env:PYTHONIOENCODING='utf-8'
```

```python
import importlib.util, sys, os
BASE = r"F:\Qoder\暗黑1重制版\暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted"
sys.path.insert(0, os.path.join(BASE, "PYZ.pyz_extracted"))
def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, "PYZ.pyz_extracted", name + ".pyc"))
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod); return mod
```

## 8. 已知坑/提醒

- **1.5.5 与 1.6.0 物品记录不同**：1.5.5 名称字段 64 字节，1.6.0 是 32 字节。必须用 1.5.5 的 SaveItem 顺序（本简报已给）。
- 游戏是 **1.5.5 非 Hellfire**（.sv，不是 .hsv），但 `dwBuff`/Hellfire 分支要保留判断。
- `stash.sv` 的 MPQ header：`hash_off` 可能小于 `block_off`（原版游戏存档是 block 表在前、hash 表在后），不要假设固定顺序，按 header 读。
- 真实存档的 `single_1.sv` 角色名是「剑来」，等级 24（测试时注意）。
- 改存档前先退出游戏；游戏运行时会持有内存状态并在退出时覆盖。
- 不要用系统 Python 3.15 去 load 3.12 pyc（magic 不匹配）。
- 原修改器 `StashFile` 的 setter 只写 `data[1:5]`，这本身没问题；问题只在 `save()` 的 MPQ 写法。
- 生成装备若写入储物箱，记录是 368 字节完整 Item；若写入角色背包，则 PlayerPack 里是 19 字节 ItemPack，另有 heroitems 的 368 字节副本，二者 seed 必须一致。**优先做储物箱**，简单且共享。
