# 暗黑破坏神1 存档修改器 v2 —— GUI 与打包报告

> 交付物：`F:\Qoder\暗黑1重制版\交付\暗黑破坏神1存档修改器-v2.exe`
> 源码：`work\app\*`　打包脚本：`work\build\build_exe.ps1`　截图：`work\docs\shots\`
> 适配：DevilutionX **1.5.5**（非 Hellfire）、Windows x64、Python 3.12

---

## 1. 一句话总结

原修改器（单页 tkinter，只能改等级/四维/箱子金币/法术）被重写为**单窗口四标签**中文界面（Round 2 增加「暗金图鉴」）：

| 标签页 | 能力 | 写盘模块 |
|---|---|---|
| 角色 | 等级 / 经验 / 四维 / 剩余属性点 / 生命法力 / 角色金币 / 法术等级、全学、遗忘 | `d1save.SaveFile` + `HeroPack` |
| 储物箱 | 金币、物品分页列表、删除物品、**异常物品检查/清理**、改金币绝不丢物品 | `work/lib/d1stash2.py`（修正版 MPQ 写入） |
| 装备生成 | 底材下拉（中文（English），已排除 starter/暗金底材）、ilvl、普通/魔法、seed、**中文前缀/后缀 + 属性说明 + 可指定数值/容差**、预览、合法性校验、生成到储物箱/背包 | `work/lib/d1itemgen.py` + `d1stash2` |
| 暗金图鉴 | 89 件暗金列表（可按底材/等级/关键字过滤）→ 固定词条中文明细 → 一键生成到储物箱/背包 | `work/lib/d1itemgen.py`（unique_id）+ `d1stash2` |

关键安全机制：**游戏运行检测**（`tasklist devilutionx.exe`，运行中拒绝写盘）、**每次写盘前两层备份**（`.bak` + `.bak-YYYYmmdd-HHMMSS`）、**写后逐字节/逐字段校验**、失败自动回滚。

---

## 2. 界面截图

| 角色页 | 储物箱页 | 装备生成页 |
|---|---|---|
| ![角色](shots/tab_char.png) | ![储物箱](shots/tab_stash.png) | ![装备生成](shots/tab_gen.png) |

Round 2 新增截图（`work/docs/shots/r2_*.png`）：

| 底材列表（无 starter/暗金名） | 中文词缀 + 说明 + 目标值 |
|---|---|
| ![底材](shots/r2_base_list.png) | ![词缀](shots/r2_affix_value.png) |

| 生成预览（中文） | 暗金图鉴 |
|---|---|
| ![预览](shots/r2_preview.png) | ![暗金](shots/r2_uniques.png) |

截图取自源码运行（`work/build/make_shots.py`，PrintWindow 离屏抓取，不需要屏幕可见）：

- 顶部实时显示“游戏正在运行 —— 已禁用写存档 / 游戏未运行 —— 可以安全写入存档”；
- 角色页：存档下拉自动选最近存档并显示「剑来 · 战士 · 24 级」，下方直接可改数值与法术；
- 储物箱页：显示 96 件物品、10 页、金币 313,108，并标注“使用修正版写入（d1stash2，不丢物品）”；
- 装备生成页：生成器就绪提示、79 种可装备底材、暗金下拉、预览/校验区。

---

## 3. 目录与文件

```
work/app/
  d1editor2.py          # 入口：App、顶部状态栏、菜单、--selftest（含真实存档哈希断言）
  d1env.py              # pyc 模块加载、路径、存档目录、游戏进程检测、备份/回滚、
                        #   ALLOW_PROTECTED_WRITES 自动测试写保护
  d1hero.py             # 角色存档读写（HeroPack 封装 + 写后校验 + 写保护）
  d1names.py            # 物品/职业/法术中文名、分类、稀有度
  d1zh.py               # 中文名/属性说明（优先 d1i18n，其次 zh_fallback.json）
  d1stash_adapter.py    # 储物箱适配层（d1stash2 优先；自动测试下返回只读保护壳）
  d1itemgen_adapter.py  # 装备生成适配层（starter/unique_only 过滤、词缀、数值、暗金）
  ui_common.py          # 样式、日志窗、后台任务 TaskRunner、消息框封装
  ui_genops.py          # 生成结果写入（储物箱/背包）+ 写后重开校验
  ui_char.py            # 「角色」页
  ui_stash.py           # 「储物箱」页（含异常物品检查/清理）
  ui_itemgen.py         # 「装备生成」页
  ui_uniques.py         # 「暗金图鉴」页
  zh_fallback.json      # PO 兜底翻译（d1i18n 缺失时用）
work/build/
  build_exe.ps1         # 一键复现打包（组织数据 → PyInstaller → 跑 --selftest）
  gen_zh_fallback.py    # 从 1.5.5 的 zh_CN.po 生成 zh_fallback.json
  smoke_test.py         # 端到端无窗口冒烟测试（只操作 work/tmp 副本）
  make_shots.py         # 进程内抓图（PrintWindow）
  screenshot.ps1        # 外部窗口抓图（备用）
  dist/暗黑破坏神1存档修改器-v2.exe
