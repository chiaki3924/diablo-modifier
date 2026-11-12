# Round 4 实测报告（probe4 · 只调查，不改源码）

> 生成时间：2026-11-11 22:12–22:50（Asia/Shanghai）
> ROOT = `F:\Qoder\暗黑1重制版`；所有脚本在 `work\tmp\p4_*.py`，用 `_py312\python.exe` 跑。
> 只生成**内存记录**，没有读写任何真实存档。
>
> **重要版本说明**：本次探测期间 core4/app4 正在落码，`d1itemgen.py` 从 142 KB（无 Round 4 参数）
> 于 22:17:11 变成 167 969 B（sha256 前缀 `AC597631279A`，已含 `max_ac/full_durability/staff_spell/
> staff_charges/allow_ac_override/staff_spells/all_affixes/affix_ilvl_band`）。
> 报告里标注了数据是「旧 core」还是「新 core」测的；**结论都以新 core 为准**，
> 游戏事实（滚动概率、法术集合、耐久公式、ilvl 窗口）与 core 版本无关。
>
> 探测结束时被测文件：
>
> | 文件 | 大小 | mtime | sha256(12) |
> |---|---|---|---|
> | `work/lib/d1itemgen.py` | 167 969 | 22:17:11 | `AC597631279A` |
> | `work/app/d1itemgen_adapter.py` | 113 471 | 22:19:31 | `D44CF9F5FF79` |
> | `work/app/ui_itemgen.py` | 81 215 | 22:19:51 | `D45AF9FA5928` |
> | `work/tests/test_round4_core.py` | 29 698 | 22:19:46 | `4A6A43295D2F` |
>
> **补记（22:52 复核）**：core4 在 22:20:51 又改了一版 core（169 211 B，sha256 前缀 `8E028421EBA6`），
> 我针对这一版**重新实测了所有「必须改」条目**：
>
> | 条目 | 在 169 211 B 版上的状态 |
> |---|---|
> | A3 法术等级门槛 | ✅ **已修**：`check_combination`/`generate` 都报 `level_window`（「法术「天启」需要物品等级 ≥ 30」），**0.000 s 快速失败**，不再白烧 200k seed |
> | A1 `allow_staff_spells=True` 仍不保证法术 | ❌ 仍在：20 次里 16 次无法术 / 4 次带法术 |
> | A2 `L>50` band=(50,50) | ❌ 仍在（`Godly`、`the whale` 实测仍是 `(50,50)`） |
> | A4 魔法无词缀路径 10 000 上限 | ❌ 仍在（`while tries < min(int(max_tries), 10000)`，行 3441）：8 次 `magic+法术+精确充能` 里 **2 次失败**（成功 0.01–0.19 s，失败 0.42 s 报 `seed_not_found`） |
> | A5 适配器 ceil 耐久 | ❌ 仍在（`base_preview(63).dur_min/dur_max = 15/42`，真值 14/40） |
> | A6 maxDur 可 >255 | ❌ 仍在（这次 roll 到 243/243；此前 258、278 都出现过） |
> | A7 词缀无 IPL_SETAC | 事实不变（0 条），暗金路径才是真实冲突点 |
> | A8 `min_ilvl` 偏大一档 | ❌ 仍在（`staff_lvl=1` 的 4 个法术都写 2） |

---

## 0. 结论摘要（可直接复制给 app4 / core4）

**已实测成立、可以放心的：**

1. **普通法杖本来就 100% 带法术与充能**（30/30 次，ilvl 10/20/40）：`magical=0`、`spell>0`、
   `charges == maxCharges`、`iName="<底材> of <法术>"`、`validate()` 全 OK。
   所以「带充能法杖生成不了」**不是游戏限制**，是魔法路径默认把 `spell!=0` 排掉了。
2. 新 core 的 `staff_spells()` 与实测可达集合**完全一致**（24 个，id 见 §2.4），
   并额外给出 `staff_lvl` / `min_ilvl`，GUI 可以直接用。
3. 满值：`max_ac=True` 只让 `validate(rec)` 报 1 条 `replay mismatch AC...`，
   `validate(rec, allow_ac_override=True)` 返回 `[]`；`replay=False` 也是 `[]`（其它规则不触发）。
   `full_durability=True` **默认 validate 就通过**（`durability` 早在忽略列表里）。
4. 满值耐久必须用**词缀之后的 `maxDur`**（新 core 已经这么做了）：`of structure` 会把
   Chain Mail 55 → 110/115，`full_durability` 写 `durability=115`，`validate` OK。
   **`of the ages`（IPL_INDESTRUCTIBLE）→ maxDur=255，新 core 会跳过并给 note，正确。**
5. 单条词缀合法 ilvl 区间公式 `[L, min(2L+1,50)]`（L<25）/ `[L,50]`（L≥25）实测**零反例**
   （对 3 个底材、267 条「类型合法」词缀逐一扫描 ilvl=1..50 比对）。
6. 实时预览成本极低：`check_combination(max_tries=None)` **3~50 µs/次**，
   `all_affixes` ≈ 40 µs/次，`staff_spells()` 首次 0.08 ms 之后走缓存 → `after(120)` 防抖绰绰有余。

**必须改 / 必须注意的（按严重度）：**

