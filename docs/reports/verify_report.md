# 游戏内验收报告（DevilutionX 1.5.5 沙盒自动化）

> 代理：game-verify
> 日期：2026-11-11
> 工作根：`F:\Qoder\暗黑1重制版`（ROOT）
> 脚本：`work\tests\game_harness.py`、`work\tests\game_flows.py`、`work\tests\game_verify.py`、`work\tests\game_probe.py`
> 截图：`work\docs\shots\`
> 沙盒运行目录：`work\sandbox\run_*`

---

## 0. 结论速览

| 验收项 | 结论 | 证据 |
|---|---|---|
| 沙盒启动（不碰真实存档） | ✅ | `%APPDATA%\diasurgical\devilution` 4 个存档 SHA256 与 `work\backup_saves` 完全一致；沙盒内存档被游戏改写 |
| 自动进入游戏（主菜单→角色→载入城镇） | ✅ | 全自动流程稳定复现，截图 `gold_02-town.png` / `b3_02-town.png` |
| 原版存档基线（游戏读→写往返） | ✅ | 游戏重写后 `stash.sv` **md5 与原文件完全一致** `9f6d65d95f2657bac91fbfcc236553fc` |
| **储物箱金币 400000 不丢物品** | ✅ **通过** | 无红字；游戏重写后 gold=400000、96 件、10 页、**96/96 条 368 字节记录逐字节一致**，与原始 backup 也逐字节一致 |
| 装备生成（背包 2 件：魔法剑 + 暗金甲） | ✅ 文件+游戏侧通过 | 游戏读档后背包 slot22/slot23 的 idx/seed/ci 原样保留（24 used / 31 格），未触发 `RemoveInvalidItem`；itemgen 用同 seed/ci 重放得到 `Brutal Sword of slaying` / `Naj's Light Plate`，`validate=[]` |
| 打开储物箱（Gillian 对话 → Access Storage） | ⚠️ 未完成 | 详见 §6；提供半自动模式与后续方案 |

**用户第一诉求（改金币不清空物品）已在游戏内得到确认。**

---

## 1. 沙盒方案（核心）

### 1.1 命令行参数（已从源码与实测双重确认）

`DevilutionX-1.5.5\Source\diablo.cpp:1010-1027`：

```cpp
} else if (arg == "--data-dir")   { paths::SetBasePath(argv[++i]);   }
} else if (arg == "--save-dir")   { paths::SetPrefPath(argv[++i]);   }
} else if (arg == "--config-dir") { paths::SetConfigPath(argv[++i]); }
```

* `--save-dir` → `PrefPath()`：**角色存档 single_N.sv 与 stash.sv 都走它**（`pfile.cpp:54-79` 的 `GetSavePath` / `GetStashSavePath` 都以 `paths::PrefPath()` 开头），因此一个开关即可隔离全部存档。
* `--config-dir` → `ConfigPath()`：`diablo.ini` 读写位置（`options.cpp:75 GetIniPath`）。
* `--data-dir` → `BasePath()`：`DIABDAT.MPQ` 等游戏数据目录。
* `devilutionx.exe --help` 实测退出码 0（Windows GUI 子系统，帮助文本打印到内部 console，抓不到 stdout，但参数语义以源码为准）。
* 注意 `paths.cpp:87-92` 有一条「若当前目录存在可写 diablo.ini 则把 PrefPath 改成 `.`」的兜底；显式传 `--save-dir/--config-dir` 后该兜底不生效（`prefPath` 已有值不再进入 if 分支）。**实测游戏目录下无 diablo.ini，不会误用。**

实际启动命令：

```
F:\Qoder\暗黑1重制版\暗黑破坏神1重构游戏本体和修改器\devilutionx\devilutionx.exe
  --save-dir  <run>\saves
  --config-dir <run>\config
  --data-dir  F:\Qoder\暗黑1重制版\暗黑破坏神1重构游戏本体和修改器\devilutionx
```

### 1.2 运行目录结构

```
work\sandbox\run_<YYYYmmdd_HHMMSS>_<tag>\
  saves\    single_0.sv single_1.sv single_2.sv stash.sv   ← 从 work\backup_saves 复制
  config\   diablo.ini                                     ← 从 backup 复制后改写
  shots\    本 run 的截图副本
```