work/docs/gui_report.md # 本文件
work/docs/shots/tab_*.png + r2_*.png
```

---

## 4. 各页细节

### 4.1 角色页

- 自动扫描 `%APPDATA%\diasurgical\devilution\*.sv`（single_/multi_/spawn_/stash 都识别，stash 自动从角色列表里排除），按修改时间倒序；显示「文件名 · 角色名 · 职业 · 等级」。
- 支持「浏览其他文件…」（filedialog）与「重新加载」。
- 可改：等级（1–50）、经验、力量/魔法/敏捷/体质、剩余属性点、生命当前/上限、法力当前/上限、角色金币、单个法术等级、全部学会（15 级）、遗忘全部。
- 生命/法力以 `pHitPoints/64` 语义直接写 `pHPBase`/`pMaxHPBase`/`pManaBase`/`pMaxManaBase`；先写等级与四维（会触发 `recalc_pools`），再覆盖生命法力，避免被重新计算覆盖。
- 保存调用 `SaveFile.save(out_path=原路径, backup=True, clear_progress=False)`，**保留关卡进度**；写前另存一份 `.bak-YYYYmmdd-HHMMSS`，写后重新打开校验角色名与等级，失败自动回滚。
- 金币说明：游戏把金币拆成 ≤5000 的堆放进背包，背包格子不够时会被少放；保存后若实际值与输入不同会在日志里标黄提示。

### 4.2 储物箱页

- 默认打开 `%APPDATA%\diasurgical\devilution\stash.sv`，单人/多人自动尝试（先按当前选择，失败自动换另一种），并显示实际使用的类型。
- 列表显示：页、左上角坐标+尺寸、物品名（存档里的英文名）、中文类型、是否暗金（★）、记录序号。
- 「保存金币」流程：
  1. 复制 `.bak-时间戳`；
  2. `Stash.gold = 新值`；
  3. `Stash.save(backup=True)`（未压缩、无扇区表、不改哈希表，符合简报 §2.4）；
  4. **重新读回并比对**：物品记录必须逐字节一致、金币必须等于输入，否则自动用备份回滚并报错。
- 「删除选中物品」同样先备份、写后校验记录集合。
- 已实测：96 件物品改金币后逐字节不变（`SMOKE OK`）；`verify_roundtrip()` 为 True。

### 4.3 装备生成页

- 左列：类型筛选（全部 / 武器 / 防具 / 戒指护符）+ 关键字搜索 + 底材列表框（中文（English））。
  - 底材来自 `d1itemgen.base_items()`，只保留 `available` 且可装备的 itype（排除 Gold/Misc/药水/卷轴/任务物品），同名去重时**优先掉落版**（`drop_rate != IDROP_NEVER`），例如 Short Sword 取 idx=119（掉落版），而不是 idx=1 的起始装备版。
  - **Round 2**：额外强制排除 `starter`（IDI_WARRIOR/WARRSHLD/WARRCLUB/ROGUE/SORCERER/SORCERER_DIABLO）与 `unique_only`（IMISC_UNIQUE）底材；最终 69 种。详见 §10.1。
- 参数（Round 2 版本）：ilvl（默认取角色等级，1–50）、稀有度（**普通/魔法**，暗金移到「暗金图鉴」页）、seed（留空 = 随机）、前缀/后缀下拉（**中文（English）+ 数值范围**）、每个词缀的「目标值/容差」、数量（1–10）。
- 生成走后台线程（`TaskRunner`），界面显示进度与已用时间并带「取消」；指定数值时提示「通常 1~3 秒」。
- 结果：`itemgen.generate(...)` 返回的 `GenItem`（368 字节记录、fields）；适配层生成**中文预览**（名称/底材/品质/伤害/防御/耐久/需求/价值/词条实际值），末尾附 d1itemgen 英文原文技术详情；随后 `itemgen.validate(record)` 校验，**校验不通过则拒绝写入并列出原因**。
- 两个目标（`ui_genops.py`，与暗金页共用）：
  - 「生成到储物箱」：`record = itemgen.generate(...).record` → `stash.add_record(record)` → `stash.save()` + 逐字节校验 + **重开校验物品数 == 写前 + N**；
  - 「生成到角色背包」：用 `base['idx']`（运行时编号）+ `fields['iSeed']` + `fields['iCreateInfo']` 调 `pack.add_item(...)`，再 `SaveFile.save(clear_progress=False)`；写后重开校验背包物品数。
- 「简易随机 → 背包（免生成器）」：不依赖 d1itemgen，随机 seed + `create_info`（普通=0；魔法=`ilvl*2 | CF_ONLYGOOD`），让游戏 `RecreateItem` 自己重建，天然合法。
- 自选词条/数值：把选中的词缀（按 **index** 传，避免同名不同档）+ `prefix_value`/`suffix_value`/`value_tolerance` 传给 `itemgen.generate(...)`，由 itemgen 做 **seed 搜索**，保证存档里的名字/数值与游戏按 seed 重算的结果一致；失败时显示 itemgen 的中文原因（含最接近值），并追加「放宽容差 / 只指定一个数值 / 换词缀」的建议，不弹 traceback。

---

## 5. 安全性设计

1. **游戏进程检测**：顶部状态栏每 ~5 秒后台 `tasklist` 检测 `devilutionx.exe`；检测到运行中时，所有保存/生成写入按钮都会先弹提示并拒绝执行。
2. **双层备份**：每次写盘前
   - 模块自身备份：`SaveFile.save(backup=True)` → `<文件>.bak`；`Stash.save(backup=True)` → `<文件>.bak`；
   - 本程序备份：`<文件>.bak-YYYYmmdd-HHMMSS`（同秒重名自动加序号）。
3. **写后校验**：
   - 角色：重新打开，比对角色名与等级；
   - 储物箱：重新打开，比对全部 368 字节物品记录 == 写前，金币 == 输入；
   - 背包：重新打开，比对 `_pNumInv` 增量；
   - 任何不一致 → 用时间戳备份回滚并报错。
4. **绝不使用原 `StashFile.save()`**（简报 §2 的 MPQ 扇区 bug），只用 `d1stash2`；`d1stash2` 缺失时退化为只读浏览并禁用保存。
5. **自动测试写保护（Round 2 新增）**：`d1env.ALLOW_PROTECTED_WRITES` 在 `--selftest`（headless）/`smoke_test.py`/`make_shots.py` 里自动为 `False`。此时
   - `d1hero.save()` 调 `assert_writable()`，写 `%APPDATA%\diasurgical\devilution` 直接抛 `ProtectedWriteError`；
   - `open_stash()` 对真实存档返回 `GuardedStash` 只读壳，`save/add_record/remove_record` 全部拦截；
   - `--selftest` 与 `smoke_test.py` 结束时会比对真实存档目录里所有 `.sv/.hsv` 的 SHA256，**必须完全一致**才算通过；
   - 附带修掉一个真实 bug：`refresh_all()` 以前会 `refresh_files()` 后选中默认的 `%APPDATA%\stash.sv`，把正在编辑的副本换掉；现在会保留当前已打开的角色/储物箱文件。
6. 开发/测试只操作 `work\tmp` 副本；`smoke_test.py` 里即使游戏在运行也只写副本（测试内单独放行），真实界面仍然拦截。

---

## 6. 打包（可复现）

### 6.1 环境

- **Python 3.12**（3.12 pyc 只能被 3.12 的 `marshal` 读）：本机用 uv 自带的完整版
  `C:\Users\39247\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none\python.exe`。
  - `ROOT\_py312` 是 embeddable 发行版，**没有 tkinter**（缺 `_tkinter.pyd`/`tk86t.dll`），不适合做 GUI 打包，故未使用。
- 创建 venv 并装 PyInstaller（脚本会自动做）：
  ```powershell
  <上面的 python.exe> -m venv work\build\venv312
  work\build\venv312\Scripts\python.exe -m pip install pyinstaller
  ```
- 本次版本：PyInstaller 6.22.3 / Python 3.12.14。

### 6.2 一键打包

```powershell
pwsh -NoProfile -File work\build\build_exe.ps1
```

脚本做的事：

1. 关掉可能残留的 v2 窗口（避免抢前台 / 文件占用）；
2. `work\build\pyc\` ← 从 `…exe_extracted\PYZ.pyz_extracted` 复制 **7 个 pyc**（d1save/d1codec/d1mpq/d1pkware/d1rng/d1items/d1spells）；
3. `work\build\lib\` ← `d1stash2.py`；`work\build\lib\py\` ← `d1itemgen.py`、`d1tables.py`、`d1i18n.py`；`work\build\lib\data\` ← `zh_CN.json`
   （`d1tables.ROOT = Path(__file__).parents[2]`、`d1i18n` 冻结模式优先 `_MEIPASS\_d1lib\data\zh_CN.json`，
   所以 d1itemgen/d1tables/d1i18n 放 `_d1lib/py/`、翻译缓存放 `_d1lib/data/`）；
4. `work\build\srcdata\DevilutionX-1.5.5\Source\` ← `itemdat.h/items.h/spelldat.h/itemdat.cpp/items.cpp/spelldat.cpp/cursor.cpp`
   （`d1tables` 在 import 时解析这些 1.5.5 源码表；不随包携带的话，exe 里的生成器会加载失败）；
5. PyInstaller 参数（关键部分）：
   ```
   --onefile --windowed --name 暗黑破坏神1存档修改器-v2 --icon <原 exe 解包的 icon.ico>
   --paths work\app
   --add-data work\build\pyc;_d1pyc
   --add-data work\build\lib;_d1lib
   --add-data work\app\zh_fallback.json;.        # d1i18n 缺失时的中文兜底表
   --add-data <每个 1.5.5 表文件>;DevilutionX-1.5.5\Source
   --add-data <每个 tsv>;devilutionX\assets\txtdata\items
   --hidden-import glob/shutil/bz2/zlib/struct/time/os/sys   # pyc 是运行时按路径加载，PyInstaller 分析不到它们的依赖
   work\app\d1editor2.py
   ```
6. 产物 `work\build\dist\暗黑破坏神1存档修改器-v2.exe`，随后自动执行 `--selftest`，并**断言日志里有 `d1i18n`（中文数据进包）与「真实存档 SHA256 前后一致」**，否则打包失败。

```
== 产物：work\build\dist\暗黑破坏神1存档修改器-v2.exe  10.7 MB
== 运行 --selftest ==
selftest exit code = 0
[19:45:05] OK: pyc 模块加载自 C:\Users\...\Temp\_MEI000047f02\_d1pyc
[19:45:06] OK: 标签页 = ['角色', '储物箱', '装备生成', '暗金图鉴']
[19:45:06] OK: 四页控件齐全
[19:45:06] OK: 读取存档 single_0.sv -> chiaki · 浪人 · 31 级, HP 111/111, 金币 14843, 法术 17
[19:45:06] OK: 读取储物箱 金币=313,108 物品=98 页=[0, 1, 2, 3, 6, 7, 8, 9, 10, 11]
[19:45:06] OK: 生成器状态 = 生成器已就绪（d1itemgen）；可指定数值；随机/自选词条；暗金图鉴；合法性校验
[19:45:06] OK: 中文数据 = 中文数据：d1i18n（d1i18n.py）
[19:45:06] OK: 基础物品 69 种（已排除 starter / unique_only）
[19:45:06] OK: 暗金图鉴 89 件（可用）
[19:45:06] OK: 生成魔法物品 Platinum Long Sword（铂金长剑）校验 通过
[19:45:06] OK: 指定数值 金=25 → Gold Long Sword（PLDam/值 25）
[19:45:06] OK: 拒绝 starter 166 = 初始装备（IDI_SORCERER_DIABLO）不能作为随机底材生成…
[19:45:06] OK: 生成暗金 Ring of Engagement（订婚戒指）校验 通过
[19:45:06] OK: 真实存档 4 个文件 SHA256 前后一致（未写入）
SELFTEST OK
== BUILD OK ==
```

> 打包版是 `--windowed`，没有控制台，`--selftest` 的日志同时写到 `%TEMP%\d1editor2_selftest.log`。

### 6.3 产物（Round 2 快照 —— 最新 Round 3 产物见 §11.7）

| 项目 | 值 |
|---|---|
| 路径 | `F:\Qoder\暗黑1重制版\交付\暗黑破坏神1存档修改器-v2.exe`（同时复制到游戏目录） |
| 大小 | 11,221,628 字节（10.7 MB） |
| SHA256 | `2E2E070A8BE5E814614D33C58113BEF0766DFCB7870E7B1531A22986335559CD` |
| 自检 | `--selftest` 退出码 0（源码与打包版都跑过） |
| 启动 | `subprocess` 启动 7 秒后进程存活、无闪退（窗口在独立 window station，外部 EnumWindows 看不到，故用进程存活 + 进程内截图双重确认） |
| 随包库 | `_d1lib/py/d1tables.py` 48845、`d1itemgen.py` 119232、`d1i18n.py` 42420；`_d1lib/data/zh_CN.json` 212709（staging 与 `work/lib` SHA256 逐一核对一致） |

---

## 7. 自测

### 7.1 `--selftest`（源码，Python 3.12）

```
work\build\venv312\Scripts\python.exe work\app\d1editor2.py --selftest
→ SELFTEST OK / EXIT=0
```

检查项（Round 2）：pyc 模块加载、四标签页、每页关键控件、真实存档只读解析、储物箱只读解析、生成器状态、中文数据来源（必须是 `d1i18n`）、底材 69 种且不含 starter/暗金名、暗金 89 件、生成 1 件魔法物品、指定数值生成（PLDam 必须等于目标值）、拒绝 166、生成 1 件暗金、**真实存档 SHA256 前后一致**。

### 7.2 端到端冒烟（`work\build\smoke_test.py`，只写 `work\tmp` 副本）

```
SMOKE OK
```

覆盖：

- 储物箱改金币 313108 → 424242，96 条记录**逐字节不变**，生成 `.bak` + `.bak-时间戳`；
- `add_record` + `flush`：97 件，原 96 件顺序与内容不变；
- 生成器：69 种可装备底材、无 Gold/药水/卷轴、同名已去重、Short Sword 选中掉落版（idx=119, saved=114）；
- 随机魔法 → 储物箱：新记录 368 字节、`validate()==[]`、写盘后重开物品数 +1；
- 生成 → 角色背包：`_pNumInv` 22 → 23，`.bak` 备份存在；
- 简易随机 → 背包：22 → 24；
- 角色改数值保存：等级 26、四维 140/30/40/60、剩余点 7、经验 5,000,000、金币 50,000、生命 190/222、法力 77/90 全部往返一致；
- **Round 2 追加**：
  - 底材列表无 starter/unique_only/166/暗金名；`check_base(166)` 拦截、`check_base(125)` 放行；
  - 前缀/后缀中文名 + 说明（残忍/Brutal：伤害 +81~95%；需要物品等级 16；适用 弓/法杖/武器）；
  - 指定前缀数值 `残忍 +85` → 记录 `PLDam=85`、`validate()==[]`、写盘后重开 +1；
  - 暗金图鉴 89 件、中文名、每件都有词条说明；`Lightsabre(uid=30)` 一键生成 → 记录名 `Lightsabre`、校验通过；
  - 伪 starter 记录（saved idx=5）被判 fatal；`scan_issues` 找到；`delete_indices` 删除后物品数回退、其余记录逐字节不变；
  - 写背包后储物箱仍指向 `work/tmp` 副本（回归 `refresh_all` 切换文件的 bug）；
  - **真实存档 4 个文件 SHA256 前后一致**。

---

## 8. 已知限制 / 注意事项

1. **背包写入有底材限制**：`d1save` 同步 `game` 块时需要可复用的 368 字节 heroitems 模板；某些底材（例如 Long Sword idx=125 在背包里没有同款）保存后会提示“1 件没有可用模板未同步”，物品不落盘。GUI 已检测并明确提示，建议优先用「生成到储物箱」（完整 368 字节记录，最稳）。
2. **角色金币受背包空间限制**：金币以 ≤5000/堆放入背包，格子不够会少放；保存后日志会提示“请求 X，实际写入 Y”。
3. **取消是“件间生效”**：`d1itemgen.generate` 没有 cancel 回调，点取消会在当前这件生成完/超时后停止；指定数值时要搜索 seed（默认 200 万次预算，通常 1~3 秒），双数值组合偶尔会失败（提示“未找到 +X，最接近 +Y”）。
4. **底材表口径**：`d1itemgen.base_items()` 默认返回 `generatable` 行；GUI 另外做防御性过滤（available + 可装备 itype + 非 starter + 非 unique_only + 非 usable），同名去重“掉落版优先”。最终 69 种（itemgen2 那边不去重时是 74 行，差 5 行来自 Ring×3→1、Amulet×2→1 与 2 件同名起始装备）。
5. **暗金 ilvl**：暗金页选中后会自动把 ilvl 抬到该暗金 `min_level`，避免 `requires item level x`。
6. **只支持 1.5.5 非 Hellfire**：物品记录是 1.5.5 布局（名字 64 字节），Hellfire/1.6 存档不要用。暗金图鉴里 Bovine Plate（uid 9）底材在非 Hellfire 不可用，按 89 件显示并说明。
7. **写盘前必须退出游戏**：本程序会拦截，但请勿用任务管理器强杀后立刻写（游戏可能已排队写盘）。
8. **未做游戏内验收**：本代理只保证文件级正确性（写后逐字节校验 + itemgen.validate）；游戏内实际拾取/持久化由 game-verify 代理验收。
9. **打包体积** 10.7 MB（onefile，含 tkinter、7 个 pyc、d1stash2/d1itemgen/d1tables/d1i18n + zh_CN.json、1.5.5 表源码与 TSV、zh_fallback.json）。
10. **截图时游戏正在运行**：`r2_*.png` 取自用户当时开着游戏的状态，顶部显示“游戏正在运行 —— 已禁用写存档”是真实状态提示，不影响功能。

---

## 9. 给用户的最短使用说明

1. **退出游戏**（程序会检测，运行中不让写）。
2. 双击 `交付\暗黑破坏神1存档修改器-v2.exe`。
3. 角色页：改数值 → 「保存到存档」（自动备份）。
4. 储物箱页：改金币 → 「保存金币」（物品一件不少，写后自校验）。
5. 装备生成页：选底材 → ilvl/稀有度 → 「生成到储物箱」或「生成到角色背包」。
   想指定词条就选「前缀/后缀」（中文名），需要固定数值就在「目标值」里填（留空=随机），程序会搜索能自然 roll 出该数值的 seed；非法组合会被拒绝并说明原因。
6. 暗金图鉴页：左侧点一件暗金 → 右侧看固定词条 → 「生成到储物箱 / 角色背包」。
7. 储物箱页：不确定存档有没有坏东西时点「检查异常物品」（会逐件校验），红色「致命」项就是会崩溃的物品，勾选后「删除选中」（自动备份 + 删后校验）。
8. 出问题：同目录的 `*.bak`、`*.bak-时间戳` 就是每次写盘前的原始文件，直接改名覆盖即可恢复。

---

## 10. Round 2 修复说明（2026-11-11 晚）

> 对应 5 个用户反馈：①生成装备后进游戏崩溃 ②底材列表出现暗金名 ③前缀/后缀英文 ④词缀数值不能指定 ⑤需要暗金图鉴；
> 外加新增的「储物箱异常物品检查/清理」。

### 10.1 问题 ②+①：底材列表与崩溃防护

**根因**：`d1tables.base_items()` 里混着两类不能当随机底材的行：
- `unique_only`（IMISC_UNIQUE，10 行）：名字就是暗金名（`Arkaine's Valor`/`Griswold's Edge`/`Veil of Steel`/`Harlequin Crest`/`The Undead Crown`/`Bovine Plate`…）；
- `starter`（IDROP_NEVER 的起始装备）：`IDI_WARRIOR`(1 Short Sword)、`IDI_WARRSHLD`(2 Buckler)、`IDI_WARRCLUB`(3 Club)、`IDI_ROGUE`(4 Short Bow)、`IDI_SORCERER`(5 Short Staff of Mana)、**`IDI_SORCERER_DIABLO`(166 Short Staff of Charged Bolt，用户崩溃元凶)**。

**做法**（`d1itemgen_adapter.BaseItem` + `ItemGen.base_items()`）：

1. 只保留 `available` + 可装备 itype（Sword/Axe/Bow/Mace/Staff/Shield/Helm/\*Armor/Ring/Amulet）+ 非 `usable`；
2. **防御性二次过滤**（不依赖 itemgen2 是否更新）：
   - `raw['unique_only']` 或 `misc_id == IMISC_UNIQUE` → 排除；
   - `raw['starter']` 或 **运行时编号 ∈ {1,2,3,4,5,166}**（由 `d1tables.ITEM_INDEXES` 的 `IDI_*` 动态解析 + 硬编码兜底）→ 排除；
   - `raw['droppable'] is False` / `drop_rate_name == IDROP_NEVER` → 排除；
   - 若 itemgen2 提供 `generatable` 字段，仍以本层规则为准（双保险）。
3. **同名去重**：`Ring`×3、`Amulet`×2 合并为 1；`Short Sword`/`Buckler`/`Club`/`Short Bow` 保留**掉落版**（119/71/140/143）。注意**不能按名字判断 starter**：这些名字同时被起始装备和正常掉落版共用（第一版实现踩过这个坑，误杀了 4 件合法底材）。
4. 最终 **69 种**（itemgen2 未去重口径 74 行）；`--selftest` 与 `smoke_test.py` 都断言：不含 starter/unique_only/166/暗金名。

**生成前拦截**（`ItemGen.check_base()`）：选到 starter / unique_only / 非掉落底材 → 直接中文提示并拒绝，例如：
> 运行时编号 166 是初始装备（starter，如 Short Sword / Short Staff of Charged Bolt），游戏不会随机生成，写进存档会导致进游戏崩溃。

底层另外还有 itemgen2 自己的拒绝（`generate(166)` 抛中文 `ItemGenError`），三层防护。

### 10.2 问题 ③：中文前缀/后缀 + 属性说明

- 新增 `work/app/d1zh.py`：优先复用 **`work/lib/d1i18n.py`**（`tr` / `item_name_cn` / `affix_name_cn` / `unique_name_cn` / `affix_desc` / `describe_power`），缺失时退回 `zh_fallback.json`（由 `work/build/gen_zh_fallback.py` 从 1.5.5 的 `zh_CN.po` 生成，1452+279 条，去 U+200B），最后才是内置常用表。打包版自检显示 `中文数据：d1i18n（d1i18n.py）`。
- 词缀下拉 = `中文（English） + 数值范围`，例如 `残忍（Brutal）  +81 ~ +95`；选中后下方显示说明：
  > 残忍（Brutal）：伤害 +81~95%；需要物品等级 16；适用 弓/法杖/武器
- 底材、暗金名、属性标签、生成预览、暗金词条全部中文；中文物品名按游戏 PO 模板拼（`{suffix}{prefix}{base}`，如“精力残忍长剑”）。
- 修正了一处潜在混淆：PO 里金属词缀 `Gold` 被翻成“金币”（那是物品 Gold），词缀处显示“金”。

### 10.3 问题 ④：词缀数值可指定

- 每个词缀行增加：`范围 +min~max`、`目标值`（空=随机）、`容差`（默认 0）。
- 数值语义 = 游戏 `SaveItemPower` 里的 `r = RndPL(param1, param2)`，也就是 tooltip 上看到的那个值（+15 力量、+20% 火抗、+85% 伤害）；范围取自 itemgen2 的 `affix_value_range`（诅咒词缀给负值，如 `Tin` → -10~-6），UI 只允许填范围内的值。
- 非数值词缀（攻速/充能/吸血/固定伤害/耐久百分比等）：数值输入**禁用**，并提示“固定效果：数值不可指定”；硬填会被 `_value_arg()` 拒绝。
- 生成：`itemgen.generate(base, ilvl, rarity, prefix=<index>, suffix=<index>, prefix_value=…, suffix_value=…, value_tolerance=…)`；adapter 默认 `max_tries`：无值 20 万、有值 **200 万**（2M 实测 ~1.2s 稳定，20 万约 40% 失败）。
- 后台线程 + 进度 + 取消；搜索失败显示 itemgen 的中文原因（含最接近值），再补一句建议（放宽容差/只指定一个数值/换词缀），**不弹 traceback**。
- 实测：`残忍(Brutal) +85` → 记录 `PLDam=85`、`validate()==[]`；`of the power +13` → `PLStr=13`。

### 10.4 问题 ⑤：暗金图鉴

新标签页「暗金图鉴」（`ui_uniques.py`）：

- 左侧 89 件可用暗金（Treeview：中文名/底材/需等级/价值），支持关键字搜索、按底材过滤、最低等级过滤；另 1 件（Bovine Plate）底材在非 Hellfire 不可用，横幅里说明。
- 右侧固定词条明细：暗金名（中/英）、底材（中文 + 英文 + runtime idx + 是否任务底材）、需求等级、价值、逐条中文词条（`describe_power`，如“光照范围 +20% / 闪电伤害 1-10 / 命中 +20% / 闪电抗性 +50%”），以及说明。
- 生成：不要前缀/后缀/数值，`unique_id` 决定词条；用 **`unique_base(uid)` 给出的底材 + unique_id** 生成（普通暗金是普通底材；10 件任务暗金如 Harlequin Crest 的底材本身就是 IMISC_UNIQUE 行，游戏里就是该暗金，`validate()` 通过）。ilvl 低于 `min_level` 时自动抬高。
- 后台线程 + 取消；写盘走与生成页相同的 `ui_genops`（写后重开校验 +N）。

### 10.5 新增：储物箱「检查异常物品 / 一键清理」

- 储物箱页新增按钮「检查异常物品」：后台逐件 `ItemGen.check_record(rec, deep=True)`：
  - **致命**：运行时编号 ∈ starter 集合（166 等）、`unique_only` 底材但品质不是暗金、`d1itemgen.validate` 报 `replay mismatch`；
  - **警告**：底材在非 Hellfire 不可用、未知编号、校验提示类差异。
- 结果弹窗（Treeview，默认全选，致命行红字）：可「全选/全不选」，点「删除选中」→ 二次确认（列出会崩溃的物品）→ `backup_file()` → 从大到小 `remove_record` → `save()` → **重新打开校验物品数 == 写前 - N 且剩余记录逐字节不变**，失败自动回滚。
- 载入储物箱时先跑一次**廉价体检**（只查编号/品质，不做 seed 重放），有可疑物品时页内黄/红条 + 日志提示：“⚠ 储物箱里有 N 处可疑物品（其中 M 处会导致进游戏崩溃）”。

### 10.6 安全事件与修复（自动测试误写真实存档）

Round 2 开发中出现过一次**自动测试误写真实 `stash.sv`**（19:39 与 19:40，各多出 1~2 件测试装备），根因是两个问题叠加：

1. `App.refresh_all()` 写完背包后调 `tab_stash.refresh_files()` + `_on_pick()`，会把储物箱切回 `%APPDATA%` 的默认 `stash.sv`（而测试本来打开的是 `work/tmp` 副本），后续生成就写到了真实存档；
2. 测试/自检没有写保护，代码路径一旦走错就没有兜底。

修复（本次已包含在交付里）：

- `refresh_all()` 现在会带着当前已打开的角色/储物箱路径刷新，**不会切回默认文件**；smoke 里加了回归断言；
- `d1env.ALLOW_PROTECTED_WRITES` + `assert_writable()`/`ProtectedWriteError`：headless（`--selftest`）、`smoke_test.py`、`D1_READONLY=1` 下禁止写真实存档；
- `open_stash()` 对真实路径返回 `GuardedStash` 只读壳，`save/add_record/remove_record` 一律抛异常；
- `d1hero.save()` 写前 `assert_writable()`；
- `--selftest`、`smoke_test.py`、`make_shots.py` 结束都断言真实存档目录 `.sv` 的 SHA256 一致；
- `build_exe.ps1` 里 selftest 日志若没有“真实存档…一致”就直接判定打包失败。

真实存档已从 `stash.sv.bak-20261111-194012` 恢复为 98 件（103,800 字节，
SHA256 `3E66494E1EF5A5F8336B0BDED4FA84985A506BD9F8627815B2AA23DE6255C93E`），之后再未写入。

### 10.7 Round 2 自测汇总

| 项目 | 结果 |
|---|---|
| 源码 `--selftest` | `SELFTEST OK`，exit 0 |
| 打包 exe `--selftest` | `SELFTEST OK`，exit 0（`d1i18n` 模式、69 底材、89 暗金、指定数值、拒绝 166、真实存档未变） |
| `smoke_test.py` | `SMOKE OK`（含全部 Round 2 项） |
| 真实存档 | 98 件，SHA256 前后一致（多次自检/截图/冒烟后仍未变） |
| 截图 | `work/docs/shots/r2_base_list.png`、`r2_affix_value.png`、`r2_uniques.png`、`r2_preview.png`、`tab_unique.png` |
| 交付 | `交付\暗黑破坏神1存档修改器-v2.exe` = 游戏目录同名 exe，11,221,628 字节，SHA256 `2E2E070A…35559CD` |

---

## 11. Round 3（2026-11-11 晚）

本轮把用户提的 4 件事全部做完并重新打包：词缀下拉带效果名、生成失败分类提示、写入页码、暗金图鉴序号+排序。
**真实存档零写入**（本轮只读；所有生成/页码测试都在 `work\tmp` 副本上）。

### 11.1 需求 ①：前缀/后缀下拉带效果名

- 下拉文本从 `残忍（Brutal）  +81 ~ +95` 变成 `残忍（Brutal） 伤害 +81 ~ +95`。
- 效果名走 core 新 API：`d1i18n.affix_effect_label(affix)`（`affix_label(kind, affix, with_effect=True)` 作为兼容备选，见 `d1zh.affix_effect_label`）；core 未就绪时依次退回
  `power_value(affix)["label"]`（表驱动：`IPL_DAMMOD`→伤害、`IPL_FIRERES`→火焰抗性、`IPL_ALLRES`→全抗性、`IPL_ATTRIBS`→所有属性、`IPL_MANA`→法力…）与 `d1zh.BUILTIN_EFFECT`（Ruby/Sapphire/Diamond/Obsidian/Dragon's 等确定项）。
- 实测（`Ring` @ ilvl 50、`Long Sword` @ ilvl 20）：

  | 词缀 | 下拉显示 |
  |---|---|
  | Ruby | `红宝石（Ruby） 火焰抗性 +51 ~ +60` |
  | Sapphire | `蓝宝石（Sapphire） 闪电抗性 +51 ~ +60` |
  | Diamond | `钻石（Diamond） 魔法抗性 +51 ~ +60` |
  | Dragon's | `翼龙的（Dragon's） 法力 +51 ~ +60` |
  | Obsidian | `黑曜石（Obsidian） 全抗性 +31 ~ +40` |
  | Brutal | `残忍（Brutal） 伤害 +81 ~ +95` |
  | the heavens | `天堂（the heavens） 所有属性 +12 ~ +15` |

