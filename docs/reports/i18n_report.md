# i18n 报告：游戏自带 zh_CN 翻译接入修改器（Round 2 · 问题 3）

> 代理：i18n　｜　日期：2026-11-11　｜　状态：**完成，11/11 测试通过**
>
> 权威来源：`ROOT\DevilutionX-1.5.5\Translations\zh_CN.po`
> （384,771 字节，2043 个 msgid，game 1.5.5 自带简体中文）
> PO sha256：`a99be0c2edbf37b6fbe42656d080796addb4cd1297fb730b2bbf09b6d57ffde0`

## 1. 交付文件

| 文件 | 说明 |
|---|---|
| `work/lib/d1i18n.py` | PO 解析、JSON 缓存加载/生成、名称/词缀/属性/暗金 powers 的中文 API |
| `work/lib/data/zh_CN.json` | 预编译缓存（212,709 字节 / 150,542 字符）：`tr` 1762 条 + `tr_ctx` 279 条，UTF-8 无 BOM，键排序，可直接 diff |
| `work/tests/test_i18n.py` | 11 组测试（JSON 缓存、PO 解析、名称、描述、暗金 powers、双数据模式、`_MEIPASS` 模拟） |
| `work/docs/i18n_report.md` | 本报告 |

未改动 `d1itemgen.py` / `d1tables.py` / `work/app/*` / 任何存档。

## 2. 数据流与运行模式

```
zh_CN.po (2043 msgid)
   │  d1i18n.py --rebuild   （一次性；PO 解析 + 去零宽 + 精简成 JSON）
   ▼
work/lib/data/zh_CN.json  ──►  tr / item_name_cn / affix_name_cn / unique_name_cn
                                   / affix_label / stat_label / affix_desc / describe_power
   ▲
   └── 回退：JSON 不存在/损坏时直接读 PO（源模式）

源模式   ：work/lib/data/zh_CN.json
PO 回退  ：ROOT/DevilutionX-1.5.5/Translations/zh_CN.po
冻结模式 ：<sys._MEIPASS>/_d1lib/data/zh_CN.json
           （另兼容 _d1lib/py/data、_d1lib/zh_CN.json、data/zh_CN.json）
环境变量 ：D1I18N_JSON / D1I18N_PO 可强制指定（测试与调试用）
```

`i18n_info()` 返回当前实际使用的模式、路径与条数，GUI 可直接显示
（`d1zh.i18n_status()` 已验证显示 `d1i18n（d1i18n.py）`）。

构建缓存（PO 改动后必须重跑）：

```
ROOT\_py312\python.exe work\lib\d1i18n.py --rebuild
ROOT\_py312\python.exe work\lib\d1i18n.py --stats [--verbose]   # 覆盖率/缺失清单
```

## 3. PO 解析覆盖的语法

| PO 特性 | 本目录中的数量 | 处理 |
|---|---|---|
| 普通 `msgid`/`msgstr` | 1762 | 直接入表 |
| `msgctxt`（`P_()`） | 279（monster 223 / spell 53 / spellbook 2 / player 1） | 单独存 `tr_ctx[ctx][msgid]`，**不**污染普通表；`tr(text, ctx=…)` / `pgettext()` / `tr_ctx()` 查询 |
| 多行 msgid/msgstr（续行 `"…"`） | 325 | 逐行 `+=` 拼接 |
| `msgid_plural` + `msgstr[0]`（`ngettext`） | 9 | 取 `msgstr[0]`（zh_CN 为 `nplurals=1`） |
| `#:` 源引用 | 全部 | 解析并存 `refs[msgid]`（用于统计来源，不写进 JSON） |
| `#, fuzzy` | 1 条（`Offline`→`回环`，明显错译） | **跳过**，宁可显示英文也不显示错译 |
| `#~` 废弃条目 | 0 | 跳过 |
| C 转义 `\n \" \\ \xNN` | 多处 | `_unescape()` 还原 |
| 未翻译（`msgstr ""`） | 0 | 跳过（保留英文） |

解析结果：`entries=1762`，`ctx=279`，`untranslated=0`，`fuzzy=1`（跳过）。
`1762 + 279 + 1(fuzzy) + 1(header) = 2043`，与 msgid 总数一致，无静默丢失。

## 4. 零宽字符（U+200B）处理

游戏 PO 在 msgstr 中大量插入 **U+200B ZERO WIDTH SPACE** 作为换行提示
（如 `短\u200b剑`、`火焰\u200b抗性: {:+d}%`），Tk 显示会变成杂字符并破坏字符串比较。

* 解析时统计：**1553 条 msgstr 含 U+200B，共清除 15,330 个字符**；
* 清除字符集：`U+200B U+200C U+200D U+2060 U+FEFF U+00AD`（后 5 个是防御性处理，
  当前 PO 只用到 U+200B）；
