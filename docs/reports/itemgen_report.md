# 装备生成移植报告（DevilutionX 1.5.5，非 Hellfire）

> 子代理：itemgen　｜　产出：`work/lib/d1tables.py`、`work/lib/d1itemgen.py`、`work/tests/test_itemgen.py`、本报告
> 权威源码：`DevilutionX-1.5.5/Source/{items.cpp,itemdat.cpp,itemdat.h,items.h,loadsave.cpp,spelldat.cpp,cursor.cpp,engine/random.cpp}`
> 真实样本：`work/backup_saves/stash.sv`（96 条 368 字节记录，只读，未修改）
> 测试命令：`F:\Qoder\暗黑1重制版\_py312\python.exe work\tests\test_itemgen.py`（当前 **15/15 通过**）

> **Round 2 变更（2026-11-11）**：`base_items()` 默认只返回 **74 条可生成的可装备底材**（排除 starter /
> unique_only / 金币药水卷轴书）；`generate()` 会对 starter 底材（含崩溃元凶 `IDI_SORCERER_DIABLO`）抛中文错误；
> 新增 `prefix_value`/`suffix_value` 数值搜索、`unique_detail()`、`affix_value_range()`；法杖默认只生成属性词缀法杖。
> **下文 §2.1/§2.2/§3.2 的旧签名/数字以 §15（Round 2）为准。**

---

## 1. 结论摘要

| 项目 | 结果 |
|---|---|
| 368 字节记录编解码 | 96/96 真实记录 **逐字节往返一致**（含名字字段 NUL 之后的垃圾字节） |
| 真实 stash 重放 `(idx, iSeed, iCreateInfo)` | 可重放 91 条（另 5 条是 NPC 货架物品，见 §8.3）：**90/91 全字段 100%**，仅 1 条 AC 差 2 |
| 96 条真实记录 `validate()` | **95/96 通过**（唯一失败是上一条的 AC 异常） |
| 随机魔法装备 | 100/100 `validate=[]`，耗时 0.03s |
| 自选词条（种子搜索） | 7 组指定前后缀全部成功且 `validate=[]`，单件 0.00–0.04s |
| 暗金 | 非 HF 可用 90 个，89 个成功生成（Bovine Plate 的底材被非 HF 排除），全部 `validate=[]` |
| 全底材压力测试 | 141 个可用底材 × 4 个 ilvl：308 件魔法 + 396 件普通全部合法，0 失败 |
| 游戏显示名一致性 | 37 条真实魔法物品 + 288 件生成魔法物品：游戏 `GetTranslatedItemNameMagical()` 重算出的名字与存档 `iName` **完全一致** |
| RNG | 与游戏同款 `d1rng.pyc` 在 300 seed × 20 次取值上完全一致 |
| 背包尺寸 | 96/96 真实物品在储物箱网格中的实际占格与表推导尺寸一致 |

---

## 2. 交付物与对外 API

### 2.1 `work/lib/d1tables.py`

纯数据层，全部从 1.5.5 源码解析（不是手抄）：

```python
base_items(include_unavailable=False, droppable_only=False) -> list[dict]
affix_list(kind)            # kind='prefix'|'suffix'
unique_list(include_unavailable=False)
spell_list()
base_by_idx(runtime_idx)    # AllItemsList 下标
base_by_saved_idx(saved_idx)# 存档里的 idx（经 RemapItemIdxFromDiablo）
base_by_name(name)          # 同名多条时优先 droppable/available
base_by_id("IDI_LONGSWR")
affix_by_index/affix_by_name
unique_by_id/unique_by_name/uniques_for_base(base_idx)
runtime_to_saved(idx) / saved_to_runtime(idx)   # RemapItemIdxToDiablo / FromDiablo
is_item_available(idx) / is_unique_available(uid)
item_size(idx_or_curs, is_curs=False)
compare_with_tsv()          # 与 1.6.0 TSV 的差异报告（供核对）
```

每个基础物品 dict 的关键字段：
`idx`(运行时)、`saved_idx`(存档)、`id`(IDI_* 符号名，可能为 None)、`name`/`sname`、
`itype`/`itype_name`、`class`、`loc`、`curs`、`drop_rate`、`min_mlvl`、`durability`、
`min_dam`/`max_dam`、`min_ac`/`max_ac`、`min_str`/`min_mag`/`min_dex`、`flags`、`misc_id`、
`spell`、`usable`、`value`、`width`/`height`/`size`、`affix_type`(AffixItemType 位)、
`anim_frames`、`unique_only`、`droppable`、`canonical`、`available`。

词缀 dict：`kind/index/name/power/power_name/param1/param2/min_level/item_types/
item_type_names/goe/goe_name/double/ok/min_val/max_val/mult_val/hellfire_only`。
暗金 dict：`index/name/base_item_id/base_item_id_name/min_level/num_powers/value/powers[6]`。
法术 dict：`index/name/book_cost/staff_cost/book_lvl/staff_lvl/min_int/staff_min/staff_max/magic_type`。

### 2.2 `work/lib/d1itemgen.py`

```python
@dataclass
class GenItem:
    record: bytes          # 368 字节，可直接交给 d1stash2.Stash.add_record()
    fields: dict           # 解码后的字段（JSON 友好，不含原始 name 缓冲）
    base: dict
    seed: int
    create_info: int
    rarity: 'normal'|'magic'|'unique'
    prefix: dict|None      # 选中的前缀（含 index/name/power/...）
    suffix: dict|None
    unique: dict|None
    def describe(self) -> str

base_items(include_unavailable=False) -> list[dict]      # 同 d1tables
eligible_affixes(base_idx, ilvl, kind='prefix', onlygood=False) -> list[dict]
generate(base_idx, ilvl=1, rarity='normal', seed=None, prefix=None, suffix=None,
         unique_id=None, max_tries=200000, strict=True, identified=True,
         stat_flag=True, position=(0,0), onlygood=False, hellfire=False,
         unique=None) -> GenItem | None
validate(rec, replay=True, hellfire=False) -> list[str]  # [] = 合规
record_to_fields(rec) -> dict
fields_to_record(fields) -> bytes
replay_item(rec_or_fields) -> GenItem
translated_item_name_magical(fields, hellfire=False) -> str|None
unique_base(unique) -> dict          # 暗金对应的底材
string_in_panel(text) -> bool        # StringInPanel 精确移植
line_width(text, spacing=2) -> int
Rng                                  # 游戏同款 LCG
```

`generate()` 语义（与主会话约定一致）：

* `seed` 给定 → 严格按该 seed 生成；`seed=None` → 随机 seed。
* 给了 `prefix`/`suffix` → **种子搜索**：从 `seed`（或随机起点）顺序试 seed，直到游戏自己的
  `GetItemPowerPrefixAndSuffix()` 正好选中该词缀，再用完整 `SetupAllItems` 流程生成整条记录。
  因此属性、名字、词缀天然自洽，游戏从 `iSeed+iCreateInfo` 重算的结果就是记录里的内容。
