# Round 7 总纲（2026-11-12）· ilvl 31~34 暗金怪掉落路线 + 双数值词缀 + 储物箱中文名

> 先读本文件。ROOT=`F:\Qoder\暗黑1重制版`；源码 `work\lib` + `work\app`；测试 `work\tests`。
> **绝不写真实存档**：只允许 `work\tmp` / `work\backup_saves` 副本；开始/结束核对
> `%APPDATA%\diasurgical\devilution` 的 `.sv` SHA256（`test_round5_spell.py` 已内建该检查）。
> 版本：`work\app\d1env.py` 的 `APP_VERSION` 本轮升到 **2.5.0**。

## 1. 用户本轮原话

1. 「暗金怪可以掉落 ilvl30+4 的装备。参考这个线索我们的修改器的物品等级也可以在 ilvl 值 31-34
   的时候走这个路线生成，防止把丢装备地上以后报无效数据包」
2. 「装备生成页面，词缀目标值只能填一个，国王词条会有二条属性（命中+伤害），修复类似问题。」
3. 「储物箱界面，物品列表也用中文显示（工作区应该有汉化表）」

## 2. 已确认事实（不要重新怀疑）

### 2.1 丢地校验（`Source/items/validation.cpp` + `Source/msg.cpp:IsPItemValid`）

常量（`Source/items.h`）：

| 名称 | 值 | 含义 |
| --- | --- | --- |
| `CF_LEVEL` | `0x003F` | 记录里的物品等级（6 bit） |
| `CF_ONLYGOOD` | `0x0040` | 不选 `PLOk == false` 的词缀 |
| `CF_UPER15` | `0x0080` | 来自暗金怪：15% 概率成暗金 |
| `CF_UPER1` | `0x0100` | 来自地牢：1% 概率成暗金 |
| `CF_UNIQUE` | `0x0200` | 已是暗金 |
| `CF_USEFUL` | `CF_UPER15\|CF_UPER1` = `0x0180` | 药水/回城卷轴那种组合 |

`IsPItemValid()` 的分支顺序（非 Hellfire，`dwBuff & CF_HELLFIRE == 0`）：

1. `IsCreationFlagComboValid()`：
   - 有 `CF_PREGEN` → 非法；
   - `(ci & CF_USEFUL) == CF_USEFUL` 且还有别的 flag → 非法；
   - 有 `CF_TOWN` 且多个 town flag → 非法。
2. `(ci & CF_TOWN) != 0` → `IsTownItemValid()`：`CF_BOY` 且 `level <= 50`，否则 `level <= 30`。
3. 否则若 `(ci & CF_USEFUL) == CF_UPER15` → `IsUniqueMonsterItemValid()`：
   记录的 level 必须等于某个**暗金怪**的 mlvl（跳过 `MT_DEFILER` / `MT_NAKRUL` / `MT_HORKDMN`）。
4. 否则 → `IsDungeonItemValid()`：level 匹配任意怪物 mlvl，否则 `level <= 30`。

校验失败 = `EventFailedPacket()`（中文「无效的数据包」），物品**不会落地**，看起来就是“消失”。

**关键结论**：记录里 `CF_UPER15` 且 level 是合法暗金怪等级时，`level > 30` 也不会被拒——
这就是「暗金怪可以掉落 ilvl30+4」的机制。`SetItems` / `SpawnItem`（`items.cpp:3266`）里暗金怪
`SpawnItem(..., onlygood=true, uper=15, lvl=monster.level)`，而 `SetupAllItems` 中
`if (uper15) iblvl = lvl + 4`（`items.cpp:1529`），所以**词缀窗口 = 记录等级 + 4**。

### 2.2 本工具采用的路线

`d1itemgen.drop_plan(ilvl)`：

| 虚拟 ilvl | 记录 level | flags | uper | onlygood | 词缀窗口 |
| --- | --- | --- | --- | --- | --- |
| 0..30 | ilvl | 0 | 0 | 原样 | `[min(ilvl//2,25), ilvl]` |
| 31..34 | ilvl-4（27..30） | `CF_UPER15\|CF_ONLYGOOD` = `0x00C0` | 15 | True | `[min(ilvl//2,25), ilvl]`（= 记录等级+4） |
| 35..50 | 不允许 `droppable=True` | — | — | — | 仅储物箱 |

- 27..30 全部是真实暗金怪等级（`work\tmp\unique_levels.py` 已逐个核对 1..30 全覆盖），
  因此 `IsUniqueMonsterItemValid()` 通过；`record_droppable()` 对 `0x00DE` / `0x02DE`（暗金多
  `CF_UNIQUE`）返回 True，对裸 ilvl 34 返回 False。