- 选中后的详细说明仍是 `affix_desc`（含需求等级 / 适用装备），不变；`Affix.desc` 未改。
- 附带改进：换 ilvl 时**不再把手选词缀抽走**——当前 ilvl 下不合法的旧选择会保留在下拉里，并在提示行用红/灰字说明“在 ilvl=N 下不合法，点生成会告诉你原因”；ilvl 输入框支持回车/失焦刷新词缀。下拉高度设为 20 行，选词缀时不用滚半天。

### 11.2 需求 ②：生成失败提示分类（原因 + 建议）

- 生成前预检：`ItemGen.check_combination(...)` 优先调 core 的 `d1itemgen.check_combination()`
  （返回 dict：`ok/code/message/suggestions`，默认 `max_tries=None` 只查规则、不搜种子，GUI 不卡），
  core 未就绪/异常时退回适配层本地规则（`_local_check_combination`，复刻等级窗口/类型/固定效果判定）。
- 失败时**不再只写日志**：预览区整段红字（`【无法生成】` + 标题 + 原因 + 建议 + 技术细节）+ 模态弹窗
  `uic.detail_warning()`（红标题 / 正文 / 建议列表 / 灰色技术细节 / 「知道了」按钮；`HEADLESS` 时只打印，
  自动化测试不会卡住）。
