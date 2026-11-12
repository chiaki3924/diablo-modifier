# Round 2 游戏内回归报告（verify2）

> 代理：verify2
> 日期：2026-11-11 19:47–20:05
> ROOT：`F:\Qoder\暗黑1重制版`
> Python 3.12：`ROOT\_py312\python.exe`
> 脚本：`work\tmp\r2v_make_samples.py`、`work\tmp\r2v_probe2.py`、`work\tmp\fast_crash_probe.py`（原版，未改）
> 样机：`work\tmp\r2v_{A,B,C,D,F}.sv`；截图：`work\docs\shots\r2v_*`；日志：`work\tmp\r2v_*.log`
> 真实存档：**全程只读**，未写入（见 §5）

---

## 0. 结论速览

| 样机 | 内容 | 游戏内结果 | 截图 |
|---|---|---|---|
| A | `King's Long Staff of haste`（普通魔法法杖，spell/charges=0） | ✅ alive / 进城镇 / 无红字 | `r2v_A_town.png`、`r2v_A_02-town.png` |
| B | `Brutal Sword of giants`（指定 **PLDam=85 / PLStr=18**） | ✅ alive / 进城镇 / 无红字 | `r2v_B_town.png` |
| C | `Naj's Light Plate`（暗金 uid=77，Plate Mail 底材） | ✅ alive / 进城镇 / 无红字 | `r2v_C_town.png` |
| D | `The Butcher's Cleaver`（暗金任务 uid=0，Cleaver 底材） | ✅ alive / 进城镇 / 无红字 | `r2v_D_town.png` |
| 复跑 | `work\tmp\probe_u0.sv`（早前生成的 Butcher's Cleaver 副本） | ✅ alive / 进城镇 / 无红字 | `r2v_u0_town.png` |
| 附加 F | `Long Staff of Fireball`（默认 rarity=normal、ilvl=60，游戏原生法术法杖） | ✅ alive / 进城镇 / 无红字 | `r2v_F_town.png` |

**用户第一诉求「新生成的装备进游戏不再崩溃」已闭环**：4 个新样机（普通魔法法杖 / 指定数值 / 两件暗金）全部进城镇，`exit_code=None`（进程存活），红字 0 像素，无一例 `0xC0000005`。

---

## 1. 方法

每个样机：从 `work\backup_saves\stash.sv`（96 件）复制 → `d1stash2.Stash.add_record()` 加 1 件 → 存为 `work\tmp\r2v_<tag>.sv`（97 件，103416 B）→ 沙盒 `--save-dir/--config-dir/--data-dir` 隔离启动 → 单人游戏 → **第 3 行 CHIAKI（Rogue，hero_row=2）** → 加载游戏 → 等 HUD。

- 崩溃判据：`proc.poll()` 是否为 `None`；非 0 时记录十进制与 `0x%08X`（`0xC0000005` 专项标记）。
- 附加判据：`enter_game`（HUD 出现）、`red_error_px`（底部消息框红字像素，>40 判红字）、城镇截图。
- 完整流程另跑 `game_verify.py`（含「ESC→保存游戏→退出」让游戏重写 stash，验证物品被接受并回写）。

## 2. 样机明细（最新 `work\lib\d1itemgen.py`）

| | base (runtime/saved idx) | seed | ci | iName | 关键字段 | validate |
|---|---|---|---|---|---|---|
| A | Long Staff 152/147 | 1923024487 | 30 | `King's Long Staff of haste` | spell=0 charges=0；PLDam=160 PLToHit=93；magical=1 | `[]` |
| B | Short Sword 119/114 | 2259500185 | 30 | `Brutal Sword of giants` | **PLDam=85**、**PLStr=18**；spell/charges=0 | `[]` |
| C | Plate Mail 67/67 | 1262591563 | 531 | `Naj's Light Plate` | Uid=77 magical=2；PLFR/PLMR=20、PLMana=1280 | `[]` |
| D | Cleaver 6/6 | 0 | 512 | `The Butcher's Cleaver` | Uid=0 magical=2；PLStr=10 | `[]` |
| F | Long Staff 152/147 | 1 | 60 | `Long Staff of Fireball` | magical=0；spell=12 charges=46（游戏原生法术法杖路径） | `[]` |

