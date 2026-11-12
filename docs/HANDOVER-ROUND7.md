# HANDOVER · Round 7（v2.5.0，2026-11-12）

本轮把用户提的三个问题都做完了：ilvl 31~34 走「暗金怪掉落路线」、双属性词缀两个输入框、
储物箱列表中文名。exe 已重新打包并三处同步，123 项测试全绿。

## 1. 现在有什么

| 位置 | 内容 |
|---|---|
| `交付\暗黑破坏神1存档修改器-v2.exe` | v2.5.0，11,358,893 字节，SHA256 `358DD1595EEC72CCB175A3EB171925BAED528196E49BF9249C2AF9C4276A911E` |
| `暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-v2.exe` | 同一个文件（SHA256 相同） |
| `交付\使用说明.txt` | 已加 v2.5.0 变更、第四节两处新 UI、第五节 ilvl 路线、第六节重写、Q&A、页脚版本/SHA |
| `交付\测试报告.md` | 新增 §12（Round 7）：根因、路线表、双数值词缀、中文名、123 项测试、截图、SHA、已知限制 |
| `交付\README.txt` | 版本/字节/SHA、Round 7 变更、源码清单更新 |
| `work\docs\ROUND7_BRIEF.md` | 本轮总纲 + 接口 + 测试/验收（给下一轮当上下文） |
| `work\docs\shots\r7_*.png` | 4 张：两槽输入、生成结果、储物箱中文名、暗金页 ≤34 |

## 2. 代码改动（只列关键文件）

### `work\lib\d1itemgen.py`
- `MAX_DROP_ILVL = 34`、`UNIQUE_DROP_BONUS = 4`、`UNIQUE_MONSTER_LEVELS`、`CF_USEFUL`。
- `drop_plan(ilvl)`：0..30 原样；31..34 → 记录等级 `ilvl-4` + `CF_UPER15|CF_ONLYGOOD`（暗金再
  `CF_UNIQUE`），词缀窗口仍是 `[min(ilvl//2,25), ilvl]`；35..50 只允许 `droppable=False`。
- `record_droppable(create_info)`：按 `IsPItemValid()` 复刻，**town flag 恰好一位**、
  `CF_USEFUL` 仅在带其它 flag 时非法（修正了第一版的误报）。
- 多槽数值：`affix_value_slots` / `_normalize_value_target` / `_consume_power_rolls` /
  `_slot_value_ok` / `_format_value_failure`；`prefix_value` 接受 int / `"151/93"` / list。
- `_calculate_to_hit_bonus` / `_tohit_bonus_range` 修正负数符号（Clumsy/Dull）。
- `_generate()` / `check_combination()` 统一走 `drop_plan()`，`uper=15` 重放后按目标品质过滤种子。

### `work\app\d1itemgen_adapter.py`
- `max_drop_ilvl`、`record_droppable`、`supports_value_slots`、`affix_value_slots`、
  `Affix.value_slots`；`GenResult.prefix_values/suffix_values/drop_mode/record_ilvl/drop_note/droppable`。
- `Affix.range_text` 两槽逐槽显示（`伤害 +151 ~ +175，命中 +76 ~ +100`），`Affix.label` 不再重复 effect。
- `generate()` 接受 `BaseItem` 与多种数值形态；`check_record()` 用 `record_droppable` 复核（非致命 warn）。

### `work\app\ui_itemgen.py`
- 「可丢地上（≤34）」；Spinbox `to=34/50`；默认 ilvl = min(角色等级, 34)；固定栏 row0 554px（≤640）。
- 每个词缀两个带标签输入框（`伤害 151~175` / `命中 76~100`），单槽隐藏、固定效果禁用显示「固定效果」。
- `_params_dict()` 单槽 int、双槽 `[v0,v1]`；`_preview_values()` 槽位级错误（点名「命中」）。
- 结果区 `drop_note` 绿字/红字，去重适配层重复的「掉落：…」行；两值用 `d1zh.power_value(..., tohit=)`。

### `work\app\ui_stash.py` + `d1stash_adapter.py`
- `record_name_cn` / `record_label_cn`：`replay_item` + `d1zh` 拼中文名；法术编号取记录 offset 224；
  `(saved_idx, seed, createInfo)` 缓存；异常一律兜底不抛。
- 列表、`scan_issues`、删除确认、异常对话框全部中文（`中文名（English）`）；名称列 320→380。

### 其它
- `work\app\ui_uniques.py`：`MAX_DROP_ILVL=34`、文案 ≤34、`min_level>34` 才自动取消勾选。
- `work\app\d1env.py`：`APP_VERSION = "2.5.0"`。
- `work\build\build_exe.ps1`：加 UTF-8 BOM（PS 5.1 读无 BOM 的 UTF-8 会乱码报错；用 `pwsh` 或
  带 BOM 的 `powershell` 均可）。

## 3. 测试（123 项，全绿）

```
test_stash.py                 14 OK
test_itemgen.py               15/15
test_itemgen2.py              10/10
test_round3_core.py           14/14
test_round4_core.py           16/16
test_round5_drop.py           13/13   ← 改写为 34 语义 + 无头 UI
test_round5_spell.py          13/13   ← 真实存档 36 个 .sv SHA256 不变
test_i18n.py                  11/11
test_round7_values.py         12/12   ← 新，含 2 项无头 UI
test_round7_stash_names.py     5/5    ← 新
```
`d1editor2.py --selftest` = `SELFTEST OK`；`smoke_test.py` = `SMOKE OK`；
打包自检 = `SELFTEST OK` + `BUILD OK`。

## 4. 已知限制 / 注意

- ilvl 35~50 仍然只能放储物箱（游戏没有合法掉落来源），UI 已红字提示。
- 31~34 的生成物带 `CF_ONLYGOOD`，不会出现诅咒词缀，属掉落路线固有行为。
- 储物箱名字里没有中文译文的物品只显示英文；预生成/损坏记录退回「底材中文名（魔法/暗金）」。
- 首次打开储物箱列表约 240ms 一次性导入（之后 0.007ms/件）。
- `work\backup_saves\stash.sv` 是测试用的 96 件样本；`work\tests\test_round7_stash_names.py`
  会把样本复制到临时目录再操作，不会删改样本本身。
- 下次打包若用 `powershell`（5.1）请确认 `build_exe.ps1` 仍带 BOM。

## 5. 下一轮可以做

- 储物箱物品详情/编辑（当前只读 + 删除）。
- ilvl 35~50 若未来 DevilutionX 放开掉落校验，只需改 `MAX_DROP_ILVL` 与 `drop_plan`。
- 把 `work\tmp\shots_r7.py` 并入 `work\build\make_shots.py`（加 `D1_SHOTS_R7=1` 分支）。