| # | 问题 | 证据 | 归属 |
|---|---|---|---|
| A1 | **「法术法杖（随机法术）」现在生成不出法术法杖**：GUI 选 `SPELL_RANDOM` 时 `_staff_params()` 只给 `allow_staff_spells=True`、`staff_spell=None`，core 的 magic 无词缀分支因此接受**任意**魔法法杖，实测 **20 次里 16 次是属性法杖（spell=0/charges=0）**，只有 4 次带法术。 | §2.2 P3 | core4（加 `require_spell`/让 allow 语义=必须带法术）+ app4 |
| A2 | **`affix_ilvl_band` 对 `min_level>50` 的词缀给出 `(50,50)`**，但这类词缀 ilvl≤50 永远出不了（实测区间为空）。现 UI 会显示 `〔ilvl 50~50〕`、推荐 ilvl 可能给 50，而生成时 `check_combination` 报 `level_window`（自相矛盾）。受影响 6 条：`Godly` / `the whale` / `Strange` / `Merciless` / `slaughter` / `Hydra's`（都是 L=60）。 | §4.3 | core4 + app4 |
| A3 | ~~`check_combination` 不检查「法术等级 ≤ ilvl//2」~~ → **已在 22:20:51 版修复**（`level_window` + 0.000 s 快速失败）。保留此条仅为记录旧版行为。 | §2.6 | —— |
| A4 | magic 无词缀/无法术前缀路径的预算被 `min(max_tries, 10000)` 截断：`staff_spell=12 + staff_charges=63` 期望 ≈1/13 000 seed，**10 000 内约一半概率失败**（8 次实测 2 次失败），失败文案写「10000 个种子的预算」而不是用户的 200 000。 | §2.5 | core4 |
| A5 | 适配器 `_natural_durability()` 用 **ceil** 算自然耐久：Chain Mail 给 `15..42`，真值 `14..40`；Long Staff 给 `10..27`，真值 `9..25`。UI 预览「耐久：a ~ b」直接用这两个数。 | §3.5 | app4 |
| A6 | `full_durability` 与 `IPL_DUR` 组合可把 `durability/maxDur` 写成 **>255**：Gothic Plate(100)+`of structure` → **278/278**；`DUR_INDESTRUCTIBLE = 255`；`validate` 不报（只查 `dur > maxDur`）。建议 `maxDur >= 255` 时跳过并提示，或让 verify4 进游戏确认显示。 | §3.6 | core4 + verify4 |
| A7 | 1.5.5 的 `PREFIXES/SUFFIXES` 里**一条 `IPL_SETAC` 都没有**（L=60 之类也没有），词缀侧的「满甲冲突」是死代码；**SETAC 冲突只在暗金路径真实可达**（30+ 个暗金，如 The Undead Crown / Arkaine's Valor / The Protector / Stormshield）。 | §3.7 | core4（保留防御性检查即可）+ app4（暗金页若加 max_ac 必须处理） |
| A8 | 新 core `min_ilvl = 2*staff_lvl`，但 `staff_lvl=1` 时实测 **ilvl=1 就能出**（`_get_staff_spell()` 里 `l = max(1, ilvl//2)`）→ 显示「ilvl≥2」偏大一档（无害，但和生成不一致）。 | §2.4 P1 | core4 |

---

## 1. 基线测试（只报告，不修）

命令：

```powershell
cd F:\Qoder\暗黑1重制版
& _py312\python.exe work\tests\test_itemgen.py
& _py312\python.exe work\tests\test_itemgen2.py
& _py312\python.exe work\tests\test_stash.py
& _py312\python.exe work\tests\test_i18n.py
```

| 测试 | 旧 core（22:12，142 KB） | 新 core（22:26，168 KB） | 结论 |
|---|---|---|---|
| `test_itemgen.py` | `15/15 tests passed`，exit 0 | `15/15 tests passed`，exit 0 | 绿 |
| `test_itemgen2.py` | `10/10 tests passed in 3.99s`，exit 0 | `10/10 tests passed in 4.04s`，exit 0 | 绿 |
| `test_stash.py` | `Ran 14 tests ... OK`，exit 0 | `Ran 14 tests in 3.885s ... OK`，exit 0 | 绿 |
| `test_i18n.py` | `11/11 tests passed`，exit 0 | `11/11 tests passed`，exit 0 | 绿 |

额外（不属于基线，但顺带确认 core4 的新测试）：

```powershell
& _py312\python.exe work\tests\test_round4_core.py   # 12/12 tests passed in 0.74s, exit 0
```

新 core 的尾部输出片段（证明 Round 4 功能面已经接通）：

```
[7/12] normal staff with staff_spell + staff_charges
    Long Staff: 'Long Staff of Firebolt' spell=1 charges=57/57
    Chinese name '火焰弹' resolved to spell 1
[9/12] magical spell staff (prefix, no suffix)
    "Knight's Staff of Apocalypse" prefix=Knight's spell=24 charges=10 validate ok
[12/12] validate(allow_ac_override=True) scope
    AC ignored, PLDam reported, length enforced, durability ignored
```

---

## 2. 法杖现状

脚本：`work\tmp\p4_intro.py`（表结构）、`work\tmp\p4_staff.py`（旧 core 行为）、
`work\tmp\p4_staff2.py`（概率/可达集合）、`work\tmp\p4_staff3.py`（搜索成本）、
`work\tmp\p4_new.py` / `p4_new2.py`（新 core）。

法杖底材（`itype_name == "Staff"`，`misc_id=23`，`affix_type=4`，`max_ac=0`）：

| idx | saved | 名称 | durability | value |
|---|---|---|---|---|
| 151 | 146 | Short Staff | 25 | 30 |
| 152 | 147 | Long Staff | 35 | 100 |
| 153 | 148 | Composite Staff | 45 | 500 |
| 154 | 149 | Quarter Staff | 55 | 1000 |
| 155 | 150 | War Staff | 75 | 1500 |