* `rarity='unique'` 时 `base_idx` 可以传 `None`，自动用暗金表对应的底材；也支持 `unique=` 别名。
* 失败默认抛 `ItemGenError`（带原因与可用词缀列表）；`strict=False` 返回 `None`。
* `ilvl` 就是 `SetupAllItems(..., lvl, ...)` 的 `lvl`，即 `iCreateInfo` 的低 6 位（0..63）。
  **游戏调用方一般传 `2 × 地牢层数`**（普通怪）/`curlv*2`（商店），所以 GUI 若用“地牢层数 N”
  应换算 `ilvl = min(2*N, 63)`。词缀窗口是 `[min(ilvl//2, 25), ilvl]`（`GetItemBonus` 会把
  minlvl 截到 25），这就是为什么 ilvl 30 的装备永远不会出 "Sharp"（1 级词缀）。
* `identified=1`（与真实储物箱一致）、`_iStatFlag=1` 是默认值；后者只是“需求是否满足”的缓存，
  游戏在拾取/移动物品时会用 `updateRequiredStatsCacheForPlayer()` 重算。

### 2.3 `work/tests/test_itemgen.py`

15 个测试（见 §9），全部真跑，不依赖 pytest。会读真实 `stash.sv`（只读），临时文件用完即删。

---

## 3. 数据来源：为什么用 1.5.5 源码而不是 1.6.0 的 TSV

### 3.1 关键发现

任务书原本建议用 `devilutionX/assets/txtdata/items/*.tsv`（1.6.0 assets）并“先当作与 1.5.5 一致”。
实测**不能**这样做：

| 物品 | 1.5.5 `itemdat.cpp` | 1.6.0 `itemdat.tsv` |
|---|---|---|
| Short Sword（droppable, runtime 119） | durability 24, value 120 | 24, 120（一致） |
| Buckler（runtime 71） | durability 16, minAC 1, maxAC 5, value 30 | 16, 1, 5, 30（一致） |
| Short Sword（starter, runtime 1） | **20, 50** | 24, 120（对应 droppable 版） |
| Potion of Healing | min_mlvl 0, value 50 | min_mlvl 1, value 50 |
| Book of | min_mlvl 2 | min_mlvl 8/14/… |

也就是说：**1.6.0 TSV 对应的是 droppable 版本**；1.5.5 的 `AllItemsList` 同时包含
starter/quest 版和 droppable 版，两者同名不同数值。`compare_with_tsv()` 在 141 个可匹配行上
发现 25 处字段差异（durability 4、minAC 1、maxAC 1、minMag 1、value 8、minMlvl 10）。
所以本实现以 **1.5.5 `itemdat.cpp`（`AllItemsList`/`ItemPrefixes`/`ItemSuffixes`/`UniqueItems`）
为唯一权威**；TSV 解析器仍保留，用于交叉核对与留证。

> 说明：1.6.0 TSV 仍然有价值——它与 droppable 版一致，可用于确认我们解析的 droppable 行没有跑偏。
> 但生成/校验绝不能用它。

### 3.2 `AllItemsList` 的行数与可用性（给 GUI 的准确数字）

| 统计 | 数字 |
|---|---|
| `AllItemsList` 总行数（含 Hellfire/哨兵） | 169 |
| 非 Hellfire 可用（`IsItemAvailable` + 可写入存档） | **141** |
| 其中 `IDROP_NEVER`（starter/任务，游戏不会随机掉落） | 34 |
| 其中 droppable（`canonical=True`，GUI 随机池应使用这一档） | **107** |
| 其中 `IMISC_UNIQUE`（`unique_only=True`，只能作为暗金出现） | 9 |
| 其中没有 `IDI_*` 枚举符号名（仍有正常数值） | 103 |
| 非 Hellfire 前缀 / 后缀 | 83 / 95（表中另有 3+3 条 Hellfire 专用） |
| 非 Hellfire 暗金 | 90（表中 110，`IsUniqueAvailable: i<=89`） |

**同名多条不是解析错误**，而是 1.5.5 的真实数据：

* `idx=1` "Short Sword"（`IDI_WARRIOR`，`IDROP_NEVER`，20/50）= 战士初始剑；
  `idx=119` "Short Sword"（无枚举名，`IDROP_REGULAR`，24/120）= 怪物掉落版。
* `idx=156/157/158` 三行都叫 "Ring"（不同 cursor graphic），真实储物箱里三种都有
  （saved 151/152/153 各一件）。
* `idx=6` "Cleaver"、`idx=31` "Griswold's Edge" 等是 `IMISC_UNIQUE` 的“暗金专用底材”，
  游戏只会通过 `SpawnUnique` 生成它们。

`base_by_name()` 的优先级：`available & droppable` > `available` > 任意；
所以 `base_by_name("Short Sword")` 返回 **119**（掉落版），`base_by_idx(1)` 仍能拿到初始版。
GUI 随机池建议直接用 `base_items(droppable_only=True)` 并过滤 `unique_only`。

### 3.3 存档 idx ↔ 运行时 idx

严格照 `loadsave.cpp:RemapItemIdxToDiablo/FromDiablo` 移植。关键点：

* `saved 154 → runtime 159`（Amulet），`saved 151 → runtime 156`（Ring），与真实记录一致。
* `IDI_SORCERER`（5，Hellfire 版魔法杖）与 `IDI_SORCERER_DIABLO`（166，Diablo 版）**共享
  saved idx 5**；加载器总是把 5 解释成 166。因此 `base_by_saved_idx()` 按“加载方向”构建，
  而不是按“保存方向”反推，否则会认错底材。
* `runtime 167`（Arena Potion）虽然 `IsItemAvailable` 为真，但 `RemapItemIdxToDiablo` 返回
  -1（会被写成金币），无法写进非 HF 存档，故 `available=False`。
* 真实储物箱里 `idx=154/156` 这类“无枚举名”的条目正是游戏正常使用的行，不是 Hellfire 残留。

---

## 4. 368 字节记录编解码

按 `loadsave.cpp:1042 SaveItem()`（1.5.5，名字字段各 64 字节）：

* `RECORD_LAYOUT` 逐字段记录 `(key, offset, struct format, C++ 类型)`；编码时按 C++ 窄类型截断
  （`i8/u8/i16/u16/i32/u32`），保证和游戏写盘一致。
* 96 条真实记录 `record_to_fields() → fields_to_record()` **逐字节相同**；所有对齐 padding
  字节都是 0（测试逐条检查了 21 个 padding 偏移）。