每次 `Sandbox()` 生成唯一时间戳目录，多代理并行不会冲突。

### 1.3 沙盒 diablo.ini 覆盖项（自动化友好）

键名取自 `work\backup_saves\diablo.ini` 与 1.5.5 `Source/options.cpp`（`OptionCategoryBase("Graphics")` 等）：

| 段 | 键 | 值 | 原因 |
|---|---|---|---|
| Graphics | `Fullscreen` | 0 | 窗口化，才能稳定截图/点击（`options.cpp:957`） |
| Graphics | `Width` / `Height` | 800 / 600 | 固定客户区，坐标常量可复用 |
| Graphics | `Fit to Screen` | 0 | 不随桌面缩放（`:959`） |
| Graphics | `Upscale` / `Integer Scaling` | 0 / 0 | 1:1 像素，避免缩放影响模板比对 |
| Graphics | `Hardware Cursor` / `Hardware Cursor For Items` | 0 / 0 | 软件光标画进画面，截图可见（`:1003-1004`） |
| Audio | `Sound Volume` / `Music Volume` | 0 / 0 | 静音 |
| StartUp | `Diablo Intro` / `Hellfire Intro` / `Splash` | 0 / 0 / 0 | 跳过开场与 logo（`:586-603`；`StartUpSplash::None == 0`，`options.h:36`） |
| Game | `Grab Input` | 0 | 不锁鼠标（`:1056`） |
| Diablo | `LastSinglePlayerHero` | 1 | 默认选中「剑来」 |

> 另注：`-n` 也可跳过启动动画（`diablo.cpp:1058`），本方案用 ini 更彻底。

### 1.4 沙盒隔离的实证

跑完整轮（进游戏→保存→退出）后：

| 文件 | 真实 `%APPDATA%\diasurgical\devilution` SHA256（前 16 位） | 与 backup 一致 |
|---|---|---|
| single_0.sv | `6B6A8FBF738EDCA5` | ✅ |
| single_1.sv | `2DEE3F41B99040A7` | ✅ |
| single_2.sv | `1C172A2E14F31AC7` | ✅ |
| stash.sv | `4E4648DF1998EA61` | ✅ |
| diablo.ini | `5DBDF2192DE32D2B` | ✅ |

同时沙盒 `saves\single_*.sv` 的 mtime 被游戏改写（`16:32:30`、`16:34:26`、`16:56`…），`stash.sv` 在「进游戏→保存游戏」后也被游戏重写。**结论：游戏只读写沙盒目录，真实存档零触碰。**

---

## 2. 自动化能力

### 2.1 截图（不依赖 Pillow/pyautogui）

本机 Python 3.12（`_py312\python.exe`）与系统 3.15 都**没有 PIL**，因此全部用 `ctypes` + Win32 GDI 实现：

* 主用：`BitBlt` 从桌面 DC 抓窗口矩形（`SRCCOPY|CAPTUREBLT`），1:1 窗口坐标；
* 兜底：`PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)` —— **实测对本游戏有效**，即使窗口被别的程序遮挡也能拿到正确画面（`shots\pw_print.png` 就是在游戏被修改器 GUI 遮住时抓的）；
* PNG 编码/解码为自写（`write_png` / `read_png`，zlib + 手写 IHDR/IDAT/IEND 与 5 种 filter），供 diff 与裁切放大使用。

### 2.2 输入

* 键盘：`keybd_event` + `MapVirtualKeyW` 扫描码；
* 鼠标：`SetCursorPos` + `mouse_event`（绝对定位，`Grab Input=0` 时有效）；
* 坐标换算：`click_shot(x,y)` 以**截图图像坐标**为准（截图抓的是窗口矩形，含标题栏，客户区原点偏移实测 `(3,26)`）。

### 2.3 一个必须记录的坑：前台窗口被别的程序占用

本机是**同桌面多代理**环境，另一个代理的修改器 GUI（窗口标题 `暗黑破坏神1 存档修改器 v2  v2.0.0`）会长期占着前台，导致：

* `SetForegroundWindow` 返回失败（Windows 前台锁）；
* `keybd_event` 的按键全部发给了那个 GUI，游戏完全收不到（实测 `ESC` 无效）；
* 桌面 DC 截图会抓到那个 GUI 覆盖在游戏上的画面（`shots\base2_01-mainmenu.png` 即此故障现场）。

