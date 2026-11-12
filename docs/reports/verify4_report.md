# Round 4 验证报告（verify4 · 独立复核 + 截图 + 打包 + 交付复制）

> 生成时间：2026-11-11 22:32–22:50（Asia/Shanghai）
> ROOT = `F:\Qoder\暗黑1重制版`；执行者：verify4（只读源码，仅改 `work/build/make_shots.py` 并新增 Round 4 段）
> 被测版本（全程未变，见 §2）：`d1itemgen.py` @22:26:08、`d1itemgen_adapter.py` @22:25:03、`ui_itemgen.py` @22:31:08、`test_round4_core.py` @22:25:28
> **真实存档全程 0 写入**：开始 / 结束各做一次 SHA256 快照（17 个存档 + 1 个 ini，逐字节一致，见 §6）。

## 0. 结论（一句话）

**全部通过**：5 套测试 + selftest + smoke 全绿；`verify_r4.py` **54/54** 项 PASS；
7 张 Round 4 截图合格；打包 `--selftest` exit 0（日志含 `d1i18n`、真实存档 SHA256 一致）；
exe 已复制到 `交付\` 与 `暗黑破坏神1重构游戏本体和修改器\`，**三处 SHA256 相同**；
真实存档（含所有 `.bak`）与 9 个源码文件哈希前后完全一致。**无功能缺陷遗留**；只剩 3 条观感/文案级观察（§8），
probe4 的 A1–A8 中 A1/A2/A3/A4/A5/A6/A8 全部已闭合（A4/A6/A8 有 `test_round4_core.py` 用例覆盖，本轮又独立复跑）。

---

## 1. 环境与命令总表

| # | 命令 | 结果 | 耗时 |
|---|---|---|---|
| 1 | `& _py312\python.exe work\tests\test_round4_core.py` | **exit 0**，`16/16 tests passed in 1.15s` | 1.5 s |
| 2 | `& _py312\python.exe work\tests\test_itemgen.py` | **exit 0**，`15/15 tests passed` | 1.0 s |
| 3 | `& _py312\python.exe work\tests\test_itemgen2.py` | **exit 0**，`10/10 tests passed in 4.00s` | 4.3 s |
| 4 | `& _py312\python.exe work\tests\test_stash.py` | **exit 0**，`Ran 14 tests in 4.014s ... OK` | 4.1 s |
| 5 | `& _py312\python.exe work\tests\test_i18n.py` | **exit 0**，`11/11 tests passed` | 0.4 s |
| 6 | `& work\build\venv312\Scripts\python.exe work\app\d1editor2.py --selftest` | **exit 0**，`SELFTEST OK`（含「真实存档 4 个文件 SHA256 前后一致（未写入）」） | 0.9 s |
| 7 | `& work\build\venv312\Scripts\python.exe work\build\smoke_test.py` | **exit 0**，`SMOKE OK`（真实存档 SHA256 前后一致） | 7.0 s |
| 8 | `& _py312\python.exe work\tmp\verify_r4.py --no-gui` | **exit 0**，`36 项 PASS 36 / FAIL 0`（GUI 段 4 项 SKIP） | 0.6 s |
| 9 | `& work\build\venv312\Scripts\python.exe work\tmp\verify_r4.py` | **exit 0**，`54 项 PASS 54 / FAIL 0` | 4.6 s |
| 10 | `$env:D1_SHOTS_R4="1"; & work\build\venv312\Scripts\python.exe work\build\make_shots.py` | **exit 0**，7 张全 saved，末尾断言「真实存档 SHA256 未变」 | 36.8 s |
| 11 | `& "F:\Qoder\暗黑1重制版\work\build\build_exe.ps1" -SkipVenv` | **BUILD OK**，exe 10.79 MB，内置 selftest exit 0 | 10.3 s |
| 12 | `Start-Process work\build\dist\暗黑破坏神1存档修改器-v2.exe --selftest -Wait` | **exit 0**（2 s），日志 2041 B，含 `d1i18n`、含「真实存档…一致」 | 2.0 s |

> 说明：`_py312\python.exe`（3.12.10）**不自带 tkinter**，所以 GUI 段（实时预览 / 推荐 ilvl / 背包 confirm）
> 用 `work\build\venv312\Scripts\python.exe`（3.12.14，带 tkinter 8.6）跑；`verify_r4.py` 用 `--no-gui` 自动跳过 GUI 段，
> core/适配器/写副本等 36 项在 `_py312` 上独立跑通（两套解释器结论一致）。

日志留档：

- `work\tmp\verify_r4_nogui.log`、`work\tmp\verify_r4_gui.log`
- `work\tmp\make_shots_r4.log`、`work\tmp\build_r4.log`
- `work\tmp\snapshot_before.txt`、`work\tmp\snapshot_after.txt`、`work\tmp\snapshot_final.txt`

---

## 2. 基线：被测源码快照（全程未改）

| 文件 | 字节 | SHA256(前 16) | mtime |
|---|---|---|---|
| `work\lib\d1itemgen.py` | 172 859 | `19AD1F4313E7255F…` | 22:26:08 |
| `work\lib\d1stash2.py` | 37 874 | `5555F184EF6AA528…` | 20:41:25 |
| `work\lib\d1i18n.py` | 47 136 | `16610F5CB63E1CB1…` | 20:38:52 |
| `work\lib\d1tables.py` | 48 845 | `CB968A6565B431B7…` | 19:45:26 |
| `work\app\d1itemgen_adapter.py` | 115 993 | `414D6F39E689ED23…` | 22:25:03 |
| `work\app\ui_itemgen.py` | 92 820 | `EFBEFBA140DDC47A…` | 22:31:08 |
| `work\app\ui_common.py` | 10 942 | `C675330A28D4F8B4…` | 20:39:45 |
| `work\app\d1editor2.py` | 30 398 | `C23B805CE39F19E0…` | 20:41:57 |
| `work\tests\test_round4_core.py` | 39 987 | `99F382F7B5B6B1DE…` | 22:25:28 |

> 开始快照与结束快照**逐字节一致**（`Compare-Object` 无差异），即本次验证未修改任何源码/测试。
> 唯一被改的文件是 `work\build\make_shots.py`（17 767 B → 28 737 B）：只新增 `r4_app / r4_first_valid / r4_pick_base /
> r4_real_generate / r4_main` 与 `D1_SHOTS_R4` 开关，旧截图段一行未动（旧 `r3_*` / `r2_*` / `tab_*` 的 mtime 仍是 20:51–20:52 与 19:46）。

---

## 3. 功能实测（`work\tmp\verify_r4.py`）

覆盖任务卡 §1 的 7 组：实时预览、全词缀、推荐 ilvl、满值、法术法杖、写储物箱副本、满值+背包 confirm。
全量 54 项（含 4 项 GUI 专属在 `--no-gui` 下跳过 → 36 项）。以下为关键样本原始输出。

### 3.1 实时预览（不生成物品）

锁子甲 / 魔法 / ilvl=20，选好前缀「勇敢」+ 后缀「稳定」，右侧预览**未生成时**即可读全：

```
稳定勇敢锁子甲（魔法）