* **重要坑：真实记录的 name/iName 字段在 NUL 之后可能有未初始化垃圾**。例如 stash 第 17 条
  （Topaz Axe of the leech）的 `iName` 在偏移 148..152 处残留 `leech`。C++ 的 `SaveItem()` 会
  把整个 64 字节数组写盘。为了字节级往返，`record_to_fields()` 额外返回 `name_raw`/`iName_raw`
  （完整 64 字节）；`fields_to_record()` 只有在“可见文本没被改过”时才复用原始缓冲，改了名字就
  按新文本重新编码。`GenItem.fields` 已剔除这两个 bytes 键，方便 GUI 做 JSON/展示。
* 我们新生成的记录，名字字段 NUL 之后全 0（游戏不读，合法）。

---

## 5. 生成流程移植范围

逐行对照 `items.cpp` 移植（非 Hellfire 分支 + 保留 `hellfire` 形参）：

| C++ | Python | 备注 |
|---|---|---|
| `GenerateRnd/AdvanceRndSeed/SetRndSeed/DiscardRandomValues/FlipCoin` | `Rng` | Borland LCG `0x015A4E35,+1`；`abs(int32)`，`INT_MIN` 特判 |
| `GetItemAttrs` | `_get_item_attrs` | 含 AC 随机（**恒定 1 次 RNG**）、需求/耐久/价值/名称、book 附魔 |
| `GetBookSpell` | `_get_book_spell` | 卷轴/书，37 个法术循环、Resurrect/HealOther 替换、书皮颜色 |
| `GetItemBLevel` | `_get_item_blevel` | 短路求值：0~2 次 `GenerateRnd(100)` |
| `CheckUnique` | `_check_unique` | 1% 命中后 `DiscardRandomValues(1)`，然后“最后一个匹配暗金” |
| `GetUniqueItem` | `_get_unique_item` | 6 条 power、`iSeed=uid`（仅 `IMISC_UNIQUE`）、`CF_UNIQUE` |
| `GetItemBonus` | `_get_item_bonus` | 按 itype 分派；`minlvl` 截到 25 |
| `GetItemPower` / `GetItemPowerPrefixAndSuffix` | `_get_item_power` / `_select_with_callbacks` | 前缀/后缀分配、`PLDouble`、GOE、onlygood、staff 排除 `IPL_CHARGES` |
| `SaveItemAffix` / `SaveItemPower` / `PLVal` | `_save_item_affix` / `_save_item_power` / `_plval` | 全部效果；`IPL_TARGAC` 非 HF 的 1<<p/3<<p 变换；TOHIT_DAMP 的 3 次 RNG；DUR/CRYSTALLINE 整除顺序 |
| `CalcItemValue` | `_calc_item_value` | VMult/VAdd，最大 1 |
| `GetStaffSpell` / `GetStaffPower` / `GetStaffPrefixId` | `_get_staff_spell` / `_get_staff_power` / `_get_staff_prefix_id` | 法杖专有：25% 走普通词缀、否则随机法术+充能；名字 "base of spell" / "prefix base of spell" |
| `ItemRndDur` | `_item_rnd_dur` | 在词缀之后消耗 1 次 RNG |
| `SetupAllItems` | `_setup_all_items` | 顺序：`SetRndSeed`→`GetItemAttrs(lvl/2)`→`iCreateInfo=lvl|flags`→`GetItemBLevel`→`CheckUnique`→`GetItemBonus`→`ItemRndDur` |
| `SetupItem` + `Item::setNewAnimation(false)` | `_setup_item` | `animFlag=0, selFlag=1, currentFrame=numFrames`（文件里存 currentFrame+1），`animWidth=96, animWidth2=16` |
| `GetTranslatedItemNameMagical` | `translated_item_name_magical` | 游戏**显示**名字用的重放路径（独立 RNG 顺序），见 §7 |
| `Item::getName` | — | 唯一/普通直接返回表名；魔法走上面的重放 |

RNG 调用顺序是本任务最容易错的地方，目前已用 91 条真实记录验证：

* `GetItemAttrs` 恒定消耗 1 次（即使 `iMaxAC==iMinAC`，`GenerateRnd(1)` 也会推进）。
* `GetItemBLevel` 的 `||` 短路：第一次 `GenerateRnd(100) <= 10` 命中时第二次不调用。
* `CheckUnique` 在 `GenerateRnd(100) > uper` 时只消耗 1 次；只有“命中且存在匹配暗金”才会
  再 `DiscardRandomValues(1)`。若命中但该底材没有对应暗金，C++ 会在 `numu==0` 直接返回，
  **不再消耗**——这一点会影响到后续词缀选择，已专门处理。
* `SaveItemPower` 的前缀数值 roll 发生在**后缀选择之前**（`prefixFound` 回调内），
  所以前缀 roll 次数会改变后缀结果；`TOHIT_DAMP`/`DOPPELGANGER` 共 3 次、`TOHIT_DAMP_CURSE` 2 次。
* 耐久 roll 在词缀之后，且只影响 durability 本身（可变量）。

---

## 6. 自选词条：种子搜索

### 6.1 为什么不能直接改 `PrePower/SufPower/iName`

游戏对“已鉴定 + `createInfo != 0` + `magical == MAGIC`”的物品，显示名由
`GetTranslatedItemNameMagical()` 用 `iSeed + iCreateInfo` **重放 RNG 重新算**（items.cpp:2307），
不读存档里的 `iName`。手改字段会导致名字/词缀/数值对不上。

### 6.2 实现

`generate(base, ilvl, 'magic', prefix=..., suffix=...)`：

1. 解析词缀（支持名字、`"of xxx"`、表下标、dict）。**同名歧义**（"Fine" 同时是武器伤害前缀和
   护甲 AC 前缀；"Crimson" 有 3 个等级段）按“该底材类型合法 + 落在 ilvl 窗口内”择一。
2. 先做可达性校验：类型不适用 / `PLMinLvl` 不在 `[ilvl//2, ilvl]` / `PLOk=false` 但
   `onlygood=True` / Hellfire 专用 → 直接报错，并在消息里列出可用词缀。
3. 为“选择阶段”做了快速模拟 `_fast_affix_indices`（缓存候选表 + 只推进 RNG，不建字段），
   命中候选后再跑一次完整 `SetupAllItems` 复核（前缀/后缀下标必须一致）。在 1871 组随机
   (底材, ilvl, seed) 上与完整流程 **0 不一致**。
4. 找到 seed 后返回完整记录。全程 0.00–0.04s（含最坏的低 ilvl 低概率组合）；
   `max_tries` 默认 200000，可调。

### 6.3 实测

```
Long Sword     ilvl  2 -> Sharp Sword of quality            pre#26  suf#0
Buckler        ilvl  2 -> Fine Buckler of the fox            pre#37  suf#50
Short Sword    ilvl 30 -> Brutal Sword of slaying            pre#19  suf#2
Leather Armor  ilvl 60 -> Godly Armor of the whale           pre#46  suf#57
Buckler        ilvl 24 -> Saintly Shield of absorption       pre#43  suf#10
Amulet         ilvl 30 -> Drake's Amulet of the zodiac       pre#73  suf#47
War Staff      ilvl 50 -> King's War Staff of haste          pre#34  suf#90
```