### 2.1 普通法杖（rarity="normal"）**本来就带法术充能** ✅

命令：`& _py312\python.exe work\tmp\p4_new.py`（P2 段）

```
P2. 普通法杖（rarity=normal）10 次 x ilvl 10/20/40
   ilvl=10 0.003s {'spell': 10}
       Long Staff of Holy Bolt spell=31 charges=75/75 magical=0 validate=OK
       Long Staff of Telekinesis spell=33 charges=29/29 magical=0 validate=OK
   ilvl=20 0.003s {'spell': 10}
       Long Staff of Charged Bolt spell=30 charges=69/69 magical=0 validate=OK
       Long Staff of Town Portal spell=7 charges=11/11 magical=0 validate=OK
   ilvl=40 0.002s {'spell': 10}
       Long Staff of Phasing spell=10 charges=49/49 magical=0 validate=OK
       Long Staff of Fireball spell=12 charges=53/53 magical=0 validate=OK
```

- **30/30 带法术**，`magical=0`（普通品质），`charges == maxCharges`，`MinMag=法术 min_int`，
  `ivalue = base + charges*staff_cost/5`，`validate()` 全 OK。
- 顶层统计（4000 seeds × 4 个 ilvl，`p4_staff2.py` F 段）：

```
ilvl=10/20/30/50 都一样（概率与 ilvl 无关）:
   mag0_spell        67.00%   ← 普通 + 法术（用户要的「普通充能法杖」）
   mag1_nospell      24.80%   ← 属性词缀法杖（GetItemPower 分支，无 spell）
   mag1_spell         7.17%   ← 魔法 + 法术（= 75% × 10% 前缀）
   mag2_*             1.02%   ← 暗金法杖
```

- 新 core 里「普通法杖 + 指定法术/充能」很好用、极快：

```
{'staff_spell': 12}                     0.001s Long Staff of Fireball  spell=12 charges=75 validate=OK
{'staff_spell': '火球术'}                0.001s Long Staff of Fireball  spell=12 charges=47 validate=OK
{'staff_spell': 12, 'staff_charges': 63} 0.010s Long Staff of Fireball  spell=12 charges=63 validate=OK
{'staff_charges': 50}                   0.004s Long Staff of Phasing   spell=10 charges=50 validate=OK
```
（`staff_charges` 单独给时会强制「必须带法术」，因为属性法杖 charges=0。）

### 2.2 魔法法杖：`allow_staff_spells=False`（默认）vs `True`

- `False`（旧 core 也一样）：**永远 `spell=0 / charges=0`**，即属性词缀法杖，`validate=OK`，
  生成 < 1 ms（快进预测路径）。20 次采样名字如 `Obsidian Long Staff of haste`、
  `Soldier's Long Staff`、`Angel's Staff of sorcery`。
- `True` **单独**用（不指定 `staff_spell/staff_charges`）：**并不能保证出法术法杖**。

```
P3. 魔法法杖：allow_staff_spells=True 单独用（不加法术过滤）
    {'无法术(属性法杖)': 8, '有法术': 2}          ← 22:17 版，10 次
补测（22:20:51 版，20 次）: {'无法术': 16, '有法术': 4}
```

根因（读码 + 实测）：magic 无词缀分支 `stat_only = is_staff and not allow_staff_spells`，
`True` 时该过滤关闭，于是**第一个**产出 `magical==MAGIC` 的 seed 就被接受；
而 seed 里 24.8% 是属性法杖、只有 7.17% 是「法术+前缀」法杖，
所以首个命中大多是属性法杖。
→ **用户需求「带充能的法杖」只有走 `staff_spell` / `staff_charges` 才可靠**；
「随机法术但必须是法术法杖」这个模式**当前 API 表达不出来**（见 A1）。

新 core 带 `staff_spell` 的魔法法术法杖（`allow_staff_spells=True`）都成功且 `validate=OK`：

```
{'staff_spell': 12}                        0.018s Raven's Staff of Fireball      spell=12 charges=68/68 pre=Raven's validate=OK
{'staff_spell': '火球术'}                   0.012s Soldier's Staff of Fireball    spell=12 charges=69/69 pre=Soldier's validate=OK
{'staff_spell': 24, 'staff_charges': 12}   0.149s Garnet Staff of Apocalypse      spell=24 charges=12/12 pre=Garnet validate=OK
{'staff_charges': 50}                      0.007s Ruby Long Staff of Phasing      spell=10 charges=50/50 pre=Ruby validate=OK
{'staff_spell': 12, 'prefix': "King's"}    0.039s King's Long Staff of Fireball   spell=12 charges=41/41 validate=OK
{'staff_spell': 12, 'suffix': 'sorcery'}   0.000s ERROR staff_spell_suffix  ✅ 规则正确
```

要点：**魔法法术法杖必定带前缀**（`GetStaffPower()` 只发前缀，10% 概率），名字是
`"<前缀> <底材> of <法术>"`；带后缀会被拒（游戏本来不会生成）。

### 2.3 指定前缀 + `allow_staff_spells=True` 可行吗？

可行，但**注意它给的还是属性法杖**（旧 core 实测，D 段）：

```
prefix=Soldier's allow=False 0.000s Soldier's Staff of wizardry  spell=0
prefix=Soldier's allow=True  0.000s Soldier's Long Staff          spell=0   ← allow 不等于「要法术」
prefix=Knight's  allow=True  0.007s Knight's Long Staff of haste  spell=0
```
新 core 同理：`allow_staff_spells=True` + 只给前缀 → 属性法杖（0.011 s）。若同时给
`staff_spell`，则得到「前缀 + 法术」法杖（0.039 s，见上）。