* 清除发生在 **写入 JSON 之前**（缓存里已是干净文本），`tr()` 查表前也会再清一次输入，
  因此 `tr("Short\u200bSword")` 与 `tr("Short Sword")` 都得到 `短剑`；
* 元数据记录在 JSON `meta.zw_entries / meta.zw_removed`，测试断言缓存值里不含 U+200B。

## 5. 覆盖统计

以当前 `d1tables`（含 starter / unique_only 全量视图）交叉验证：

| 类别 | 命中 | 总数 | 覆盖率 | 缺失 |
|---|---|---|---|---|
| 底材 base item | 86 | 86 | **100%** | 无 |
| 前缀 prefix | 86 | 86 | **100%** | 无 |
| 后缀 suffix | 98 | 98 | **100%** | 无 |
| 暗金 unique | 110 | 110 | **100%** | 无（其中非 Hellfire 可用 90 件） |
| 法术 spell（`msgctxt=spell`） | 53 | 53 | 100% | 无 |

说明：

* `d1tables` 里另有 4 类引擎占位行（`Non Item`、`Scroll of None`、
  `Book of `（模板，游戏运行时拼法术名）、`Arena Potion`），PO 里本就没有对应
  msgid，它们不是可生成/可显示的物品，已在统计中排除；
* 早期 `d1tables` 版本（未做 starter/unique_only 过滤）会看到这批占位名，
  当前 `base_items()` 已不返回它们，属预期。

## 6. API 与真实输出

```python
import d1i18n as I

I.tr("Short Sword")            # '短剑'（自动去 U+200B；无译文返回原文）
I.tr("Offline", "离线")         # '离线'（fuzzy 条目被跳过 → 用调用方默认值）
I.tr("Firebolt", ctx="spell")  # '火焰弹'    == I.pgettext("spell", "Firebolt")

I.item_name_cn("Leather Armor")        # '皮甲'
I.item_name_cn("Ring")                 # '戒指'
I.item_name_cn("Amulet")               # '护符'
I.affix_name_cn("prefix", "Brutal")    # '残忍'
I.affix_name_cn("suffix", "of the Fox")# '狐狸'（也接受表内写法 'the fox'）
I.unique_name_cn("Naj's Light Plate")  # '诺吉的轻铠甲'
I.affix_label("prefix", affix)         # '残忍（Brutal）'
I.affix_label("suffix", affix)         # '匆忙（of haste）'
I.stat_label("fireres")                # '火焰抗性'（也接受 'IPL_FIRERES'/'Fire Resist'）
```

### 6.1 `affix_desc(affix, value=None)`

数值一律来自 `param1..param2`（`SaveItemPower()` 的 `RndPL` 范围），
**绝不使用 `min_val/max_val`**（那是 `CalcItemValue()` 的金币价格映射）。
真实输出：

```
残忍（Brutal）：伤害 +81~95%；需要物品等级 16；适用 弓/法杖/武器
狐狸（of the fox）：生命 +10~15；需要物品等级 1；适用 杂项/盾牌/防具
蓝宝石（Sapphire）：闪电抗性 +51~60%；需要物品等级 26；适用 杂项/弓/法杖/武器/盾牌/防具
锋利（Sharp）：命中 +1~5%，伤害 +20~35%；需要物品等级 1；适用 弓/法杖/武器
锡（Tin）：命中 -10%~-6%；需要物品等级 3；适用 杂项/弓/武器
匆忙（of haste）：固定效果：最快攻击；需要物品等级 27；适用 法杖/武器
晶状（Crystalline）：固定效果：低耐久，伤害 +200~280%；需要物品等级 5；适用 武器
```

指定值（问题 4 用）：

```
巨人（of giants）：力量 +15（指定值）；需要物品等级 17；适用 杂项/弓/武器/防具
蓝宝石（Sapphire）：闪电抗性 +30%（指定值）；需要物品等级 26；适用 …
匆忙（of haste）：固定效果：最快攻击（该词缀为固定效果，不能指定数值）；…
```

固定效果词缀（攻速/硬直恢复/格挡/吸血/充能/法术/穿透/击退…）输出
`固定效果：…`，不带 `~` 数值范围；`value` 给定时明确提示不可指定。

### 6.2 `describe_power(power)`（暗金固定词条）

```
The Butcher's Cleaver : 力量 +10 / 固定伤害 4-24 / 固定耐久 10
The Undead Crown      : 固定效果：生命偷取 / 护甲等级 8 / 固定效果：改变物品外观（不影响属性）
Gleamsong             : 法力 +25 / 力量 -3 / 体力 -3 / 固定效果：相位术 76 次充能
Naj's Light Plate     : 固定效果：无力量要求 / 魔法 +5 / 法力 +20 / 全抗性 +20% / 法术等级 +1 / …
```