全部 `validate=[]`；同一 `seed` + 同一请求结果确定可复现。

### 6.4 GUI 注意

* 词缀有等级窗口：低等级词缀（"Sharp"、"of the Fox" 等）只出现在低 ilvl；
  高 ilvl 装备只能选高等级词缀。`eligible_affixes()` 就是给下拉框用的“当前 ilvl 可选列表”。
* 部分词缀只适用于特定类型（"of the Fox" 是 Armor/Shield/Misc 的生命后缀，长剑拿不到）。
  这属于游戏规则，不是 bug；错误信息会提示。
* 想“任意词条 + 任意底材”都被允许是不可能的；`strict=False` 可让 UI 走“不可用”分支。

---

## 7. 名称与字宽（StringInPanel 精确复现）

* `GetItemPower` / `GetTranslatedItemNameMagical` 在名字过长时会**回退到短名**
  （`AllItemsList[].iSName`），阈值是 `StringInPanel(name) = GetLineWidth(name, GameFont12, 2) < 254`。
* 字宽表来自游戏资产 `devilutionx.mpq` 的 `fonts\12-00.clx`（256 个 glyph，CLX 帧头里的
  `width`），已内嵌为 `d1itemgen.FONT12_WIDTHS`。`line_width()` 按“每字符 width+2，最后减 2”计算。
* 真实对照：`"Ivory Two-Handed Sword of the stars"` = 337px → 回退成
  `"Ivory Sword of the stars"`（226px），与真实 stash 第 86 条完全一致；
  `"Master's Two-Handed Sword"` = 245px → 保留长名（真实第 95 条也是长名）。
* 37 条真实魔法物品 + 288 件生成物品：游戏显示名重放 == 存档 `iName`，0 差异。
* **已知 1.5.5 自身怪癖**：法杖在 `ilvl > 51` 时，生成路径（`GetStaffSpell→GetItemPower`）
  用 `minlvl = ilvl/2`，而显示路径把 minlvl 截到 25，可能选到不同前缀（名字与属性不符）。
  `generate()` 会跳过这类 seed（`_display_name_consistency`），`validate()` 对
  `ilvl>51` 的法杖不报此差异（避免误判真实存档）。建议 GUI 把法杖 ilvl 限制在 ≤51。

---

## 8. 真实存档回归（96 条）

### 8.1 方法

对每条记录：`record_to_fields` → `replay_item`（按 `magical` 分派：普通/魔法/暗金）→
逐字段比较 `_GENERATION_KEYS`（53 个生成相关字段）。

### 8.2 结果

| 分类 | 数量 | 说明 |
|---|---|---|
| 普通 | 52 | 其中 5 条是 NPC 货架物品（`CF_HEALER/CF_WITCH`），另有 47 条可完整重放 |
| 魔法 | 37 | 全部可重放 |
| 暗金 | 7 | 全部可重放（任务暗金 AC 不参与比较） |

* 可重放 **91/91**：除 `durability`（可变量）外所有生成字段 100%。
* 唯一异常：**第 84 条 "Glorious Splint Mail"（magic, ci=0x00CA）AC 记录 32、重放 30**。
  AC 是 `GetItemAttrs` 的第一次 RNG，seed 固定 → 本应可复现；该条其余 52 个字段全部一致。
  最可能的原因：这条物品是旧版修改器手工生成/编辑过（`create_info` 与 seed 不是同一次生成
  的产物），或来自更老版本存档。只影响 1 个字节段的属性，不影响合法性。
* `durability` 全部排除比较，因为耐久是**可变的游戏状态**（打怪会掉、铁匠会修）。例：
  - 第 3 条 Arkaine's Valor 记录 25 / 表 40（磨损）；
  - 第 21 条 Splint Mail 记录 65 = maxDur（修满）；
  - 第 71 条 Undead Crown 记录 48 / 表 50（磨损）。
* 5 条 NPC 货架物品（`ci` 含 `CF_HEALER=0x4000` 或 `CF_WITCH=0x2000`）无法用 `SetupAllItems`
  重放：NPC 生成会先跑 `RndWitchItem/RndHealerItem` 消耗 RNG，再 `GetItemAttrs`，且不调
  `ItemRndDur`/`SetupItem`（所以它们的 `numFrames/currentFrame` 是 0/1、耐久满值）。
  这类物品仍然**合法**，`validate` 对它们只做结构/表检查，不做 RNG 重放。

### 8.3 真实记录 `validate()` 明细

| 类型 | 通过 | 总数 |
|---|---|---|
| 普通 | 52 | 52 |
| 魔法 | 36 | 37（#84 AC） |
| 暗金 | 7 | 7 |
| **合计** | **95** | **96** |

---

## 9. 测试清单（`work/tests/test_itemgen.py`，15/15）

1. **tables**：数量、starter/droppable 双条目、idx↔saved 映射、尺寸、TSV 差异。
2. **record codec**：96 条真实记录逐字节往返、padding 全 0、名字截断/NUL。
3. **rng**：已知序列 + 与 `d1rng.pyc` 300 seed × 20 次比对。
4. **stash replay**：91 条逐字段、只允许已记录的 #84 AC 异常。
5. **stash validate**：95/96，按类型拆分。
6. **100 随机魔法**：`validate=[]`、368 字节、往返、名字非空、多样性。
7. **指定词条**：7 组、确定性、不可达拒绝、`strict=False`。
8. **eligible affixes**：等级窗口、类型过滤、PLDouble、staff 专项、unique-only 底材。
9. **普通物品**：武器/护甲/盾/戒指/项链/弓/法杖/卷轴，法杖仍随机法术+充能。
10. **暗金**：89 个生成并校验；7 条真实暗金逐字段重放。
11. **显示名重放**：37 真实 + 288 生成。
12. **背包尺寸**：96/96 与真实储物箱网格一致。
13. **名称/字宽**：真实长名/短名对、精确像素宽度。
14. **validate 拒绝**：截断、空名、类型不符、Hellfire 效果、错误 iName、无词缀值、坏 idx、错 Uid。
15. **describe/边界**：ilvl 0..63、未知底材、unique-only 底材。

---

## 10. 生成压力测试（全底材）

```
141 个非 HF 可用底材 × ilvl {1,10,30,55}：
  魔法 308 件成功 + 0 失败（unique_only/非装备类按预期拒绝）
141 × ilvl {0,5,40}：
  普通 396 件成功 + 0 失败
```
所有成功件 `validate=[]`。暗金：90 个非 HF 可用暗金中 89 个生成成功
（Bovine Plate 的底材 `IDI_LGTFORGE` 被非 HF `IsItemAvailable` 排除）。

---

## 11. 合规规则（`validate` 实际检查项）