### 2.4 可做法杖的法术（`T.SPELLS` staff_min>0）

`staff_min>0` 的行有 **50 个**，但 `GetStaffSpell()` 实际只能抽到 **24 个**：

```
可达（实测枚举 seeds 1..30000，ilvl=50）：[1,2,3,4,6,7,8,10,11,12,13,14,15,18,20,21,23,24,29,30,31,33,35,36]
```

3 个例子（id / name / staff_min / staff_max / min_int / staff_lvl）：

| id | name | cn | staff_min | staff_max | min_int | staff_lvl | 最小 ilvl（实测） |
|---|---|---|---|---|---|---|---|
| 12 | Fireball | 火球术 | 40 | 80 | 48 | 7 | 14 |
| 30 | Charged Bolt | 电荷弹 | 40 | 80 | 25 | 1 | **1**（core 写 2） |
| 24 | Apocalypse | 天启 | 8 | 12 | 149 | 15 | 30 |

另外 `1 Firebolt 火焰弹 40~80`、`3 Lightning 闪电术 20~60`、`18 Nova 闪电新星 16~32`、
`35 Blood Star 血星 20~60`、`36 Bone Spirit 骨灵 20~60` 等。

**不可达的 26 个及原因**（写 GUI 帮助/报错文案时有用）：

- `staff_lvl == -1`：`5 Identify`、`16 Doom Serpents`、`17 Blood Ritual`、`19 Invisibility`、
  `25 Etherealize`、`26 Item Repair`、`27 Staff Recharge`、`28 Trap Disarm`、`47~51 Rune of *`。
- 被 `GetStaffSpell()` 的 1..37 循环跳过：`32 Resurrect`、`34 Heal Other`、`37 Mana`
  （循环里 `s == Resurrect → Telekinesis`、`s == HealOther → BloodStar`、`s == 37(max_spells) → Firebolt`）。
- `id >= 38` 永远抽不到（循环上限 37）：`38 the Magi`、`39 the Jester`、`40 Lightning Wall`、
  `41 Immolation`、`42 Warp`、`43 Reflect`、`44 Berserk`、`45 Ring of Fire`、`46 Search`。
- `0 Null`。

新 core `staff_spells()` 输出 **24 条且 id 顺序与实测集合完全相同**，`min_ilvl` 见 §4/A8；
`cn` 来自 `d1i18n.spell_name_cn(id)`（注意：该函数要 **int id**，传英文名会得到
`法术 #Fireball` 这种兜底串）。

### 2.5 法术/充能搜索成本（新 core）

```
Staff ilvl30 normal spell=12 charges=63          0.023s  OK
Staff ilvl30 magic  spell=12                     0.009s  OK
Staff ilvl30 magic  spell=24 charges=12          0.004s  OK
Staff ilvl30 magic  spell=12 + prefix King's    0.039s  OK
Staff ilvl30 magic  spell=12 + charges=63        0.399s  ERROR seed_not_found（只搜了 10000）
Staff ilvl30 magic  spell=12 + King's + charges=40  6.999s ERROR seed_not_found（跑满 200000）
```

- 普通法杖带指定法术很快（1~22 seed 命中；Apocalypse 除外）。
- **魔法**法杖每个 seed 都要完整 `_setup_all_items`（无法快进），实测 **~33~40 µs/seed** →
  200 000 预算 ≈ 7 s，2 000 000 ≈ 70 s。GUI 文案「可能需要几十秒」是准确的，且必须允许取消。
- 指定「法术 + 精确充能」的联合概率 ≈ `7.17% × 1/(staff_max-staff_min+1)`（Fireball 是 1/41）
  ≈ 1/13 000 seed；再叠前缀会更稀（示例 200 000 都没命中）。
- **10 000 上限导致的概率性失败（A4，最新版仍在）**：同一请求（`magic + staff_spell=12 +
  staff_charges=63`，`max_tries=200000`）连跑 8 次：

```
ok=6 fail=2   成功用时: 0.19s / 0.43s / 0.16s / 0.08s / 0.07s / 0.09s / 0.01s / 0.42s
失败: ERROR seed_not_found（消息里写「在 10000 个种子的预算内」）
```
  失败概率与理论一致（1-(1-7.3e-5)^10000 ≈ 48%），也就是**同样参数点两次，可能一次成一次败**。

### 2.6 ilvl 与法术等级门槛

`_get_staff_spell(g, lvl)` 里 `l = max(1, lvl//2)`，要求 `staff_lvl(s) <= l`。

**旧 core（22:17 版）没有这层预检**，实测白等：

```
Staff normal staff_spell=24（Apocalypse，staff_lvl=15）—— 22:17 版
   ilvl=20  6.908s ERROR seed_not_found（200000 seeds）
   ilvl=29  6.654s ERROR seed_not_found（200000 seeds）
   ilvl=30  0.001s OK  Long Staff of Apocalypse
```

**最新 core（22:20:51 版）已修（A3）**：`ilvl < min_ilvl` 直接 `level_window`，0.000 s：

```
check_combination(ilvl=20, staff_spell=24) -> False level_window
   法术「天启（Apocalypse）」需要物品等级 ≥ 30（当前 ilvl=20）；请把 ilvl 提到 30 或换一个低阶法术
check_combination(ilvl=29, staff_spell=24) -> False level_window
check_combination(ilvl=30, staff_spell=24) -> True  ok
check_combination(ilvl=13, staff_spell=12 火球术) -> False level_window（需要 ≥14）
check_combination(ilvl=14, staff_spell=12) -> True  ok
generate(ilvl=20, staff_spell=24) -> 0.000s ERROR level_window（同文案）
```

