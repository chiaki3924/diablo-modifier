"""暗黑破坏神1 存档修改器 v2 —— 入口。

用法：
    python d1editor2.py            # 图形界面
    python d1editor2.py --selftest # 无窗口自检（退出码 0 = 通过）
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# 让源码模式与打包模式都能 import 同目录模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ui_common as uic  # noqa: E402
import d1env  # noqa: E402
from d1env import (APP_TITLE, APP_VERSION, MODULES, is_game_running,  # noqa: E402
                   list_save_files, settings_dir)
from ui_char import CharTab  # noqa: E402
from ui_itemgen import GenTab  # noqa: E402
from ui_stash import StashTab  # noqa: E402
from ui_uniques import UniqueTab  # noqa: E402


class App(tk.Tk):
    def __init__(self, headless: bool = False):
        super().__init__()
        self.headless = headless
        uic.HEADLESS = headless
        # 自动测试（--selftest / smoke / 截图）一律禁止写真实存档：
        # 任何写 %APPDATA% 的尝试都会抛 ProtectedWriteError。
        d1env.ALLOW_PROTECTED_WRITES = not headless and not os.environ.get("D1_READONLY")
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry("1260x920")
        self.minsize(1080, 760)
        self.game_running = False
        self._name_cache: dict[tuple, str] = {}
        self._game_queue: queue.Queue = queue.Queue()
        self._game_thread = None
        self._game_last = 0.0
        self._poll_id = None
        self._modules_ok = MODULES.load()
        self._style = uic.make_style(self)

        self._build_top()
        self._build_body()
        self._build_bottom()
        self._build_menu()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda e: self.refresh_all())
        self.bind("<Control-s>", lambda e: self._save_current())
        self.after(150, self._poll_game_state)
        self.after(400, self._initial_load)

    # ------------------------------------------------------------ 布局
    def _build_top(self) -> None:
        bar = ttk.Frame(self, padding=(10, 8, 10, 4))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(2, weight=1)
        ttk.Label(bar, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(bar, text=f"v{APP_VERSION}", style="Hint.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 16))
        self.game_lbl = ttk.Label(bar, text="游戏状态：检查中…", style="Sub.TLabel")
        self.game_lbl.grid(row=0, column=2, sticky="w")
        ttk.Button(bar, text="刷新 (F5)", command=self.refresh_all).grid(row=0, column=3, padx=4)
        ttk.Button(bar, text="打开存档目录",
                   command=lambda: os.startfile(str(settings_dir()))).grid(row=0, column=4, padx=4)
        self.rowconfigure(0, weight=0)

    def _build_body(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 0))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.tab_char = CharTab(self.nb, self)
        self.tab_stash = StashTab(self.nb, self)
        self.tab_gen = GenTab(self.nb, self)
        self.tab_unique = UniqueTab(self.nb, self)
        self.nb.add(self.tab_char, text=" 角色 ")
        self.nb.add(self.tab_stash, text=" 储物箱 ")
        self.nb.add(self.tab_gen, text=" 装备生成 ")
        self.nb.add(self.tab_unique, text=" 暗金图鉴 ")
        # 截图/自动化用：D1_START_TAB=char|stash|gen|unique
        start = os.environ.get("D1_START_TAB", "").strip().lower()
        if start in ("char", "stash", "gen", "unique"):
            self.nb.select({"char": 0, "stash": 1, "gen": 2, "unique": 3}[start])

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 4, 10, 8))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.log_pane = uic.LogPane(bottom, height=4)
        self.log_pane.grid(row=0, column=0, sticky="ew")
        self.status_lbl = ttk.Label(bottom, text="就绪", style="Hint.TLabel")
        self.status_lbl.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.log(f"启动完成；pyc 模块：{'已加载' if self._modules_ok else '加载失败：' + str(MODULES.error)}")

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="刷新 (F5)", command=self.refresh_all)
        file_menu.add_command(label="保存当前页 (Ctrl+S)", command=self._save_current)
        file_menu.add_separator()
        file_menu.add_command(label="打开存档目录", command=lambda: os.startfile(str(settings_dir())))
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.configure(menu=menubar)

    # ------------------------------------------------------------ 通用
    def log(self, msg: str, tag: str | None = None) -> None:
        try:
            self.log_pane.write(str(msg), tag)
        except Exception:  # noqa: BLE001
            _selftest_out(msg)
        try:
            self.status_lbl.configure(text=str(msg))
        except Exception:  # noqa: BLE001
            pass

    def _save_current(self) -> None:
        idx = self.nb.index(self.nb.select())
        if idx == 0:
            self.tab_char.save()
        elif idx == 1:
            self.tab_stash.save_gold()
        else:
            self.log("装备生成页没有「保存」操作，生成时会自动保存。")

    def _on_close(self) -> None:
        try:
            if self._poll_id:
                self.after_cancel(self._poll_id)
                self._poll_id = None
        except Exception:  # noqa: BLE001
            pass
        try:
            self.destroy()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 游戏状态
    def _poll_game_state(self) -> None:
        """后台线程跑 tasklist，主线程 only 消费结果（Tk 不是线程安全的）。"""
        now = time.time()
        thread = getattr(self, "_game_thread", None)
        if (thread is None or not thread.is_alive()) and now - getattr(self, "_game_last", 0) > 5:
            self._game_last = now
            q = self._game_queue

            def worker():
                try:
                    q.put(is_game_running())
                except Exception:  # noqa: BLE001
                    q.put(False)

            self._game_thread = threading.Thread(target=worker, daemon=True)
            self._game_thread.start()
        try:
            while True:
                self._set_game_state(self._game_queue.get_nowait())
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_id = self.after(600, self._poll_game_state)

    def _set_game_state(self, running: bool) -> None:
        changed = running != self.game_running
        self.game_running = running
        if running:
            self.game_lbl.configure(text="● 游戏正在运行 —— 已禁用写存档，请先退出游戏",
                                    style="Bad.TLabel")
        else:
            self.game_lbl.configure(text="● 游戏未运行 —— 可以安全写入存档", style="Ok.TLabel")
        if changed:
            self.log("检测到游戏%s" % ("启动：写操作已禁用" if running else "已退出：可以保存"), 
                     "warn" if running else "ok")
        try:
            self.tab_char._update_banner()
        except Exception:  # noqa: BLE001
            pass

    def require_game_closed(self) -> bool:
        try:
            self.game_running = is_game_running()
        except Exception:  # noqa: BLE001
            self.game_running = False
        self._set_game_state(self.game_running)
        if self.game_running:
            uic.warn("游戏正在运行",
                     "检测到 devilutionx.exe 正在运行。\n\n"
                     "游戏退出时会用内存里的角色覆盖存档，现在写入会丢失。\n请先退出游戏再保存。")
            self.log("写操作被拒绝：游戏正在运行", "warn")
            return False
        return True

    # ------------------------------------------------------------ 数据
    def quick_name(self, path: Path) -> str:
        """存档列表里显示『角色名 · 职业 · 等级』（带缓存）。"""
        try:
            st = path.stat()
            key = (str(path), st.st_mtime, st.st_size)
        except OSError:
            key = (str(path), 0)
        if key in self._name_cache:
            return self._name_cache[key]
        text = path.name
        try:
            d1save = MODULES.d1save
            pack = d1save.SaveFile(str(path)).pack
            from d1names import class_name
            name = pack.name if isinstance(pack.name, str) else str(pack.name)
            text = f"{name} · {class_name(int(pack.hero_class))} · {int(pack.level)} 级"
        except Exception as exc:  # noqa: BLE001
            text = f"{path.name}（{type(exc).__name__}）"
        self._name_cache[key] = text
        return text

    def _initial_load(self) -> None:
        if self.headless:
            return
        self.tab_char.refresh_saves()
        self.tab_stash.refresh_files()
        # 默认自动选最近存档 / 默认储物箱
        try:
            if self.tab_char.save_var.get():
                self.tab_char._on_pick()
        except Exception as exc:  # noqa: BLE001
            self.log(f"自动载入角色失败：{exc}", "warn")
        try:
            if self.tab_stash.file_var.get():
                self.tab_stash._on_pick()
        except Exception as exc:  # noqa: BLE001
            self.log(f"自动载入储物箱失败：{exc}", "warn")

    def refresh_all(self, keep_char: bool = False) -> None:
        self._name_cache.clear()
        cur_char = None
        try:
            if self.tab_char.hero is not None:
                cur_char = Path(self.tab_char.hero.path)
        except Exception:  # noqa: BLE001
            cur_char = None
        self.tab_char.refresh_saves(select=cur_char)
        # 刷新时保持当前已打开的储物箱文件（否则会跳回 %APPDATA% 的 stash.sv，
        # 测试/浏览副本时尤其危险）
        cur = None
        try:
            if self.tab_stash.stash is not None:
                cur = Path(self.tab_stash.stash.path)
        except Exception:  # noqa: BLE001
            cur = None
        self.tab_stash.refresh_files(select=cur)
        if not keep_char:
            try:
                if self.tab_char.save_var.get():
                    self.tab_char._on_pick()
            except Exception as exc:  # noqa: BLE001
                self.log(f"刷新角色失败：{exc}", "warn")
        try:
            if self.tab_stash.file_var.get():
                self.tab_stash._on_pick()
        except Exception as exc:  # noqa: BLE001
            self.log(f"刷新储物箱失败：{exc}", "warn")
        self.tab_gen._update_target_labels()

    def on_char_loaded(self, path: Path) -> None:
        # ilvl 默认取角色等级（最多 50）
        try:
            hero = self.tab_char.hero
            if hero is not None:
                self.tab_gen.set_ilvl(hero.level)
        except Exception:  # noqa: BLE001
            pass
        self.tab_gen._update_target_labels()

    def on_stash_loaded(self, path: Path) -> None:
        self.tab_gen._update_target_labels()
        # 启动/刷新时做一次便宜的体检：发现 starter 之类会崩溃的物品就报黄条
        try:
            self.tab_stash.report_issues()
        except Exception as exc:  # noqa: BLE001
            self.log(f"储物箱体检失败：{exc}", "warn")

    # ------------------------------------------------------------ 帮助
    def _show_help(self) -> None:
        uic.info("使用说明", (
            "1) 角色页：改等级/属性/金币/法术后点「保存到存档」。\n"
            "   写入前会自动备份 .bak 与 .bak-时间戳；默认保留关卡进度。\n\n"
            "2) 储物箱页：金币改动只写 gold 字段，物品记录逐字节校验，确认一件不少才落盘。\n"
            "   使用修正版 MPQ 写入（未压缩、无扇区表），不会再把箱子写空。\n\n"
            "3) 装备生成页：选物品/ilvl/稀有度 → 生成到储物箱或角色背包。\n"
            "   默认「随机合法」词条；非法组合会被拒绝并给出原因。\n\n"
            "注意：写入前请退出游戏；游戏运行中本程序会拒绝保存。\n"
            "真实存档位于 %APPDATA%\\diasurgical\\devilution。"
        ))

    def _show_about(self) -> None:
        uic.info("关于", (
            f"{APP_TITLE} v{APP_VERSION}\n\n"
            "本项目基于自研的 3.12 存档读写模块：\n"
            "  · 角色读写：d1save.SaveFile / HeroPack\n"
            "  · 储物箱写入：lib/d1stash2.py（修正 MPQ 扇区 bug）\n"
            "  · 装备生成：lib/d1itemgen.py（1.5.5 规则移植）\n\n"
            "适配 DevilutionX 1.5.5（非 Hellfire）。"
        ))


# ---------------------------------------------------------------- 自检

def _selftest_out(*parts) -> None:
    msg = " ".join(str(p) for p in parts)
    try:
        print(msg)
    except Exception:  # noqa: BLE001 - windowed 模式 stdout 为 None
        pass
    if getattr(sys, "frozen", False):
        try:
            import tempfile
            import time
            path = Path(tempfile.gettempdir()) / "d1editor2_selftest.log"
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:  # noqa: BLE001
            pass


def _zh_status() -> str:
    try:
        import d1zh
        return d1zh.i18n_status()
    except Exception as exc:  # noqa: BLE001
        return f"中文模块加载失败：{exc}"


def _saves_snapshot() -> dict[str, tuple]:
    """真实存档目录快照（名字 -> 大小/修改时间/SHA256），自检前后比对用。"""
    import hashlib
    out: dict[str, tuple] = {}
    base = settings_dir()
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        try:
            if not p.is_file() or p.suffix.lower() not in (".sv", ".hsv"):
                continue
            if ".bak" in p.name.lower():
                continue
            st = p.stat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            out[p.name] = (st.st_size, st.st_mtime_ns, digest)
        except Exception:  # noqa: BLE001
            continue
    return out


def run_selftest() -> int:
    uic.HEADLESS = True
    # 自检绝不写真实存档：自动测试模式下任何写 %APPDATA% 的尝试都会抛异常
    d1env.ALLOW_PROTECTED_WRITES = False
    failures: list[str] = []
    _selftest_out("=== d1editor2 selftest start ===")
    snap_before = _saves_snapshot()

    if not MODULES.load():
        _selftest_out("FAIL: pyc 模块加载失败：", MODULES.error)
        return 1
    _selftest_out("OK: pyc 模块加载自", MODULES.dir)

    app = None
    try:
        app = App(headless=True)
        app.withdraw()
        app.update_idletasks()
        app.update()

        tabs = [app.nb.tab(i, "text").strip() for i in range(app.nb.index("end"))]
        _selftest_out("OK: 标签页 =", tabs)
        if len(tabs) != 4:
            failures.append(f"标签页数量 {len(tabs)} != 4")

        # 角色页控件
        for name in ("save_box", "sp_level", "var_str", "var_gold", "spell_tree", "btn_save"):
            if not hasattr(app.tab_char, name):
                failures.append(f"角色页缺少控件 {name}")
        # 储物箱页
        for name in ("file_box", "tree", "var_gold", "lbl_count", "btn_check", "warn_lbl"):
            if not hasattr(app.tab_stash, name):
                failures.append(f"储物箱页缺少控件 {name}")
        # 生成页
        for name in ("listbox", "var_ilvl", "var_rarity", "cb_pre", "btn_stash", "btn_bag",
                     "preview", "valid_lbl", "ent_pre_value", "ent_suf_value",
                     "lbl_pre_desc", "lbl_suf_desc", "lbl_pre_range",
                     "var_page", "sp_page"):
            if not hasattr(app.tab_gen, name):
                failures.append(f"生成页缺少控件 {name}")
        # 暗金图鉴页
        for name in ("tree", "var_search", "var_base", "preview", "btn_stash", "btn_bag",
                     "var_page", "sp_page"):
            if not hasattr(app.tab_unique, name):
                failures.append(f"暗金图鉴页缺少控件 {name}")
        _selftest_out("OK: 四页控件齐全")

        # 真实存档只读加载（不写盘）
        saves = [p for p in list_save_files() if p.name.lower() != "stash.sv"]
        if saves:
            from d1hero import HeroEdit
            h = HeroEdit(saves[0])
            _selftest_out(f"OK: 读取存档 {saves[0].name} -> {h.summary()}, "
                           f"HP {h.hp[0]}/{h.hp[1]}, 金币 {h.gold}, 法术 {len(h.known_spells)}")
            if not h.name:
                failures.append("角色名为空")
            if not (1 <= h.level <= 50):
                failures.append(f"等级异常：{h.level}")
        else:
            _selftest_out("SKIP: 没有找到角色存档")

        # 储物箱只读加载
        st_path = settings_dir() / "stash.sv"
        if st_path.is_file():
            from d1stash_adapter import open_stash
            st = open_stash(st_path, multiplayer=False)
            _selftest_out(f"OK: 读取储物箱 金币={st.gold:,} 物品={st.item_count()} 页={st.pages()}")
            if st.item_count() <= 0:
                failures.append("储物箱物品数为 0（可疑）")
        else:
            _selftest_out("SKIP: 没有找到 stash.sv")

        # 生成器状态
        info = app.tab_gen.gen
        _selftest_out("OK: 生成器状态 =", info.status_text())
        _selftest_out("OK: 组合预检 =",
                      "core d1itemgen.check_combination" if info.supports_check_combination
                      else "本地规则（core 未提供 check_combination）")
        _selftest_out("OK: 中文数据 =", _zh_status())
        bases = info.base_items()
        _selftest_out(f"OK: 基础物品 {len(bases)} 种（已排除 starter / unique_only）")
        if not 50 <= len(bases) <= 90:
            failures.append(f"底材数量异常：{len(bases)}（应 50~90）")
        if len(bases) != len({b.name.lower() for b in bases}):
            failures.append("底材仍存在同名重复")
        if any(b.starter or b.unique_only for b in bases):
            failures.append("底材列表里仍有 starter / unique_only 条目")
        if any(b.idx == 166 for b in bases):
            failures.append("底材列表里出现了 IDI_SORCERER_DIABLO(166)")
        banned = ("Arkaine's Valor", "Griswold's Edge", "Veil of Steel", "Harlequin Crest",
                  "Naj's Light Plate", "The Undead Crown", "Empyrean Band", "Optic Amulet")
        bad_names = [b.label for b in bases if b.name in banned]
        if bad_names:
            failures.append("底材列表混入暗金名：" + "、".join(bad_names))
        _selftest_out("OK: 底材前 4 个 =", [b.label for b in bases[:4]])

        # 暗金图鉴
        uniques = info.uniques()
        _selftest_out(f"OK: 暗金图鉴 {len(uniques)} 件（可用）")
        if len(uniques) != 89:
            failures.append(f"暗金数量 {len(uniques)} != 89")
        if uniques:
            u0 = uniques[0]
            if not u0.cn or u0.cn == u0.en:
                failures.append(f"暗金中文名为空/未翻译：{u0.en}")
            _selftest_out(f"OK: 暗金示例 = {u0.label} / 底材 {u0.base_cn} / 需Lv{u0.min_level}")
            rows = u0.to_rows()
            if not rows:
                failures.append("暗金词条为空")
            else:
                _selftest_out("OK: 词条示例 =", rows[0][1])

        # 生成自检（不写盘）：普通魔法 + 指定数值
        if info.ready:
            try:
                res = info.generate(125, 20, rarity="magic")
                _selftest_out(f"OK: 生成魔法物品 {res.name}（{res.name_cn}）"
                              f"校验 {'通过' if not res.validation else res.validation}")
                if res.validation:
                    failures.append("生成魔法物品校验失败")
                if res.name_cn and res.name_cn == res.name:
                    failures.append("生成物品没有中文名")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"生成魔法物品失败：{exc}")
            try:
                pre = [a for a in info.eligible_affixes(125, 20, "prefix") if a.numeric]
                if pre and info.supports_values:
                    a = pre[0]
                    lo, hi = a.range_tuple()
                    want = (lo + hi) // 2
                    res2 = info.generate(125, 20, rarity="magic", prefix=a.index,
                                         prefix_value=want)
                    field = {"IPL_DAMP": "PLDam", "IPL_TOHIT": "PLToHit"}.get(
                        str(a.raw.get("power_name")), "")
                    got = res2.fields.get(field) if field else None
                    _selftest_out(f"OK: 指定数值 {a.cn}={want} → {res2.name}（PLDam/值 {got}）")
                    if field and got is not None and abs(int(got) - want) > 0:
                        failures.append(f"指定数值未生效：要 {want}，实际 {got}")
                else:
                    _selftest_out("SKIP: 该 itemgen 版本不支持指定数值；或没有可指定数值的词缀")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"指定数值生成失败：{exc}")
            try:
                info.generate(166, 20, rarity="magic")
                failures.append("starter 166 没有被拒绝！")
            except Exception as exc:  # noqa: BLE001
                _selftest_out(f"OK: 拒绝 starter 166 = {str(exc)[:60]}…")
            try:
                u = uniques[-1] if uniques else None
                if u is not None and u.base_available:
                    res3 = info.generate(u.base_idx, max(20, u.min_level),
                                         rarity="unique", unique=u.uid)
                    _selftest_out(f"OK: 生成暗金 {res3.name}（{res3.name_cn}）"
                                  f"校验 {'通过' if not res3.validation else res3.validation}")
                    if res3.validation:
                        failures.append("生成暗金校验失败")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"生成暗金失败：{exc}")

        # ---------------- Round 3：效果名 / 组合预检 / 暗金排序 ----------------
        try:
            pre = info.eligible_affixes(125, 20, "prefix")
            brutal = next((a for a in pre if a.en == "Brutal"), None)
            if brutal is None:
                _selftest_out("SKIP: ilvl20 长剑没有 Brutal 前缀")
            else:
                _selftest_out(f"OK: 下拉词条带效果名 = {brutal.label}")
                if "伤害" not in brutal.label:
                    failures.append(f"词缀下拉没有效果名：{brutal.label}")
            ring_pre = info.eligible_affixes(156, 50, "prefix")
            ruby = next((a for a in ring_pre if a.en == "Ruby"), None)
            if ruby is not None:
                _selftest_out(f"OK: 效果名示例 = {ruby.label}")
                if "火焰抗性" not in ruby.label:
                    failures.append(f"红宝石的效果名不是火焰抗性：{ruby.label}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"词缀效果名检查失败：{exc}")

        try:
            T = getattr(info.mod, "T", None)
            obs = T.affix_by_name("prefix", "Obsidian") if T is not None else None
            hea = T.affix_by_name("suffix", "of the heavens") if T is not None else None
            if obs is None or hea is None:
                _selftest_out("SKIP: 找不到 Obsidian / of the heavens 词缀行")
            else:
                bad20 = info.check_combination(156, 20, "magic", prefix=obs["index"],
                                               suffix=hea["index"])
                _selftest_out(f"OK: 预检 ilvl20 = {bad20.code}｜{bad20.message}")
                if bad20.ok:
                    failures.append("Ring+Obsidian+of the heavens 在 ilvl20 应判为不合法")
                elif "24" not in bad20.message:
                    failures.append(f"ilvl20 预检没提示『把 ilvl 提到 24』：{bad20.message}")
                ok30 = info.check_combination(156, 30, "magic", prefix=obs["index"],
                                              suffix=hea["index"])
                _selftest_out(f"OK: 预检 ilvl30 = ok={ok30.ok}｜{ok30.title}")
                if not ok30.ok:
                    failures.append(f"Ring+Obsidian+of the heavens 在 ilvl30 应判为合法："
                                    f"{ok30.message}")
                bad50 = info.check_combination(156, 50, "magic", prefix=obs["index"],
                                               suffix=hea["index"])
                if bad50.ok or "49" not in bad50.message:
                    failures.append(f"ilvl50 预检应提示『把 ilvl 降到 49』：{bad50.message}")
                else:
                    _selftest_out(f"OK: 预检 ilvl50 = {bad50.code}｜{bad50.message}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"组合预检检查失败：{exc}")

        try:
            tab_u = app.tab_unique
            tab_u._loaded(uniques)
            first_natural = tab_u.tree.item(tab_u.tree.get_children()[0], "values")
            tab_u.sort_by("value")
            asc = tab_u.tree.item(tab_u.tree.get_children()[0], "values")
            tab_u.sort_by("value")
            desc = tab_u.tree.item(tab_u.tree.get_children()[0], "values")
            head = tab_u.tree.heading("value", "text")
            _selftest_out(f"OK: 暗金排序 原始首行={first_natural} 升序首行={asc} "
                          f"降序首行={desc} 表头={head!r}")
            if str(first_natural[0]) != "1":
                failures.append(f"暗金序号列第一行不是 1：{first_natural}")
            if int(asc[4].replace(",", "")) > int(desc[4].replace(",", "")):
                failures.append("价值升序/降序没有反转")
            if "▼" not in head:
                failures.append(f"降序时表头没有 ▼：{head!r}")
            tab_u.sort_by("name")
            if "▲" not in tab_u.tree.heading("name", "text"):
                failures.append("按名称升序时表头没有 ▲")
            # 选中项在排序后必须还在（右侧详情不丢）
            tab_u.tree.selection_set(tab_u.tree.get_children()[3])
            tab_u._on_select()
            uid_before = getattr(tab_u._current(), "uid", None)
            tab_u.sort_by("lvl")
            uid_after = getattr(tab_u._current(), "uid", None)
            if uid_before != uid_after:
                failures.append(f"排序后选中的暗金变了：{uid_before} -> {uid_after}")
            else:
                _selftest_out(f"OK: 排序后选中项保持（uid={uid_after}）")
            if tab_u.var_page.get().strip() != "1":
                failures.append(f"暗金页「写入页码」默认不是 1：{tab_u.var_page.get()!r}")
            if app.tab_gen.var_page.get().strip() != "1":
                failures.append(f"生成页「写入页码」默认不是 1：{app.tab_gen.var_page.get()!r}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"暗金排序检查失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        failures.append(f"自检异常：{type(exc).__name__}: {exc}")
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001
                pass

    # 真实存档必须一个字节都没动
    snap_after = _saves_snapshot()
    if snap_after != snap_before:
        changed = [k for k in snap_before if snap_before.get(k) != snap_after.get(k)]
        changed += [k for k in snap_after if k not in snap_before]
        _selftest_out("FAIL: 自检修改了真实存档：", changed)
        failures.append(f"真实存档被修改：{changed}")
    else:
        _selftest_out(f"OK: 真实存档 {len(snap_before)} 个文件 SHA256 前后一致（未写入）")

    if failures:
        _selftest_out("\nSELFTEST FAILED:")
        for f in failures:
            _selftest_out("  -", f)
        return 1
    _selftest_out("\nSELFTEST OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--selftest", action="store_true", help="无窗口自检")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()

    uic.setup_dpi()
    try:
        app = App()
    except Exception as exc:  # noqa: BLE001
        uic.HEADLESS = False
        messagebox.showerror("启动失败", f"{type(exc).__name__}: {exc}")
        raise
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