结构/索引：
* 长度 368；`idx` 能按“加载方向”映射到运行时底材且 `available`；
* `iType/loc/class/miscId` 与底材表一致（暗金的 `loc/curs` 允许被 `IPL_ONEHAND/IPL_INVCURS` 改）；
* 名字/iName 非空；`magical ∈ {0,1,2}`；`identified/StatFlag ∈ {0,1}`；
* 非 HF：`dwBuff` 无 Hellfire 位、`PrePower/SufPower <= IPL_LASTDIABLO`。

数值：
* `durability ≤ maxDur`（允许 255 不可破坏）；`minDam ≤ maxDam`；`0 ≤ MinStr/MinMag/MinDex ≤ 255`；
* `0 ≤ charges ≤ maxCharges`；`ivalue ≥ 0`；`iIvalue ≥ 0`（任务物品可为 0）；AC 在 int16 内（**允许负 AC**，
  Harlequin Crest 的 `IPL_AC_CURSE` 就是负的）。

词缀：
* 普通：`PrePower/SufPower` 必须都是 -1；
* 魔法：至少一个词缀 power id；每个 power id 必须能在对应表中找到“适用于该物品类型”的词缀；
  `VAdd/VMult` 不能全 0；
* 暗金：`Uid` 合法且可用、底材 `itemItemId` 匹配、`iName == 表名`、`CF_UNIQUE` 置位；
  `IMISC_UNIQUE` 底材还要求 `iSeed == Uid`。

重放一致性（默认开启）：
* 用 `(idx, iSeed, iCreateInfo)` 重跑完整生成流程，逐字段比对（`durability` 除外；
  任务暗金 `AC` 除外）；不一致会给出“游戏会设 X，记录是 Y”；
* 额外检查 `GetTranslatedItemNameMagical()` 重算的**显示名**是否等于 `iName`（法杖 ilvl>51 除外）；
* NPC 货架物品（`CF_TOWN`/`CF_SMITH`）跳过完整重放，只做结构检查。

---

## 12. 已知差异与风险

| # | 事项 | 影响 | 处置 |
|---|---|---|---|
| 1 | 真实 stash #84 AC 32 vs 重放 30 | 单条记录无法由 seed 复现 | 报告留证；其余 52 字段一致；疑似旧修改器产物 |
| 2 | `durability` 是可变状态 | 重放值通常 ≠ 记录值 | 回归/validate 的重放比较排除；仍检查 `≤ maxDur` |
| 3 | NPC 货架物品（5 条）RNG 流不同 | 无法 `SetupAllItems` 重放 | 只做结构检查；`generate()` 目前不模拟 `RndWitchItem` 等 NPC 流程 |
| 4 | Hellfire | 只实现非 HF 的 368 字节记录；`hellfire` 形参保留但记录仍 368（HF 实际 372） | 本项目目标是 `.sv` 非 HF；如要做 HF 需另加 4 字节 `_iDamAcFlags` |
| 5 | 法杖 ilvl>51 的名字/属性错位（游戏自身 bug） | 显示名可能与属性不符 | 生成时过滤该类 seed；validate 不对真实法杖报错；建议 GUI 限制 ≤51 |
| 6 | 名字字段 NUL 后垃圾字节 | 简单 `str` 编解码会丢字节 | `name_raw/iName_raw` 保留原始缓冲；生成记录为 0 |
| 7 | 金币生成 | 未实现（`GetItemAttrs` 的金币分支） | 本任务只做装备 |
| 8 | 显示语言 | 存档存英文名（与真实存档一致），游戏按语言翻译显示 | 不能预知玩家语言；英文名是 1.5.5 存盘格式的既定内容 |
| 9 | 同名物品 | `base_by_name` 只能返回一个 | 已用 `droppable/canonical` 优先级 + `base_by_idx` 精确取；GUI 展示可用 `droppable` 字段 |
| 10 | `_iStatFlag` | 默认 1；对高需求装备可能是“善意谎言” | 游戏拾取/移动时会重算；不影响读档合法性 |

---

## 13. 给 GUI / stash-core 的集成说明

```python
import sys
sys.path.insert(0, r"F:\Qoder\暗黑1重制版\work\lib")
import d1tables as T
import d1itemgen as G
import d1stash2

# 随机魔法装备（ilvl 语义 = iCreateInfo 的 level 位，通常是 2×地牢层数）
base = T.base_by_name("Long Sword")
item = G.generate(base["idx"], ilvl=40, rarity="magic")
assert G.validate(item.record) == []
stash = d1stash2.Stash(r"...\stash.sv")
page, x, y = stash.add_record(item.record)
stash.save()

# 自选词条（名字或下标；失败抛 ItemGenError，消息里带可用词缀）
item = G.generate(base["idx"], 40, "magic", prefix="King's", suffix="of carnage")

# 暗金：base_idx 可省，自动取暗金底材
item = G.generate(None, 27, "unique", unique_id="The Grandfather")

# UI 下拉框
bases = [b for b in T.base_items(droppable_only=True) if not b["unique_only"]]
affixes = G.eligible_affixes(base["idx"], ilvl, "prefix")
print(item.describe())
```

* 性能：随机生成 <1ms；种子搜索 0–40ms；`validate` 每次 <2ms。
* `add_record` 会把记录里的 `position` 改成储物箱格子坐标（stash-core 行为），其余字节不动。
  冒烟测试：生成 3 件（魔法×2 + 暗金×1）→ `add_record` → `save` 到临时文件 → 重新打开，
  96→99 条、记录内容一致、`validate` 全通过。

---

## 14. 复现

```powershell
$env:PYTHONIOENCODING='utf-8'
F:\Qoder\暗黑1重制版\_py312\python.exe F:\Qoder\暗黑1重制版\work\lib\d1tables.py   # 表自检
F:\Qoder\暗黑1重制版\_py312\python.exe F:\Qoder\暗黑1重制版\work\lib\d1itemgen.py  # 生成自检
F:\Qoder\暗黑1重制版\_py312\python.exe F:\Qoder\暗黑1重制版\work\tests\test_itemgen.py
```

真实存档只读使用；测试中的临时 `.sv` 写到 `%TEMP%` 并删除，未触碰 `%APPDATA%`。

---

# 15. Round 2（2026-11-11）：崩溃修复、底材过滤、数值搜索、暗金图鉴

> 子代理：itemgen2　｜　产出：`work/lib/d1tables.py`、`work/lib/d1itemgen.py`、
> `work/tests/test_itemgen2.py`、本报告 §15
> 测试：`_py312\python.exe work\tests\test_itemgen2.py` → **10/10 passed（约 4s）**；
> `_py312\python.exe work\tests\test_itemgen.py` → **15/15 passed**（Round 1 回归）
> 真实存档只读；`stash.sv` 仍是 96 条记录，本 Round 没有写入任何存档。

## 15.1 崩溃根因：starter 底材 `IDI_SORCERER_DIABLO`

