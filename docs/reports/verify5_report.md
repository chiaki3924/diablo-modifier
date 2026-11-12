# Round 5 验证报告（verify5）

- 日期：2026-11-12（01:00 ~ 01:05）
- ROOT：`F:\Qoder\暗黑1重制版`
- 版本：**v2.4.0**（`work\app\d1env.py` `APP_VERSION = "2.4.0"`）
- 结论：**通过**。9 个测试命令全部 exit 0；独立实测 9/9；7 张截图；打包 BUILD OK、内置 selftest exit 0；真实存档 SHA256 前后完全一致；三处 exe SHA256 相同。
- 安全：全程未写真实存档（`%APPDATA%\diasurgical\devilution`），未改源码/测试，游戏未启动（打包与截图前后均确认无 devilutionx 进程）。

---

## 1. 测试（串行，9 个命令）

日志：`work\tmp\verify5_tests.log`；机读汇总：`work\tmp\verify5_tests.json`。

| # | 命令 | exit | 结果 | 耗时 |
|---|---|---|---|---|
| 1 | `_py312\python.exe work\tests\test_round5_drop.py` | 0 | **11/11** | 1.1s |
| 2 | `_py312\python.exe work\tests\test_round5_spell.py` | 0 | **12/12** | 2.2s |
| 3 | `_py312\python.exe work\tests\test_round4_core.py` | 0 | **16/16** | 1.4s |
| 4 | `_py312\python.exe work\tests\test_itemgen.py` | 0 | **15/15** | 1.0s |
| 5 | `_py312\python.exe work\tests\test_itemgen2.py` | 0 | **10/10** | 4.0s |
| 6 | `_py312\python.exe work\tests\test_stash.py` | 0 | **14/14** | 3.9s |
| 7 | `_py312\python.exe work\tests\test_i18n.py` | 0 | **11/11** | 0.4s |
| 8 | `work\build\venv312\Scripts\python.exe work\app\d1editor2.py --selftest` | 0 | SELFTEST OK | 0.8s |
| 9 | `work\build\venv312\Scripts\python.exe work\build\smoke_test.py` | 0 | SMOKE OK | 6.6s |

合计 **89** 条测试全部通过（11+12+16+15+10+14+11）；selftest 与 smoke 串行执行，无 97→96 计数竞态。

- `test_round5_drop` 的 headless UI 子进程：`UI-CHILD-OK`（venv312，tkinter 8.6）。
- `test_round5_spell` 的 headless CharTab 子进程：`UI-CHILD-OK`；结束时输出“真实存档目录未被写入（5 个文件 SHA256 一致）”。
- selftest：pyc 加载、四页控件、读取 single_1、储物箱 81 件、生成器、暗金 89、词条、合法/非法预检、排序、真实存档 4 个 `.sv` SHA 一致。
- smoke：备份 `smoke_stash.sv.bak-*` 写在 `work\tmp`，真实存档 4 个 `.sv` SHA 一致。

## 2. 功能实测（`work\tmp\verify_r5.py`，独立实现，9/9）

运行：`work\build\venv312\Scripts\python.exe work\tmp\verify_r5.py`（exit 0，1.54s）。日志：`work\tmp\verify_r5.log`。