- 词缀窗口不变，所以本体生成逻辑（`GetItemBonus(..., iblvl/2, iblvl, ...)`）完全复用；
  **31~34 唯一新解锁的词缀是前缀 `Emerald`**（index 66，`IPL_ALLRES` 41~50，min_level 31）——
  这就是「为什么值得支持到 34」的直接收益，也是回归测试的锚点。
- 副作用（写进说明即可，不必规避）：
  - `CF_ONLYGOOD` 会排除 `PLOk == false` 的诅咒词缀（Clumsy / Dull 等），31~34 的生成物不会带诅咒；
  - `CF_UPER15` 自带 15% 暗金概率，`_gen_normal/_gen_unique` 用 `uper=15` 重放并按目标品质过滤种子，
    实际生成结果与所选品质一致（`validate()` + `record_droppable()` 双重校验）。
- ilvl 35..50 仍然允许（`droppable=False`），但 UI 必须红字提示「只能放储物箱，丢地上会提示
  无效的数据包并消失」，并且结果区显示 `GenResult.drop_note`。

### 2.3 双数值词缀（「国王」两条属性）

`SaveItemPower()`（`items.cpp:746`）里 `IPL_TOHIT_DAMP` / `IPL_TOHIT_DAMP_CURSE` /
`IPL_DOPPELGANGER` 先 `r = RndPL(p1, p2)` 加到伤害，再**单独一次** `CalculateToHitBonus()`：

| 词缀 | index | min_level | 伤害/主值 | 命中 | `PLOk` |
| --- | --- | --- | --- | --- | --- |
| Clumsy | 24 | 5 | −50..−75 | −6..−10 | false |
| Dull | 25 | 1 | −25..−45 | −1..−5 | false |
| Sharp | 26 | 1 | +20..+35 | +1..+5 | false |
| Fine | 27 | 6 | +36..+50 | +6..+10 | true |
| Warrior's | 28 | 11 | +51..+65 | +11..+15 | true |
| Soldier's | 29 | 16 | +66..+80 | +16..+20 | true |
| Lord's | 30 | 21 | +81..+95 | +21..+30 | true |
| Knight's | 31 | 23 | +96..+110 | +31..+40 | true |
| Master's | 32 | 29 | +111..+125 | +41..+50 | true |
| Champion's | 33 | 40 | +126..+150 | +51..+75 | true |
| King's | 34 | 28 | +151..+175 | +76..+100 | true |
| Doppelganger's | 85 | 11 | +81..+95 | +21..+30 | true |

**本轮同时修掉一个真 bug**：`CalculateToHitBonus()` 对 `-50` / `-25` 返回
`-RndPL(6,10)` / `-RndPL(1,5)`（负值）。旧实现按正数返回，导致诅咒词缀（Clumsy/Dull）生成的
`iPLToHit` 是正的，与游戏重算不一致。修法：**先按正幅度掷骰、再取负**（`_calculate_to_hit_bonus`），
既对齐数值也保持 RNG 抽取次数/映射完全一致（不能直接改成 `RndPL(-hi,-lo)`，会错位）。

`d1itemgen` 新增 API：

- `affix_value_slots(affix, kind=None, hellfire=False)` →
  `[{"key": "value"|"tohit", "label": "伤害"|"命中", "range": (lo, hi)}, ...]`；
  固定效果（攻速、充能、法术等）返回 `[]`。
- `affix_value_slot_range(affix, slot)`、`_normalize_value_target()`（int / `"151/93"` / list / tuple；
  未填的槽位用 `None`；float 非整数与越界分别报 `bad_value` / `value_out_of_range`）。
- `prefix_value` / `suffix_value` 兼容旧用法：单个 int 只钉住 slot 0，第二条属性仍然随机。

## 3. 改动清单

### 3.1 `work\lib\d1itemgen.py`

- `MAX_DROP_ILVL = 34`、`UNIQUE_DROP_BONUS = 4`、`UNIQUE_MONSTER_LEVELS = frozenset(range(1, 31))`、
  `CF_USEFUL = CF_UPER15 | CF_UPER1`。
- `droppable_level_ok()`（能力上限 0..34）、`drop_plan()`（返回 mode/record_ilvl/uper/onlygood/flags/
  affix_ilvl）、`record_droppable(create_info)`（按游戏四条校验器逐条复刻，**记录级**判断）。
  - 实现要点（第一次写错过，已修正）：`CF_TOWN` 分支要求「**只有一个** town flag 位」
    （`flags & (flags-1) == 0`，不是 `flags == CF_TOWN`）；`CF_USEFUL` 只在**恰好两位、无其它 flag**
    时合法（`(flags & CF_USEFUL) == CF_USEFUL and not (flags & ~CF_USEFUL)`），不能反过来把所有
    双位组合都判非法。修正后 Adria 的 `0x400F`（`CF_HEALER|15`）、女巫的 `0x2010`
    （`CF_WITCH|16`）等正常城镇物品不再被误报「丢地上会无效」，储物箱「检查异常物品」
    对 96 件干净物品从 5 条误报降到 0 条。
