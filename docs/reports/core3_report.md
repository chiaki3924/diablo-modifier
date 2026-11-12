# core3 报告 · Round 3（词缀效果名 / 组合预检 / 指定页写入）

日期：2026-11-11 20:50
代理：core3
范围：`work/lib/d1i18n.py`、`work/lib/d1itemgen.py`（小改）、`work/lib/d1stash2.py`（仅 page 校验，写盘逻辑未动）、
`work/tests/test_round3_core.py`、本文件。
未改 `work/app/*`、未写真实存档。

---

## 0. 结论

| 项目 | 结果 |
|---|---|
| `d1i18n.affix_effect_label()` | 新增；86 前缀 + 98 后缀全部有可读效果名 |
| `d1i18n.affix_label(..., with_effect=True)` | 新增；132 条数值词缀显示「效果名 +min~max」，固定效果显示「固定效果：…」 |
| `d1itemgen.check_combination()` | 新增；9 类必需 code 全部可复现，返回值固定 6 键 |
| `ItemGenError.code` | 新增（默认 `"error"`，旧代码零改动）；`generate()` 与预检同码 |
| `Stash.add_record(page=...)` | 语义确认 + 越界校验 + 新增 `strict_page=False`；写盘逻辑未改 |
| `test_round3_core.py` | **14/14 通过**（0.6s） |
| 回归 | test_itemgen2 **10/10**、test_itemgen **15/15**、test_stash **14/14**、test_i18n **11/11** |
| 真实存档 | 只读；测试前后 SHA256 均为 `89CE5C08…`（103 件，92,112B），零写入 |
| `work/backup_saves/stash.sv` | 只读副本，SHA256 不变（`4E4648DF…`，96 件） |