| 项 | 结论 | 实测样本 |
|---|---|---|
| 丢地：ilvl≤30 生成 | OK | 普通 ilvl 30 `iCreateInfo=0x001E`；魔法 `0x001E` Master's Long Sword；暗金 `0x021E` The Grandfather；`(ci&0x3F)==ilvl`、flags 组合合法、`IsDungeonItemValid` 等价判断为真、`validate()==[]` |
| 丢地：31/34/50 | OK | 三种品质 + adapter 全部抛 `drop_ilvl`（信息含“30”、建议含“把 ilvl 降到 30”）；`droppable=False` 仍按原 ilvl 生成；adapter `drop_note` 含“只能放储物箱” |
| 丢地：headless UI | OK | 载入 34 级角色 → 默认 `var_drop_safe=True`、ilvl 钳到 30、Spinbox 1..30、`_params_dict()["droppable"]=True`；固定栏 `reqwidth=609px`（row0 554px）≤ 640px；取消勾选 → 1..50、ilvl 34 预览“可丢地上：否”、红字 `#c62828`、含“只能放储物箱/无效的数据包”；重新勾选钳回 30 |
| 丢地：暗金页 | OK | The Grandfather(min_level 27)：勾选、ilvl 27、预览“可丢地上：是”；`min_level>30` 分支用合成暗金(min_level=34) 验证：自动取消勾选、范围 1..50、提示“只能放储物箱，不能丢地上”、再次勾选被拒绝；暗金选项行 reqwidth ≤640 |
| 丢地：真实 stash | OK | 81 件物品中 **9 件 ilvl>30**（43×3、49×5、35×1），`check_record(deep=True)` 全部 `warn`、**0 fatal**；扫描前后物品数 81 不变、真实 `stash.sv` 与副本 SHA256 均不变 |
| 法术：白名单 | OK | `learnable_spells()` 22 条，id = 1,2,3,4,6,7,8,10,11,12,13,14,15,20,21,23,29,30,31,33,35,36；不含 5/9/16/17/18/19/22/24/25/26/27/28/32/34/37+；多人 23 条（含 34） |
| 法术：位图 | OK | `spell_bitmask`: 1→0x1、12→0x800、36→0x800000000、0→0 |
| 法术：原子写 | OK | 副本 `set_spell_level(12,1)`：等级变化仅 `[(12,0,1)]`，位变化仅 `[11]`；47 个 `pSplLvl` 全量回写；save/reload 后等级与位图完全一致；`spell_bit_mismatches()==[]` |
| 法术：共存/批量/职业位 | OK | 先学 3 再学 20 共存，位图只加 bit2/bit19；26/27/28 职业位保留；`learn_all(15)` 只把 22 条设为 15；`forget_all()` 只清 22 条并清位，职业位保留；隐藏 37~46 未被触碰 |
| 法术：清理非原版 | OK | 清 21 个（37~46 + 5/9/16/17/18/19/22/24/25/32/34）等级与位归零；26/27/28 的等级与位保留；22 条原版等级不变；save/reload 后保持 |
| 法术：headless UI | OK | 树 22 行、行文本 `id · 中文名`、row→id 映射正确、白名单说明 Label 存在、“清理非原版法术”按钮存在；应用 12 号=3 后其它 21 行文本/46 个等级不变；清理后 32/37=0、26=5、树仍 22 行、隐藏提示 3→1、位图无不一致 |

真实存档（开始/结束快照，逐字节一致）：

| 文件 | 大小 | SHA256（开始 = 结束） |
|---|---|---|
| single_0.sv | 3,415,207 | `E3029DFD92AA7AA46154014B946265EE7C0B436180798866F534E93F475E6D8F` |
| single_1.sv | 1,053,779 | `893FA93553C6E9F28BC17643A0700A73C7EFB2C54877732582538B5E668ED050` |
| single_2.sv | 2,904,940 | `F5128663C7E071A7F8033BCD2A907DDCF5C8B948C89EC0D541651319D5DEE172` |
| stash.sv | 85,995 | `85D45A73C495FD144FC286FC86CA8129EE785CB53BF6E1F8B3EBA03654477C60` |
| diablo.ini | 3,710 | `5DBDF2192DE32D2B38A5A99A15EBA326A28CF5899E39A2FCB0E419D6BCF8B85F` |

> 这是当前用户存档的新快照（不是 Round 4 旧哈希）；测试、截图、打包、复制 exe 之后再次核对，5 个文件全部一致。

## 3. 截图（7 张，`work\docs\shots\`）

`make_shots.py` 只**新增** Round 5 段（`D1_SHOTS_R5=1` 单独运行），既有截图未重出。截图进程 `D1_READONLY=1` + `ALLOW_PROTECTED_WRITES=False`；角色/储物箱都载入 `work\tmp` 副本。窗口 1300×1080（角色页 1300×1320，保证 22 行全部可见），右侧列完整、中文不截断。

| 文件 | 内容 |
|---|---|
| `shots/r5_drop_safe_on.png` | 装备生成页：☑ 可丢地上（≤30）、ilvl 30、预览“可丢地上：是（ilvl 30 ≤ 30）” |
| `shots/r5_drop_safe_off.png` | 取消勾选：ilvl 34、范围恢复 1..50、红字“可丢地上：否…”+“⚠ ilvl>30…丢地上会提示「无效的数据包」并消失” |
| `shots/r5_unique_drop.png` | 暗金页 The Grandfather(min 27)：☑ 可丢地上、ilvl 27、预览“可丢地上：是（ilvl 27 ≤ 30）”、提示“勾选：ilvl 1~30…” |
| `shots/r5_stash_warn.png` | 储物箱「检查异常物品」结果窗：9 条 ilvl>30“警告”+ 1 条“护甲为满值（直接写入记录，非 seed 重放值）”，共 10 行（见遗留 2） |
| `shots/r5_spell_list.png` | 角色页法术：22 行（1…36）、“只显示 1.5.5 原版可学习法术…”说明、“隐藏 3 个非原版/职业法术等级”、“清理非原版法术”按钮 |
| `shots/r5_spell_cleanup.png` | 清理后：日志“已清理 21 个非原版法术（等级与记忆位归零）…”，隐藏提示 3 → 1，26 号职业法术保留 5，树仍 22 行 |
| `shots/r5_spell_apply.png` | 选中 12 · 火球术、等级设为 3 后：该行=3，其它 21 行等级不变；日志“法术「火球术」等级设为 3（尚未保存）” |