- 失败分类（core code → 本地统一 code）：`bad_base`→底材非法、`level_window`→词缀等级窗口（按消息再细分为
  “等级不够”/“ilvl 太高”，分别给“把 ilvl 提到 N”/“把 ilvl 降到 N”）、`bad_affix`→不适用该底材、
  `fixed_affix_value`→固定效果不能指定数值、`value_out_of_range`→数值越界、`seed_not_found`→合法但预算内没搜到、
  `goe_conflict`→善良/邪恶冲突、`staff_ilvl`→法杖怪癖、`bad_ilvl/bad_rarity/bad_value`→参数有误。
  旧版异常（无 `.code`）用正则兜底，仍给中文原因。
- 用户给的验收例子（`Ring + Obsidian(全抗) + of the heavens(全属性)`）：

  | ilvl | 结果 |
  |---|---|
  | 20 | 拒绝：`前缀「Obsidian」需要词缀等级 24，ilvl=20 只允许 10..20；请把 ilvl 提到 24（或更高）`；建议两条（前缀 24 / 后缀 25） |
  | 30 | 通过：生成 `天堂黑曜石戒指`，`validate()==[]` |
  | 49 | 通过：同上 |
  | 50 | 拒绝：`前缀「Obsidian」是 24 级词缀，低于 ilvl=50 允许的窗口 25..50；请把 ilvl 降到 49（24..49 都可以）` |