底材：锁子甲（Chain Mail）    防具/中型护甲  2x3

基础属性（自然范围 → 满值）
  护甲：18 ~ 22     满值 22
  耐久：14 ~ 40 / 最大 55   满值 55
  需求：力量 30
  基础价值：1,250

词缀（全部显示；生成时按 ilvl 校验）
  前缀：勇敢（Valiant） 护甲 +56 ~ +70  〔ilvl 10~21〕
  后缀：稳定（stability） 硬直恢复 固定效果  〔ilvl 10~21〕

合法性（ilvl=20）
  ✔ 规则检查通过
    该组合符合游戏规则（实时预览不搜索 seed）。
  → 当前 ilvl 20（前缀/后缀共同合法区间：ilvl 10~21） 已在合法区间内，可以直接生成。
```

- 3 个底材（Chain Mail / Long Sword / Long Staff）都断言到 `基础属性 / 护甲 / 耐久 / 伤害 / 词缀 / 合法性 / ilvl` 七个字段。
- **未生成物品**：把 `ItemGen.generate` 换成计数桩后，`preview_text()` 调用 **0 次**；`_last_results` 仍为空。

### 3.2 全词缀 vs eligible（Chain Mail）

```
prefix: all=31  eligible(20)=14  eligible(30)=14
suffix: all=62  eligible(20)=18  eligible(30)=11
```

- Chain Mail 的 31 条前缀 + 62 条后缀，label **100% 带** `〔ilvl L~H〕`（缺区间 0 条）。
- 预览正文里标了「31 前缀 / 62 后缀」，说明「全部显示、生成时按 ilvl 校验」。

```
生锈（Rusted） 护甲 -50 ~ -25 〔ilvl 1~3〕
优良（Fine） 护甲 +20 ~ +30 〔ilvl 1~3〕
脆弱（Vulnerable） 护甲 -100 ~ -51 〔ilvl 3~7〕
强壮（Strong） 护甲 +31 ~ +40 〔ilvl 3~7〕
...
```

**L>50 的 Godly（probe4 的 A2，已修）**：

```
神佑（Godly） 护甲 +171 ~ +200 〔需要 ilvl 60（超出可选 1~50，无法生成）〕
band = (60, 50)            ← lo > hi，不再诈称 (50,50)
recommend_ilvl = None      ← 不再推荐 ilvl=50
预览合法性段：
  ✘ 前缀「神佑」需要 ilvl 60（超出可选 1~50，无法生成），请换一条词缀