用户 stash 新加的 `[96] saved idx=5` 被加载器解释成运行时 **166 = `IDI_SORCERER_DIABLO`**
（`Short Staff of Charged Bolt`，Sorcerer 初始法杖），进游戏即 `0xC0000005`（访问冲突）。
根因不是词缀/数值，而是**底材本身**：`AllItemsList` 里有 4 条职业初始物品（`IDROP_NEVER`），
它们的法术/充能由 `InitPlayer()` 的职业初始化流程配置，随机生成器写出的记录与游戏对
"starter spell staff" 的期望不一致。

| id | runtime idx | saved idx | 名字 | 说明 |
|---|---|---|---|---|
| `IDI_WARRIOR` | 1 | 1 | Short Sword | 战士初始剑（20/50，掉落版是 119：24/120） |
| `IDI_ROGUE` | 4 | 4 | Short Bow | 弓箭手初始弓 |
| `IDI_SORCERER` | 5 | 5 | Short Staff of Mana | 法师初始法杖（非 HF `IsItemAvailable` 为 false） |
| `IDI_SORCERER_DIABLO` | **166** | **5** | Short Staff of Charged Bolt | **崩溃元凶**（Diablo 版法师杖） |

> 关键坑：`IDI_SORCERER` 与 `IDI_SORCERER_DIABLO` **共用 saved idx 5**，加载器总是把 5 解成 166。
> 所以过滤必须按 `IDI_*` 名字（`id` 字段），**不能按 saved idx**。

## 15.2 底材分类：starter / unique_only / equipment / generatable

`d1tables._finalize_base()` 给每条底材新增字段：

```python
starter      = id in {IDI_WARRIOR, IDI_ROGUE, IDI_SORCERER, IDI_SORCERER_DIABLO}
unique_only  = misc_id == IMISC_UNIQUE          # 原有
equipment    = itype not in (Misc, Gold, None) and loc != ILOC_UNEQUIPABLE
generatable  = available and equipment and not starter and not unique_only
```

1.5.5 非 Hellfire 的实际数字（自检/测试都断言）：

| 统计 | 数字 |
|---|---|
| `AllItemsList` 总行数 | 169 |
| 非 HF 可用（`available`） | 141 |
| **默认 `base_items()`（= generatable，可生成的可装备底材）** | **74** |
| 其中 droppable（`droppable_only=True`） | 72 |
| starter | 4（3 条 available） |
| unique_only | 10（`Cleaver`、`Arkaine's Valor`、`Griswold's Edge`、`Veil of Steel`、`Harlequin Crest`…9 条 available） |
| 非装备（金币/药水/卷轴/书/任务道具） | 83 行（其中 55 行 available） |
| 5 把普通法杖 | 151 Short / **152 Long** / 153 Composite / 154 Quarter / 155 War（`spell=0`，可安全生成魔法） |

> 74 条里有 2 条是战士的备用初始装备（`id` 为 `IDI_WARRSHLD` Buckler idx=2、`IDI_WARRCLUB` Club idx=3，
> 都是 `IDROP_NEVER` 但只是普通护甲/武器行，不是法术法杖，游戏按普通物品加载，所以保留在可生成池；
> 要"只显示真掉落"用 `droppable_only=True` → 72 条）。

API 变化（覆盖 §2.1/§2.2 的旧签名）：

```python
# d1tables
base_items(include_unavailable=False, droppable_only=False,
           include_starter=False, include_unique_only=False,
           include_non_equipment=False)          # 默认 74 条 generatable
base_by_name(name, include_starter=False, include_unique_only=False,
             include_unavailable=False, include_non_equipment=False)
base_by_sname(...)                                # 同样的 include_* 参数
STARTER_ITEM_IDS / STARTER_ID_SET                 # starter 名单（按 IDI_ 名）

# d1itemgen
base_items(...)                                   # 透传
generate(..., prefix_value=None, suffix_value=None, value_tolerance=0,
         allow_staff_spells=False, allow_non_equipment=False)
eligible_affixes(base_idx, ilvl, kind="prefix", onlygood=False)   # 法杖不再列 IPL_SPELL/IPL_CHARGES
affix_value_range(affix, kind=None, hellfire=False) -> (lo, hi) | None
is_value_affix(affix, kind=None) -> bool
unique_detail(uid|name|dict) -> dict
```

`generate()` 的拒绝规则（都是 `ItemGenError`，中文原因）：

```text
初始装备（IDI_SORCERER_DIABLO）不能作为随机底材生成：'Short Staff of Charged Bolt'
（saved idx=5, runtime idx=166）是职业初始物品，写入存档会让游戏崩溃
（已验证 IDI_SORCERER_DIABLO → 0xC0000005）；请改用普通底材（Short Staff (runtime idx=151)）
```

* `generate(166)` / `generate("Short Staff of Charged Bolt")` / `generate("IDI_SORCERER_DIABLO")` /
  `generate(5)`（saved 5 → 166）/ `generate(1)` / `generate(4)` 全部拒绝；`strict=False` 返回 `None`。
* 普通同名底材不受影响：`generate("Short Sword")` 解析到 **119**（掉落版），`generate(152, …)` 正常。
* `unique_only` 底材：`generate("Cleaver", …)` 报 "unique-only base item … use a normal base + unique_id instead"。
* 非装备：`generate("Scroll of Identify", …)` 报 "「Scroll of Identify」不是可装备底材 …"；
  调试可传 `allow_non_equipment=True`（卷轴/书仍走 `GetBookSpell`，`validate=[]`）。

> Round 1 的 `work/tests/test_itemgen.py` 只改了 **5 处期望**（`base_items()` 74、全表 169/141、
> `Cleaver` 用 `include_unique_only=True`、卷轴用 `include_non_equipment=True`+`allow_non_equipment=True`、
> 法杖 ilvl 63 跳过），校验规则一条没放宽，仍 15/15。

## 15.3 数值搜索：`prefix_value` / `suffix_value`

### 目标值定义

* 目标值 = **游戏 tooltip 上的显示值**，也就是 `SaveItemPower()` 从
  `param1..param2` 里 `GenerateRnd` 出来的那个 `r`（含 TARGAC 的 `1<<p / 3<<p` 变换）。
  **不是** 词缀表的 `min_val/max_val`（那是 `CalcItemValue` 的价值映射，与显示无关）。
* `LIFE`/`MANA`：存档写 `PLHP/PLMana = r << 6`，但显示值是 `r`（点数）。指定 `+15` 生命 →
  `PLHP == 15<<6 == 960`。
* 诅咒词缀用**负数**（`Tin` = `IPL_TOHIT_CURSE`，范围 `(-10, -6)`；`PLToHit` 为负）。
* 只有下表 effect 支持数值；其余（CHARGES / SPELL / FASTATTACK / STEALLIFE / INDESTRUCTIBLE /
  DUR 百分比 / 固定 flag / 触发类）传 value 会抛
  "词缀 X 的效果 IPL_… 不是可指定的数值效果（固定/特殊效果…），不能指定数值"。