---

## 3. 满值可行性

脚本：`work\tmp\p4_full.py`（旧 core）、`work\tmp\p4_new.py`（新 core P5 段）、
`work\tmp\p4_dur.py`（耐久范围）、`work\tmp\p4_adapter.py`（适配器）。

### 3.1 满 AC + 满耐久：字段与 validate

Chain Mail（idx 63）：`min_ac=18 max_ac=22 durability=55 itype=MediumArmor value=1250`。

新 core 实测（`p4_new.py` P5）：

```
{'max_ac': True}                         AC=22 dur=15/55 iName='Chain Mail of the wolf'
   _extra: applied_max_ac=True  applied_full_durability=False  note='护甲取最大 22'
   validate(rec)                         = ['replay mismatch AC: game would set 20, record has 22']
   validate(rec, allow_ac_override=True)  = []
   validate(rec, replay=False)            = []

{'full_durability': True}                AC=18 dur=55/55
   _extra: applied_max_ac=False applied_full_durability=True note='耐久取满 55'
   validate(rec) = []                      ← 默认就通过

{'max_ac': True, 'full_durability': True} AC=22 dur=55/55
   note='护甲取最大 22；耐久取满 55'
   validate(rec) = ['replay mismatch AC: ...']，allow_ac_override=True → []
```

旧 core 同样条件用 `record_to_fields/fields_to_record` 手工改字段，结论一致：

```
只改 durability=maxDur(55)   -> validate=[]；validate(replay=False)=[]
只改 AC=max_ac(22)           -> validate=['replay mismatch AC: game would set 20, record has 22']
两个都改                     -> 同上一条；validate(replay=False)=[]
replay_item + _compare_generation(ignore=('durability',))        -> [('AC', 20, 22)]
replay_item + _compare_generation(ignore=('durability','AC'))    -> []
```

`record_to_fields(rec) → fields_to_record(...)` **字节精确往返**（`r2 == rec`，368 B，69 个字段，
其中 `name_raw`/`iName_raw` 是原始 64 B 缓冲）。

### 3.2 `durability` 本来就在 validate 的忽略列表里 ✅

- 源码：`validate()` 的 replay 段 `ignore.add("durability")`（注释：可磨损的游戏状态）。
- 实测：把耐久改成 `1` / `0` / `maxDur` → `validate` 全部 `[]`；
  只有 `durability = maxDur+1` 才报 `durability 56 exceeds maxDur 55`。
- 所以「满耐久」**不会**触发其它规则；唯一会被 replay 抓到的是 `AC`。

### 3.3 满耐久必须取「词缀之后的 maxDur」⚠️

```
suffix=structure   ilvl=20  Amber Mail of structure     dur=110/110 note='耐久取满 110'  validate=[]
suffix=structure   ilvl=25  Chain Mail of structure     dur=115/115 note='耐久取满 115'  validate=[]
suffix=the ages    ilvl=25  Chain Mail of the ages       dur=255/255
       note='该物品不可破坏/没有耐久，耐久满值未生效'   ← INDESTRUCTIBLE 分支正确
```
（`IPL_DUR` 加法在 `_save_item_power` 里已经改过 `maxDur`，新 core 用 `g.f["maxDur"]` 写入，
顺序正确；若用 `base["durability"]` 就会错。）

### 3.4 `max_ac` 只对 `max_ac>0` 的底材生效

```
武器 Long Sword + max_ac=True -> AC=0 note='该底材没有护甲（max_ac=0），护甲满值未生效'
Chain Mail + 前缀 Saintly(IPL_ACP +117%) + 满值 -> AC=22 PLAC=117 dur=55/55 validate(allow_ac_override=True)=[]
```
`IPL_ACP`（百分比护甲）与「护甲取最大」不冲突（写的是不同字段）；`IPL_AC_CURSE` 是加法，新 core 用
`max_ac - r` 叠加，语义正确。

### 3.5 自然耐久范围：**用截断除法，不是 ceil** ⚠️

`_item_rnd_dur()`：`durability = rnd(maxDur/2) + maxDur/4 + 1`，C++ 整除 →
`[maxDur//4 + 1, maxDur//2 + maxDur//4]`。实测（3000 seeds 枚举，集合无缺口）：

| 底材 | maxDur | 实测 | floor 公式 | ceil 公式（brief/适配器） |
|---|---|---|---|---|
| Chain Mail | 55 | **14..40** | 14..40 ✅ | 15..42 ❌ |
| Long Staff | 35 | **9..25** | 9..25 ✅ | 10..27 ❌ |
| Leather Armor | 35 | **9..25** | 9..25 ✅ | 10..27 ❌ |
| Plate Mail | 75 | **19..55** | 19..55 ✅ | 20..57 ❌ |
| Gothic Plate | 100 | **26..75** | 26..75 ✅ | 26..75 ✅（100 能被 4 整除，两者相同） |

`ROUND4_BRIEF.md` §3.2 的 ceil 写法对 `maxDur % 4 != 0` 的底材偏大 1~2；
适配器 `_natural_durability()`（`(max_dur+3)//4` / `(max_dur+1)//2`）实测就偏大：

```
ChainMail   实测 14..40  base_preview 15..42  *** 不符 ***
LongStaff   实测  9..25  base_preview 10..27  *** 不符 ***
PlateMail   实测 19..55  base_preview 20..57  *** 不符 ***
```
UI 预览「耐久：a ~ b / 最大 c」直接显示这两个数（`ui_itemgen.py:1055`）。