- A：`generate(152, ilvl=30, rarity='magic', prefix="King's", suffix='haste')` —— 0.003 s 命中；**stat 法杖路径，spell==0 / charges==0 确认**。
- B：`generate('Short Sword', ilvl=30, rarity='magic', prefix='Brutal', suffix='giants', prefix_value=85, suffix_value=18, max_tries=2_000_000)` —— 0.1–0.3 s 命中，**PLDam 恰为 85、PLStr 恰为 18**（存档字段 = 游戏 tooltip 值）。
- C：`unique_detail(77)` → base_idx=67；`generate(67, ilvl=19, rarity='unique', unique_id=77)` → `Naj's Light Plate`。
- D：`unique_detail(0)` → base_idx=6；`generate(6, ilvl=1, rarity='unique', unique_id=0)` → `The Butcher's Cleaver`。
- 4 个 stash 副本均复核：加入前 96 件 → 加入后 97 件，最后一条记录除 `posx/posy`（储物箱锚点，必须改）外与生成记录逐字节一致。

## 3. 探针结果

`work\tmp\r2v_probes.jsonl`（`r2v_probe2.py`，逐条 JSON）：

| tag | alive | enter_game | hud | red_error_px | exit_code | 截图 |
|---|---|---|---|---|---|---|
| A | True | True | True | 0 | None | `work\docs\shots\r2v_A_town.png` |
| B | True | True | True | 0 | None | `work\docs\shots\r2v_B_town.png` |
| C | True | True | True | 0 | None | `work\docs\shots\r2v_C_town.png` |
| D | True | True | True | 0 | None | `work\docs\shots\r2v_D_town.png` |
| u0 | True | True | True | 0 | None | `work\docs\shots\r2v_u0_town.png` |
| F | True | True | True | 0 | None | `work\docs\shots\r2v_F_town.png` |

### 3.1 一次「假崩溃」的记录（重要）

首次用原版 `work\tmp\fast_crash_probe.py` 跑 A 时得到 **`alive False exit 4294967295`（0xFFFFFFFF = -1）**，但**不是崩溃**：

- `fast_crash_probe.py` 只固定 `sleep(3.5)` 就点主菜单；**冷启动**（闲置后第一次启动，本次 19:49:32）DevilutionX 画主菜单需要 >4 s，点击全部落到错误画面；
- 最后一次点击 `(384,519)` 落主菜单「退出暗黑破坏神」`(400,513)` 上 → 游戏自行退出，返回 -1；
- 反证：A 用 `game_verify.py` 完整流程 **通过**（进城镇、红字 0、stash 被游戏重写 97 件）；A 用原版 `fast_crash_probe.py` 在热启动下复跑得到 `alive True exit None`（`work\tmp\r2v_probe_A_warm.log`）。
- 因此新增 `work\tmp\r2v_probe2.py`：用 `game_flows.Flow.wait_main_menu()/enter_game()`（像素判定+重试）代替固定 sleep，并额外校验 HUD/红字/截图。**原版 `fast_crash_probe.py` 未修改**。
- 另注意：原版探针「alive True」在未进入游戏（停留在菜单）时也会为 True，故本报告以「alive + enter_game + HUD + 红字 0」四联为判据。
- 全程**未出现 0xC0000005**。

### 3.2 完整流程（game_verify，样机 A）

`work\tmp\r2v_gv_A.log` / `work\sandbox\run_20261111_195025_r2v_A_gv`：

```
checks = {main_menu: true, enter_game: true, no_red_error: true, stash_file_survived: true}
red_error.px = 0
stash 103416 -> 90608 B（游戏用自己的压缩器重写）
```

解析游戏重写后的 stash：**97 件、gold 313108、页 [0,1,2,3,6,7,8,9,10,11] 全在**；最后一件 `idx=147 seed=1923024487 ci=30 name='Long Staff' iName="King's Long Staff of haste" spell=0 charges=0` —— **游戏读档 → 重建 → 再写回后该物品原样保留，未被 `RemoveInvalidItem` 清理**。

## 4. 反向 API（未入库，只测生成器）