**解决办法（已实测有效）**：发一次 `VK_MENU`(ALT) 解锁前台锁，再 `SetForegroundWindow`：

```python
user32.keybd_event(0x12, 0x38, 0, 0)
user32.SetForegroundWindow(hwnd)          # 这一步返回 1，成功
user32.keybd_event(0x12, 0x38, KEYEVENTF_KEYUP, 0)
```

已内建在 `GameWindow.focus()`（失败还有 `AttachThreadInput` 兜底）；抢不到前台时截图自动退回 `PrintWindow`。
**注意**：直接 `PostMessage(WM_KEYDOWN/WM_LBUTTONDOWN)` 试图绕过焦点是**无效的**——SDL2 在无键盘焦点时丢弃键盘事件（实测 ESC 无反应）。

### 2.4 状态判定（像素级，无需模板图）

| 函数 | 判据 | 实测值 |
|---|---|---|
| `hud_present()` | 底部信息面板区 `(80,490)-(730,600)` 亮像素比 > 0.18 | 游戏内 0.32；主菜单 0.03 |
| `is_main_menu()` | 菜单文字区 `(290,285)-(515,535)` 亮像素比 > 0.09，且 HUD 不存在 | 主菜单 0.129；角色选择 0.052 |
| `red_error_text()` | 底部消息框 `(255,535)-(560,600)` 中 `r>140,g<90,b<90` 像素数 | 正常 0 |
| `wait_stable()` / `wait_change()` | 连续两帧 `image_diff_ratio` 收敛 / 突变 | 用来自动等待读盘、菜单切换 |

红字判据对应游戏内 `EventPlrMsg(..., UiFlags::ColorRed)`：`loadsave.cpp:2281` “Stash version invalid…”、`:2300` “Stash size invalid…”。

---

## 3. 固化的界面坐标（800×600、中文、DevilutionX 标题）

```
主菜单      单人游戏(400,296) 多人(400,325) 设置(400,354) 支持(400,384)
            显示制作组(400,453) 退出暗黑破坏神(400,513)
角色选择    列表 4 行 y=349/376/404/431，x≈492；确定(384,519) 删除(500,519) 取消(640,519)
保存已存在  加载游戏(492,380) 新游戏(492,404)；确定(384,519) 取消(640,519)
游戏内 ESC  保存游戏(400,231) 选项(400,260) 新游戏(400,289) 加载游戏(400,318) 退出游戏(400,396)
```

角色列表实测顺序为 `贫道张角(single_2) / 剑来(single_1) / CHIAKI(single_0) / 新英雄`，所以 **`剑来` = 第 2 行（`CHAR_ROWS[1] = 376`）**，也是 ini `LastSinglePlayerHero=1` 的默认选中项。

同一轮内完整的自动流程：

```
启动 → 等主菜单 → 单人游戏 → 点第2行(剑来) → 确定 → 加载游戏 → 确定
     → 等 HUD 出现（=已进入城镇）→ 截图 → [按 I 开背包 / 走位开箱]
     → ESC → 保存游戏（存档并回主菜单）→ 退出暗黑破坏神（干净退出）
```

---

## 4. 验收 A：储物箱金币 400000，物品不丢（用户第一诉求）

**样本**：`work\tmp\stash_gold400000.sv`（未压缩写法：block flags `0x80000000`、`csize==usize==37448`、无扇区表）

**沙盒**：`work\sandbox\run_20261111_164646_gold1\`
**命令**：

```powershell
F:\Qoder\暗黑1重制版\_py312\python.exe work\tests\game_verify.py run ^
  --tag gold1 --stash "F:\Qoder\暗黑1重制版\work\tmp\stash_gold400000.sv" --shots-prefix "gold_"