```

### 3.3 推荐 ilvl（Ring + Obsidian + of the heavens）

| 当前 ilvl | 推荐 ilvl | 期望 |
|---|---|---|
| 20 | **25** | 25（低于交集下限 25 → 取下限） |
| 30 | **30** | 30（当前合法 → 保持当前值） |
| 50 | **49** | 49（高于交集上限 49 → 取上限） |

ilvl=20 时预览还给出：`→ 推荐 ilvl 25（前缀/后缀共同合法区间：ilvl 25~49）；点「用推荐 ilvl」可自动填入。`

### 3.4 满值（Chain Mail，`max_ac + full_durability`）

```
记录: Chain Mail of the wolf  AC=22  dur=55/55
备注: 护甲取最大 22；耐久取满 55
validate()                        = ['replay mismatch AC: game would set 19, record has 22']
validate(allow_ac_override=True)  = []
check_record                      = [('warn', '护甲为满值（直接写入记录，非 seed 重放值）')]
```

- `AC == base_preview.max_ac(22)` ✔；`durability == maxDur(55)` ✔（用的是**词缀之后**的 `maxDur`，本例无 IPL_DUR 词缀，故等于底材 55）。
- 默认 `validate` **只报 AC 一条**（`durability` 本就在忽略列表）；`allow_ac_override=True` → `[]`。
- 储物箱「检查异常物品」只给 `warn`，**不判 fatal**，不会误导用户删物品。
- 顺带复核 probe4 的 A5：`base_preview` 自然耐久是 **floor 14~40**（不是 ceil 15~42），已修。

### 3.5 法术法杖

**（a）普通长杖 ×10，随机法术 + `require_staff_spell=True` → 10/10**

```
 1. Long Staff of Town Portal   spell= 7 charges=  8 OK
 2. Long Staff of Guardian      spell=13 charges= 20 OK
 3. Long Staff of Healing       spell= 2 charges= 38 OK
 4. Long Staff of Holy Bolt     spell=31 charges= 71 OK
 5. Long Staff of Phasing       spell=10 charges= 63 OK
 6. Long Staff of Phasing       spell=10 charges= 53 OK
 7. Long Staff of Inferno       spell=20 charges= 27 OK
 8. Long Staff of Holy Bolt     spell=31 charges= 56 OK
 9. Long Staff of Nova          spell=18 charges= 27 OK