* 接受 dict（`power_name`/`type_name` + `param1`/`param2`）、`(name, p1, p2)` 元组、裸 power 名；
* 固定效果文案优先取 PO 里游戏自己的 tooltip 句子（`indestructible`→坚不可摧、
  `hit steals 3% mana`→命中时3%法力偷取、`quick/fast/faster/fastest attack`→快速/更快/极速/最快攻击…），
  PO 缺条目时用内置中文兜底；
* `IPL_SPELL` 通过 `d1tables.spell_by_id()` + `msgctxt='spell'` 得到法术名（相位术、火焰弹…）。
* 110 件暗金的 **503 条 powers 全部**输出中文（测试逐条断言）。

## 7. PL_* 效果 → 中文映射（实现于 `_POWER_SPEC`）

| PL 效果 | 中文/数值语义 |
|---|---|
| `TOHIT` / `TOHIT_CURSE` | 命中 +r% / −r%（命中率百分比） |
| `DAMP` / `DAMP_CURSE` | 伤害 +r% / −r%（`_iPLDam` 是伤害百分比） |
| `TOHIT_DAMP(_CURSE)` | 命中 +a%，伤害 +b%；命中部分按 `CalculateToHitBonus(param1)` 查表（20→1~5 … 151→76~100；诅咒用 25→1~5、50→6~10 取负） |
| `ACP` / `ACP_CURSE` | 护甲 +r% / −r% |
| `SETAC` / `AC_CURSE` | 护甲等级 r / −r |
| `FIRERES/LIGHTRES/MAGICRES/ALLRES`（含 `_CURSE`） | 火焰/闪电/魔法/全抗性 ±r% |
| `ALLRESZERO` | 固定：所有抗性归零 |
| `STR/MAG/DEX/VIT/ATTRIBS`（含 `_CURSE`） | 力量/魔法/敏捷/体力/所有属性 ±r |
| `LIFE` / `MANA`（含 `_CURSE`） | 生命/法力 ±r（存档 `PLHP=r<<6`，**显示值仍为 r**） |
| `DAMMOD` | 伤害 +r% |
| `LIGHT` / `LIGHT_CURSE` | 光照范围 ±(10×r)% |
| `DUR` / `DUR_CURSE` | 耐久 ±r% |
| `INDESTRUCTIBLE` | 固定：坚不可摧 |
| `FASTATTACK` / `FASTRECOVER` / `FASTBLOCK` / `FASTCAST` | 固定：快速…最快攻击 / 打击回复 / 格挡 / 施法 |
| `STEALMANA` / `STEALLIFE` | 固定：命中时偷取 param1% 法力/生命 |
| `CHARGES` | 固定：充能次数 ×param1 |
| `SPELL` | 固定：<法术名> param2 次充能 |
| `FIREDAM/LIGHTDAM/ADDACLIFE/FIRE_ARROWS/LIGHT_ARROWS/FIREBALL/SETDAM` | 火焰/闪电/火焰箭/闪电箭/火球/固定伤害 p1-p2 |
| `SETDUR` | 固定耐久 p1 |
| `GETHIT` / `GETHIT_CURSE` | 受击伤害 −r / +r（`GETHIT` 是好的，减伤） |
| `THORNS` | 固定：攻击者受到 p1~p2 点伤害 |
| `MULT_ARROWS` / `KNOCKBACK` / `NOMANA` / `ABSHALFTRAP` / `TARGAC` / `RNDARROWVEL` / `ONEHAND` / `DRAINLIFE` / `RNDSTEALLIFE` / `NOMINSTR` / `ADDMANAAC` / `DEVASTATION` / `PERIL` / `JESTERS` / `ACDEMON` / `ACUNDEAD` / `MANATOLIFE` / `LIFETOMANA` / `3XDAMVDEM` / `INVCURS` / `CRYSTALLINE` / `DECAY` | 固定效果，文案取自 PO tooltip |
| 其他/未知 `IPL_*` | `stat_label()` 可读名，再不行 `特殊效果`（当前 503 条 powers 无命中此项） |

## 8. 与 UI 的对接（已实测）

* `d1zh.py`（gui2）优先调用 `d1i18n`，实测：
  `item_name_cn('Short Sword')→短剑`、`unique_name("Naj's Light Plate")→诺吉的轻铠甲`、
  `affix_desc(...)→残忍（Brutal）：伤害 +81~95%；需要物品等级 16；适用 弓/法杖/武器`、
  `i18n_status()→中文数据：d1i18n（d1i18n.py）`。