所有 stash 测试只在 `work\tmp\test_round3_core_<pid>\` 的副本上 `save()`，测试结束自动删除。

---

## 1. 词缀效果名 API（GUI 下拉用）

### 1.1 `affix_effect_label(affix) -> str`

输入 `d1tables` 词缀行（`power_name`/`param1`/`param2`），返回简短中文效果名。
也接受裸 `ItemPower` 名（如 `"IPL_FIRERES"`）；无词缀信息返回 `""`。

| 词缀 | power | 返回 |
|---|---|---|
| Ruby | IPL_FIRERES | 火焰抗性 |
| Sapphire | IPL_LIGHTRES | 闪电抗性 |
| Diamond | IPL_MAGICRES | 魔法抗性 |
| Obsidian | IPL_ALLRES | 全抗性 |
| of the heavens | IPL_ATTRIBS | 所有属性 |
| Dragon's | IPL_MANA | 法力 |
| of the fox | IPL_LIFE | 生命 |
| Brutal | IPL_DAMP | 伤害 |
| Bronze | IPL_TOHIT | 命中 |
| of strength | IPL_STR | 力量 |
| of dexterity | IPL_DEX | 敏捷 |
| of vitality | IPL_VIT | 体力 |
| of magic | IPL_MAG | 魔法 |
| Glorious | IPL_ACP | 护甲 |
| haste | IPL_FASTATTACK | 攻速 |
| of the leech | IPL_STEALLIFE | 吸血 |
| Plentiful | IPL_CHARGES | 充能 |

实现：优先 `_EFFECT_SHORT`（仅两个口语化缩写：`攻击速度→攻速`、`生命吸取→吸血`），
其余直接取 `_POWER_SPEC[power][0]`，最后回落 `stat_label()`——与 `affix_desc()` 同一套翻译，
没有第二份词表，也没有改 PO 里的词缀名（`Dragon's` 仍是 `Dragon's`，中文仍是「翼龙的」）。

### 1.2 `affix_label(kind, affix, with_effect=False) -> str`

原签名兼容：`with_effect=False` 时输出与旧版逐字节一致（`中文名（English）`）。
`with_effect=True` 时：

- 数值词缀：`中文名（English） 效果名 +min~max`
- 固定效果：`中文名（English） 固定效果：…`（复用 `affix_desc` 的措辞，绝不编造数值）

示例（与实际输出逐字节一致）：

```text
红宝石（Ruby） 火焰抗性 +51~+60
蓝宝石（Sapphire） 闪电抗性 +51~+60
钻石（Diamond） 魔法抗性 +51~+60
翼龙的（Dragon's） 法力 +51~+60
黑曜石（Obsidian） 全抗性 +31~+40
天堂（of the heavens） 所有属性 +12~+15
匆忙（of haste） 固定效果：最快攻击
久远（of the ages） 固定效果：坚不可摧
丰富（Plentiful） 固定效果：充能次数 ×2
水蛭（of the leech） 固定效果：命中时3%生命偷取
锡（Tin） 命中 -10~-6
```

范围取自 `d1itemgen.affix_value_range()`（懒加载），因此下拉里能选的数值永远与
`generate(prefix_value=...)` 接受的范围一致；`d1itemgen` 不可用时回落到
`_POWER_SPEC` 的 `param1..param2`。格式按 Round 3 要求：**两端带符号、不带 % 单位**；
详细说明（含 `%`、需求等级、适用类型）仍由 `affix_desc()` 提供，两者不冲突。

---

## 2. 组合预检 API

### 2.1 签名与返回

```python
d1itemgen.check_combination(
    base_idx, ilvl, rarity="magic",
    prefix=None, suffix=None,
    prefix_value=None, suffix_value=None,
    onlygood=False,
    unique_id=None, seed=1, max_tries=None, value_tolerance=0,
    allow_staff_spells=False, allow_non_equipment=False,
) -> dict
```

返回固定 6 键：

```python
{
  "ok": bool,
  "code": str,                 # 见下表
  "message": str,              # 直接可显示的中文；level_window 含“把 ilvl 提到/降到 X”
  "suggestions": [str, ...],   # 已去重、可直接列在弹窗里
  "prefix": dict | None,       # 解析后的 d1tables 词缀行（含 level band）
  "suffix": dict | None,
}
```

对用户输入**不抛异常**（兜底 `code="error"`，message 带异常信息）。
规则全部调用 `generate()` 自己的函数：`_reject_base` / `_resolve_affix` /
`_check_value_target` / `_check_affix_reachable` / `_goe_conflict_error` /
`_affix_window` / `_search_seed` / `eligible_affixes`，不另写一套判定。

`max_tries=None`（默认）**只做规则预检、不搜种子**，可放在下拉/输入变化时实时调用；
传整数则在预算内真实搜索，搜不到返回 `seed_not_found`（有数值目标时 message 含最接近值）。
`seed` 默认 `1`，预检可复现。

### 2.2 错误码表

| code | 触发条件 | message 示例 / 要点 | suggestions |
|---|---|---|---|
| `ok` | 规则允许；传了 `max_tries` 时还要求预算内找到 | `规则检查通过：…` / `组合合法，预算内找到：Obsidian Ring of the heavens` | 空 |
| `bad_base` | 未知底材 / starter / unique_only / 不可装备 | `初始装备（IDI_SORCERER_DIABLO）…请改用普通底材（Short Staff…/Long Staff…）`、`「Cleaver」是 unique-only 底材…`、`「Gold」不是可装备底材…` | 可用替代底材 |
| `bad_affix` | 词缀不存在 / 类型不适用 / onlygood 坏词缀 / Hellfire-only / 普通或暗金物品带词缀 | `前缀「Brutal」不适用于「Ring」…可用的前缀：Crimson、Garnet…`；`找不到后缀「…」`；`后缀「the pit」是“坏”词缀…不能出现在 onlygood 物品上` | 列出该类物品可用词缀 |
| `level_window` | `min_level` 不在 `min(ilvl//2,25)..ilvl` | `前缀「Obsidian」需要词缀等级 24，ilvl=20 只允许 10..20；请把 ilvl 提到 24（或更高）`；`前缀「Obsidian」是 24 级词缀，低于 ilvl=50 允许的窗口 25..50；请把 ilvl 降到 49（24..49 都可以）` | 前后缀分别给出应调到多少 |
| `goe_conflict` | 善良前缀 + 邪恶后缀，或邪恶前缀 + 善良后缀（GOE_ANY 不冲突） | `前缀「Gold」是善良词缀，后缀「of trouble」是邪恶词缀…（GOE 冲突）` | 列出中立（GOE_ANY）后缀 |
| `fixed_affix_value` | 对固定效果指定了数值 | `后缀「the ages」的效果 IPL_INDESTRUCTIBLE 不是可指定的数值效果…请去掉 suffix_value` | 去掉数值 |
| `value_out_of_range` | 目标值不在 `param1..param2 ± tolerance` | `未找到 前缀 Ruby = +100（最接近 +60，差距 40）；该词缀的可选范围是 +51~+60` | 给出正确区间 |
| `seed_not_found` | 规则合法，但 `max_tries` 预算内无种子（或数值搜索未命中） | `未找到 前缀 Brutal = +85（最接近 +86，差距 1）…已尝试 2000 个种子`；无数值目标时说明没有最接近值 | `提高 max_tries` / `放宽容差` / `只指定一个数值` |
| `staff_ilvl` | 属性法杖 `ilvl>51`（`allow_staff_spells=False`） | `法杖在 ilvl > 51 时…不能生成属性词缀法杖` | `ilvl 降到 51` 或 `allow_staff_spells=True` |
| `bad_rarity` | rarity 不是 normal/magic/unique | `稀有度必须是 normal（普通）/ magic（魔法）/ unique（暗金）` | 改成三者之一 |
| `bad_ilvl` | `ilvl` 不在 0..63 | `ilvl 必须是 0..63…` | 改 ilvl |
| `bad_value` | `prefix_value/suffix_value` 不是整数 | `…必须是整数，收到 …` | 填整数 |
| `error` | 兜底（未预期异常） | 含异常类型与文本 | 空 |

### 2.3 `ItemGenError.code` / `.suggestions`

```python
class ItemGenError(ValueError):
    code = "error"          # 类属性默认值，旧的 raise ItemGenError("...") 不受影响
    suggestions = ()
    def __init__(self, message="", code=None, suggestions=None): ...
```

`generate()` 失败时按同一张表打码（`strict=False` 仍返回 `None`）。现有中文消息中
被测试断言的句子全部保留（`未找到`、`已尝试`、`不是可指定的数值效果`、`需要同时指定`、
`只适用于`、`初始装备`、`法杖`、`unique-only`）；只有此前没有断言的英文消息
（等级窗口、类型不适用、未知底材、无种子）改成了中文，并补了 suggestions。

### 2.4 实际示例（Ring + Obsidian + of the heavens）

```python
>>> G.check_combination(ring, 30, "magic", prefix="Obsidian", suffix="of the heavens")
{'ok': True, 'code': 'ok', 'message': '规则检查通过：未搜索种子（传 max_tries 可顺便验证能否生成）',
 'suggestions': [], 'prefix': {'name': 'Obsidian', ...}, 'suffix': {'name': 'the heavens', ...}}

>>> G.check_combination(ring, 20, "magic", prefix="Obsidian", suffix="of the heavens")["message"]
'前缀「Obsidian」需要词缀等级 24，ilvl=20 只允许 10..20；请把 ilvl 提到 24（或更高）'
# suggestions：["前缀「Obsidian」需要词缀等级 24：把 ilvl 提到 24（或更高）",
#               "后缀「the heavens」需要词缀等级 25：把 ilvl 提到 25（或更高）"]

>>> G.check_combination(ring, 50, ...)["message"]
'前缀「Obsidian」是 24 级词缀，低于 ilvl=50 允许的窗口 25..50；请把 ilvl 降到 49（24..49 都可以）'

>>> G.check_combination(ring, 30, ..., max_tries=200000)["message"]
'组合合法，预算内找到：Obsidian Ring of the heavens'
```

---

## 3. 指定页写入（`d1stash2.Stash.add_record`）

### 3.1 现有语义（已确认，未改）

- `page` 是 **0-based**：`page=0` 是第 1 页；有效范围 `0..99`（`MAX_STASH_PAGES=100`）。
- 指定页有空位 → 放该页；指定页**不存在** → 新建该页（放在 `(0,0)`）——即“指定空页”。
- 指定页已满且 `strict_page=False`（默认）→ 按页号升序**顺延**到其它有空位的页；
  所有页都满 → 新建 `max(page)+1`；100 页都满 → `StashError("储物箱已满…")`。
- 记录 `position` 仍按 `fix_position=True` 改成左下角锚点；写盘逻辑/格式完全未动。

### 3.2 本轮小改

1. **页号越界**（`<0` 或 `>99`，或非整数）在 `add_record` 入口直接抛 `StashError`，
   不再把 `page=-1` 写成 `0xFFFFFFFF`、`page=100` 写成非法页：

   ```text
   页码越界：100。page 是 0-based，有效范围 0..99（第 1 页 = page 0，第 100 页 = page 99）
   ```

2. 新增关键字参数 `strict_page=False`（向后兼容）。GUI 的“写入第 N 页”可传
   `page=N-1, strict_page=True`：指定页放不下时得到明确错误，而不是悄悄写到别的页：

   ```text
   第 1 页（page=0）没有能放下 1x1 物品的空位；请换一页、新建一页，或允许自动顺延（strict_page=False）
   ```

   指定页不存在时 `strict_page=True` 也会正常新建该页（符合“可指定空页”）。

> GUI 接入：用户输入 1-based 页号 N → `add_record(rec, page=N-1, strict_page=True)`；
> 返回值 `(page, x, y)` 里的 `page` 可用于回显“实际写入第 page+1 页”。
> 不传 `page` 时行为与 v2.1 完全一致（默认第一页有空位就写第一页）。

---

## 4. 测试

### 4.1 新测试 `work\tests\test_round3_core.py`（14/14）

```powershell
& "F:\Qoder\暗黑1重制版\_py312\python.exe" work\tests\test_round3_core.py
# 14/14 tests passed in 0.59s
```

覆盖：

1. `affix_effect_label` 16 个代表词缀（含要求的 火焰/闪电/全抗/所有属性/法力/攻速/吸血/充能），
   并扫描 184 条词缀全部有可读效果名。
2. `affix_label(with_effect=True)`：Ruby / Sapphire / Diamond / Dragon's / Obsidian / heavens
   逐字节比对；固定效果（haste / the ages / Plentiful / the leech）无假数值；
   132 条数值词缀的后缀范围与 `affix_value_range()` 完全一致；`with_effect=False` 与旧格式一致。
3. Ring + Obsidian + of the heavens：ilvl=30/40 → `ok`；ilvl=20 → `level_window` +
   “提到 24”（并提示后缀需要 25）；ilvl=50 → `level_window` + “降到 49”；
   `max_tries=200000` 实际生成到 `Obsidian Ring of the heavens`。
4. 固定词缀 + value → `fixed_affix_value`；越界 → `value_out_of_range`（含最接近值/区间）；
   区间内 → `ok`。
5. starter / unique_only / 金币 / 未知底材 → `bad_base`；Brutal 用在戒指 → `bad_affix`；
   未知后缀 / onlygood + 坏词缀 / normal+词缀 / 暗金+词缀 → `bad_affix`。
6. GOE：`Gold`(good) + `trouble`(evil) → `goe_conflict`；`Gold` + `the wolf`(GOE_ANY) → ok；
   反向 `Vicious`(evil) + `vigor`(good) → `goe_conflict`。
7. 法杖 ilvl=60 → `staff_ilvl`（建议 51）；ilvl=51 → ok；`bad_rarity` / `bad_ilvl`；
   暗金低于 min_level → `level_window`。
8. `seed_not_found`：Brutal+giants 双数值 2000 seeds（message 含“最接近 +86”）；
   Obsidian+heavens 20 seeds；同组合 200k seeds → ok。
9. `generate()` 的 8 个失败路径逐一对码；预检与 `generate()` 对同一请求返回相同 code。
10. 预检通过后 `generate()` 产出记录 `validate()==[]`。
11. stash：page 0/1/5/99、`-1/100/12345` 越界、满页顺延、`strict_page=True` 报错、
    `page=None`、不存在页新建、100 页全满；save/reload 保留页号与记录。
12. 安全：真实存档 run 前后 SHA256 一致且仍为 `89CE5C08…` 基线；backup stash 不变。

### 4.2 回归（全部通过）

| 套件 | 结果 |
|---|---|
| `work\tests\test_itemgen2.py` | 10/10（3.79s） |
| `work\tests\test_itemgen.py` | 15/15 |
| `work\tests\test_stash.py` | 14/14（3.72s） |
| `work\tests\test_i18n.py` | 11/11 |
| `work\tests\test_round3_core.py` | 14/14（0.59s） |

真实存档：`%APPDATA%\diasurgical\devilution\stash.sv`，103 件 / gold 313108 /
SHA256 `89CE5C0896B13223F429241DAFFBD41F9B26FE4D418B1546889BCEC72A5F7BC0`（92,112B），
测试运行前后完全一致（只读校验，未打开写模式）。

---

## 5. 给 gui3 的接入清单

1. 下拉文本：把 `Affix.label` 改成
   `d1i18n.affix_label(kind, raw, with_effect=True)`（或 `affix_effect_label(raw)` +
   现有 `range_text`）。效果名与范围已由 core3 保证和生成器一致。
2. 生成前预检：`G.check_combination(base_idx, ilvl, rarity, prefix=…, suffix=…,
   prefix_value=…, suffix_value=…, onlygood=…)`，默认零搜索、可实时调用；
   弹窗按 `code` 着色：`ok` 绿；`level_window` / `goe_conflict` / `fixed_affix_value` /
   `value_out_of_range` / `bad_affix` / `bad_base` / `staff_ilvl` 红；
   `seed_not_found` 橙（“组合合法，只是没搜到”，建议放宽预算）。`suggestions` 直接列条。
3. 生成失败：`except d1itemgen.ItemGenError as exc: exc.code / exc.suggestions / str(exc)`。
4. 页码：用户 1-based N → `page=N-1, strict_page=True`；捕获 `StashError` 显示
   “页码越界 / 第 N 页没有空位”。不指定页时保持 `add_record(rec)` 原行为。
5. 不要缓存 `check_combination` 的 `prefix`/`suffix` dict 后修改——它们是表行的副本。

## 6. 已知限制

- `check_combination` 默认不搜种子，`ok` 只代表“规则允许”；传 `max_tries` 才会验证种子。
- 预检的种子搜索起点固定为 `seed=1`（可复现）；`generate()` 仍用随机/指定种子，
  因此“预检 200k 没找到”不代表 `generate(max_tries=2M)` 一定失败。
- 数值标签按 Round 3 要求写成 `+51~+60`（无 `%`）；tooltip 的完整文案仍用 `affix_desc`
  （带 `%`、需求等级、适用类型）。
- 固定效果（攻速/充能/法术/吸血/耐久百分比等）不能指定数值，标签也不会显示范围。
- 属性法杖仍受 ilvl<=51 限制；GOE 冲突只在前缀为善良/邪恶时成立，GOE_ANY 前缀不限制后缀。