### 3.6 `maxDur` 可以 >255（INDESTRUCTIBLE 哨兵是 255）

```
DUR_INDESTRUCTIBLE = 255
Gothic Plate(100) + of structure  ilvl=20  Gothic Plate of structure  dur=278 maxDur=278  validate=[]
Gothic Plate(100) + of structure  ilvl=25  Gothic Plate of structure  dur=258 maxDur=258  validate=[]
（旧 core 同一组合未开满值时是 233 / 290，说明 IPL_DUR 可到 +200%）
1.5.5 里没有任何底材的原生 durability 是 255；255 只由 IPL_INDESTRUCTIBLE 写入。
```
→ `full_durability` 在 `maxDur` 落在 256..300 时会把耐久写成 >255；`validate` 不报错，
但游戏端可能把 255 当「不可破坏」或截断。**建议 `maxDur >= 255` 时跳过并提示**，
或至少让 verify4 进游戏看一眼显示（A6）。

### 3.7 `IPL_SETAC` 词缀：1.5.5 **一条都没有**

```
PREFIXES/SUFFIXES 里 power_name==IPL_SETAC 的条数: 0
```
词缀表里与 AC 相关的只有：`IPL_ACP`（10 条：Fine/Strong/Grand/.../Godly）、`IPL_ACP_CURSE`（2 条：
Rusted/Vulnerable）。`IPL_AC_CURSE`、`IPL_AC` 也不在词缀表里。
**`IPL_SETAC`（effect id 75）只被暗金 powers 使用**（54 处 powers 里 30+ 个暗金）：

```
uid=1  The Undead Crown   SETAC 8      uid=7  Arkaine's Valor SETAC 25
uid=59 The Protector      SETAC 40     uid=84 Stormshield    SETAC 40 + INDESTRUCTIBLE
uid=67 Gotterdamerung     SETAC 60     uid=78 Demonspike Coat SETAC 100 + INDESTRUCTIBLE
...（共 54 条 powers 命中）
```
实测暗金 + `max_ac=True` 全部被拒、错误码正确：

```
uid=1   The Undead Crown  max_ac=True -> ERROR base_stats_conflict | 暗金「The Undead Crown」的固定特效用 IPL_SETAC...
uid=7   Arkaine's Valor   max_ac=True -> ERROR base_stats_conflict
uid=59  The Protector     max_ac=True -> ERROR base_stats_conflict
uid=84  Stormshield       max_ac=True -> ERROR base_stats_conflict
（不带 max_ac 时正常：AC=8 / 25 / 40 / 40）
```
→ 词缀侧冲突是死代码（保留无害）；**`_setac_source(unique=...)` 这条才是真正会触发的**，
如果暗金页（图鉴/生成）也提供「护甲满值」，必须把 `base_stats_conflict` 变成中文提示 +
「取消满值」建议（适配器 `classify_error` 已有对应分支可复用）。

---

## 4. ilvl 窗口

脚本：`work\tmp\p4_ilvl.py`、`work\tmp\p4_ilvl2.py`、`work\tmp\p4_new2.py`（P7）。

窗口实现：`_affix_window(ilvl) = (min(ilvl//2, 25), ilvl)`（`_cdiv` 是 C++ 截断除法，实测
`ilvl=51 → (25,51)`，`ilvl=50 → (25,50)`，`ilvl=1 → (0,1)`）。

### 4.1 公式验证：267 条「类型合法」词缀，**0 条反例**

对 Chain Mail(63) / Long Sword / Long Staff 的 `all_affixes()` 每一条，扫描 ilvl=1..50，
用 `eligible_affixes()` 求真实出现区间，再与公式比对：

```
检查词缀条数: {'ok': 267}   不一致: 6（全部是 min_level=60 的，见 §4.3）
```

### 4.2 正例 / 反例

正例：

| 词缀 | L | 实测合法区间 | 公式 (50 封顶) |
|---|---|---|---|
| 前缀 Brutal（残忍） | 16 | **(16, 33)** | (16, 33) ✅ |
| 后缀 of the heavens（天堂） | 25 | **(25, 50)** | (25, 50) ✅ |
| 前缀 King's | 28 | **(28, 50)** | (28, 50) ✅ |
| 后缀 of the ages | 25 | **(25, 50)** | (25, 50) ✅ |
| 前缀 Saintly（圣者） | 24 | **(24, 49)** | (24, 49) ✅ |

逐点反例（Brutal，L=16，Long Sword）：

```
ilvl=15 window=(7,15)  -> False   ← 下限 7 太高（L=16 进不了窗口）
ilvl=16 window=(8,16)  -> True
ilvl=32 window=(16,32) -> True
ilvl=33 window=(16,33) -> True    ← 2L+1 = 33，最后一天
ilvl=34 window=(17,34) -> False   ← 下限 17 > 16
ilvl=50 window=(25,50) -> False
```

`of the heavens`（L=25）：ilvl 16..24 全 False，ilvl 25 开始 True，一直到 50 —— 与
「L≥25 时区间 [L,50]」一致。

`eligible_affixes` 在 ilvl=16/20/30/50（Long Sword，数量随窗口变化）：

```
ilvl=16 window=(8,16)   前缀 24 个 / 后缀 13 个
ilvl=20 window=(10,20)  前缀 30 个 / 后缀 18 个
ilvl=30 window=(15,30)  前缀 34 个 / 后缀 15 个
ilvl=50 window=(25,50)  前缀 14 个 / 后缀  5 个   ← 高级 ilvl 反而更少，用户会觉得「词缀变少了」
```