10. Long Staff of Nova          spell=18 charges= 23 OK
```

**（b）普通长杖 + 指定 Firebolt + 指定充能 63**

```
名称: Long Staff of Fireball / 火球术长杖
spell=12 charges=63/63 seed=4251055886
validate() = []
```

**（c）魔法长杖 + 前缀 King's + `require_staff_spell=True`**

```
名称: King's Staff of Apocalypse / 天启国王的长杖     （另一次抽样：King's Staff of Guardian）
prefix='国王的' suffix='' spell=24 charges=8/8
validate() = []
```

**（d）魔法长杖 + 后缀 → 正确拒绝**

```
ItemGenError code=staff_spell_suffix
法术法杖没有后缀：GetStaffSpell() → GetStaffPower() 只会给前缀，
游戏不可能生成「Long Staff」+ 后缀「sorcery」的法杖
```

**（e）probe4 遗留 A1 复测：魔法长杖 +「随机法术」（不指定 spell）也必须带法术 → 10/10**

```
 1. Flaming Staff of Elemental      spell=29 charges= 46 OK
 2. Master's Staff of Golem         spell=21 charges= 26 OK
 3. Dull Long Staff of Guardian     spell=13 charges= 17 OK
 4. Crimson Long Staff of Golem     spell=21 charges= 17 OK
 5. King's Staff of Bone Spirit     spell=36 charges= 56 OK
 6. Red Long Staff of Fireball      spell=12 charges= 40 OK
 7. Spider's Staff of Flame Wave    spell=15 charges= 20 OK
 8. Crimson Staff of Firebolt       spell= 1 charges= 72 OK
 9. Lapis Staff of Town Portal      spell= 7 charges= 11 OK
10. Diamond Staff of Teleport       spell=23 charges= 22 OK
```

> probe4 记录的是「20 次里 16 次是属性法杖」；现在 UI 对法术法杖固定传 `require_staff_spell=True`，
> API 层 10/10 必带法术/充能 → **A1 已闭合**。

### 3.6 写储物箱副本后重开校验（`work\tmp\stash_r4.sv`）

```
副本原 SHA256: 820B70A648431B2D…（= 真实 stash.sv 的哈希）
副本新 SHA256: 044A549D3B4FDEFA7650B621993C64DE1A198A7C30F1EEABB2CA5123AA8BC4B1
物品数: 116 -> 118（pages=[0,1,2,3,6,7,8,9,10,11,95,97,98,99]）  写入位置: (0,7,1) / (0,0,2)
满值锁子甲: AC=22 dur=55/55 name='Chain Mail'  validate(allow_ac_override=True)=[]
法术法杖:   spell=12 charges=63/63 name='Long Staff of Fireball'  validate=[]
真实 stash.sv SHA256（未变）= 820B70A648431B2DB3610D67592AD3608FF04B1455EFF5CE3352C08FBC10F2F0
```

- 用 `d1stash2.load_stash()` 打开副本 → `add_record()` ×2 → `save(backup=False)` → **重新打开**再校验：
  物品数 +2、`record_to_fields` 的 `AC / durability / maxDur / spell / charges` 全部正确、`validate` 通过。
- 写入前后副本哈希变了（证明真的落盘），**真实 `stash.sv` 哈希没变**。

### 3.7 满值 + 写入背包（HEADLESS confirm）

```
[PASS] 角色副本已载入（背包目标不是真实存档） :: work\tmp\hero_r4.sv
[PASS] gen_to_backpack 前参数带满值（max_ac/full_durability=True）
[CONFIRM] 满值物品写入背包会失效: 背包写入只保存 seed，游戏会按 seed 重建物品：
· 「护甲满值 / 耐久满值」在背包里会被重建成随机值；
· 想要满值请点「生成到储物箱」——那里写完整 368 字节记录，满值生效。