- 生成成功但 `validate()` 失败：`classify_validation()` 给中文说明（名字重放不一致 / seed 重放不一致 / 记录异常），
  预览红字 + 弹窗，**未写入任何物品，也不弹 traceback**（`ui_itemgen.py`、`ui_uniques.py` 两条路径都改了）。

### 11.3 需求 ③：储物箱「写入页码」

- 装备生成页 / 暗金图鉴页各加一个 `写入页码` Spinbox（1-based，默认 1，范围 1~100；**留空 = 自动找空位/新建页**）。
- 写入调用链：`ui_genops.write_to_stash(..., page=N)` → `ui_stash.add_record(record, page=N-1)` →
  `d1stash2.add_record(record, page=...)`。d1stash2 的语义是“指定页优先，放不下按页号升序继续找，最后新建页”，
  正好满足“从指定页开始依次填空位”。
- 页码非法（0 / 非数字 / >100）在点按钮时直接中文提示，**不会启动后台生成、不写盘**。
- 指定页不存在或放不下时：仍然按规则顺延，但成功弹窗里明确写
  “注意：指定的第 N 页放不下（不存在或已满），这些物品被顺序放到了 第 X 页…；想固定页请先腾空该页，或把页码留空”。
- 写后校验仍是 `flush()`：保存 → 重新打开 → 物品数必须 +N → 逐字节一致，失败回滚。
- 冒烟实测：指定第 2 页写入 1 件 → 重开 stash 后该记录落在 0-based page=1（即第 2 页）；页码 0 被拒绝且物品数不变。