`_VALUE_POWERS`（effect → `(记录字段, 符号, shift)`，`字段 = 显示值 << shift`）：

| effect | 字段 | effect | 字段 |
|---|---|---|---|
| IPL_TOHIT / _CURSE | PLToHit | IPL_DAMP / _CURSE | PLDam |
| IPL_TOHIT_DAMP / _CURSE | PLDam（+ 命中由 p1 决定） | IPL_DOPPELGANGER | PLDam |
| IPL_ACP / _CURSE | PLAC | IPL_ALLRES | PLFR/PLLR/PLMR |
| IPL_FIRERES / LIGHTRES / MAGICRES | PLFR/PLLR/PLMR | IPL_STR/MAG/DEX/VIT (+CURSE) | PLStr/PLMag/PLDex/PLVit |
| IPL_ATTRIBS (+CURSE) | 四个属性 | IPL_LIFE / _CURSE | PLHP（shift 6） |
| IPL_MANA / _CURSE | PLMana（shift 6） | IPL_DAMMOD | PLDamMod |
| IPL_TARGAC | PLEnAc | | |

### 算法

1. `_resolve_affix(..., want_value=…)` 先定位词缀行（同名多档时优先"范围包含目标值"的那一档，
   例如 ilvl 20 的 `Crimson` 有 21..30 / 31..40 两档，`prefix_value=35` 会选 31..40 档）。
2. `_check_value_target()` 先做可行性检查：词缀必须可数值、值必须在 `param1..param2`（±容差）内，
   越界立即报 "未找到 前缀 X = 值（最接近 Y，差距 d）"，不浪费搜索。
3. 快速选择阶段（`_fast_magic_selection` / `_fast_staff_selection` → `_fast_selection`）**精确复刻
   `SaveItemPower` 的 RNG 消耗**：
   * 前缀：`_rnd_pl(p1,p2)` 必 roll；`IPL_TOHIT_DAMP` / `IPL_DOPPELGANGER` 额外 1 次
     `_rnd_pl` + `CalculateToHitBonus`（共 3 次）；`IPL_TOHIT_DAMP_CURSE` 额外命中 roll；
     `IPL_TARGAC` 非 HF 先把 `p1,p2` 变成 `1<<p1, 3<<p2`；
   * 后缀：索引 roll；**只有请求了后缀数值时**才再 roll 后缀值（它之后没有别的 RNG 消费者，
     跳过可提速；不请求后缀时不选后缀，进一步提速）；
   * 用 `_fast_blevel()` 内联 `GetItemBLevel` 的短路顺序（第 1 次 `GenerateRnd(100)` 必消耗）。
4. 前缀/后缀下标与数值都匹配后，跑**完整 `_setup_all_items`** 复核：
   下标一致、`magical==MAGIC`、`_display_name_consistent`（游戏显示名重放等于 `iName`）、
   `_verify_values()` 逐字段核对：
   * 该词缀 roll 出的显示值 == 目标（±容差）；
   * 该词缀对记录字段的实际 delta == `目标 << shift`；
   * 若另一词缀没有改同一字段，则记录字段绝对值 == `目标 << shift`
     （`Brutal` + `of slaying` 这类会叠加不同字段的组合也正确；同字段叠加时以 per-slot 值为准）。
5. 命中后 `_make_gen_item()` 生成 368 字节记录，`GenItem._extra` 附
   `prefix_value`/`suffix_value`（带符号显示值）与 `prefix_power`/`suffix_power`。
6. 失败消息（GUI 直接显示）：

```text
未找到 后缀 of giants = +15（最接近 +16，差距 1）；'Short Sword' ilvl=30 的可选范围是 +16~+20，
已尝试 200000 个种子（容差 0）
```

### 性能与预算（本机 Python 3.12 实测）

| 场景 | 命中率 / 耗时 |
|---|---|
| 快速选择单 seed | **2.7 µs**（≈ 368k seed/s） |
| 单词缀 + 单值（`Short Sword` + `of the giants` 16..20） | 数百 seed，**0.001–0.02 s** |
| 双词缀 + 单值（`Brutal` + `slaying`，值 81/90/95） | 2.5 万–13 万 seed，**0.02–1.5 s** |
| 双词缀 + 双值（Ring `Bronze +3` / `strength +4`） | **0.02–0.05 s** |
| 双词缀 + 双值（`Brutal +85%` / `giants +18`，最坏现实组合） | 期望 ~137k seed；`max_tries=200000` 只有 ~77% 成功，**`max_tries=2,000,000` → >99.99%**，实测 5/5 成功共 ~2.8 s |

* `max_tries` 默认仍是 **200000**（不指定数值时足够）；**指定 value 时调用方应传
  `max_tries=2_000_000`**（GUI 适配层已经这么做，见 `d1itemgen_adapter.generate`）。
* 双值搜索失败概率是 `1-(1-p)^n`，p≈7e-6；2M 次仍失败的概率 < 1e-4。

### 限制

| 限制 | 说明 |
|---|---|
| 非数值词缀 | CHARGES/SPELL/FASTATTACK/FASTRECOVER/FASTBLOCK/STEAL*/INDESTRUCTIBLE/KNOCKBACK/DUR(_CURSE)/CRYSTALLINE/FIREDAM/LIGHTDAM/固定 flag → 明确报错，不能指定数值 |
| 值越界 | 立即报"最接近/差距"，不会静默返回近似值（除非 `value_tolerance>0`） |
| 单词缀多档同名 | 按"范围包含目标值"选档；GUI 传 `index` 时无歧义 |
| `Hydra's`（法杖专用 MANA 前缀，min_level 56） | 只能出现在 ilvl ≥56 的法杖上，而属性法杖限制 ilvl ≤51 → 无法用数值搜索；游戏里它只出现在**法术法杖**上 |
| Hellfire-only 词缀（如 `Doppelganger's`） | 非 HF 生成器不可达（本来就不在候选里） |
| 双词缀 + 双值 | 成本是概率乘积，需要提高 `max_tries`；GUI 显示"通常 1~3 秒"是合理的 |

## 15.4 法杖安全策略

* **默认 `allow_staff_spells=False`**：`rarity='magic'` 的法杖只走 `GetStaffSpell()` 的 25%
  分支 `GetItemPower(lvl/2, lvl, AFFIX_STAFF)`，产物是**属性词缀法杖**
  （如 `King's Long Staff of haste`），`spell=0`、`charges=0`、`maxCharges=0`。
  这样不会把 75% 的随机法术/充能带进存档（用户看不到也验证不了）。
* 5 把普通法杖 × ilvl {1,10,30,45,51} 全部 `validate=[]`，全部 `spell=charges=0`。
* 词缀候选里额外过滤 `IPL_SPELL` / `IPL_CHARGES`（对法杖而言会改写 spell/charges，与名字重放冲突）。
* `ilvl > 51` 的属性法杖被拒绝：游戏自身在 `ilvl>51` 时生成路径用 `minlvl=ilvl/2`、显示路径截到 25，
  名字与属性会不一致（§7 的老问题）→ 报中文错误，建议 ilvl ≤51。