`all_affixes` 数量（全量，不看 ilvl）：

```
Chain Mail  前缀 31 / 后缀 62     （eligible(30): 17 / 11）
Long Sword  前缀 57 / 后缀 60     （eligible(30): 34 / 15）
Long Staff  前缀 45 / 后缀 12     （eligible(30): 27 / 4）
```

### 4.3 反例：`affix_ilvl_band` 把 L>50 的词缀 clamp 成 (50,50) ❌

```
('Chain Mail','prefix','Godly',     60, band=(50,50), 实测=(None,None))
('Chain Mail','suffix','the whale', 60, band=(50,50), 实测=(None,None))
('Long Sword','prefix','Strange',   60, band=(50,50), 实测=(None,None))
('Long Sword','prefix','Merciless', 60, band=(50,50), 实测=(None,None))
('Long Sword','suffix','slaughter', 60, band=(50,50), 实测=(None,None))
('Long Staff','prefix',"Hydra's",   60, band=(50,50), 实测=(None,None))
```
`check_combination(ChainMail, ilvl=50, prefix='Godly')` → `ok=False, code=level_window`
（「需要词缀等级 60，ilvl=50 只允许 25..50」）。也就是说 band 说「ilvl 50~50 可选」，
预检说「不行」。GUI 现显示 `神佑（Godly） 护甲 +171 ~ +200 〔ilvl 50~50〕`，
且「用推荐 ilvl」可能填 50 → 必然报错。
建议 `affix_ilvl_band` 在 `L > 50` 时返回 `(L, 50)`（hi < lo 表示不可达）或 `(0, 0)`，
GUI 显示 `〔需要 ilvl 60（超出 1~50，出不了）〕`。

### 4.4 ilvl 上限的小事实

- core 允许 `ilvl 0..63`；`_affix_window` 在 51..63 时 `minlvl` 固定 25，所以 **L≥25 的词缀在
  ilvl 51~63 仍然可选**（实测 King's 的真实区间是 (28,63)）。GUI 合同只到 50，所以「[L,50]」
  只在「ilvl≤50」前提下成立；`affix_ilvl_band` 的 50 封顶符合合同，但别拿它去校验 ilvl>50 的请求。
- `ilvl` 与「角色需求等级」无关：需求来自 `MinStr/MinMag/MinDex`（底材 + 词缀）。

---

## 5. 耗时（供 GUI 进度文案 / 取消策略）

`p4_time.py`（旧 core）+ `p4_new2.py` P8（新 core），同一台机器：

| 场景 | 耗时 |
|---|---|
| 魔法 Chain Mail ilvl20，无词缀 | < 1 ms |
| 魔法 Chain Mail ilvl25 + 前缀 Saintly | < 1 ms |
| 魔法 Long Sword ilvl25 + 前缀 Brutal + 后缀 the heavens + 双数值 | **0.080 s** |
| 同上 + 满值（max_ac + full_durability） | **0.137 s** |
| 普通法杖 + 指定法术 + 精确充能 | 0.010 ~ 0.023 s |
| 魔法法术法杖 + 指定法术（带前缀） | 0.009 ~ 0.040 s |
| 魔法法术法杖 + 指定法术 + 精确充能 | 0.004 ~ 0.150 s |
| 魔法法术法杖 + 法术 + 精确充能（稀组合，200k 用尽） | **6.999 s** |
| 普通法杖 + Apocalypse 但 ilvl 太低（旧 core，200k 用尽） | **6.9 s**（必然失败；最新 core 已改 0.000 s 报错） |
| `check_combination(max_tries=None)` | **45 µs**（词缀）/ **3~4 µs**（法术法杖规则） |
| `eligible_affixes` | 3.7 µs |
| `all_affixes` | ~40 µs |
| `staff_spells()` | 首次 0.084 ms，之后缓存 ≈0 |
| `base_items()` 全表 | 25 µs |

单 seed 全量 `_setup_all_items` 成本（决定「搜索类」任务上限）：

```
ChainMail ilvl=10  14.9 us/seed  → 200k ≈ 3.0s，2M ≈ 30s
ChainMail ilvl=30  18.5 us/seed  → 200k ≈ 3.7s，2M ≈ 37s
ChainMail ilvl=50  22.9 us/seed  → 200k ≈ 4.6s，2M ≈ 46s
法术法杖分支（每个 seed 都全量）     ~33~40 us/seed → 200k ≈ 7s，2M ≈ 70~80s
```

GUI 现状的预算是 200 000（无目标值）/ 2 000 000（有目标值），
**法术法杖遇到 2 000 000 会到 70 s**，进度文案与取消按钮必须覆盖这段时间；
另外 magic 无词缀分支被 `min(max_tries, 10000)` 截断（A4），这是「明明有 200k 预算却报 10000」的原因。

---

## 6. 坑（逐条，附证据）

1. **`allow_staff_spells=True` ≠ 要法术法杖**。它只是「允许」，magic 无词缀分支里第一个魔法法杖就返回，
   实测 20 次里 16 次是属性法杖 → 用户选了「法术法杖（随机法术）」却拿到无法术的法杖（A1）。
   修法建议：给 `generate/check_combination` 加 `require_spell: bool=False`，或在
   `_search_seed`/无词缀分支里对 `allow_staff_spells and staff_spell is None and staff_charges is None`
   也要求 `g.f["spell"] != 0`。