### 11.4 需求 ④：暗金图鉴序号 + 排序

- 表格列改为 `序号 / 暗金名称 / 底材 / 需等级 / 价值`。
- 点任意表头排序，再次点同一列反向（`▲`/`▼` 显示在当前排序列的表头上）；**序号 = 当前显示顺序**，排序/过滤后重新编号 1..N。
- 默认顺序 = 暗金表原始顺序（序号列即该顺序）；按名称/底材用中文排序，按需等级/价值按数值排序。
- 排序/过滤都走同一个 `_refresh_list()`：先记住当前选中暗金的 uid，重建后按 uid 重新选中并 `see()` 到可见位置，
  右侧详情不受影响；「生成到储物箱/背包」仍作用于 `_row_map` 里的选中暗金。
- 过滤（搜索/底材/最低等级）与排序可叠加；计数行会写“显示 X / 89 件（按「价值」▼ 降序；再次点表头反转）”。
- 实测：价值升序/降序两端值正确；序号连续 1..89；排序后选中 uid 不变（selftest 断言 uid=30 Lightsabre、冒烟断言 uid=44）。

### 11.5 截图（`work/docs/shots/`）

| 文件 | 内容 |
|---|---|
| `r3_affix_effect.png` | 长剑前缀下拉：`残忍（Brutal） 伤害 +81 ~ +95` 等带效果名 |
| `r3_affix_effect2.png` | 戒指前缀下拉：`红宝石（Ruby） 火焰抗性 +51 ~ +60`、`钻石（Diamond） 魔法抗性`、`翼龙的（Dragon's） 法力` |
| `r3_page.png` | 装备生成页「写入页码 = 2」+ 说明 |
| `r3_fail_preview.png` | 失败提示：预览区红字（原因 + 建议 + 技术细节） |
| `r3_fail_dialog.png` | 失败弹窗：`词缀等级不够（游戏规则不允许）` + `请把 ilvl 提到 24` + 两条建议 |
| `r3_uniques_before.png` | 暗金图鉴：序号列（原始顺序），选中 Lightsabre，右侧详情 |
| `r3_uniques_after.png` | 按「价值」▼ 排序后：序号重排、表头 ▼、选中项/右侧详情保持 |
| `r3_uniques_sorted_top.png` | 排序后回到顶部：序号 1..N、价值从 251,175 递减 |