仍然写入角色背包吗？ -> True
[SPY] write_to_backpack 被调用：1 件（测试桩，未写盘）
```

- `uic.HEADLESS=True` → `confirm()` 直接返回 `True` 并打印；确认**走到了 confirm 分支**（参数确实带满值）。
- 实际写盘函数被测试桩替换（不写任何存档）；角色对象来自 `work\tmp\hero_r4.sv` 副本。
- 预览区同时断言到「满值只对「生成到储物箱」有效；写背包会被游戏按 seed 重建为随机值」这段文案。

---

## 4. 截图（7 张，`work\docs\shots\`）

执行：`$env:D1_SHOTS_R4="1"` → `make_shots.py`（只跑 Round 4 段，旧图不动）。
**真实存档哈希在截图流程前后由脚本断言未变**；窗口在 R4 段放大到 1300×1080（避免底栏遮住左列内容），
储物箱目标切到 `work\tmp\stash_r4_shot.sv` 副本（日志可见「已载入储物箱: stash_r4_shot.sv」）。

| # | 文件 | 大小 | 说明 |
|---|---|---|---|
| 1 | `work\docs\shots\r4_live_preview.png` | 137 266 B | 锁子甲 + 魔法 + 前缀「勇敢」/后缀「稳定」+ ilvl 20，右侧**未生成**的完整实时预览（基础属性/词缀/合法性/推荐 ilvl 全可读） |
| 2 | `work\docs\shots\r4_all_affixes.png` | 148 522 B | 前缀下拉展开（30 行可见），每行都带 `〔ilvl L~H〕`：从「生锈〔ilvl 1~3〕」到「钻石〔ilvl 26~50〕」，用 `capture_composite` 合成，无黑边 |
| 3 | `work\docs\shots\r4_max_stats.png` | 141 318 B | 「4. 基础属性」选「满值（护甲最大 + 耐久满）」+ 灰字自然范围（护甲 18~22 满 22；耐久 14~40/最大 55 满 55），预览出现「满值提示：满值只对「生成到储物箱」有效…」 |
| 4 | `work\docs\shots\r4_staff_spell.png` | 147 903 B | 长杖 + 形态「法术法杖（带充能）」+ 法术「火焰弹（Firebolt）充能 40~80」+ 充能目标 60，预览「法杖／形态／法术／目标充能 60」全显示，后缀行写明「法术法杖没有后缀」 |
| 5 | `work\docs\shots\r4_recommend.png` | 140 479 B | Ring + Obsidian + of the heavens + **ilvl 故意填 50**：预览给出「✘ ilvl 太高…请把 ilvl 降到 49（24..49 都可以）」+「→ 推荐 ilvl 49」，右下校验标签红字，「用推荐 ilvl」按钮变为可用并显示 `推荐 ilvl: 49` |
| 6 | `work\docs\shots\r4_generated_max.png` | 153 035 B | **真实生成**一件满值锁子甲（`Amber Mail of absorption`）后 `_show_results`：属性「护甲 22，耐久 55/55」、基础属性「护甲取最大 22；耐久取满 55（直接写入记录）」、`✔ 合法性校验通过`、记录长度 368 字节（**未写盘**） |
| 7 | `work\docs\shots\r4_generated_staff.png` | 133 726 B | **真实生成**一件法术法杖（`Long Staff of Fireball`，普通品质 ilvl=20）后 `_show_results`：`法术：火球术（Fireball） 充能 63/63`、技术详情 `spell Fireball charges 63/63`、`✔ 校验通过`（**未写盘**） |

检查结论：7 张均无控件重叠/遮挡（放大窗口后左列「4. 基础属性」与固定底栏不再互相裁剪）；
中文无截断；右侧预览可读；下拉/弹窗用屏幕合成，无黑块。

---

## 5. 打包与交付

```
== 打包库：_d1lib/d1stash2.py
== 打包库：_d1lib/py/d1itemgen.py / d1tables.py / d1i18n.py
== 打包中文数据：_d1lib/data/zh_CN.json（207.7 KB）
== 已打包 1.5.5 物品表源码：7 个文件
== 产物：work\build\dist\暗黑破坏神1存档修改器-v2.exe  10.79 MB
== 运行 --selftest ==  selftest exit code = 0
== BUILD OK ==
```

内置自检关键行（证明打进去的是**当前** Round 4 源码，且没写真实存档）：

```
OK: pyc 模块加载自 ...\_MEI000030d02\_d1pyc
OK: 生成器状态 = 生成器已就绪（d1itemgen）；可指定数值；随机/自选词条；暗金图鉴；合法性校验
OK: 中文数据 = 中文数据：d1i18n（d1i18n.py）          ← 脚本要求日志含 d1i18n
OK: 下拉词条带效果名 = 残忍（Brutal） 伤害 +81 ~ +95 〔ilvl 16~33〕
OK: 预检 ilvl50 = affix_level_too_high｜前缀「Obsidian」是 24 级词缀…请把 ilvl 降到 49（24..49 都可以）
OK: 真实存档 4 个文件 SHA256 前后一致（未写入）
SELFTEST OK
```

再单独跑一次产物 `--selftest`：**exit 0**（2.0 s），日志 2 041 B，`d1i18n` ✔、「真实存档…一致」✔。

### 三处 exe SHA256（完全相同）

| 位置 | 字节 | SHA256 |
|---|---|---|
| `work\build\dist\暗黑破坏神1存档修改器-v2.exe` | 11 317 403 | `80664622E5A7284A66A4C36FA7188C069AD9E2EE790DCB1A59F84B52CDB8F833` |
| `交付\暗黑破坏神1存档修改器-v2.exe` | 11 317 403 | `80664622E5A7284A66A4C36FA7188C069AD9E2EE790DCB1A59F84B52CDB8F833` |
| `暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-v2.exe` | 11 317 403 | `80664622E5A7284A66A4C36FA7188C069AD9E2EE790DCB1A59F84B52CDB8F833` |

> 旧版（20:51 打包）是 11 262 228 B，已被本次 Round 4 产物替换。
> `build_exe.ps1` 按要求先清空重建了 `work\build\dist`、`work\build\pyi`、`work\build\pyc`、`work\build\lib`、`work\build\srcdata`。

---

## 6. 真实存档 SHA256 快照（开始 = 结束，逐字节一致）

目录 `%APPDATA%\diasurgical\devilution`，共 18 个文件（含所有 `.bak`）：

| 文件 | 字节 | SHA256 |
|---|---|---|
| `diablo.ini` | 3710 | `AFB950A86950628CD262B504D17365EC99994A5637C4D5229E5D575FA4FA457E` |
| `single_0.sv` | 3415207 | `6B6A8FBF738EDCA5DE2BA265DB99A7FE541417FA1515D46A5B6E1D52E8EEC9BD` |
| `single_1.sv` | 929607 | `2DEE3F41B99040A7C4DCDB967CA889A6703FA98A7A50223D4CD31B09ACA137D0` |
| `single_2.sv` | 2904940 | `D49B49FAB717C23B8F66E48704EBA6884CBF767B3E2FEF2A57A8CF01CCF44100` |
| `stash.sv` | 95927 | `820B70A648431B2DB3610D67592AD3608FF04B1455EFF5CE3352C08FBC10F2F0` |
| `stash.sv.bak` | 112568 | `BA14DEF415A671971EA7A082420233343C2F4D023F2FC6F44213754A7926F148` |
| `stash.sv.bak-20261111-211730` | 90346 | `4E4648DF1998EA61B23799D8D89AE15367399838341797E2CBBD4525A773C192` |
| `stash.sv.bak-20261111-213035` | 90569 | `B40E4C977793BE7B1C583A85807BF2A616B5C0E640937FA4B4DDD870CACEFFBC` |
| `stash.sv.bak-20261111-213127` | 105272 | `DAFBDBD4C77AE50146A5EF5014D5819BD66E57E2A9DDBA28CF7B960B557F8883` |
| `stash.sv.bak-20261111-213601` | 106360 | `D289A232A07E12FAD314346BD2C5CB575657884E20F16EA20A42A045C3F7377F` |
| `stash.sv.bak-20261111-214322` | 107512 | `CCF277E46C8FBD1D79E3204F8423E111EA7F47146674F70AFB565174332BC210` |
| `stash.sv.bak-20261111-214454` | 108792 | `3746034F4DE4F5A32D3EC136738155E6C65094B32F81F2E38F5D7817FA56C943` |
| `stash.sv.bak-20261111-214617` | 110136 | `7BFE21FD420FB75DE391BD6419BDE076B85170D242A73AD00ADB3A79024A2EC0` |
| `stash.sv.bak-20261111-214703` | 110648 | `F5B2A969855040D8DC86158FC049ED182EC5E76D0D6FCFE3D997215CE89DCBF0` |
| `stash.sv.bak-20261111-214809` | 111032 | `3FD9506CCF597FD0B05E96A7E00DDB1F788B90DEA0B86045175DB049CA9B9CF7` |
| `stash.sv.bak-20261111-215212` | 111608 | `D08BBECB15FA3F084FED7746DBF00ED0BBDD126C9A57BBC38AD5F5CBE0E41888` |
| `stash.sv.bak-20261111-215217` | 112184 | `6D49DAC1539A46309E9456004A618DCD7BB3522742FF67790AFF08085903208D` |
| `stash.sv.bak-20261111-215224` | 112568 | `BA14DEF415A671971EA7A082420233343C2F4D023F2FC6F44213754A7926F148` |

校验方式：开始/结束各 `Get-ChildItem | ForEach { Get-FileHash -Algorithm SHA256 }` 后 `Compare-Object`，
结果**无任何差异**；`verify_r4.py`、`smoke_test.py`、`--selftest`、`make_shots.py` 内部也各自断言了一次。
本次所有写盘只发生在 `work\tmp\`：`stash_r4.sv`、`stash_r4_shot.sv`、`hero_r4.sv`。

副本哈希自证（收尾核对）：

| 副本 | SHA256 | 与谁相同 |
|---|---|---|
| `work\tmp\hero_r4.sv` | `D49B49FAB717C23B…` | **= 真实 `single_2.sv`** → 背包 confirm 测试全程未写角色存档 |
| `work\tmp\stash_r4_shot.sv` | `820B70A648431B2D…` | **= 真实 `stash.sv`** → 截图流程只「载入浏览」，连副本都没写 |
| `work\tmp\stash_r4.sv` | `044A549D3B4FDEFA…` | ≠ 真实 `stash.sv` → 功能测试确实写的是副本（+2 件） |

---

## 7. 复现命令

```powershell
cd F:\Qoder\暗黑1重制版
$env:PYTHONIOENCODING='utf-8'