* 需要游戏原生的法术法杖时显式传 `allow_staff_spells=True`（走完整 `GetStaffSpell`，仍 `validate=[]`）。
* `rarity='normal'` 的法杖行为不变（仍是"<base> of <spell>"+充能，与游戏掉落一致）。

## 15.5 `unique_detail()`（暗金图鉴）

```python
G.unique_detail(77)
# {'uid': 77, 'index': 77, 'name': "Naj's Light Plate", 'name_en': "Naj's Light Plate",
#  'base_idx': 67, 'base_saved_idx': 67, 'base_name': 'Plate Mail', 'base_name_en': 'Plate Mail',
#  'base_id': None, 'base_itype': 'HeavyArmor',
#  'min_level': 19, 'value': 78700, 'num_powers': 6, 'available': True,
#  'powers': [{'type': 65, 'type_name': 'IPL_NOMINSTR', 'param1': 0, 'param2': 0}, ...]}
```

* 只给英文；中文名/属性说明由 `d1i18n`（`unique_name_cn` / 属性文案）补齐，避免 lib 依赖 app。
* 90 件暗金全部有完整条目；**Bovine Plate** 的底材 `IDI_LGTFORGE` 在非 HF 不可写，
  返回 `available=False` + `base_idx=32`/`base_name='Bovine Plate'`（GUI 图鉴过滤掉即可，不抛异常）。
* 暗金生成仍然用"普通底材 + `unique_id`"：`generate("Plate Mail", 27, "unique", unique_id=77)`；
  任务暗金（`Griswold's Edge` 等）走自己的 `IMISC_UNIQUE` 底材行，`_unique_base_index()` 已显式
  打开 starter/unique_only/non-equipment 过滤。

## 15.6 Round 2 测试（`work/tests/test_itemgen2.py`，10/10）

1. **底材过滤**：默认 74 条；不含 4 个 starter（按 id + runtime idx 双查）、10 个 unique_only、
   非装备；`152 Long Staff` 在列表；`base_by_idx(5).saved_idx==base_by_idx(166).saved_idx==5`；
   `base_by_saved_idx(5).idx==166`；`generatable` 与公式逐行一致；全表 169 / 可用 141。
2. **崩溃防护**：9 种入口（166 / 名字 / `IDI_*` / saved 5 / 1 / 4 / unique 等）全部拒绝，
   消息含"初始装备"+"IDI_"；`strict=False` 返回 None；`Short Sword`（119）仍可生成。
3. **法杖安全**：`Long Staff` ilvl30 魔法 → `spell=charges=0`；`King's Long Staff of haste` →
   `validate=[]`、spell/charges=0；5 把法杖 × 5 个 ilvl 全部 stat staff；ilvl 60 拒绝；
   `allow_staff_spells=True` 能找到法术法杖且 `validate=[]`。
4. **暗金**：4 个 unique_only 名字作魔法底材被拒；`Plate Mail + uid 77` → `Naj's Light Plate`
   `validate=[]`；任务暗金 `Griswold's Edge` 正常；89 件可用暗金全部 base+uid 生成并校验。
5. **数值搜索 +STR**：`Short Sword` + `of the giants`（= `of giants` / `giants` 都能解析）
   `+16..+20` × 5 个不同 seed（共 25 件）→ `PLStr` 精确、`validate=[]`、`_extra.suffix_value` 一致；
   `+15/+21/+10` 越界 → "未找到/最接近/差距"；`value_tolerance=1` 接受 +16 代替 +15。
6. **LIFE/MANA/伤害%**：`of the fox +12` → `PLHP=768`；`Dragon's +55` → `PLMana=3520`；
   `Brutal +85` → `PLDam=85`；`Brutal +81/+90/+95` + 后缀 `slaying` → `PLDam` 精确。
7. **双值**：`Ring` `Bronze +3` / `of strength +4` × 3 seed → `PLToHit=3`、`PLStr=4`；
   `Brutal +85%` + `giants +18` 5 个不同起始 seed、`max_tries=2,000,000` → **5/5 成功**（~2.8s）；
   小预算（2000）失败时给出明确消息；不可能目标（+99）报错。
8. **错误处理**：4 个非数值词缀（haste/the ages/Plentiful/the leech）明确报错；只给 value 不给词缀报错；
   normal/unique + value 报错；诅咒词缀 `Tin -8` → `PLToHit=-8`；`affix_value_range()` 对固定效果返回 None。
9. **unique_detail**：77 的 15 个键齐全；90 件全部完整；Bovine Plate 是唯一 `available=False` 的。
10. **记录完整性**：5 个数值用例（STR/ALLRES/TOHIT/LIFE/MAG）从**写出的 368 字节**重新解码，
    字段精确、往返一致、`validate=[]`、显示名与 `iName` 一致。

其他 Round 2 回归（脚本实测，未写存档）：

* 74 个底材 × ilvl {1,10,30,50} 魔法 = 296 件，`validate=[]`，0 失败（0.09s）；
* 74 个底材 × ilvl {0,5,40} 普通 = 222 件，0 失败（0.03s）；
* 132 个数值词缀逐一"找可选底材 + 随机目标值 + 搜索"：130 个字段精确，
  2 个不可达且原因明确（`Hydra's` 只能 ilvl≥56 法杖；`Doppelganger's` Hellfire-only）。
* `work/tests/test_stash.py` 14/14 仍通过（stash 编解码/网格不受影响）。

## 15.7 给 GUI / 打包的提示

1. 底材下拉直接用 `G.base_items()`（74 条），**不需要**再过滤 `unique_only`；若要"只显示可掉落"用
   `droppable_only=True`（72 条）。`b["generatable"] / b["starter"] / b["equipment"]` 可直接判断。
2. 生成失败统一捕获 `ItemGenError`，`str(exc)` 已是中文可显示文案（starter / 非装备 / 数值不可达 /
   法杖 ilvl 限制 / 非数值词缀）。
3. 指定数值时传 `prefix_value`/`suffix_value` + `max_tries=2_000_000`（适配层已自动）；
   单词缀数值 GUI 可提示"约 1 秒"，双值提示"1~3 秒"。
4. 词缀下拉改用 `eligible_affixes()`（法杖不再出现充能/法术词缀），数值范围用
   `G.affix_value_range(affix)`（负值表示诅咒），是否可填数值用 `G.is_value_affix(affix)`。
5. 暗金图鉴用 `G.unique_detail(uid)`；`available=False` 的（Bovine Plate）建议灰显/过滤。
6. **打包注意**：`work/build/lib/py/` 里是 `work/lib` 的**暂存副本**（Round 1 版本），
   重建 exe 前必须从 `work/lib` 重新 staging（`build_exe.ps1` 的步骤），否则 exe 仍是旧表/旧生成器。