2. **魔法法术法杖必须带前缀**（`GetStaffPower` 只给前缀）：所以「法术法杖 + 后缀」被拒是对的，
   但 UI 要写清「法术法杖名字一定是『<前缀> <底材> of <法术>』」，否则用户会以为随机。
3. **ilvl 太低 + 指定法术**：规则是 `staff_lvl <= max(1, ilvl//2)`（`Apocalypse` 需要 ilvl≥30）。
   旧 core 会白烧 200k seed / 6.9 s 报 `seed_not_found`；**最新 core 已改成 0.000 s 的
   `level_window`**（「法术「天启」需要物品等级 ≥ 30」）。GUI 的「用推荐 ilvl」应把
   `min_ilvl` 当作下限（`ui_itemgen.recommend_ilvl` 已这么做）。
4. **magic 无词缀路径 10 000 上限**（最新版仍在，行 3441）：`staff_charges` 目标约 1/13 000 seed，
   8 次实测 2 次失败、且错误里写 10000（A4）。同一参数点两次结果可能不同，用户会当成「随机失败」。
5. **`affix_ilvl_band` 的 L>50 分支**（A2）：6 条 L=60 词缀给出 (50,50)，与预检矛盾。
6. **自然耐久范围**：用 floor（`maxDur//4+1` ~ `maxDur//2+maxDur//4`），不是 ceil（A5）。
   `ROUND4_BRIEF.md` §3.2 的 ceil 文案也应改，否则 docs4 抄进说明书会写错。
7. **`durability` 已在 validate 忽略列表**，`AC` 没有：所以「满耐久」不需要 `allow_ac_override`，
   「满护甲」需要。适配器 `validate(record, allow_ac_override=max_ac)` 的传法正确
   （实测 `validation=[]`，`check_record` 也只给 warn「护甲为满值…」）。
8. **`maxDur` 可被 `IPL_DUR` 推到 255 以上**（278/258 实测），`full_durability` 会把耐久写成 >255；
   `validate` 不报（只查 `dur > maxDur`）。建议 `maxDur >= 255` 时跳过（A6）。
9. **SETAC 只出现在暗金**（0 条词缀）：词缀侧冲突检查留着当防御，但真正的用户可见场景是
   「暗金 + 护甲满值」→ `base_stats_conflict`（A7）。UI 的 `sets_ac` 判断对词缀永远是 False。
10. **`d1i18n.spell_name_cn()` 要 int id**，传英文名兜底成 `法术 #Fireball`。
    `d1zh.spell_name(id)` 也可用；实测 24 个法术都有中文名（火焰弹/火球术/天启/电荷弹/…）。
11. **`staff_spells()` 的 `min_ilvl` 偏大一档**（staff_lvl=1 实测 ilvl=1 就出，代码写 2）。
12. **同参数每次结果不同**（`seed=None` 走 `_random_seed()`）：GUI 结果里要显示 seed，
    否则用户「再来一次」拿到的属性值（尤其指定数值时的实际 roll）不可复现。
13. **`check_combination` 便宜**（3~50 µs），实时预览不要传 `max_tries`（合同一致）；
    但注意它对「法术等级」不设防（第 3 条），预览与生成会短暂不一致。
14. `generate()` 的 magic 无词缀分支上限 `min(max_tries, 10000)` 与 `_search_seed` 的 `max_tries`
    是两套预算，报错文案里的数字也随之变化，GUI 别把 200000 硬编码进提示。

---

## 7. 复现命令

```powershell
cd F:\Qoder\暗黑1重制版
$env:PYTHONIOENCODING='utf-8'      # 否则中文输出是 GBK 乱码

# 基线
& _py312\python.exe work\tests\test_itemgen.py
& _py312\python.exe work\tests\test_itemgen2.py
& _py312\python.exe work\tests\test_stash.py
& _py312\python.exe work\tests\test_i18n.py
& _py312\python.exe work\tests\test_round4_core.py

# 探测脚本（全部只读内存）
& _py312\python.exe work\tmp\p4_intro.py     # 表结构 / 法术表 / staff_min>0
& _py312\python.exe work\tmp\p4_staff.py     # 普通/魔法/allow/前缀（旧 core 行为）
& _py312\python.exe work\tmp\p4_staff2.py    # 概率分布 + 可达法术枚举（约 20s）
& _py312\python.exe work\tmp\p4_staff3.py    # 指定法术/充能搜索成本
& _py312\python.exe work\tmp\p4_full.py      # 满 AC/耐久的 validate 行为
& _py312\python.exe work\tmp\p4_dur.py       # 耐久自然范围（floor vs ceil）+ 适配器快照
& _py312\python.exe work\tmp\p4_ilvl.py      # ilvl 窗口（含跨底材噪声，可跳过）
& _py312\python.exe work\tmp\p4_ilvl2.py     # ilvl 窗口（按类型过滤，267 条 0 反例）
& _py312\python.exe work\tmp\p4_time.py      # 耗时基准（末段会抛，见下）
& _py312\python.exe work\tmp\p4_new.py       # 新 core：staff_spells / 满值 / SETAC
& _py312\python.exe work\tmp\p4_new2.py      # 新 core：法术法杖 / band / 耗时
& _py312\python.exe work\tmp\p4_adapter.py   # 适配器 + GUI 依赖的字段
```

已知脚本瑕疵（不影响结论，报错在末尾）：`p4_time.py` 最后一段用 `ilvl=20 + 前缀 Saintly(L=24)`
会抛 `level_window`；`p4_ilvl.py` 4.2 段把「词缀类型不合法」也计入不一致（`p4_ilvl2.py` 已修正）。