- `_generate()` / `check_combination()` 统一走 `drop_plan()`：`record_ilvl` 写记录、`uper` 传
  `_setup_all_items()` / `_search_seed()` / `_gen_*()`，`affix_ilvl` 用于词缀可达性与窗口判断；
  `display_ilvl` 保留用户填的 31~34 用于报错文案与结果展示。
- 多槽数值：`_consume_power_rolls()` 返回 `{"value", "tohit"}`；`_fast_selection()` 返回
  `(pre, suf, pre_rolls, suf_rolls)`；`_slot_value_ok()` / `_check_value_target()` /
  `_format_value_failure()` 按槽位校验并在错误信息里点名「命中」。
- 修 `_calculate_to_hit_bonus()` 的负数符号（见 2.3）。
- `_drop_ilvl_error()` 文案改为「把 ilvl 降到 34」，suggestions 同步。

### 3.2 `work\app\d1itemgen_adapter.py`

- `max_drop_ilvl = 34`、`record_droppable()`、`supports_value_slots()`、`affix_value_slots()`。
- `Affix.value_slots`；`GenResult` 新增 `prefix_values` / `suffix_values` / `drop_mode` /
  `record_ilvl` / `ilvl`。
- `generate()` 接受 `BaseItem`、list/元组/字符串形式的值；`POWER_FIELD` 补
  `IPL_TOHIT_DAMP`→(`PLDam`,+1)、`IPL_TOHIT_DAMP_CURSE`→(`PLDam`,−1)、`IPL_DOPPELGANGER`→(`PLDam`,+1)`，
  这样 `prefix_values` 能回读真实数值；`_chinese_describe()` 输出两行：
  `掉落：可丢地上：是（暗金怪掉落路线：记录等级 30 + CF_UPER15，词缀等级 34）`、
  `前缀：国王的（伤害 +151%，命中 +93%）`。
- `check_record()` 用 `record_droppable()` 复核每个存档记录，非致命 `warn`。

### 3.3 UI

- `work\app\ui_itemgen.py`
  - `MAX_DROP_ILVL = 34`；勾选「可丢地上（≤34）」时 Spinbox 上界 34，取消后 50；载入角色时
    `ilvl = min(角色等级, 34)`；固定栏 row0 = 554px / 整条 609px（≤640，不裁切）；
  - 提示文案说明 31~34 自动走暗金怪路线、35~50 只能进储物箱；
  - 结果区显示 `drop_note`（绿字）、`droppable=False` 时红字警告「丢地上会提示『无效的数据包』并消失」；
    适配层 `res.text` 里同一句「掉落：…」会被去重，结果区只出现一次；
  - 每个词缀最多两个带标签的数值输入框（`伤害 151~175` / `命中 76~100`），单槽词缀隐藏第二个，
    固定效果禁用并显示「固定效果」；`_params_dict()` 单槽发 int、双槽发 `[v0, v1]`（空槽 `None`），
    都空则不发；
  - 预览/结果用 `d1zh.power_value(aff, value, tohit=...)` 显示两个真实值；
    两槽词缀的预览行不再重复效果名（之前会出现「命中/伤害 伤害 +151 ~ +175，命中 +76 ~ +100」）。
- `work\app\d1itemgen_adapter.py`（本轮补充）
  - `Affix.range_text` 对两槽词缀逐槽输出（`伤害 +151 ~ +175，命中 +76 ~ +100`），
    `Affix.label` 不再重复拼 `effect`，下拉框文案与实际可填值一致。
- `work\app\ui_uniques.py`：`MAX_DROP_ILVL = 34`，勾选文案「可丢地上（≤34）」，
  `min_level > 34` 的暗金才自动取消勾选（实际表里没有，保留逻辑以防数据表更新）。
- `work\app\ui_stash.py` + `work\app\d1stash_adapter.py`：新增 `record_label_cn(rec)` /
  `record_name_cn(rec)`，储物箱列表、`scan_issues`、删除确认、异常对话框都显示中文名
  （格式 `中文名（English）`，无名时退回英文/`item_label`）。
  - 实现：`d1itemgen.replay_item()` 重放 + `d1zh` 中文模板；暗金用 `unique_name`，
    魔法用 `item_full_name_cn(底材, 前缀, 后缀, 法术)`；法术编号取记录 offset 224
    （重放对法术书可能取到别的法术）；按 `(saved_idx, seed, createInfo)` 缓存；
    任何异常都退回「底材中文名（魔法/暗金）」或英文名，不抛、不崩。
  - 性能：模块导入一次性 243ms（d1itemgen+d1tables）+ 16ms（d1zh）；96 件 16ms（0.17ms/件），
    缓存后 0.007ms/次；首次 `_fill_list` 265~287ms。

## 4. 测试

新增/改写：

- `work\tests\test_round5_drop.py`（改写为 34 语义，13 项）：`drop_plan` 表、normal/magic/unique 在
  20/30/31/34 的记录、Emerald@34 全抗、35/50 `drop_ilvl`、`check_combination` 契约、旧 API
  (`droppable=False`) 不变、adapter `drop_mode`/`record_ilvl`/`drop_note`、`check_record` 警告、
  无头 UI（默认 34 / 范围 1..34 / 取消后 1..50 / 红字 / 暗金页 min_level>34 自动取消）、真实存档只读。
- `work\tests\test_round7_values.py`（**12 项**）：12 个双数值词缀的槽位表、`_normalize_value_target`、
  King's `[151,93]` / `"151/93"` / `[None,93]` / 单 int 兼容、Knight's/Master's/Lord's/Champion's、
  诅咒 Clumsy `[-50,-8]` / Dull `[-25,-2]`（负数 + replay 一致）、前缀+后缀同时定值、
  越界信息点名「命中」、`d1zh` 显示、adapter `value_slots`/`prefix_values`/文案，
  以及两项**无头 UI**：两个输入框（标签 `伤害 151~175` / `命中 76~100`，单槽隐藏、固定效果禁用）、
  实时预览同时列出两条范围。
- `work\tests\test_round7_stash_names.py`（**5 项**，新文件）：96 件记录 96 个中文名、
  `中文名（English）` 格式、零/0xFF/短记录不抛异常、法杖与法术书（`法术书：传送术`、
  `召唤元素长杖`）、无头 UI 列表 96 行全中文 + `scan_issues` 名称中文 + 删除确认文案中文
  （在 `work\tmp` 副本上跑，确认框被替换为「否」，不会删任何东西）。
- 回归：`test_stash.py` 14、`test_itemgen.py` 15/15、`test_itemgen2.py` 10/10、
  `test_round3_core.py` 14/14、`test_round4_core.py` 16/16、`test_round5_drop.py` 13/13、
  `test_round5_spell.py` 13/13、`test_i18n.py` 11/11 → **合计 123 项全绿**；
  `d1editor2.py --selftest` = `SELFTEST OK`，`smoke_test.py` = `SMOKE OK`。

运行方式（务必用 venv 3.12，且设置 UTF-8）：

```powershell
$env:PYTHONIOENCODING="utf-8"
F:\Qoder\暗黑1重制版\work\build\venv312\Scripts\python.exe work\tests\test_round7_values.py
F:\Qoder\暗黑1重制版\work\build\venv312\Scripts\python.exe work\tests\test_round5_drop.py
```

## 5. 验收标准

1. ilvl 31/32/33/34 + 「可丢地上」生成的普通/魔法/暗金物品：记录 level = ilvl−4，带
   `CF_UPER15|CF_ONLYGOOD`（暗金再带 `CF_UNIQUE`），`validate() == []`，`record_droppable() == True`；
   游戏内丢地上不报「无效的数据包」。
2. ilvl 30 及以下行为与上一版完全一致（记录 level = ilvl，无 flag）。
3. 「国王的」等 12 个词缀可分别指定伤害与命中；只填一个时另一条随机；错误信息点名具体槽位；
   诅咒词缀的主值与命中都是负数且与游戏重算一致。
4. 储物箱列表显示中文名，暗金显示中文暗金名，魔法物品显示「前缀 + 底材 + of 后缀」。
5. `使用说明.txt` / `测试报告.md` / `README.txt` / `源码` 同步更新；exe 由
   `work\build\build_exe.ps1` 重新构建并复制到 `交付\` 与
   `暗黑破坏神1重构游戏本体和修改器\`。

## 6. 构建

```powershell
powershell -ExecutionPolicy Bypass -File F:\Qoder\暗黑1重制版\work\build\build_exe.ps1
```

构建后核对：`交付\暗黑破坏神1存档修改器-v2.exe` 的版本字符串、文件大小、SHA256；
启动一次确认三个页面正常（储物箱列表中文、装备页两个数值框、暗金页 ilvl 34）。