# 测试
& _py312\python.exe work\tests\test_round4_core.py
& _py312\python.exe work\tests\test_itemgen.py
& _py312\python.exe work\tests\test_itemgen2.py
& _py312\python.exe work\tests\test_stash.py
& _py312\python.exe work\tests\test_i18n.py
& work\build\venv312\Scripts\python.exe work\app\d1editor2.py --selftest
& work\build\venv312\Scripts\python.exe work\build\smoke_test.py

# 功能实测（两条都跑；_py312 无 tkinter，GUI 段用 venv312）
& _py312\python.exe work\tmp\verify_r4.py --no-gui
& work\build\venv312\Scripts\python.exe work\tmp\verify_r4.py

# 截图（只出 Round 4 的 7 张；不设 D1_SHOTS_R4 则连同旧图一起重出）
$env:D1_SHOTS_R4="1"
& work\build\venv312\Scripts\python.exe work\build\make_shots.py

# 打包 + 交付复制
& "F:\Qoder\暗黑1重制版\work\build\build_exe.ps1" -SkipVenv
Copy-Item work\build\dist\暗黑破坏神1存档修改器-v2.exe 交付\ -Force
Copy-Item work\build\dist\暗黑破坏神1存档修改器-v2.exe "暗黑破坏神1重构游戏本体和修改器\" -Force
Get-FileHash work\build\dist\暗黑破坏神1存档修改器-v2.exe,"交付\暗黑破坏神1存档修改器-v2.exe","暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-v2.exe" -Algorithm SHA256
```

---

## 8. 遗留问题 / 观察（均非阻塞，未擅自改源码）

**没有功能缺陷遗留。** 下面 #1–#3 只是观感/文案/命名层面，docs4 不必当缺陷写。

| # | 级别 | 现象 | 位置 | 建议 |
|---|---|---|---|---|
| 1 | 观感（排版） | `_show_results` 顶部自行打印「中文名/英文名/前缀/后缀/法术/基础属性」，紧接着 `res.text` 又打印一遍「名称/中文名/底材/品质」，同一屏重复。见 `r4_generated_max.png` 前 12 行。 | `ui_itemgen._show_results` | 后续轮次可去掉顶部重复行，只留 `res.text`；不影响功能与校验。 |
| 2 | 观感（文案） | 实时预览正文里「✘ 原因」是黑色正文；红色只在右下角校验标签。任务卡写「预览显示红字原因」，实际是**标签红字 + 正文黑字**。 | `ui_itemgen._compose_preview`（始终返回 `color=None`） | 若要求整段变红，可在 `chk.ok is False` 时返回 `"#c62828"`；纯观感。 |
| 3 | 观感（命名） | 魔法化后英文名会省略底材的「Chain」：`Chain Mail` → `Crystal Mail of the wolf` / `Amber Mail of absorption`。这是 1.5.5 自己的魔法命名规则（`_generate_magic_item_name`），**不是**换底材（实测 `runtime_idx=63`、`AC` 上限 22 都对）。 | `d1itemgen._generate_magic_item_name` | 说明书里提一句「魔法物品名会缩短底材名」即可，不是 bug。 |

### probe4 遗留项：全部已闭合（A4 / A6 / A8 有 core 测试覆盖，本轮又独立复跑）

> **更正**：本报告初版把 A4/A6/A8 写成「未覆盖」，是错的。core4 最终版已修，`test_round4_core.py`
> 的 `[11] spell/charges search uses the full budget`、`[12] full_durability above the 255 sentinel`、
> `[1] staff_spells() ... min_ilvl` 三条用例就是为它们写的；我也用 `_py312` 直接复跑了一次（下方为实测输出）。

| 条目 | 状态 | 证据（本轮实测 / 测试用例） |
|---|---|---|
| A1 `allow_staff_spells=True` 不保证法术 | ✅ 已闭合 | UI 传 `require_staff_spell=True`：普通杖 **10/10**、魔法杖 **10/10** 带法术+充能（§3.5 a/e） |
| A2 `L>50` band 给 `(50,50)` | ✅ 已闭合 | `band=(60,50)`，label 显示「需要 ilvl 60（超出可选 1~50，无法生成）」，`recommend_ilvl=None` |
| A3 法术等级门槛白烧 200k seed | ✅ 已闭合 | 0.000 s 报 `level_window`；selftest 复核 `预检 ilvl50 → 降到 49`；core 测试 `[10] staff spell ilvl guard (min_ilvl)` |
| A4 magic 无词缀分支 `min(max_tries, 10000)` 截断 | ✅ 已闭合 | core 测试 `[11] spell/charges search uses the full budget`；实测 `Bone Spirit + 40 充能` 命中 **seed=10013**（超过旧 10k 上限），`spell=36 charges=40`、`validate=[]` |
| A5 适配器 ceil 耐久（15~42 / 10~27） | ✅ 已闭合 | `base_preview` 给 floor **14~40**（`maxDur=55`），§3.4 |
| A6 `maxDur` 超 255 时 `full_durability` 写 >255 | ✅ 已闭合 | core 测试 `[12] full_durability above the 255 sentinel`；实测 `Gothic Plate + of structure` → `maxDur=300 > 255` ⇒ `applied_full_durability=False`、`durability` 保持自然值 220、`note=最大耐久 300 超过 255（游戏上限），未强制满值`、`validate=[]` |
| A7 词缀侧 IPL_SETAC 死代码 | 事实不变（非缺陷） | 1.5.5 词缀表 0 条 SETAC；暗金路径才是真实冲突点，`base_stats_conflict` 已就绪 |
| A8 `staff_spells().min_ilvl` 偏大一档 | ✅ 已闭合 | core 测试 `[1]` 断言 `Firebolt min_ilvl == 1`；实测 `Firebolt=1 / Healing=1 / Apocalypse=30`，且 `check_combination(152, ilvl=1, 普通杖, Firebolt).ok == True`（ilvl=1 就能出，与实现一致） |

> 结论：probe4 的 A1–A8 里，A1/A2/A3/A4/A5/A6/A8 全部已闭合，A7 是「事实不变、非缺陷」。
> **本轮没有任何功能缺陷需要 core4/app4 再改**；#1–#3 为观感级，交由主会话决定是否在后续轮次顺手改。

---

## 9. 附：本次产出/改动清单

- 新增 `work\tmp\verify_r4.py`（功能实测，54 项断言）
- 新增 `work\docs\shots\r4_*.png` ×7
- 改 `work\build\make_shots.py`（**只加** Round 4 段与 `D1_SHOTS_R4` 开关，旧段零改动）
- 新增 `work\docs\verify4_report.md`（本文件）
- 日志：`work\tmp\{verify_r4_nogui,verify_r4_gui,make_shots_r4,build_r4}.log`、`work\tmp\snapshot_{before,after,final}.txt`
- 打包产物：`work\build\dist\暗黑破坏神1存档修改器-v2.exe` → 已复制 `交付\` 与 `暗黑破坏神1重构游戏本体和修改器\`
- 临时副本（可随时删）：`work\tmp\stash_r4.sv`（+2 件）、`stash_r4_shot.sv`（截图浏览用）、`hero_r4.sv`（= `single_2.sv` 副本）