```

**过程与结果**

1. 进游戏全程**没有红字**：`red_error = {px: 0, detected: false}`（自动检测；对应游戏里 `LoadStash()` 的两处红色告警）。
2. 站桩 → ESC → 保存游戏 → 主菜单 → 退出游戏，**游戏自己把沙盒 `stash.sv` 重写了一遍**（103096 B → 90354 B，游戏用自己的压缩器重写）。
3. 用 `work\lib\d1stash2.Stash` 解析游戏重写后的文件：

```
gold   = 400000                                     ✅ 与样本一致
items  = 96                                         ✅ 一件没少
pages  = [0,1,2,3,6,7,8,9,10,11]                    ✅ 10 页全在
records identical vs 样本 : 96/96                   ✅ 368 字节记录逐字节相同
records identical vs 原始 backup : 96/96            ✅ 连原存档记录也未变
grids  identical : True                             ✅ 10x10 布局一致
```

4. **基线对照**：用**原版** `stash.sv` 跑同一流程，游戏重写后 md5 与原文件完全一致（`9f6d65d95f2657bac91fbfcc236553fc`），说明「保存会重写 stash」这条路径本身稳定可复现；换了修改过的文件同样稳定。

**判据意义**：这比截图更硬——游戏走完了 `LoadStash() → Stash.stashList → SaveStash()` 全链路，说明

* MPQ 未压缩无扇区表写法被游戏接受（`IsStashSizeValid` 未失败，否则会 `Stash={}` 并红字）；
* 金币被正确读成 400000；
* 96 件物品全部被正确解析、重建、再写回，**没有被 `RemoveInvalidItem` 或空箱覆盖**。

截图：
* `shots\gold_01-mainmenu.png` 主菜单
* `shots\gold_02-town.png` **进入城镇（无红字）**
* `shots\gold_05-backmenu.png` 保存后回到主菜单

> `stash_gold400000_implode.sv`（兼容写法）**未测**——未压缩写法已通过，按简报 §2.4 它就是推荐方案，逃生门不需要启用。若后续要交付对原修改器读取器兼容的写法，再补测这一份即可（脚本一条命令）。

---

## 5. 验收 B：装备生成（背包 2 件）

**样本**：`work\tmp\single_1_affix_test.sv`（剑来副本，背包新增 2 件）
**沙盒**：`work\sandbox\run_20261111_164933_affix1\`、`run_20261111_165335_tip1\`
**命令**：

```powershell
... _py312\python.exe work\tests\game_verify.py run --tag affix1 ^
  --char "F:\Qoder\暗黑1重制版\work\tmp\single_1_affix_test.sv" --inventory --shots-prefix "affix_"