* `d1zh` 之前找 `d1i18n.tr_ctx` / `pgettext` 取 `msgctxt` 法术名，本模块已提供
  `pgettext(ctx, text)` 与 `tr_ctx(ctx, text)`，法术名不再回退英文。
* `affix_label()` 后缀显示为 `中文（of xxx）`（游戏内后缀就是 `of …` 组合形式），
  下拉可直接用。

## 9. 打包注意（需 GUI/build 代理执行，本代理未改 build 文件）

当前 `work/build/build_exe.ps1` 只把 `d1stash2`、`d1itemgen`、`d1tables` 拷到
`_d1lib` / `_d1lib/py`，**没有**带 `d1i18n.py` 和 `data/zh_CN.json`。冻结版需要追加：

```powershell
Copy-Item (Join-Path $lib "d1i18n.py") (Join-Path $stageNested "d1i18n.py")   # _d1lib/py/d1i18n.py
$dataSrc = Join-Path $lib "data"
$dataDst = Join-Path $stageLib "data"
New-Item -ItemType Directory -Force -Path $dataDst | Out-Null
Copy-Item (Join-Path $dataSrc "zh_CN.json") $dataDst                          # _d1lib/data/zh_CN.json
```

（`d1env.py` 的 `lib_module()` 会搜索 `_d1lib` 与 `_d1lib/py`，因此 `d1i18n.py`
放 `_d1lib/py/` 即可；JSON 由本模块从 `_MEIPASS/_d1lib/data/` 读取，
已用模拟 `_MEIPASS` 的测试验证。）若忘记带 JSON，冻结版仍能尝试
`_MEIPASS/DevilutionX-1.5.5/Translations/zh_CN.po`，但该 PO 目前未打包，最终会退化为英文。

## 10. 已知差异/决策（重要）

1. **`of the Fox` 不是敏捷**。简报示例写「狐狸：敏捷 +X~Y」，但 1.5.5
   `itemdat.cpp:376` 中 `{"the fox", {IPL_LIFE, 10, 15}}`，游戏 tooltip 是生命 +10~15。
   测试按真实表断言「生命」，另用 `of Dexterity`（IPL_DEX）验证「敏捷」路径；
   GUI 不要按简报硬编码敏捷。
2. **Vitality 的译名**：PO 把 `{:+d} to vitality` 译为「+N 活力」，`Vitality:` 也译「活力」。
   本模块 `stat_label('vit')` 按任务要求用 **体力**，`affix_desc`/`describe_power`
   统一输出「体力」（与简报一致，但与游戏 tooltip 的「活力」不同）。若要完全贴游戏，
   把 `_STAT_LABELS['vit']` 改成「活力」即可（单点修改）。
3. **前缀 `Gold`**：PO 只有一条 `Gold → 金币`（那是金币/物品 Gold），词缀表复用同一
   msgid，游戏会显示「金币 长剑」。本模块对**前缀**特判为「金」（`_PREFIX_OVERRIDES`），
   物品 Gold 仍为「金币」。`d1zh` 原本也这么兜底，行为一致。
4. **`ok`/`PLOk` 不是诅咒标记**。源码里 `PLOk` 只用于 `onlygood` 生成过滤
   （`if (onlygood && !ItemPrefixes[j].PLOk) continue;`）。`Tin`（诅咒）与
   `Sharp`/`Brutal` 的 `ok` 都是 false，但 Sharp 并无诅咒。UI 不应把
   `ok=false` 标成「坏词缀」。
5. **`IPL_INVCURS`**（68 件暗金带）只改图标外观、不影响属性，`describe_power`
   输出「固定效果：改变物品外观（不影响属性）」，图鉴可按需隐藏。
6. 若干后缀直译较生硬（`haste→匆忙`、`quality→质量`、`the fool→傻瓜`），
   这是游戏官方译法，为保证与游戏内名称一致而保留；如需更自然可加 `_SUFFIX_GLOSS`
   覆盖表（当前未加，避免与游戏名不一致）。
7. `d1tables.unique_detail()`（itemgen2 负责）当前尚未出现；测试对它做了可选适配，
   一旦提供会自动改用 `unique_detail()['powers']` 验证。

## 11. 自测

```
ROOT\_py312\python.exe work\tests\test_i18n.py
→ 11/11 tests passed
```

覆盖点：JSON 缓存与 PO 重建结果逐条相等（防缓存过期）、PO 语法（msgctxt/多行/
转义/复数/fuzzy/#: 引用）、零宽字符、四类名称、`affix_desc`（含 param 语义与
min_val 不泄漏、指定值、固定效果拒绝）、110 件暗金 503 条 powers、`stat_label`、
PO 回退模式、模拟 `_MEIPASS` 冻结布局、`tr()` 边界。