截图流程（`work/build/make_shots.py`，`D1_SHOTS_R3=1` 只跑 Round 3）：主窗口用 `PrintWindow` 抓，
ttk 下拉列表和自定义弹窗是独立顶层窗口，改用屏幕抓那一小块后按窗口偏移合成——图里不会混进桌面上别的程序。

### 11.6 本轮改动文件

| 文件 | 改动 |
|---|---|
| `work/app/d1zh.py` | 新增 `affix_effect_label()`（core → power_value → BUILTIN_EFFECT 四级兜底）、`BUILTIN_EFFECT` |
| `work/app/d1itemgen_adapter.py` | `Affix.label` 带效果名；新增 `ComboCheck`、`check_combination()`（core 优先 + 本地规则）、`classify_error()`、`classify_validation()`、core→本地 code 映射 |
| `work/app/ui_common.py` | 新增 `detail_warning()`（原因+建议弹窗）、`set_text(..., color=)` 红字 |
| `work/app/ui_itemgen.py` | 页码 Spinbox / `_page_arg()` / `_preflight()` / `_show_check()`；预检 + 失败分类 + 校验失败中文提示；换 ilvl 保留手选词缀；下拉 20 行 |
| `work/app/ui_uniques.py` | 序号列、表头排序（▲/▼）、选中项保持、页码 Spinbox、失败/校验中文提示 |
| `work/app/ui_genops.py` | `write_to_stash(..., page=)`：页码校验、逐件按页写、实际落页与目标页不一致时中文提示 |
| `work/app/ui_stash.py` | `add_record(..., page=)` 透传 0-based 页号（兼容旧 d1stash2） |
| `work/app/d1editor2.py` | selftest 增加：页码默认值、效果名、Ring+Obsidian 预检（20/30/50）、暗金排序/序号/选中保持 |
| `work/build/make_shots.py` | Round 3 截图（下拉/弹窗用合成抓取） |
| `work/build/smoke_test.py` | Round 3 冒烟：指定页写入、非法页码、预检分类、排序/序号/选中保持 |