```

**结果**

1. 进游戏无红字（`red_error.px = 0`）。
2. 按 `I` 打开背包 → 截图：两件新物品**都在背包网格里**（左上角：2×3 的深色板甲 + 1×3 的短剑）。
   放大图 `shots\affix_inv_zoom.png` 可清楚看到网格与物品。
3. **游戏读档后没有删掉任何一件**。用 `d1save` 解析「读档前样本」与「游戏保存后的沙盒 `single_1.sv`」的 19 字节 ItemPack：

| | 使用中的背包槽 | 网格占用 |
|---|---|---|
| 原始 `single_1.sv` | 22 | 22 |
| `single_1_affix_test.sv` | **24** | **31** |
| 游戏读档+保存后 | **24** | **31** |

   新增两项完全相同地保留：

```
slot22  idx=114(Short Sword, droppable 版)  seed=0xc264656d  create_info=0x1e(30)
slot23  idx=67 (Plate Mail)                 seed=0x47bb3c38  create_info=0x213(531, unique 标记)
```

   （`idx`/`seed`/`ci` 三元组在游戏往返前后逐一相同；`ci` 低字节 30 = ilvl，`0x200` 为 unique 标记）

4. `work\lib\d1itemgen.py` 用同一 `seed`/`create_info` 重放得到 **Brutal Sword of slaying** 与 **Naj's Light Plate**，`validate()` 返回 `[]`（合规）。两者相互印证：游戏侧保留的正是 itemgen 生成的那两件，且没有触发非法物品清理。

截图：
* `shots\affix_02-town.png` 城镇（无红字）
* `shots\affix_03-inventory.png` **背包已打开，两件新物品可见**
* `shots\affix_inv_zoom.png` 背包区域 2× 放大（看清 2×3 板甲 + 1×3 短剑）
* `shots\tip_inv.png` / `tip_plate.png` / `tip_sword.png` 悬停尝试（tooltip 文字未稳定捕获，见 §6）

**未做**：`single_1_itemgen_test.sv`（3 件随机）、`single_1_item_test.sv`（4 件简单随机）、`stash_affix_test.sv`（储物箱 98 件）未单独跑一遍。机制与上面完全一致（同一 `add_item` + 同一读档路径），命令已封装，随时可跑：

```powershell
... game_verify.py run --tag itemgen1 --char "...\single_1_itemgen_test.sv" --inventory
... game_verify.py run --tag stashaffix --stash "...\stash_affix_test.sv"
```

---

## 6. 未完成项与替代方案：打开储物箱

### 6.1 为什么难

DevilutionX **没有**地上的储物箱对象，也没有开箱快捷键。唯一入口是与酒馆女招待 **Gillian** 对话：

```cpp
// Source/stores.cpp:1312 StartBarmaid()
AddSText(0, 12, _("Talk to Gillian"),  ColorBlue|AlignCenter, true);
AddSText(0, 14, _("Access Storage"),   ColorWhite|AlignCenter, true);   // ← 储物箱
AddSText(0, 18, _("Say goodbye"),      ColorWhite|AlignCenter, true);
// Source/stores.cpp:2060 BarmaidEnter() case 14 → IsStashOpen = true; Stash.RefreshItemStatFlags();
```

即：**走到 Gillian（tile `{43,66}`，`towners.cpp:791`）身边 → 左键点她 → 对话菜单按 ↓↓ + Enter 选 “Access Storage”**。

本代理已完成前半段工程（键盘 ↓/Enter 可驱动该菜单，`game_flows.Flow.open_stash()` 已实现“按标定文件走位 + 对话 + ↓↓ + Enter + 像素判定”），但**没能在时限内把“走到 Gillian 身边”这一步标定出来**：

* 角色出生点来自存档里保存的坐标，三个角色各不相同；
* 相机在城镇边缘会被 clamp，角色不一定在屏幕正中，无法用固定偏移推算 Gillian 的屏幕位置；
* 城镇是固定 `.dun`，但把「角色 tile」与「屏幕 tile」对齐需要一次标定（源码 `ViewPosition` 是视口左上角，`CreateTown` 新建游戏时为 `{75,68}`）。

### 6.2 已就绪的半自动模式（推荐给人工确认时用）

```powershell
# 1) 建沙盒（可选替换 stash）并启动，人只需要走位+点 Gillian
... game_verify.py run --tag manual --stash "...\stash_itemgen_test.sv" --open-stash

# 或纯手工：
... game_harness.py new --tag manual          # 打印沙盒路径
... game_harness.py launch --reuse            # 启动游戏
... game_harness.py shot 箱前                 # 任意时刻截图
... game_harness.py key TAB / DOWN / ENTER    # 发按键
... game_harness.py click 400 300             # 按截图坐标点击
... game_harness.py info                      # 窗口几何/是否前台
... game_harness.py kill
```

`game_verify.py --open-stash` 会读取标定文件 `work\sandbox\stash_click.json`：

```json
{ "pre_walk": [[600,420],[640,380]], "talk": [520,330],
  "menu_down": 2, "menu_enter": 1 }
```

人工把坐标填进去后，之后每一步都能全自动重放（这是本代理留下的“标定接口”，无需改代码）。

### 6.3 结论的替代支撑

按主会话确认的口径：**“进游戏无红字 + 退出后沙盒 stash 未被清空 + 文件仍是 96 件”** 已达成，且实际拿到了更强的证据（游戏重写后 96/96 记录逐字节一致、gold 正确、页数正确）。因此「改金币不丢物品」这一用户第一诉求**判定通过**，开箱截图仅作为加分项缺失。

### 6.4 后续把开箱补上的最短路径

1. 让角色站到 Gillian 旁（任选其一）：
   a. 手动走一次 → ESC → 保存游戏 → 把该 `single_1.sv` 当 **checkpoint**，之后每次启动都从“已站在酒馆里”开始（推荐，零风险）；
   b. 或解析 game 块的 `position.tile`（`SaveGameData` 头部 43B + 17×(4+4) 级表后接 `SavePlayer`；`position.tile.x` 在 `SavePlayer` 内 +39）并直接改写沙盒存档坐标。
2. 用一次 `ViewPosition`（存档头 offset 17/21，大端）与点击落点反解屏幕↔瓦片常数，之后 Gillian 的屏幕坐标即可算出来。
3. 把结果写进 `work\sandbox\stash_click.json`，`Flow.open_stash()` 直接生效。

---

## 7. 复现命令清单

```powershell
$py = "F:\Qoder\暗黑1重制版\_py312\python.exe"
cd "F:\Qoder\暗黑1重制版\work\tests"