| 用例 | 结果 |
|---|---|
| `generate(166)`（IDI_SORCERER_DIABLO） | ✅ 抛 `ItemGenError`：初始装备不能作为随机底材，并给出替代 `Short Staff(151)/Long Staff(152)` |
| `generate(152, ilvl=60, rarity='magic')` | ✅ 抛法杖 ilvl>51 名字重放不一致错误（中英混合中文原因） |
| `generate(152, ilvl=60)`（默认 **normal**） | ⚠️ **不抛错**，返回游戏原生法术法杖（`Long Staff of Firewall`，spell≠0）。这是库的既定语义：`test_itemgen2` 要求的是 `generate(152, 60, "magic")` 抛错；普通法杖带法术是游戏正常掉落路径。本报告附加样机 F 已在游戏内验证该路径**不崩**。若验收口径要求「任何 rarity 的 ilvl>60 法杖都拒绝」，需 itemgen2 再确认（属口径差异，非崩溃缺陷）。 |
| `generate(1)`（IDI_WARRIOR Short Sword 初始版） | ✅ 抛 starter 错误，并提示普通 Short Sword(runtime 119) |
| unique_only 底材（Cleaver）当 magic 生成 | ✅ 抛 `unique-only base item` 错误 |

## 5. 最终 exe 自检 + 真实存档只读核对

exe：`交付\暗黑破坏神1存档修改器-v2.exe`（11221628 B，2026-11-11 19:47:23，SHA256 前 16 位 `2E2E070A8BE5E814`）。

`Start-Process ... --selftest -Wait` → **exit code 0**，日志（`%TEMP%\d1editor2_selftest.log`，19:49:22 一轮）：

```
OK: 读取储物箱 金币=313,108 物品=98 页=[0,1,2,3,6,7,8,9,10,11]
OK: 基础物品 69 种（已排除 starter / unique_only）
OK: 暗金图鉴 89 件（可用）
OK: 拒绝 starter 166 ...
OK: 生成暗金 Ring of Engagement（订婚戒指）校验 通过
OK: 真实存档 4 个文件 SHA256 前后一致（未写入）
SELFTEST OK
```

自检前后**真实存档 5 个文件 SHA256 全部一致**（4 个 .sv + diablo.ini），确认 selftest/生成路径不写真实存档。

### 5.1 真实 `%APPDATA%\diasurgical\devilution` vs `work\backup_saves`（19:47 采样，只读）

| 文件 | 真实大小 | backup 大小 | SHA256 一致 | 说明 |
|---|---|---|---|---|
| single_0.sv | 3492888 | 3415207 | ❌ | 用户实际游玩过的 CHIAKI 存档（晚于 backup），**mtime 19:20:58，本代理全程未变** |
| single_1.sv | 929607 | 929607 | ✅ | `2DEE3F41…` |
| single_2.sv | 2904940 | 2904940 | ✅ | `1C172A2E…` |
| stash.sv | 103800 | 90346 | ❌（预期） | 主会话清理后 98 件：`3E66494E1EF5A5F8336B0BDED4FA84985A506BD9F8627815B2AA23DE6255C93E`，gold 313108，**无 166 / 无 saved idx=5** |
| diablo.ini | 3710 | 3710 | ✅ | `5DBDF219…` |

收尾复核（20:05）：`devilutionx.exe` 无残留进程；真实 stash 仍 **98 件 / SHA256 `3E66494E…` / mtime 19:40:06**，`single_0.sv` mtime 仍 **19:20:58** —— 沙盒隔离成立，真实存档零写入。

## 6. 复现命令

```powershell
$py = "F:\Qoder\暗黑1重制版\_py312\python.exe"
cd "F:\Qoder\暗黑1重制版"
& $py work\tmp\r2v_make_samples.py                 # 生成 5 个样机 + stash 副本 + r2v_samples.json
& $py work\tmp\r2v_probe2.py A work\tmp\r2v_A.sv 2  # 稳健探针（B/C/D/F/u0 同理）
& $py work\tests\game_verify.py run --tag r2v_A_gv --stash work\tmp\r2v_A.sv --hero-row 2 --shots-prefix r2v_A_
Start-Process "交付\暗黑破坏神1存档修改器-v2.exe" -ArgumentList --selftest -Wait -PassThru
```

## 7. 给后续的提醒

1. `fast_crash_probe.py` 的固定 `sleep(3.5)` 冷启动会误判（把「退出游戏」当崩溃），复跑前先等上一次游戏退出/或直接用 `r2v_probe2.py`。
2. 同桌面多代理抢前台：本轮的 6 次探针均在 104 s 级别完成一次进城镇，未见前台争用导致的失败（`focus()` 的 ALT 解锁有效）。
3. 若 B 类双数值搜索在别的 seed 上变慢，`max_tries` 给 2e6 足够（本次 0.1–0.3 s）；失败信息会带「最接近值+差距」。