截图流程前后 `saves_hash()` 一致，脚本末尾打印“真实存档 SHA256 未变”。

> 说明：真实 single_2.sv 本身没有隐藏法术等级（`hidden=[]`）。为展示“隐藏提示/清理前后变化”，截图用的是 `work\tmp\r5_char_shot.sv` 副本，并在副本里预置 26=5、32=4、37=7；**真实存档未做任何预置**。

## 4. 打包与交付

- 命令：`& work\build\build_exe.ps1 -SkipVenv`
- 结果：**BUILD OK**（exit 0，10.3s）；产物 `work\build\dist\暗黑破坏神1存档修改器-v2.exe`，10.81 MB（11,333,323 字节）。
- 内置 `--selftest`：**exit 0**，`SELFTEST OK`。
- 自检日志含 `中文数据 = 中文数据：d1i18n（d1i18n.py）`（build_exe.ps1 的 `d1i18n` 校验通过）。
- 自检日志：`真实存档 4 个文件 SHA256 前后一致（未写入）`。
- 包内容核对（直接读 exe 内 PyInstaller 归档，不是只看源码）：
  - `_d1lib\py\d1tables.py` 含 `def learnable_spells`、`D1_LAST_SPELL`（已确认字节存在）；
  - PYZ 内 `d1env` 代码常量含 `2.4.0`（`2.4.0 in d1env consts: True`），即 exe 版本 v2.4.0。
- 日志：`work\tmp\build_r5.log`。

三处 exe（SHA256 完全相同）：

| 位置 | 大小 | SHA256 |
|---|---|---|
| `work\build\dist\暗黑破坏神1存档修改器-v2.exe` | 11,333,323 | `88F4EB83B8A0AB015C14A9A75AE293E1578CF27E981EF6FA723A5F9365CEE4FC` |
| `交付\暗黑破坏神1存档修改器-v2.exe` | 11,333,323 | `88F4EB83B8A0AB015C14A9A75AE293E1578CF27E981EF6FA723A5F9365CEE4FC` |
| `暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-v2.exe` | 11,333,323 | `88F4EB83B8A0AB015C14A9A75AE293E1578CF27E981EF6FA723A5F9365CEE4FC` |

（复制后 `THREE_MATCH=True`。）

## 5. 遗留 / 说明

1. **9 件旧高 ilvl 物品未删未改**：真实 stash 81 件中 9 件 ilvl>30（43×3、49×5、35×1，如 King's Sword of carnage、Obsidian Ring of the zodiac、Holy Shield of the tiger）。检查结果全部是 `warn`，只读展示，未做任何修改/删除；它们仍只能放储物箱，不能丢地上。
2. **储物箱深度检查还有 1 条非 ilvl 警告**：Holy Shield of the tiger 带“护甲为满值（直接写入记录，非 seed 重放值）”，所以 `r5_stash_warn.png` 共 10 行（9 条 ilvl>30 + 1 条满值）。这是既有历史数据提示，不是本轮 bug，也未改动。
3. **暗金页 `min_level>30` 分支当前不可由真实数据触发**：89 件可用暗金中 `min_level` 最大 27（The Grandfather / Royal Circlet）。该分支属于防御性代码，用合成暗金（min_level=34）验证通过（自动取消勾选、拒绝再次勾选、只能放储物箱提示）。drop5 单测同样用 fake 覆盖。
4. **法术隐藏位保守**：`clear_non_original_spells()` 只清 37~46 与不可学习法术，26/27/28 三个职业自带能力的位/等级保留；`learn_all/forget_all` 也只动 22 条可见法术。截图副本额外预置的隐藏法术仅存在于 `work\tmp`。
5. **截图页面高度**：角色页用 1300×1320 让 22 行法术一次显示完整（默认 1260×920 只能显示约 14 行）；装备/暗金/储物箱仍为 1300×1080。未修改任何布局代码，只在截图脚本里调窗口大小。
6. 本次未发现源码 bug；`make_shots.py` 只新增 R5 段，其它截图与既有功能未受影响。

## 6. 相关文件

- 测试日志：`work\tmp\verify5_tests.log` / `.json`
- 实测脚本与日志：`work\tmp\verify_r5.py` / `work\tmp\verify_r5.log`
- 截图日志：`work\tmp\make_shots_r5.log`
- 打包日志：`work\tmp\build_r5.log`
- 截图：`work\docs\shots\r5_*.png`（本报告 7 张：drop_safe_on/off、unique_drop、stash_warn、spell_list/cleanup/apply）