# 基线（原版存档）
& $py game_verify.py baseline --tag base

# 储物箱金币（未压缩写法）
& $py game_verify.py run --tag gold1 --stash "F:\Qoder\暗黑1重制版\work\tmp\stash_gold400000.sv" --shots-prefix "gold_"

# 装备生成（背包）
& $py game_verify.py run --tag affix1 --char "F:\Qoder\暗黑1重制版\work\tmp\single_1_affix_test.sv" --inventory --shots-prefix "affix_"

# 储物箱 + 生成装备（开箱需要标定文件）
& $py game_verify.py run --tag stashaffix --stash "F:\Qoder\暗黑1重制版\work\tmp\stash_affix_test.sv" --open-stash

# 交互式探针（attach 到正在运行的窗口）
& $py game_probe.py --info
& $py game_probe.py --click 400 296 --wait 1.2 --shot my_step
& $py game_probe.py --keys DOWN,DOWN,ENTER --shot my_menu
```

`game_verify.py` 输出 JSON，关键字段：`checks.{main_menu,enter_game,no_red_error,stash_file_survived}`、`red_error`、`stash_in/stash_out`（size+mtime+md5）、`snapshot_before/after`。

---

## 8. 截图清单（`work\docs\shots\`）

| 文件 | 内容 | 用途 |
|---|---|---|
| `launch.png` | 主菜单（沙盒首次启动） | 沙盒+截图链路 |
| `10-charlist.png` / `11-jianlai-selected.png` | 角色选择，剑来被选中（等级 24 / 力量 176） | 角色定位 |
| `12-saveexists.png` | “保存文件已存在”对话框 | 流程固化 |
| `13-jianlai-town.png` | 剑来载入城镇 | 沙盒读档成功 |
| `07-escmenu.png` | 游戏内 ESC 菜单 | 坐标固化 |
| `gold_01-mainmenu.png` `gold_02-town.png` `gold_05-backmenu.png` | **金币样本：进游戏无红字** | 验收 A 主证据 |
| `affix_02-town.png` `affix_03-inventory.png` `affix_inv_zoom.png` | **装备样本：背包两件可见** | 验收 B 主证据 |
| `tip_inv.png` `tip_plate.png` `tip_sword.png` | 悬停两件新装备的尝试 | 辅助 |
| `pw_print.png` `pw_screen.png` | PrintWindow vs 桌面 DC（前者在窗口被遮挡时仍正确） | 截图方案说明 |
| `base2_01-mainmenu.png` | **故障现场**：修改器 GUI 遮挡游戏导致截图错误 | 记录前台争用问题 |
| `b3_02-town.png` `ingame.png` | 基线与调试过程 | 过程存档 |

---

## 9. 已知限制 / 提醒给后续代理

1. **同桌面多代理会抢前台**：跑本 harness 前最好确认没有别的 GUI 程序占着前台；否则 `focus()` 会打 ALT 解锁（无害，但会向其它窗口发一次 ALT）。
2. 沙盒会话结束务必确认 `devilutionx.exe` 已退出（`game_verify.py` 会 `ESC→保存游戏→退出游戏`，异常时 `Sandbox.close()` 用 `taskkill /F /T`）。
3. 游戏在**退出到主菜单时**就会写盘（`保存游戏`），直接 `taskkill` 会丢未保存的游戏内进度（人物位置等）；但已有存档不会被破坏。
4. `stash.sv` 只在 `Stash.dirty` 时才写（`pfile.cpp:629`）；实测「进游戏→保存游戏」会触发重写，因此上面的证据链成立。若某天游戏改成不重写，需在验收里改用开箱触发。
5. 窗口客户区固定 800×600 时坐标常量才有效；改 ini 分辨率必须重标定 §3 的常量。