### 11.7 Round 3 自测与交付

| 项目 | 结果 |
|---|---|
| 源码 `--selftest` | `SELFTEST OK`，exit 0（含效果名、预检 20/30/50、排序、真实存档一致） |
| `smoke_test.py` | `SMOKE OK`（Round 1/2 全项 + Round 3：页码、预检分类、排序） |
| 打包 exe `--selftest` | exit 0；日志含 `d1i18n`、`组合预检 = core d1itemgen.check_combination`、`真实存档…一致` |
| 版本 | 窗口标题/关于框版本号 `2.2.0`（`d1env.APP_VERSION`，Round 3 起） |
| 产物 | `work/build/dist/暗黑破坏神1存档修改器-v2.exe`，11,262,228 字节，SHA256 `B826DE439995A3EA439F8092B9D36315E91792CD6729DCE8E2B3167E54BDBBC6` |
| 三处一致 | `work/build/dist`、`交付\暗黑破坏神1存档修改器-v2.exe`、`暗黑破坏神1重构游戏本体和修改器\暗黑破坏神1存档修改器-v2.exe` 三处 SHA256 相同（`B826DE43…DBBC6`） |
| 真实存档 | **103 件** / gold 313,108，SHA256 `89CE5C0896B13223F429241DAFFBD41F9B26FE4D418B1546889BCEC72A5F7BC0`，本轮所有自检/冒烟/截图前后一致（零写入） |

> 基线说明：Round 2 交接记录的 98 件基线（SHA `3E66494E…`）在本轮开始前已被其它代理的自动测试写到 105 件；
> 期间由主代理恢复到 103 件（98 件 + 5 件用户生成暗金：Constricting Ring、Stormshield、Naj's Light Plate、
> Demonspike Coat、The Grandfather）。本轮所有验收都以恢复后的 **103 件 / `89CE5C08…`** 为基线；
> 98 件旧版本仍可从 `stash.sv.bak-20261111-194012` 取回。

### 11.8 已知限制（Round 3 新增）

- 预检默认只查规则（不搜种子），所以“合法但预算内没搜到”只会在真正生成时出现——那时分类为
  `seed_not_found`，建议放宽容差 / 只指定一个数值 / 换词缀。
- core 把“等级不够”和“ilvl 太高”都归为 `level_window`，GUI 按消息里的“提到 N / 降到 N”再细分标题。
- 指定页码只在“该页能放下”时严格生效；d1stash2 的语义是“放不下就顺延”，因此可能落到后续页（会明确提示）。
- 序号是**显示顺序**，不是暗金的固定编号；按名称排序用中文字符的 Unicode 顺序（不是拼音）。
- 只支持 1.5.5 非 Hellfire `.sv`；写盘前必须退出游戏。
