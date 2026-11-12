"""「装备生成」标签页（Round 4：实时预览 + 全词缀 + 满值 + 充能法杖）。

左列（自上而下）：
  1. 底材              —— 类型 / 搜索 / Listbox
  2. 词缀（全部显示）  —— 前缀/后缀下拉（每项带〔ilvl L~H〕）+ 范围/目标值/容差/说明
  3. 法杖              —— 属性法杖 / 法术法杖（带充能），仅 Staff 底材显示
  4. 基础属性          —— 随机 / 满值 / 仅护甲最大 / 仅耐久满
  5. 校验与生成        —— ilvl（勾选丢地保护 1~34，取消 1~50）+「用推荐 ilvl」
                         + seed/数量/写入页码/生成按钮
右侧：实时预览（未生成时）+ 合法性标签 + 目标标签。

实时预览只调用 ``gen.base_preview()`` / ``gen.all_affixes()`` /
``gen.check_combination(max_tries=None)``，**不生成物品、不搜索 seed**，
由 ``after(120, ...)`` 防抖，任何底材/词缀/ilvl/满值/法杖选项变化都会刷新。
"""
from __future__ import annotations

import inspect
import random
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import d1zh
import ui_common as uic
import ui_genops
from d1itemgen_adapter import (KIND_ORDER, ItemGen, classify_error,
                               classify_validation)

RANDOM_LABEL = "（随机合法）"
SPELL_RANDOM = "（随机法术）"
PAGE_AUTO = "自动"

#: 基础属性（Round 4）：护甲 / 耐久是否直接写满值
BASE_RANDOM = "随机（游戏原值）"
BASE_FULL = "满值（护甲最大 + 耐久满）"
BASE_AC = "仅护甲最大"
BASE_DUR = "仅耐久满"
BASE_CHOICES = [BASE_RANDOM, BASE_FULL, BASE_AC, BASE_DUR]

#: 法杖形态（记录里 var_staff_mode 的值）
STAFF_STAT = "stat"
STAFF_SPELL = "spell"
STAFF_MODE_CN = {STAFF_STAT: "属性法杖", STAFF_SPELL: "法术法杖（带充能）"}

#: 装备生成页只做「普通 / 魔法」；暗金走「暗金图鉴」页（词条固定）。
RARITY_KEYS = ["normal", "magic"]
RARITY_CN = {"normal": "普通", "magic": "魔法"}

#: ``itype_name`` -> 中文（预览用）
ITYPE_CN = {
    "Sword": "剑", "Axe": "斧", "Bow": "弓", "Mace": "锤/棍", "Staff": "法杖",
    "Shield": "盾牌", "Helm": "头盔",
    "LightArmor": "轻型护甲", "MediumArmor": "中型护甲", "HeavyArmor": "重型护甲",
    "Ring": "戒指", "Amulet": "护身符",
}


#: 丢地上合法（IsDungeonItemValid）的最高 ilvl（Round 6；运行时优先用 gen.max_drop_ilvl）
MAX_DROP_ILVL = 34

#: 快捷键 / 防抖毫秒
DEBOUNCE_MS = 120


class GenTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.gen = ItemGen()
        self.items = []
        self._filtered = []
        self._pre_map: dict[str, object] = {}
        self._suf_map: dict[str, object] = {}
        # ---- Round 6：每个词缀最多两个数值框（King's = 伤害 + 命中）----
        self._val_rows: dict[str, dict] = {}
        self._last_results = []
        self._runner = uic.TaskRunner(self)
        # ---- Round 4：预览缓存 / 防抖 / 法术表 ----
        self._affix_cache: dict[tuple, list] = {}
        self._bp_cache: dict[int, dict] = {}
        self._spell_map: dict[str, dict | None] = {SPELL_RANDOM: None}
        self._spells_loaded = False
        self._refresh_job = None
        self._suppress_refresh = False
        self._ready = False
        self._build()
        self._ready = True
        self.after(250, self._load_items)

    # ============================================================ 构建
    def _build(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.banner = ttk.Label(self, text="", style="Bad.TLabel",
                                wraplength=1080, justify="left")
        self.banner.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.banner.grid_remove()

        left = self._build_left()

        self._build_base(left)          # 1. 底材
        self._build_affix(left)         # 2. 词缀（全部显示）
        self._build_staff(left)         # 3. 法杖
        self._build_base_stats(left)    # 4. 基础属性
        self._build_preview(right_col=1)
        self._build_gen_bar()           # 预览下方：等级/数量/页码/生成按钮
        self._bind_left_wheel()

        self._bind_preview_traces()
        self._on_rarity()
        self._update_staff_state()
        self._update_base_stats_hint()
        self._update_target_labels()
        uic.set_text(self.preview, self._help_text())

    @staticmethod
    def _help_text() -> str:
        return "先在左侧选择底材，再按需调整词缀。\n\n右侧会实时预览，确认后即可写入储物箱或角色背包。"

    # ------------------------------------------------------------ 左列容器（可滚动）
    def _canvas_bg(self) -> str:
        try:
            return ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        except Exception:  # noqa: BLE001
            return "#f0f0f0"

    def _build_left(self):
        """左列放进 Canvas：5 个分区在 1260x920 下装不满时自动出现滚动条。

        Round 4 多了「法杖 / 基础属性」两个分区，纵向会超出窗口高度；这里用
        标准 canvas+scrollbar 方案保证任何分区都不会被裁掉（内容装得下时滚动条
        自动隐藏）。
        """
        box = ttk.Frame(self)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self._left_canvas = tk.Canvas(box, width=640, highlightthickness=0,
                                      borderwidth=0, background=self._canvas_bg())
        self._left_canvas.grid(row=0, column=0, sticky="nsew")
        self._left_sb = ttk.Scrollbar(box, orient="vertical",
                                      command=self._left_canvas.yview)
        self._left_sb.grid(row=0, column=1, sticky="ns")
        self._left_sb.grid_remove()
        self._left_canvas.configure(yscrollcommand=self._left_sb.set)
        left = ttk.Frame(self._left_canvas)
        left.columnconfigure(0, weight=1)
        self._left = left
        self._left_window = self._left_canvas.create_window((0, 0), window=left,
                                                            anchor="nw")
        self._left_canvas.bind("<Configure>", self._on_left_canvas)
        left.bind("<Configure>", lambda e: self._sync_left_scroll())
        return left

    def _on_left_canvas(self, _event=None) -> None:
        try:
            width = max(620, self._left_canvas.winfo_width())
            self._left_canvas.itemconfigure(self._left_window, width=width)
        except tk.TclError:
            return
        self._sync_left_scroll()

    def _sync_left_scroll(self) -> None:
        """内容比可视区高才显示滚动条，否则隐藏并回到顶部。"""
        try:
            canvas = self._left_canvas
            need = self._left.winfo_reqheight()
            have = canvas.winfo_height()
        except tk.TclError:
            return
        if have <= 1:
            return
        if need > have + 2:
            self._left_sb.grid()
        else:
            self._left_sb.grid_remove()
            canvas.yview_moveto(0)
        try:
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(need, have)))
        except tk.TclError:
            pass

    def _on_left_wheel(self, event):
        try:
            if not self._left_sb.winfo_ismapped():
                return None
            step = -1 if getattr(event, "delta", 0) > 0 else 1
            self._left_canvas.yview_scroll(step, "units")
        except tk.TclError:
            return None
        return "break"

    def _bind_left_wheel(self, widget=None) -> None:
        """给左列所有「本身不处理滚轮」的控件绑滚轮（下拉/Spinbox/列表保持原生）。"""
        widget = widget if widget is not None else self._left
        native = {"TCombobox", "TSpinbox", "TEntry", "Listbox", "Text", "TScrollbar"}
        for child in widget.winfo_children():
            try:
                cls = child.winfo_class()
            except tk.TclError:
                continue
            if cls in native:
                continue
            child.bind("<MouseWheel>", self._on_left_wheel)
            self._bind_left_wheel(child)
        try:
            self._left_canvas.bind("<MouseWheel>", self._on_left_wheel)
        except tk.TclError:
            pass

    def scroll_left_bottom(self) -> None:
        """把左列滚到底（截图/自动化用）。"""
        try:
            self._left_canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    def scroll_left_top(self) -> None:
        """把左列滚到顶（截图/自动化用）。"""
        try:
            self._left_canvas.yview_moveto(0.0)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 1. 底材
    def _build_base(self, left) -> None:
        pick = ttk.LabelFrame(left, text="底材")
        pick.grid(row=0, column=0, sticky="ew")
        pick.columnconfigure(1, weight=1)
        ttk.Label(pick, text="类型").grid(row=0, column=0, sticky="e")
        self.var_cat = tk.StringVar(value="全部")
        self.cb_cat = ttk.Combobox(pick, textvariable=self.var_cat, state="readonly",
                                   values=["全部"] + KIND_ORDER, width=10)
        self.cb_cat.grid(row=0, column=1, sticky="w", padx=(4, 8))
        self.cb_cat.bind("<<ComboboxSelected>>", lambda e: self._refresh_item_list())
        ttk.Label(pick, text="搜索").grid(row=0, column=2, sticky="e")
        self.var_search = tk.StringVar()
        ent = ttk.Entry(pick, textvariable=self.var_search, width=12)
        ent.grid(row=0, column=3, sticky="w", padx=(4, 8))
        ent.bind("<KeyRelease>", lambda e: self._refresh_item_list())
        self.lbl_bases = ttk.Label(pick, text="", style="Hint.TLabel")
        self.lbl_bases.grid(row=0, column=4, sticky="w")

        list_frame = ttk.Frame(pick)
        list_frame.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=(6, 0))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, height=17, exportselection=False,
                                  activestyle="dotbox", width=40,
                                  background=uic.SURFACE, foreground=uic.TEXT,
                                  selectbackground=uic.ACCENT, selectforeground="#FFFFFF")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_item_select())

    # --------------------------------------------------- 2. 词缀（全部显示）
    def _build_affix(self, left) -> None:
        opts = ttk.LabelFrame(left, text="词缀")
        opts.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        opts.columnconfigure(3, weight=1)
        self._affix_opts = opts

        # 稀有度（普通 / 魔法；暗金在「暗金图鉴」页）
        rf = ttk.Frame(opts)
        rf.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(rf, text="稀有度").grid(row=0, column=0, padx=(0, 4))
        self.var_rarity = tk.StringVar(value="magic")
        self.rarity_buttons = []
        for i, key in enumerate(RARITY_KEYS):
            rb = ttk.Radiobutton(rf, text=RARITY_CN[key], value=key,
                                 variable=self.var_rarity, command=self._on_rarity)
            rb.grid(row=0, column=i + 1, padx=2)
            self.rarity_buttons.append(rb)

        # 前缀
        ttk.Label(opts, text="前缀").grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.var_pre = tk.StringVar(value=RANDOM_LABEL)
        self.cb_pre = ttk.Combobox(opts, textvariable=self.var_pre, state="readonly",
                                   width=60, height=22)
        self.cb_pre.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(4, 0),
                         pady=(6, 0))
        self.cb_pre.bind("<<ComboboxSelected>>", lambda e: self._on_affix_pick("pre"))
        self.cb_pre.configure(postcommand=lambda: self._fit_affix_popup(self.cb_pre))
        self._build_value_row(opts, "pre", row=2)
        self.lbl_pre_desc = ttk.Label(opts, text="", style="Hint.TLabel", wraplength=560,
                                      justify="left")
        self.lbl_pre_desc.grid(row=3, column=0, columnspan=4, sticky="w", pady=(1, 0))

        # 后缀
        ttk.Label(opts, text="后缀").grid(row=4, column=0, sticky="e", pady=(6, 0))
        self.var_suf = tk.StringVar(value=RANDOM_LABEL)
        self.cb_suf = ttk.Combobox(opts, textvariable=self.var_suf, state="readonly",
                                   width=60, height=22)
        self.cb_suf.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(6, 0))
        self.cb_suf.bind("<<ComboboxSelected>>", lambda e: self._on_affix_pick("suf"))
        self.cb_suf.configure(postcommand=lambda: self._fit_affix_popup(self.cb_suf))
        self._build_value_row(opts, "suf", row=5)
        self.lbl_suf_desc = ttk.Label(opts, text="", style="Hint.TLabel", wraplength=560,
                                      justify="left")
        self.lbl_suf_desc.grid(row=6, column=0, columnspan=4, sticky="w", pady=(1, 0))

        self.affix_hint = ttk.Label(opts, text="", style="Hint.TLabel", wraplength=560,
                                    justify="left")
        self.affix_hint.grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 0))
        # Round 6：数值框的红字提示（非整数 / 超范围），有内容时才占一行
        self.lbl_value_hint = ttk.Label(opts, text="", style="Bad.TLabel",
                                        wraplength=560, justify="left")
        self.lbl_value_hint.grid(row=8, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self.lbl_value_hint.grid_remove()

    def _fit_affix_popup(self, combo: ttk.Combobox) -> None:
        """弹层独立加宽：保留表单紧凑，同时完整展示长词缀说明。"""
        try:
            values = [str(v) for v in combo.cget("values")]
            longest = max((len(v) for v in values), default=60)
            width = max(60, min(120, longest + 2))
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            combo.nametowidget(f"{popdown}.f.l").configure(width=width)
        except (tk.TclError, AttributeError):
            pass

    def _build_value_row(self, parent, which: str, row: int):
        """一个词缀的数值行：范围 + 槽 0 + 槽 1（两值时）+ 容差。

        槽位来自 ``Affix.value_slots``：多数词缀 1 个（如「力量」），``King's``
        等 12 条 TOHIT_DAMP 词缀 2 个（「伤害」「命中」），固定效果 0 个。
        """
        is_pre = which == "pre"
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=4, sticky="w", padx=(52, 0), pady=(3, 0))
        lbl_range = ttk.Label(frame, text="范围：—", style="Hint.TLabel", width=30)
        lbl_range.grid(row=0, column=0, sticky="w")
        lbl0 = ttk.Label(frame, text="目标值")
        lbl0.grid(row=0, column=1, padx=(6, 2))
        var0 = tk.StringVar()
        ent0 = ttk.Entry(frame, textvariable=var0, width=6)
        ent0.grid(row=0, column=2)
        lbl1 = ttk.Label(frame, text="命中")
        var1 = tk.StringVar()
        ent1 = ttk.Entry(frame, textvariable=var1, width=6)
        lbl1.grid(row=0, column=3, padx=(8, 2))
        ent1.grid(row=0, column=4)
        lbl1.grid_remove()          # 单槽词缀时收起第二个输入框
        ent1.grid_remove()
        ttk.Label(frame, text="容差").grid(row=0, column=5, padx=(8, 2))
        tol_var = tk.StringVar(value="0")
        sp = ttk.Spinbox(frame, from_=0, to=50, textvariable=tol_var, width=3)
        sp.grid(row=0, column=6)
        self._val_rows[which] = {
            "frame": frame, "lbl_range": lbl_range, "lbl0": lbl0, "var0": var0,
            "ent0": ent0, "lbl1": lbl1, "var1": var1, "ent1": ent1,
            "sp": sp, "tol_var": tol_var, "sig": None, "fixed": False,
        }
        if is_pre:
            self._fpre = frame
            self.lbl_pre_range = lbl_range
            self.var_pre_value, self.ent_pre_value = var0, ent0
            self.var_pre_value2, self.ent_pre_value2 = var1, ent1
            self.lbl_pre_value, self.lbl_pre_value2 = lbl0, lbl1
            self.var_pre_tol, self.sp_pre_tol = tol_var, sp
        else:
            self._fsuf = frame
            self.lbl_suf_range = lbl_range
            self.var_suf_value, self.ent_suf_value = var0, ent0
            self.var_suf_value2, self.ent_suf_value2 = var1, ent1
            self.lbl_suf_value, self.lbl_suf_value2 = lbl0, lbl1
            self.var_suf_tol, self.sp_suf_tol = tol_var, sp
        return frame

    # ------------------------------------------------------------ 3. 法杖
    def _build_staff(self, left) -> None:
        box = ttk.LabelFrame(left, text="法杖")
        box.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        box.columnconfigure(1, weight=1)
        self.staff_box = box

        ttk.Label(box, text="形态").grid(row=0, column=0, sticky="e")
        self.var_staff_mode = tk.StringVar(value=STAFF_STAT)
        mf = ttk.Frame(box)
        mf.grid(row=0, column=1, columnspan=2, sticky="w", padx=(4, 0))
        self.rb_staff_stat = ttk.Radiobutton(
            mf, text="属性法杖（随机词缀）", value=STAFF_STAT,
            variable=self.var_staff_mode, command=self._on_staff_mode)
        self.rb_staff_stat.grid(row=0, column=0, padx=(0, 10))
        self.rb_staff_spell = ttk.Radiobutton(
            mf, text="法术法杖（带充能）", value=STAFF_SPELL,
            variable=self.var_staff_mode, command=self._on_staff_mode)
        self.rb_staff_spell.grid(row=0, column=1)

        ttk.Label(box, text="法术").grid(row=1, column=0, sticky="e", pady=(4, 0))
        self.var_spell = tk.StringVar(value=SPELL_RANDOM)
        self.cb_spell = ttk.Combobox(box, textvariable=self.var_spell, state="readonly",
                                     width=44, height=20)
        self.cb_spell.grid(row=1, column=1, columnspan=2, sticky="w", padx=(4, 0),
                           pady=(4, 0))
        self.cb_spell.bind("<<ComboboxSelected>>", lambda e: self._schedule_refresh())

        ttk.Label(box, text="充能目标").grid(row=2, column=0, sticky="e", pady=(3, 0))
        cf = ttk.Frame(box)
        cf.grid(row=2, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=(3, 0))
        self.var_charges = tk.StringVar()
        self.ent_charges = ttk.Entry(cf, textvariable=self.var_charges, width=8)
        self.ent_charges.grid(row=0, column=0)
        ttk.Label(cf, text="（留空 = 随机）",
                  style="Hint.TLabel").grid(row=0, column=1, padx=(6, 0))

        self.lbl_staff_hint = ttk.Label(box, text="", style="Hint.TLabel", wraplength=560,
                                        justify="left")
        self.lbl_staff_hint.grid(row=3, column=0, columnspan=3, sticky="w", pady=(3, 0))

    # ------------------------------------------------------------ 4. 基础属性
    def _build_base_stats(self, left) -> None:
        box = ttk.LabelFrame(left, text="基础属性")
        box.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="取值").grid(row=0, column=0, sticky="e")
        self.var_base_stats = tk.StringVar(value=BASE_RANDOM)
        self.cb_base_stats = ttk.Combobox(box, textvariable=self.var_base_stats,
                                          state="readonly", values=list(BASE_CHOICES),
                                          width=28)
        self.cb_base_stats.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.cb_base_stats.bind("<<ComboboxSelected>>",
                                lambda e: self._on_base_stats_change())
        self.lbl_base_stats_hint = ttk.Label(box, text="", style="Hint.TLabel",
                                             wraplength=560, justify="left")
        self.lbl_base_stats_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                                      pady=(3, 0))

    def _build_gen_bar(self) -> None:
        """左列底部固定栏：ilvl / 推荐 / seed / 页码 / 生成按钮 / 进度。

        920 高度下左列内容会超出窗口，这里把**高频参数和按钮**钉在底部，
        无论怎么滚动都能直接看到「用推荐 ilvl」和「生成到储物箱」。
        """
        bar = self._action_bar

        # row0：ilvl + 用推荐 ilvl + 推荐值
        row0 = ttk.Frame(bar)
        row0.grid(row=0, column=0, sticky="w")
        self._gen_row0 = row0
        ttk.Label(row0, text="物品等级").grid(row=0, column=0, sticky="e")
        self.var_ilvl = tk.StringVar(value="20")
        self.sp_ilvl = ttk.Spinbox(row0, from_=1, to=self._drop_cap(),
                                   textvariable=self.var_ilvl, width=5)
        self.sp_ilvl.grid(row=0, column=1, sticky="w", padx=(4, 8))
        self.sp_ilvl.bind("<<Increment>>", lambda e: self._schedule_refresh())
        self.sp_ilvl.bind("<<Decrement>>", lambda e: self._schedule_refresh())
        # Round 6：默认勾选 = 保证生成物可丢地上（ilvl<=34；31~34 走暗金怪路线，
        # 勾选框保持短文本，避免固定操作栏超出宽度）
        self.var_drop_safe = tk.BooleanVar(value=True)
        cap = self._drop_cap()
        self.chk_drop_safe = ttk.Checkbutton(row0, text="可丢地上",
                                             variable=self.var_drop_safe,
                                             command=self._on_drop_safe)
        self.chk_drop_safe.grid(row=0, column=2, padx=(0, 8))
        self.btn_recommend = ttk.Button(row0, text="使用推荐等级",
                                        command=self._on_recommend)
        self.btn_recommend.grid_remove()
        self.lbl_recommend = ttk.Label(row0, text="", style="Hint.TLabel", width=18,
                                       anchor="w")
        self.lbl_recommend.grid_remove()
        self.btn_recommend.state(["disabled"])

        # row1：数量 / 写入页码；种子默认收进高级选项
        row1 = ttk.Frame(bar)
        row1.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lbl_seed = ttk.Label(row1, text="种子")
        self.lbl_seed.grid(row=0, column=0, sticky="e")
        self.var_seed = tk.StringVar()
        self.ent_seed = ttk.Entry(row1, textvariable=self.var_seed, width=10)
        self.ent_seed.grid(row=0, column=1, sticky="w", padx=(4, 10))
        self._seed_visible = True
        self._toggle_seed()  # 默认隐藏
        ttk.Label(row1, text="数量").grid(row=0, column=2, sticky="e")
        self.var_count = tk.StringVar(value="1")
        ttk.Spinbox(row1, from_=1, to=10, textvariable=self.var_count, width=4).grid(
            row=0, column=3, sticky="w", padx=(4, 10))
        ttk.Label(row1, text="写入页码").grid(row=0, column=4, sticky="e")
        self.var_page = tk.StringVar(value="1")
        self.sp_page = ttk.Spinbox(row1, from_=1, to=100, width=5,
                                   textvariable=self.var_page)
        self.sp_page.grid(row=0, column=5, padx=(4, 6))

        # row2：生成按钮
        row2 = ttk.Frame(bar)
        row2.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.btn_stash = ttk.Button(row2, text="生成到储物箱", style="Primary.TButton",
                                    command=self.gen_to_stash)
        self.btn_stash.grid(row=0, column=0, padx=(0, 6))
        self.btn_bag = ttk.Button(row2, text="放入角色背包", command=self.gen_to_backpack)
        self.btn_bag.grid(row=0, column=1, padx=(0, 6))
        uic.more_button(row2, (
            ("使用推荐等级", self._on_recommend),
            ("显示或隐藏种子", self._toggle_seed),
            None,
            ("简易随机到背包", self.simple_to_backpack),
        )).grid(row=0, column=2)
        self.btn_cancel = ttk.Button(row2, text="取消", command=self._cancel)
        self.btn_cancel.grid_remove()
        self.btn_cancel.state(["disabled"])

        # row3：进度 / 提示（空时收起，把高度还给左列内容）
        self.progress = ttk.Label(bar, text="", style="Hint.TLabel", wraplength=600,
                                  justify="left")
        self.progress.grid(row=3, column=0, sticky="w", pady=(3, 0))
        self._set_progress("")
        self._on_drop_safe()        # 初始化 Spinbox 的上限（勾选=34）

    def _toggle_seed(self) -> None:
        self._seed_visible = not self._seed_visible
        if self._seed_visible:
            self.lbl_seed.grid()
            self.ent_seed.grid()
        else:
            self.lbl_seed.grid_remove()
            self.ent_seed.grid_remove()

    def _set_progress(self, text: str) -> None:
        """写进度文本；空文本时把这一行收起（固定栏更矮，左列能多看一截）。"""
        text = str(text or "")
        try:
            self.progress.configure(text=text)
            if text:
                self.progress.grid()
            else:
                self.progress.grid_remove()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 右侧预览
    def _build_preview(self, right_col: int) -> None:
        right = ttk.LabelFrame(self, text="预览与写入", padding=10)
        right.grid(row=1, column=right_col, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.preview = tk.Text(right, wrap="word", width=52, height=22, state="disabled",
                               relief="flat", background=uic.SURFACE, foreground=uic.TEXT,
                               padx=8, pady=8)
        psb = ttk.Scrollbar(right, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=psb.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        psb.grid(row=0, column=1, sticky="ns")
        self.valid_lbl = ttk.Label(right, text="", wraplength=520, justify="left")
        self.valid_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.target_lbl = ttk.Label(right, text="", style="Hint.TLabel", wraplength=520,
                                    justify="left")
        self.target_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 8))
        self._action_bar = ttk.Frame(right, padding=(0, 4))
        self._action_bar.grid(row=3, column=0, columnspan=2, sticky="ew")
        self._action_bar.columnconfigure(0, weight=1)

    # ------------------------------------------------------------ 防抖 / 追踪
    def _bind_preview_traces(self) -> None:
        """所有会影响预览的输入都 ``after(120, ...)`` 防抖刷新。"""
        for var in (self.var_ilvl, self.var_pre_value, self.var_pre_value2,
                    self.var_suf_value, self.var_suf_value2,
                    self.var_pre_tol, self.var_suf_tol, self.var_charges,
                    self.var_staff_mode, self.var_base_stats, self.var_pre,
                    self.var_suf, self.var_spell, self.var_rarity):
            try:
                var.trace_add("write", self._schedule_refresh)
            except Exception:  # noqa: BLE001 - 极老 tk 没有 trace_add
                pass
        # Round 5：勾选状态还要同步 Spinbox 范围 / 钳制 ilvl，不能只刷新预览
        try:
            self.var_drop_safe.trace_add("write", lambda *a: self._on_drop_safe())
        except Exception:  # noqa: BLE001
            pass

    def _schedule_refresh(self, *_args) -> None:
        if not getattr(self, "_ready", False):
            return
        self._suppress_refresh = False
        try:
            if self._refresh_job is not None:
                self.after_cancel(self._refresh_job)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._refresh_job = self.after(DEBOUNCE_MS, self._do_refresh)
        except tk.TclError:
            self._refresh_job = None

    def _do_refresh(self) -> None:
        self._refresh_job = None
        try:
            self.refresh_preview()
        except tk.TclError:
            pass

    # ============================================================ 数据
    def _load_items(self) -> None:
        if self.items:
            return
        if self._runner.busy():
            return
        self._set_progress("正在载入物品表…")
        self._runner.run(
            lambda put, cancel: self.gen.base_items(),
            on_done=self._items_loaded,
            on_error=lambda exc, tb: self._set_progress(f"载入物品表失败：{exc}"),
        )

    def _items_loaded(self, items) -> None:
        self.items = list(items or [])
        self._set_progress("")
        self._affix_cache.clear()
        self._bp_cache.clear()
        self._load_spells()
        self._refresh_item_list()
        if not self.gen.ready:
            self._suppress_refresh = True
            uic.set_text(self.preview, "生成器未就绪。可在「更多」中使用简易随机。")
            self.banner.configure(text="生成器未就绪", style="Bad.TLabel")
            self.banner.grid()
        else:
            self.banner.grid_remove()
            self._schedule_refresh()
        self.btn_stash.state(["!disabled"] if self.gen.ready else ["disabled"])
        self.btn_bag.state(["!disabled"] if self.gen.ready else ["disabled"])
        self._update_target_labels()

    def _refresh_item_list(self) -> None:
        cur = self._current_item()
        cur_idx = cur.idx if cur is not None else None
        cat = self.var_cat.get()
        kw = self.var_search.get().strip().lower()
        self._filtered = [
            b for b in self.items
            if b.generatable
            and (cat == "全部" or b.kind == cat)
            and (not kw or kw in b.cn.lower() or kw in b.name.lower() or kw in str(b.idx))
        ]
        self.listbox.delete(0, "end")
        for b in self._filtered:
            self.listbox.insert("end", b.cn or b.name)
        self.lbl_bases.configure(text=f"{len(self._filtered)} 种")
        if self._filtered:
            pos = 0
            if cur_idx is not None:
                for i, b in enumerate(self._filtered):
                    if b.idx == cur_idx:
                        pos = i
                        break
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(pos)
            self._on_item_select()
        else:
            self._refresh_affixes()
            self._update_staff_state()
            self._update_base_stats_hint()
            self._schedule_refresh()

    def _current_item(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        try:
            return self._filtered[sel[0]]
        except IndexError:
            return None

    def _on_item_select(self) -> None:
        if self._current_item() is None:
            return
        self._update_staff_state()
        self._refresh_affixes()
        self._update_base_stats_hint()
        self._schedule_refresh()

    # ------------------------------------------------------------ 底材预览缓存
    def _base_preview(self, base_idx: int) -> dict:
        """``gen.base_preview()`` 的缓存包装（纯本地，不生成物品）。"""
        key = int(base_idx)
        if key in self._bp_cache:
            return self._bp_cache[key]
        data: dict = {}
        try:
            data = dict(self.gen.base_preview(key) or {})
        except Exception as exc:  # noqa: BLE001 - 预览失败不能影响生成
            self._log(f"底材预览失败（idx={key}）：{exc}", "warn")
            data = {}
        if not data:
            b = self.gen.base_item_by_idx(key)
            data = {
                "base_idx": key,
                "base_cn": getattr(b, "cn", "") or "",
                "base_en": getattr(b, "name", "") or "",
                "kind": getattr(b, "kind", "") or "",
                "itype_name": str((getattr(b, "raw", {}) or {}).get("itype_name") or ""),
                "size": tuple(getattr(b, "size", (1, 1)) or (1, 1)),
                "min_dam": 0, "max_dam": 0, "min_ac": 0, "max_ac": 0,
                "dur_min": 0, "dur_max": 0, "max_dur": 0, "durability_raw": 0,
                "req_str": 0, "req_mag": 0, "req_dex": 0, "value": 0,
                "can_max_ac": False, "can_full_dur": False,
            }
        self._bp_cache[key] = data
        return data

    def _current_base_preview(self) -> dict:
        b = self._current_item()
        if b is None:
            return {}
        return self._base_preview(b.idx)

    # ------------------------------------------------------------ 词缀（全量）
    def _affix_rows(self, base_idx: int, kind: str) -> list[tuple[str, object]]:
        """该底材类型全部适用词缀（不按 ilvl 过滤），返回 [(label, Affix)]。"""
        key = (int(base_idx), kind)
        if key in self._affix_cache:
            return self._affix_cache[key]
        rows: list[tuple[str, object]] = []
        fn = getattr(self.gen, "all_affixes", None)
        raw = []
        if callable(fn):
            try:
                raw = list(fn(int(base_idx), kind) or [])
            except Exception as exc:  # noqa: BLE001 - 预览/列表失败不能崩界面
                self._log(f"读取词缀列表失败（{kind}）：{exc}", "warn")
                raw = []
        seen: set[str] = set()
        for aff in raw:
            try:
                label = aff.label
            except Exception:  # noqa: BLE001
                continue
            if not label or label in seen:
                continue
            seen.add(label)
            rows.append((label, aff))
        self._affix_cache[key] = rows
        return rows

    def _refresh_affixes(self) -> None:
        """重建前缀/后缀下拉：**全部词缀**，保留用户已选项（标签完全一致时）。"""
        b = self._current_item()
        prev_pre = self.var_pre.get()
        prev_suf = self.var_suf.get()
        self._pre_map = {RANDOM_LABEL: None}
        self._suf_map = {RANDOM_LABEL: None}
        if b is not None and self.gen.ready:
            for kind, mapping, cb, prev in (
                    ("prefix", self._pre_map, self.cb_pre, prev_pre),
                    ("suffix", self._suf_map, self.cb_suf, prev_suf)):
                for label, aff in self._affix_rows(b.idx, kind):
                    mapping[label] = aff
                cb["values"] = list(mapping)
                cb.set(prev if prev in mapping else RANDOM_LABEL)
            self.affix_hint.configure(text="")
        else:
            self.cb_pre["values"] = [RANDOM_LABEL]
            self.cb_suf["values"] = [RANDOM_LABEL]
            self.cb_pre.set(RANDOM_LABEL)
            self.cb_suf.set(RANDOM_LABEL)
            if b is None:
                self.affix_hint.configure(text="先选底材。")
            elif not self.gen.ready:
                self.affix_hint.configure(text="词缀列表未就绪。")
            else:
                self.affix_hint.configure(text="该底材没有词缀。")
        self._on_affix_pick("pre")
        self._on_affix_pick("suf")

    def _affix(self, kind: str):
        """当前选中的词缀对象（未选 = None）。"""
        mapping = self._pre_map if kind == "pre" else self._suf_map
        var = self.var_pre if kind == "pre" else self.var_suf
        return mapping.get(var.get())

    @staticmethod
    def _affix_index(aff):
        if aff is None:
            return None
        try:
            return int(aff.index)
        except Exception:  # noqa: BLE001
            try:
                return aff.en or None
            except Exception:  # noqa: BLE001
                return None

    def _on_affix_pick(self, which: str) -> None:
        is_pre = which == "pre"
        mapping = self._pre_map if is_pre else self._suf_map
        var = self.var_pre if is_pre else self.var_suf
        row = self._val_rows.get(which) or {}
        lbl_range = row.get("lbl_range") or (self.lbl_pre_range if is_pre
                                            else self.lbl_suf_range)
        lbl_desc = self.lbl_pre_desc if is_pre else self.lbl_suf_desc
        sp = self.sp_pre_tol if is_pre else self.sp_suf_tol
        row_frame = row.get("frame") or (self._fpre if is_pre else self._fsuf)
        aff = mapping.get(var.get())
        magic = self.var_rarity.get() == "magic"
        if aff is None or not magic:
            lbl_range.configure(text="范围：—")
            lbl_desc.configure(text="")
            lbl_desc.grid_remove()
            row_frame.grid_remove()     # 未选词缀时不占高度
            self._render_value_slots(which, None)
            sp.state(["!disabled"] if magic else ["disabled"])
            self._schedule_refresh()
            return
        row_frame.grid()
        numeric = aff.numeric
        slots = self._value_slots(aff)
        rng = aff.range_tuple()
        band = self._affix_band_text(aff)
        if len(slots) > 1:
            # 两段数值：每段的范围写在各自的输入框标题里，这里只放摘要（避免截断）
            lbl_range.configure(text=f"两段数值 {band}")
        elif numeric and rng:
            lbl_range.configure(text=f"范围：{rng[0]:+d} ~ {rng[1]:+d} {band}")
        elif rng:
            lbl_range.configure(text=f"范围：{rng[0]:+d} ~ {rng[1]:+d}（固定）{band}")
        else:
            lbl_range.configure(text=f"范围：固定效果 {band}")
        desc = aff.desc
        if not numeric:
            desc += "\n固定效果：数值不可指定（攻速 / 充能 / 吸血 / 固定伤害之类）"
        # 说明只占最多 2 行，避免把第 5 节挤到窗口外
        desc_lines = [ln for ln in str(desc).splitlines() if ln.strip()]
        if len(desc_lines) > 2:
            desc_lines = desc_lines[:2]
            desc_lines[-1] = desc_lines[-1].rstrip("；;，,") + "…"
        lbl_desc.configure(text="\n".join(desc_lines))
        lbl_desc.grid()
        self._render_value_slots(which, aff)
        sp.state(["!disabled"] if (numeric and self.gen.supports_values) else ["disabled"])
        if numeric and not self.gen.supports_values:
            self.affix_hint.configure(text="当前版本不支持指定数值，只能随机。")
        self._schedule_refresh()

    # ------------------------------------------------------------ 数值槽（Round 6）
    @staticmethod
    def _value_slots(aff) -> list[dict]:
        """``Affix.value_slots`` 的安全包装（旧适配层 / 异常时退回空列表）。"""
        if aff is None:
            return []
        try:
            return [dict(s) for s in (aff.value_slots or [])]
        except Exception:  # noqa: BLE001 - 取不到就按「没有可填数值」处理
            return []

    @staticmethod
    def _slot_range_text(lo: int, hi: int) -> str:
        """槽位范围文本：``151~175`` / ``-50~-25`` / ``+6``。"""
        try:
            lo, hi = int(lo), int(hi)
        except (TypeError, ValueError):
            return "?"
        if lo == hi:
            return f"{lo:+d}" if lo < 0 else str(lo)
        return f"{lo}~{hi}"

    @classmethod
    def _slot_title(cls, spec: dict, index: int = 0) -> str:
        """输入框标题：``伤害 151~175`` / ``命中 76~100``。"""
        label = str(spec.get("label") or ("伤害" if index == 0 else "命中") or "数值")
        rng = spec.get("range")
        if not rng:
            return label
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (TypeError, ValueError, IndexError):
            return label
        return f"{label} {cls._slot_range_text(lo, hi)}"

    def _render_value_slots(self, which: str, aff) -> None:
        """按 ``Affix.value_slots`` 重建数值框：1 个 / 2 个 / 固定效果。

        槽位数量不变（例如换成另一条单槽词缀）时保留用户已填的文本，
        只有槽位结构真的变了才清空，避免打字打一半被抹掉。
        """
        row = self._val_rows.get(which)
        if not row:
            return
        magic = self.var_rarity.get() == "magic"
        slots = self._value_slots(aff) if (aff is not None and magic) else []
        numeric = bool(aff is not None and getattr(aff, "numeric", False))
        ent_ok = bool(slots and numeric and self.gen.supports_values)
        row["ent0"].state(["!disabled"] if ent_ok else ["disabled"])
        row["ent1"].state(["!disabled"] if (len(slots) > 1 and ent_ok) else ["disabled"])
        # 两段数值时范围摘要只写「两段数值〔区间〕」，宽度自适应；单槽保持固定宽度
        try:
            row["lbl_range"].configure(width=0 if len(slots) > 1 else 30)
        except tk.TclError:
            pass
        if len(slots) > 1:
            row["lbl1"].configure(text=self._slot_title(slots[1], 1))
            row["lbl1"].grid()
            row["ent1"].grid()
        else:
            row["lbl1"].grid_remove()
            row["ent1"].grid_remove()
        if aff is None or not magic:
            row["sig"] = None
            row["fixed"] = False
            row["lbl0"].configure(text="目标值")
            if str(row["var0"].get()):
                row["var0"].set("")
            if str(row["var1"].get()):
                row["var1"].set("")
            return
        if not slots:
            # 固定效果：框里写「固定效果」并且禁用（不参与参数解析）
            row["fixed"] = True
            if row["sig"] != ("fixed",):
                row["sig"] = ("fixed",)
                row["var0"].set("固定效果")
                row["var1"].set("")
            row["lbl0"].configure(text="数值")
            return
        row["fixed"] = False
        sig = tuple((str(s.get("key")), str(s.get("label")), tuple(s.get("range") or (0, 0)))
                    for s in slots)
        if row["sig"] != sig:
            row["sig"] = sig
            row["var0"].set("")
            row["var1"].set("")
        row["lbl0"].configure(text=self._slot_title(slots[0], 0))

    def _value_texts(self, which: str) -> tuple[str, str]:
        """当前词缀两个数值框的文本（固定效果 / 未选词缀时返回空串）。"""
        row = self._val_rows.get(which)
        if not row or row.get("fixed"):
            return "", ""
        aff = self._affix(which)
        if aff is None or self.var_rarity.get() != "magic":
            return "", ""
        slots = self._value_slots(aff)
        if not slots:
            return "", ""
        text0 = str(row["var0"].get() or "")
        text1 = str(row["var1"].get() or "") if len(slots) > 1 else ""
        return text0, text1

    def _set_value_hint(self, text: str) -> None:
        """数值输入的红字提示；空文本时把这一行收起。"""
        lbl = getattr(self, "lbl_value_hint", None)
        if lbl is None:
            return
        text = str(text or "")
        try:
            if text:
                lbl.configure(text=text)
                lbl.grid()
            else:
                lbl.configure(text="")
                lbl.grid_remove()
        except tk.TclError:
            pass

    def _value_arg(self, text: str) -> int | None:
        """输入框文本 -> int（空 / 非法 = None）；非法时写一条红字提示。"""
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            return int(raw)      # 允许前导 +（int("+151") == 151）
        except ValueError:
            self._set_value_hint(f"「{raw}」不是整数：数值框只填整数（例如 151），"
                                 "留空 = 该槽随机。")
            return None

    @staticmethod
    def _pack_values(values: list) -> object:
        """槽值 -> 适配层接受的形状：单槽 int，两槽 ``[v0, v1]``，全空 None。"""
        vals = list(values or [])
        if not vals:
            return None
        if any(v is not None for v in vals[1:]):
            return vals
        return vals[0]

    def _on_rarity(self) -> None:
        rarity = self.var_rarity.get()
        magic = rarity == "magic"
        state = ["!disabled"] if magic else ["disabled"]
        for w in (self.cb_pre, self.cb_suf):
            w.state(state)
        self._on_affix_pick("pre")
        self._on_affix_pick("suf")
        self._schedule_refresh()

    # ------------------------------------------------------------ 法杖
    def _is_staff(self) -> bool:
        bp = self._current_base_preview()
        return str(bp.get("itype_name") or "") == "Staff"

    def _load_spells(self) -> None:
        """``gen.spells()`` -> 下拉 label 映射（缺失时留空，不让界面崩）。"""
        rows: list[dict] = []
        fn = getattr(self.gen, "spells", None)
        if callable(fn):
            try:
                rows = [dict(r) for r in (fn() or []) if isinstance(r, dict)]
            except Exception as exc:  # noqa: BLE001
                self._log(f"读取法杖法术列表失败：{exc}", "warn")
                rows = []
        core_map = self._core_spell_meta()
        mapping: dict[str, dict | None] = {SPELL_RANDOM: None}
        for row in rows:
            try:
                sid = int(row.get("id", -1))
            except (TypeError, ValueError):
                continue
            if sid < 0:
                continue
            row = dict(row)
            extra = core_map.get(sid) or {}
            if not row.get("min_ilvl"):
                row["min_ilvl"] = extra.get("min_ilvl")
            if not row.get("staff_lvl"):
                row["staff_lvl"] = extra.get("staff_lvl")
            mapping[self._spell_label(row)] = row
        self._spell_map = mapping
        self._spells_loaded = True
        try:
            self.cb_spell["values"] = list(mapping)
            if self.var_spell.get() not in mapping:
                self.var_spell.set(SPELL_RANDOM)
        except Exception:  # noqa: BLE001
            pass

    def _core_spell_meta(self) -> dict[int, dict]:
        """core ``staff_spells()`` 里的 ``min_ilvl`` / ``staff_lvl``（适配层可能没透传）。"""
        mod = getattr(self.gen, "mod", None)
        fn = getattr(mod, "staff_spells", None) if mod is not None else None
        out: dict[int, dict] = {}
        if not callable(fn):
            return out
        try:
            for row in fn() or []:
                if isinstance(row, dict):
                    out[int(row.get("id", row.get("index", -1)))] = row
        except Exception:  # noqa: BLE001
            return {}
        return out

    @staticmethod
    def _spell_label(row: dict) -> str:
        name = str(row.get("name") or "")
        cn = str(row.get("cn") or "") or name
        head = f"{cn}（{name}）" if cn and name and cn != name else (cn or name or "?")
        lo = int(row.get("staff_min") or 0)
        hi = int(row.get("staff_max") or 0)
        label = f"{head} 充能 {lo}~{hi}"
        try:
            mi = int(row.get("min_ilvl") or 0)
        except (TypeError, ValueError):
            mi = 0
        if mi > 1:
            label += f"〔ilvl≥{mi}〕"
        return label

    @staticmethod
    def _spell_min_ilvl(row) -> int | None:
        if not isinstance(row, dict):
            return None
        try:
            mi = int(row.get("min_ilvl") or 0)
        except (TypeError, ValueError):
            mi = 0
        if mi > 0:
            return mi
        try:
            lvl = int(row.get("staff_lvl") or 0)
        except (TypeError, ValueError):
            lvl = 0
        if lvl > 0:
            return max(1, min(50, 2 * lvl))
        return None

    def _update_staff_state(self) -> None:
        """法杖分区只在 Staff 底材显示；非杖底材清空法杖参数。"""
        is_staff = self._is_staff()
        if is_staff:
            self.staff_box.grid()
            hint = ("法术法杖只有前缀、没有后缀；随机法术也要求 seed 带法术/充能。")
            self.lbl_staff_hint.configure(text=hint)
            self._on_staff_mode()
        else:
            self.staff_box.grid_remove()
            if self.var_staff_mode.get() != STAFF_STAT:
                self.var_staff_mode.set(STAFF_STAT)
            if self.var_spell.get() != SPELL_RANDOM:
                self.var_spell.set(SPELL_RANDOM)
            if self.var_charges.get():
                self.var_charges.set("")
            self.cb_spell.state(["disabled"])
            self.ent_charges.state(["disabled"])

    def _on_staff_mode(self) -> None:
        spell_mode = self.var_staff_mode.get() == STAFF_SPELL and self._is_staff()
        state = ["!disabled"] if spell_mode else ["disabled"]
        self.cb_spell.state(state)
        self.ent_charges.state(state)
        if self._is_staff():
            if spell_mode:
                self.lbl_staff_hint.configure(
                    text="法术法杖只有前缀、没有后缀；随机法术也要求 seed 带法术/充能。")
            else:
                self.lbl_staff_hint.configure(
                    text="属性法杖按法杖词缀表随机生成（默认，不搜法术）。")
        self._schedule_refresh()

    def _staff_params(self, strict: bool = True) -> dict:
        """当前法杖选项 -> ``staff_spell/staff_charges/allow_staff_spells``。

        ``strict=True`` 时参数不合法直接抛 ``ValueError``（生成入口用），
        否则把原因放进 ``error``（实时预览用）。
        """
        out = {"is_staff": False, "mode": STAFF_STAT, "spell": None, "spell_row": None,
               "charges": None, "allow": False, "require": False, "error": ""}
        bp = self._current_base_preview()
        if str(bp.get("itype_name") or "") != "Staff":
            return out
        out["is_staff"] = True
        mode = STAFF_SPELL if self.var_staff_mode.get() == STAFF_SPELL else STAFF_STAT
        out["mode"] = mode
        if mode != STAFF_SPELL:
            return out
        out["allow"] = True
        # Round 4（A1）：即便法术「随机」，也要求 seed 必须带法术/充能，
        # 否则 core 会接受 spell=0 的属性法杖，和用户选的「法术法杖」不符。
        out["require"] = True
        row = self._spell_map.get(self.var_spell.get())
        if isinstance(row, dict):
            out["spell_row"] = row
            try:
                out["spell"] = int(row.get("id"))
            except (TypeError, ValueError):
                out["spell"] = None
        raw = self.var_charges.get().strip()
        if raw:
            try:
                val = int(raw)
            except ValueError:
                out["error"] = "充能目标必须是整数（留空 = 随机）。"
                if strict:
                    raise ValueError(out["error"])
                return out
            if val < 0:
                out["error"] = "充能目标必须 ≥ 0。"
                if strict:
                    raise ValueError(out["error"])
                return out
            if not isinstance(row, dict):
                out["error"] = "要指定充能目标，请先选一个法术（或把充能留空 = 随机）。"
                if strict:
                    raise ValueError(out["error"])
                return out
            lo = int(row.get("staff_min") or 0)
            hi = int(row.get("staff_max") or 0)
            if not (lo <= val <= hi):
                name = str(row.get("cn") or row.get("name") or "该法术")
                out["error"] = f"充能目标 {val} 超出「{name}」的范围 {lo}~{hi}。"
                if strict:
                    raise ValueError(out["error"])
                return out
            out["charges"] = val
        return out

    # ------------------------------------------------------------ 基础属性
    def _base_stats_flags(self) -> dict:
        choice = self.var_base_stats.get()
        if choice == BASE_FULL:
            return {"max_ac": True, "full_dur": True}
        if choice == BASE_AC:
            return {"max_ac": True, "full_dur": False}
        if choice == BASE_DUR:
            return {"max_ac": False, "full_dur": True}
        return {"max_ac": False, "full_dur": False}

    def _on_base_stats_change(self) -> None:
        self._update_base_stats_hint()
        self._schedule_refresh()

    def _update_base_stats_hint(self) -> None:
        bp = self._current_base_preview()
        if not bp:
            self.lbl_base_stats_hint.configure(text="先选底材。")
            return
        max_ac = int(bp.get("max_ac") or 0)
        max_dur = int(bp.get("max_dur") or 0)
        parts: list[str] = []
        if max_ac > 0:
            parts.append(f"护甲 {bp.get('min_ac')}~{max_ac}（满 {max_ac}）")
        else:
            parts.append("无护甲")
        if max_dur > 0:
            parts.append(f"耐久 {bp.get('dur_min')}~{bp.get('dur_max')}/最大 {max_dur}"
                         f"（满 {max_dur}）")
        else:
            parts.append("无耐久")
        self.lbl_base_stats_hint.configure(
            text="；".join(parts))

    # ------------------------------------------------------------ 目标标签
    def _update_target_labels(self) -> None:
        try:
            stash = self.app.tab_stash.stash
        except Exception:  # noqa: BLE001
            stash = None
        stash_s = Path(stash.path).name if stash is not None else "未打开"
        try:
            char = self.app.tab_char.hero
        except Exception:  # noqa: BLE001
            char = None
        char_s = char.name if char is not None else "未选角色"
        self.target_lbl.configure(text=f"储物箱：{stash_s}    背包：{char_s}")

    # ============================================================ 实时预览
    def refresh_preview(self, force: bool = False) -> str:
        """重算并写入右侧预览（**不生成物品、不搜索 seed**）。

        公开接口，供测试/截图直接调用；返回值同 ``preview_text()``。
        """
        self._refresh_job = None
        if not self._ready:
            return ""
        if self._suppress_refresh and not force:
            return uic.get_text(self.preview)
        try:
            text, color = self._compose_preview()
        except Exception as exc:  # noqa: BLE001 - 预览绝不能崩界面
            self._log(f"实时预览失败：{type(exc).__name__}: {exc}", "warn")
            text, color = f"实时预览失败：{type(exc).__name__}: {exc}", "#c62828"
        uic.set_text(self.preview, text, color=color)
        self._update_recommend_button()
        return text

    def preview_text(self) -> str:
        """预览区纯文本（会先强制刷新一次）。"""
        self.refresh_preview(force=True)
        return uic.get_text(self.preview)

    # ------------------------------------------------------------ 推荐 ilvl
    def _ilvl_plan(self) -> dict:
        """前缀/后缀合法 ilvl 区间的交集（不看当前 ilvl）。

        ``no_overlap`` 有两种来源：区间真的不重叠；或某条词缀 ``min_level > 50``
        （Godly 等 6 条词缀，界面可选 ilvl 只有 1~50，永远出不了）。后者在
        ``bad_reason`` 里写明是哪一条、需要多少 ilvl。
        """
        entries: list[dict] = []
        cap = self._max_ilvl()
        if self.var_rarity.get() == "magic":
            for kind in ("pre", "suf"):
                aff = self._affix(kind)
                if aff is None:
                    continue
                try:
                    lo, hi = int(aff.band[0]), int(aff.band[1])
                except Exception:  # noqa: BLE001
                    continue
                try:
                    level = int(aff.min_level)
                except Exception:  # noqa: BLE001
                    level = lo
                bad = lo > hi or level > cap
                entries.append({"kind": kind, "aff": aff, "lo": lo, "hi": hi,
                                "level": level, "bad": bad})
        plan = {"entries": entries, "lo": None, "hi": None, "no_overlap": False,
                "bad_reason": "", "span_text": ""}
        bad = [e for e in entries if e["bad"]]
        if bad:
            e = bad[0]
            kind_cn = "前缀" if e["kind"] == "pre" else "后缀"
            need = max(e["level"], e["lo"])
            plan["no_overlap"] = True
            plan["bad_reason"] = (f"{kind_cn}「{e['aff'].cn}」需要 ilvl {need}"
                                  f"（超出可选 1~{cap}，无法生成），请换一条词缀")
            return plan
        if not entries:
            return plan
        lo = max(e["lo"] for e in entries)
        hi = min(e["hi"] for e in entries)
        plan["lo"], plan["hi"] = lo, hi
        if lo > hi:
            plan["no_overlap"] = True
            plan["bad_reason"] = (f"前缀/后缀没有共同的合法 ilvl（{lo}~{hi} 不重叠），"
                                  "请换一条词缀")
            return plan
        if len(entries) > 1:
            plan["span_text"] = f"前缀/后缀共同合法区间：ilvl {lo}~{hi}"
        else:
            label = "前缀" if entries[0]["kind"] == "pre" else "后缀"
            plan["span_text"] = f"{label}合法区间：ilvl {lo}~{hi}"
        return plan

    def recommend_ilvl(self) -> int | None:
        """推荐 ilvl：当前值合法就保持当前值，否则收紧到交集边界。

        * 当前 ilvl ∈ [有效下限, 上限] -> 推荐当前 ilvl（按钮显示「当前已是」）；
        * 当前 < 下限 -> 推荐下限；当前 > 上限 -> 推荐上限；
        * 词缀区间为空 / 某条词缀超出当前 ilvl 上限 / 无词缀且无法术 -> None。
        法杖法术的 ``min_ilvl`` 参与有效下限；上限 = 勾选「可丢地上」时的 34，否则 50。
        """
        if not self.gen.ready or self._current_item() is None:
            return None
        plan = self._ilvl_plan()
        if plan.get("no_overlap"):
            return None
        cap = self._max_ilvl()
        staff = self._staff_params(strict=False)
        spell_min = self._spell_min_ilvl(staff.get("spell_row"))
        lo, hi = plan.get("lo"), plan.get("hi")
        if lo is None:
            if not spell_min:
                return None
            lo = hi = max(1, min(cap, int(spell_min)))
        lo, hi = int(lo), int(hi)
        if spell_min:
            lo = max(lo, max(1, min(cap, int(spell_min))))
            if lo > hi:
                return None
        cur = self._ilvl_or_none()
        if cur is None or cur < lo:
            return max(1, min(cap, lo))
        if cur > hi:
            return max(1, min(cap, hi))
        return cur

    def _update_recommend_button(self) -> None:
        rec = self.recommend_ilvl()
        cur = self._ilvl_or_none()
        if rec is None:
            self.btn_recommend.state(["disabled"])
            self.lbl_recommend.configure(text="推荐 —")
            return
        if cur == rec:
            self.btn_recommend.state(["disabled"])
            self.lbl_recommend.configure(text=f"推荐 {rec}（已是）")
        else:
            self.btn_recommend.state(["!disabled"])
            self.lbl_recommend.configure(text=f"推荐 {rec}")

    def _on_recommend(self) -> None:
        rec = self.recommend_ilvl()
        if rec is None:
            uic.warn("没有推荐 ilvl",
                     "先选一条前缀/后缀（或法杖法术）；词缀合法区间为空、"
                     "或两条词缀没有共同的合法 ilvl 时，需要换一条词缀。")
            return
        self.var_ilvl.set(str(rec))
        self.refresh_preview(force=True)

    # ------------------------------------------------------------ 预览正文
    def _compose_preview(self) -> tuple[str, str | None]:
        b = self._current_item()
        if b is None:
            self.valid_lbl.configure(text="", style="Hint.TLabel")
            return ("请先在左侧选择一件底材。\n\n"
                    "词缀和属性设置会实时反映在右侧预览中。", None)
        bp = self._base_preview(b.idx)
        magic = self.var_rarity.get() == "magic"
        pre = self._affix("pre") if magic else None
        suf = self._affix("suf") if magic else None
        staff = self._staff_params(strict=False)
        spell_row = staff.get("spell_row") if staff.get("is_staff") else None
        ilvl = self._ilvl_or_none()

        base_cn = str(bp.get("base_cn") or b.cn)
        itype = str(bp.get("itype_name") or "")
        size = bp.get("size") or b.size or (1, 1)
        try:
            sw, sh = int(size[0]), int(size[1])
        except Exception:  # noqa: BLE001
            sw, sh = 1, 1
        quality = RARITY_CN.get(self.var_rarity.get(), self.var_rarity.get())

        if staff.get("is_staff") and staff.get("mode") == STAFF_SPELL:
            spell_cn = ""
            if isinstance(spell_row, dict):
                spell_cn = str(spell_row.get("cn") or spell_row.get("name") or "")
            name = d1zh.item_full_name_cn(base_cn, pre.cn if pre else "", "", spell_cn)
        else:
            name = d1zh.item_full_name_cn(base_cn, pre.cn if pre else "",
                                          suf.cn if suf else "")

        lines: list[str] = [f"{name}（{quality}）", ""]
        kind = str(bp.get("kind") or b.kind)
        itype_cn = ITYPE_CN.get(itype, itype)
        lines.append(f"底材：{base_cn}    {kind}/{itype_cn}  {sw}x{sh}")
        lines.append("")

        # ---- 基础属性 ----
        lines.append("基础属性")
        min_ac = int(bp.get("min_ac") or 0)
        max_ac = int(bp.get("max_ac") or 0)
        if max_ac > 0:
            lines.append(f"  护甲：{min_ac} ~ {max_ac}     满值 {max_ac}")
        min_dam = int(bp.get("min_dam") or 0)
        max_dam = int(bp.get("max_dam") or 0)
        if max_dam > 0 or min_dam > 0:
            lines.append(f"  伤害：{min_dam} ~ {max_dam}")
        max_dur = int(bp.get("max_dur") or 0)
        if max_dur > 0:
            lines.append(f"  耐久：{bp.get('dur_min')} ~ {bp.get('dur_max')} / 最大 {max_dur}"
                         f"   满值 {max_dur}")
        req = []
        for key, label in (("req_str", "力量"), ("req_dex", "敏捷"), ("req_mag", "魔法")):
            val = int(bp.get(key) or 0)
            if val:
                req.append(f"{label} {val}")
        lines.append("  需求：" + ("、".join(req) if req else "无"))
        lines.append(f"  基础价值：{int(bp.get('value') or 0):,}")
        lines.append("")

        # ---- 词缀 ----
        lines.append("词缀")
        if not magic:
            lines.append("  （普通物品没有词缀）")
        else:
            lines.append("  " + self._affix_line("前缀", pre))
            if staff.get("is_staff") and staff.get("mode") == STAFF_SPELL:
                if suf is None:
                    lines.append("  后缀：（法术法杖没有后缀，游戏规则）")
                else:
                    lines.append("  " + self._affix_line("后缀", suf)
                                 + "  ← 法术法杖不能用后缀")
            else:
                lines.append("  " + self._affix_line("后缀", suf))
        lines.append("")

        # ---- 法杖 ----
        staff_spell_min = self._spell_min_ilvl(spell_row)
        if staff.get("is_staff"):
            lines.append("法杖")
            lines.append(f"  形态：{STAFF_MODE_CN.get(staff.get('mode'), '属性法杖')}")
            if staff.get("mode") == STAFF_SPELL:
                if isinstance(spell_row, dict):
                    target = staff.get("charges")
                    target_s = f"{target}" if target is not None else "随机"
                    lines.append(f"  法术：{self._spell_label(spell_row)}"
                                 f"    目标充能 {target_s}")
                else:
                    lines.append(f"  法术：{SPELL_RANDOM}（由游戏随机滚，充能也随机）")
                if staff_spell_min and (ilvl is None or ilvl < staff_spell_min):
                    lines.append(f"该法术需要 ilvl ≥ {staff_spell_min}")
                if suf is not None:
                    lines.append("法术法杖不能带后缀，请清空后缀")
            lines.append("")

        # ---- 合法性 ----
        plan = self._ilvl_plan()
        rec = self.recommend_ilvl()
        # 词缀 min_level 超过当前可选上限时：core 还会建议「把 ilvl 提到 40」，
        # 和界面 1~34/1~50 矛盾，这里过滤掉那类建议/句子，只保留我们自己的说明。
        cap_text = f"超出可选 1~{self._max_ilvl()}"
        cap_bad = bool(plan.get("no_overlap")
                       and cap_text in str(plan.get("bad_reason") or ""))
        chk, err_text = self._preview_check(b, ilvl, magic, pre, suf, staff)
        conflict = self._base_stats_conflict(pre, suf)
        if err_text:
            lines.append(err_text)
        elif chk is None:
            lines.append("生成器未就绪")
        elif not chk.ok:
            lines.append(chk.title)
            for part in str(chk.message).splitlines():
                part = part.strip()
                if cap_bad:
                    part = re.sub(
                        r"[；;]?\s*请把\s*ilvl\s*提到\s*\d+\s*(（或更高）|\(或更高\))?",
                        "", part).strip()
                if part:
                    lines.append(f"    {part}")
            if not cap_bad:
                for suggest in (chk.suggestions or [])[:3]:
                    lines.append(f"    · {suggest}")
        if conflict:
            lines.append(conflict)

        if plan.get("no_overlap"):
            lines.append(str(plan.get('bad_reason')))
        elif (rec is None and staff_spell_min and plan.get("hi") is not None
              and int(staff_spell_min) > int(plan["hi"])):
            lines.append("该法术的 ilvl 超出词缀合法区间，请换词缀或法术。")
        elif rec is not None:
            span = plan.get("span_text") or ""
            extra = f"（{span}）" if span else ""
            if ilvl == rec:
                lines.append(f"推荐 ilvl {rec}{extra}（当前已符合）")
            else:
                lines.append(f"推荐 ilvl {rec}{extra}")
        lines.append("")

        # ---- 满值提示 ----
        flags = self._base_stats_flags()
        if flags["max_ac"] or flags["full_dur"]:
            lines.append("满值只对生成到储物箱有效。")
            if flags["max_ac"] and not bp.get("can_max_ac"):
                lines.append("该底材没有护甲。")
            if flags["full_dur"] and not bp.get("can_full_dur"):
                lines.append("该底材没有耐久。")
            if conflict:
                lines.append(conflict)
            lines.append("")
        elif not self.gen.ready:
            lines.append("")

        # ---- Round 6：可丢地上（IsDungeonItemValid: ilvl<=34，31~34 走暗金怪路线）----
        drop_safe = self._drop_safe_on()
        cap = self._drop_cap()
        bonus = max(1, cap - 3)
        if ilvl is None:
            drop_text = "否（未填 ilvl）"
        elif (drop_safe and ilvl <= cap) or ilvl <= 30:
            drop_text = "是"
        else:
            drop_text = "否"
        lines.append(f"可丢地上：{drop_text}")
        drop_danger = (not drop_safe and ilvl is not None and ilvl > 30)
        if drop_danger:
            lines.append("只能放储物箱：丢地上会提示「无效的数据包」并消失。")
        lines.append("")

        ok_all = (not err_text and not conflict
                  and (chk is None or chk.ok))
        if drop_danger:
            self.valid_lbl.configure(text="只能放储物箱", style="Bad.TLabel")
        elif ok_all:
            self.valid_lbl.configure(
                text="可以生成", style="Ok.TLabel")
        else:
            title = err_text or (conflict if conflict else
                                 (chk.title if chk is not None else "生成器未就绪"))
            self.valid_lbl.configure(text=title, style="Bad.TLabel")
        return ("\n".join(lines).rstrip() + "\n",
                "#c62828" if drop_danger else None)

    def _affix_band_text(self, aff) -> str:
        """词缀合法 ilvl 区间文本（Round 4 A2 / Round 6 动态上限）。

        少数 ``min_level`` 高于当前上限（勾选「可丢地上」时上限 34，否则 50）的
        词缀会给出空区间；界面必须写「需要 ilvl N（超出可选 1~34，无法生成）」，
        不能显示成「〔ilvl 34~34〕」误导用户。
        """
        if aff is None:
            return ""
        cap = self._max_ilvl()
        try:
            lo, hi = int(aff.band[0]), int(aff.band[1])
        except Exception:  # noqa: BLE001
            return ""
        try:
            level = int(aff.min_level)
        except Exception:  # noqa: BLE001
            level = lo
        if lo > hi or level > cap:
            need = max(level, lo)
            return f"需要 ilvl {need}（超出可选 1~{cap}，无法生成）"
        return f"〔ilvl {lo}~{hi}〕"

    def _target_values_text(self, which: str, aff) -> str:
        """实时预览：把用户填的目标数值显示成「伤害 +151%，命中 +93%」。"""
        if aff is None:
            return ""
        slots = self._value_slots(aff)
        if not slots:
            return ""
        texts = self._value_texts(which)
        vals: list = []
        for i, _spec in enumerate(slots):
            text = str(texts[i] if i < len(texts) else "").strip()
            vals.append(self._value_arg(text) if text else None)
        if not any(v is not None for v in vals):
            return ""
        try:
            info = d1zh.power_value(aff.raw, vals[0] if vals else None,
                                    tohit=(vals[1] if len(vals) > 1 else None))
            body = str(info.get("text") or "")
        except Exception:  # noqa: BLE001
            body = ""
        return f"（目标：{body}）" if body else ""

    def _affix_line(self, label: str, aff) -> str:
        if aff is None:
            return f"{label}：（未选，生成时随机）"
        band = self._affix_band_text(aff)
        effect = ""
        try:
            effect = aff.effect
        except Exception:  # noqa: BLE001
            effect = ""
        body = str(aff.cn)
        try:
            two_slots = len(aff.value_slots) > 1
        except Exception:  # noqa: BLE001
            two_slots = False
        # 两条属性时 range_text 已分开写「伤害 …，命中 …」，不再重复效果名
        if effect and not two_slots:
            body += f" {effect}"
        target = self._target_values_text("pre" if label == "前缀" else "suf", aff)
        return f"{label}：{body} {aff.range_text} {target} {band}".replace("  ", " ").rstrip()

    def _base_stats_conflict(self, pre, suf) -> str:
        flags = self._base_stats_flags()
        if not flags["max_ac"]:
            return ""
        for label, aff in (("前缀", pre), ("后缀", suf)):
            if aff is None:
                continue
            try:
                sets_ac = bool(aff.sets_ac)
            except Exception:  # noqa: BLE001
                sets_ac = False
            if sets_ac:
                return (f"{label}「{aff.cn}」直接设定护甲值（IPL_SETAC），"
                        "不能与「护甲满值」同时使用；请取消护甲满值或换一条词缀。")
        return ""

    def _preview_values(self) -> tuple[object, object, int, str]:
        """数值框 -> ``(prefix_value, suffix_value, 容差, 错误文本)``。

        单槽给 int；两槽给 ``[v0, v1]``（空槽用 ``None``）；两个都空 = None。
        槽位范围取自 ``Affix.value_slots``，超范围时给出带槽位名（「命中」）的错误。
        """
        tol = 0
        errs: list[str] = []
        for tol_var in (self.var_pre_tol, self.var_suf_tol):
            raw = str(tol_var.get() or "").strip()
            if not raw:
                continue
            try:
                tol = max(tol, int(raw))
            except ValueError:
                errs.append("容差必须是整数")
        self._set_value_hint("")
        out: dict[str, object] = {"pre": None, "suf": None}
        for which, kind_cn in (("pre", "前缀"), ("suf", "后缀")):
            aff = self._affix(which)
            if aff is None:
                continue
            slots = self._value_slots(aff)
            texts = self._value_texts(which)
            if not slots or not any(str(t or "").strip() for t in texts):
                continue
            values: list = []
            for i, spec in enumerate(slots):
                text = str(texts[i] if i < len(texts) else "").strip()
                label = str(spec.get("label") or "数值")
                value = self._value_arg(text)
                if text and value is None:
                    errs.append(f"{kind_cn}「{label}」必须是整数"
                                f"（范围 {self._slot_range_text(*spec.get('range'))}）")
                    values.append(None)
                    continue
                rng = spec.get("range")
                if value is not None and rng and not (
                        int(rng[0]) - tol <= value <= int(rng[1]) + tol):
                    if len(slots) > 1:
                        errs.append(f"{kind_cn}「{label}」{value:+d} 超出「{aff.cn}」的范围 "
                                    f"{int(rng[0]):+d} ~ {int(rng[1]):+d}")
                    else:
                        errs.append(f"{kind_cn}目标值 {value:+d} 超出「{aff.cn}」的数值范围 "
                                    f"{int(rng[0]):+d} ~ {int(rng[1]):+d}")
                values.append(value)
            out[which] = self._pack_values(values)
        return out["pre"], out["suf"], tol, "；".join(errs)

    def _preview_check(self, b, ilvl, magic, pre, suf, staff):
        """返回 (ComboCheck|None, 错误文本)。优先用 core 规则预检，不搜 seed。"""
        if ilvl is None:
            return None, f"ilvl（物品等级）必须填 1~{self._max_ilvl()} 的整数。"
        if staff.get("error"):
            return None, staff["error"]
        if not self.gen.ready:
            return None, ""
        pre_val, suf_val, tol, verr = self._preview_values()
        if verr:
            return None, verr
        if magic and staff.get("mode") == STAFF_SPELL and suf is not None:
            return None, ("法术法杖只有前缀，没有后缀（游戏规则）：请把后缀改回"
                          "「（随机合法）」，或把形态改回「属性法杖」。")
        flags = self._base_stats_flags()
        kwargs = {
            "base": b, "ilvl": int(ilvl),
            "rarity": self.var_rarity.get(),
            "prefix": self._affix_index(pre) if magic else None,
            "suffix": self._affix_index(suf) if magic else None,
            "prefix_value": pre_val, "suffix_value": suf_val,
            "value_tolerance": int(tol or 0),
            "max_ac": flags["max_ac"], "full_durability": flags["full_dur"],
            "staff_spell": staff.get("spell"), "staff_charges": staff.get("charges"),
            "allow_staff_spells": staff.get("allow"),
            "require_staff_spell": staff.get("require"),
            "droppable": self._drop_safe_on(),
        }
        try:
            return self._call_check(**kwargs), ""
        except Exception as exc:  # noqa: BLE001
            return None, f"预检异常：{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------ 调用适配层（签名兼容）
    def _call_check(self, **kwargs):
        """``gen.check_combination``：只传它认识的参数（Round 4 参数可能尚未落地）。"""
        fn = self.gen.check_combination
        params = self._signature_params(fn)
        if params:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        return fn(**kwargs)

    def _call_generate(self, **kwargs):
        """``gen.generate``：同样只传签名里有的关键字。"""
        fn = self.gen.generate
        params = self._signature_params(fn)
        if params:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        return fn(**kwargs)

    @staticmethod
    def _signature_params(fn) -> dict:
        try:
            return dict(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            return {}

    # ------------------------------------------------------------ 参数
    def _drop_safe_on(self) -> bool:
        """「保证可丢地上」是否勾选（默认 True，缺控件时按安全侧）。"""
        var = getattr(self, "var_drop_safe", None)
        try:
            return bool(var.get()) if var is not None else True
        except Exception:  # noqa: BLE001
            return True

    def _drop_cap(self) -> int:
        """可丢地上的最高 ilvl：优先 core ``MAX_DROP_ILVL``（34），否则回退常量。"""
        try:
            cap = int(getattr(self.gen, "max_drop_ilvl", MAX_DROP_ILVL) or MAX_DROP_ILVL)
        except (TypeError, ValueError):
            cap = MAX_DROP_ILVL
        return cap if cap > 0 else MAX_DROP_ILVL

    def _max_ilvl(self) -> int:
        """当前允许的最高 ilvl：勾选「可丢地上」= 34（core 上限），取消 = 50。"""
        return self._drop_cap() if self._drop_safe_on() else 50

    def _on_drop_safe(self) -> None:
        """勾选/取消「可丢地上」：同步 ilvl Spinbox 范围并钳制当前值。"""
        if not hasattr(self, "sp_ilvl"):
            return
        cap = self._drop_cap()
        try:
            self.sp_ilvl.configure(from_=1, to=cap if self._drop_safe_on() else 50)
        except tk.TclError:
            pass
        if self._drop_safe_on():
            raw = self.var_ilvl.get().strip()
            try:
                current = int(raw)
            except ValueError:
                current = None
            if current is not None and current > cap:
                self.var_ilvl.set(str(cap))
        self._schedule_refresh()

    def set_ilvl(self, value: int) -> None:
        self.var_ilvl.set(str(max(1, min(self._max_ilvl(), int(value)))))
        self._schedule_refresh()

    def _ilvl_or_none(self) -> int | None:
        raw = self.var_ilvl.get().strip()
        if not raw:
            return None
        try:
            ilvl = int(raw)
        except ValueError:
            return None
        return ilvl if 1 <= ilvl <= self._max_ilvl() else None

    def _seed_arg(self) -> int | None:
        raw = self.var_seed.get().strip()
        if not raw:
            return None
        try:
            seed = int(raw, 0)
        except ValueError:
            raise ValueError("seed 必须是整数（可留空）。")
        if not (0 <= seed <= 0xFFFFFFFF):
            raise ValueError("seed 范围 0~4294967295。")
        return seed

    def _count_arg(self) -> int:
        try:
            count = int(self.var_count.get())
        except ValueError:
            raise ValueError("数量必须是整数。")
        if not (1 <= count <= 10):
            raise ValueError("一次最多生成 10 件。")
        return count

    def _affix_arg(self, mapping: dict, label: str):
        raw = mapping.get(label)
        if raw is None:
            return None
        # 传 index：itemgen 用 index 定位词缀，避免同名不同档的歧义
        return self._affix_index(raw)

    def _value_and_tol(self, which: str) -> tuple[object, int]:
        """生成用：返回 ``(数值参数, 容差)``（单槽 int / 两槽 list），不合法抛 ``ValueError``。"""
        is_pre = which == "pre"
        aff = self._pre_map.get(self.var_pre.get()) if is_pre else \
            self._suf_map.get(self.var_suf.get())
        tol_text = (self.var_pre_tol if is_pre else self.var_suf_tol).get().strip() or "0"
        try:
            tol = int(tol_text)
        except ValueError:
            raise ValueError("容差必须是整数（默认 0）。")
        if tol < 0 or tol > 50:
            raise ValueError("容差范围 0~50。")
        text0, text1 = self._value_texts(which)
        if not str(text0 or "").strip() and not str(text1 or "").strip():
            return None, tol
        if aff is None:
            raise ValueError("请先选择词缀，再填目标值。")
        slots = self._value_slots(aff)
        if not slots:
            raise ValueError(f"「{aff.cn}」是固定效果词缀，不能指定数值（请清空目标值）。")
        if not self.gen.supports_values:
            raise ValueError("当前生成器版本还不支持指定数值，请清空「目标值」。")
        values: list = []
        for i, spec in enumerate(slots):
            text = str(text0 if i == 0 else text1 if i == 1 else "").strip()
            label = str(spec.get("label") or "数值")
            if not text:
                values.append(None)
                continue
            try:
                value = int(text)       # 允许前导 +
            except ValueError:
                raise ValueError(f"「{label}」必须是整数"
                                 f"（范围 {self._slot_range_text(*spec.get('range'))}）。")
            rng = spec.get("range")
            if rng and not (int(rng[0]) - tol <= value <= int(rng[1]) + tol):
                raise ValueError(f"「{label}」{value:+d} 超出「{aff.cn}」的范围 "
                                 f"{int(rng[0]):+d} ~ {int(rng[1]):+d}。")
            values.append(value)
        return self._pack_values(values), tol

    def _page_arg(self) -> int | None:
        """「写入页码」→ 1-based 页号；留空 = None（自动找空位/新建页）。"""
        raw = self.var_page.get().strip()
        if not raw:
            return None
        try:
            page = int(raw)
        except ValueError:
            raise ValueError("「写入页码」必须是整数（留空 = 自动找空位/新建页）。")
        if not (1 <= page <= 100):
            raise ValueError("「写入页码」范围 1~100（1 = 储物箱第 1 页）。")
        return page

    def _safe_page(self) -> int | None:
        """``_page_arg`` 的不抛版本（只给 ``_params_dict`` 填字段用）。"""
        raw = self.var_page.get().strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    # ------------------------------------------------------------ 参数装配（Round 4）
    def _params_dict(self) -> dict:
        """生成参数（dict 版，Round 4 合同 3.3）。不合法抛 ``ValueError``。"""
        b = self._current_item()
        reason = self.gen.check_base(b)
        if reason:
            raise ValueError(reason)
        ilvl = self._ilvl_or_none()
        if ilvl is None:
            raise ValueError(f"ilvl（物品等级）必须是 1~{self._max_ilvl()} 的整数。")
        rarity = self.var_rarity.get()
        if rarity not in RARITY_KEYS:
            raise ValueError("稀有度只能是普通或魔法；暗金请用「暗金图鉴」页。")
        seed = self._seed_arg()
        count = self._count_arg()
        magic = rarity == "magic"
        prefix = suffix = None
        pre_value = suf_value = None
        tolerance = 0
        if magic:
            prefix = self._affix_arg(self._pre_map, self.var_pre.get())
            suffix = self._affix_arg(self._suf_map, self.var_suf.get())
            pre_value, pre_tol = self._value_and_tol("pre")
            suf_value, suf_tol = self._value_and_tol("suf")
            tolerance = max(pre_tol, suf_tol)
        staff = self._staff_params(strict=True)
        if magic and staff.get("mode") == STAFF_SPELL and suffix is not None:
            raise ValueError("法术法杖只有前缀，没有后缀（游戏规则）："
                             "请把后缀改回「（随机合法）」，或把形态改回「属性法杖」。")
        flags = self._base_stats_flags()
        if flags["max_ac"]:
            for aff in (self._affix("pre"), self._affix("suf")):
                if aff is not None and getattr(aff, "sets_ac", False):
                    raise ValueError(
                        f"「{aff.cn}」直接设定护甲值（IPL_SETAC），不能与「护甲满值」同时使用；"
                        "请把「基础属性」改回随机，或换一条词缀。")
        return {
            "base": b,
            "ilvl": ilvl,
            "rarity": rarity,
            "seed": seed,
            "prefix": prefix,
            "suffix": suffix,
            "count": count,
            "pre_value": pre_value,
            "suf_value": suf_value,
            "tolerance": tolerance,
            "max_ac": flags["max_ac"],
            "full_durability": flags["full_dur"],
            "staff_spell": staff.get("spell"),
            "staff_charges": staff.get("charges"),
            "allow_staff_spells": staff.get("allow"),
            "require_staff_spell": staff.get("require"),
            "droppable": self._drop_safe_on(),
            "page": self._safe_page(),
        }

    def _params(self):
        """旧接口（``work/build/make_shots.py`` 仍按下标使用）：保持 tuple 形状。"""
        p = self._params_dict()
        return (p["base"], p["ilvl"], p["rarity"], p["seed"], p["prefix"],
                p["suffix"], p["count"], p["pre_value"], p["suf_value"],
                p["tolerance"])

    def params_for_test(self) -> dict:
        """测试用：返回 ``_params_dict()``；不弹窗、不生成。

        参数不合法时返回 ``{"error": "原因"}``（而不是抛异常）。
        """
        try:
            return self._params_dict()
        except ValueError as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------ 预检
    def _preflight(self, params: dict) -> bool:
        """生成前预检；不合法时红字 + 弹窗，返回 False。"""
        kwargs = {
            "base": params["base"], "ilvl": params["ilvl"], "rarity": params["rarity"],
            "prefix": params["prefix"], "suffix": params["suffix"],
            "prefix_value": params["pre_value"], "suffix_value": params["suf_value"],
            "value_tolerance": params["tolerance"],
            "max_ac": params["max_ac"], "full_durability": params["full_durability"],
            "staff_spell": params["staff_spell"],
            "staff_charges": params["staff_charges"],
            "allow_staff_spells": params["allow_staff_spells"],
            "require_staff_spell": params["require_staff_spell"],
            "droppable": params.get("droppable", False),
        }
        try:
            chk = self._call_check(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 预检本身不该阻断生成
            self._log(f"组合预检跳过（{type(exc).__name__}: {exc}）", "warn")
            return True
        if chk.ok:
            if chk.message:
                self._log(f"组合预检通过：{chk.message}", "ok")
            return True
        self._show_check(chk)
        return False

    def _show_check(self, chk) -> None:
        """把 ComboCheck 显示到预览区（红字）+ 弹窗（原因 + 建议）。"""
        self._suppress_refresh = True
        text = "【无法生成】\n\n" + chk.text()
        uic.set_text(self.preview, text, color="#c62828")
        self.valid_lbl.configure(text=chk.title, style="Bad.TLabel")
        self._set_progress("组合不合法，未生成任何物品。")
        self._log(f"生成被拒绝：{chk.title}｜{chk.message}", "err")
        uic.detail_warning(
            "无法生成该物品", chk.title, chk.message, chk.suggestions, chk.detail,
            parent=self, modal=True)

    # ------------------------------------------------------------ 预览（真实结果）
    def _affix_for_result(self, which: str, name_cn: str):
        """按中文名找当前底材列表里的词缀对象（显示实际数值用）。"""
        mapping = self._pre_map if which == "pre" else self._suf_map
        for aff in mapping.values():
            if aff is None:
                continue
            try:
                if str(aff.cn) == str(name_cn):
                    return aff
            except Exception:  # noqa: BLE001
                continue
        return None

    def _actual_values_text(self, which: str, name_cn: str, values) -> str:
        """``GenResult.prefix_values`` -> 「（伤害 +151%，命中 +93%）」。"""
        vals = [v for v in (values or [])]
        if not vals:
            return ""
        aff = self._affix_for_result(which, name_cn)
        if aff is None:
            return ""
        tohit = vals[1] if len(vals) > 1 else None
        try:
            info = d1zh.power_value(aff.raw, vals[0], tohit=tohit)
            body = str(info.get("text") or "")
        except Exception:  # noqa: BLE001
            body = ""
        return f"（{body}）" if body else ""

    def _mark_preview(self, needle: str, color: str, tag: str) -> None:
        """给预览区里出现 ``needle`` 的片段上色（``uic.set_text`` 之后调用）。"""
        if not needle:
            return
        try:
            widget = self.preview
            widget.configure(state="normal")
            widget.tag_configure(tag, foreground=color)
            start = "1.0"
            while True:
                pos = widget.search(needle, start, stopindex="end")
                if not pos:
                    break
                end = f"{pos}+{len(needle)}c"
                widget.tag_add(tag, pos, end)
                start = end
            widget.configure(state="disabled")
        except tk.TclError:
            pass

    def _show_results(self, results) -> None:
        self._last_results = list(results)
        self._suppress_refresh = True
        if not results:
            return
        res = results[0]
        lines = ["【实际生成结果】", ""]
        if res.name_cn:
            lines.append(f"中文名：{res.name_cn}")
        lines.append(f"英文名：{res.name or '?'}")
        if res.prefix:
            lines.append(f"前缀：{res.prefix}"
                         + self._actual_values_text("pre", res.prefix,
                                                    getattr(res, "prefix_values", None)))
        if res.suffix:
            lines.append(f"后缀：{res.suffix}"
                         + self._actual_values_text("suf", res.suffix,
                                                    getattr(res, "suffix_values", None)))
        if getattr(res, "staff_spell", None):
            try:
                spell_cn = d1zh.spell_name(int(res.staff_spell))
            except Exception:  # noqa: BLE001
                spell_cn = ""
            charges = getattr(res, "charges", None)
            max_charges = getattr(res, "max_charges", None)
            extra = ""
            if charges is not None:
                extra = f" 充能 {charges}"
                if max_charges is not None:
                    extra += f"/{max_charges}"
            lines.append(f"法术：{spell_cn or res.staff_spell}{extra}")
        note = str(getattr(res, "base_stats_note", "") or "")
        if note:
            lines.append(f"基础属性：{note}")
        # ---- Round 6：掉落说明（可丢地上 = 绿字；只能放储物箱 = 红字警告）----
        drop_note = str(getattr(res, "drop_note", "") or "")
        droppable = bool(getattr(res, "droppable", False))
        if drop_note:
            lines.append(f"掉落：{drop_note}")
        if drop_note and not droppable:
            lines.append("该物品只能放储物箱。")
        lines.append("")
        body = res.text or ""
        if drop_note:
            # res.text（适配层）里也有同一句「掉落：…」，这里已经单独写在头部，
            # 去掉重复行，避免结果区出现两次一模一样的掉落说明。
            dup = f"掉落：{drop_note}"
            if dup in body:
                body = "\n".join(ln for ln in body.splitlines() if ln.strip() != dup)
        text = "\n".join(lines) + body
        if len(results) > 1:
            text = f"（本次共 {len(results)} 件，下面显示第 1 件）\n\n" + text
        if res.record:
            text += f"\n\n记录长度：{len(res.record)} 字节"
        uic.set_text(self.preview, text)
        if drop_note:
            self._mark_preview(f"掉落：{drop_note}",
                               "#1a7f37" if droppable else "#c62828", "dropnote")
        if drop_note and not droppable:
            self._mark_preview("该物品只能放储物箱", "#c62828", "dropwarn")
        bad = [v for r in results for v in (r.validation or [])]
        if bad:
            self.valid_lbl.configure(text="校验未通过：\n" + "\n".join(bad[:8]),
                                     style="Bad.TLabel")
        elif drop_note and not droppable:
            self.valid_lbl.configure(text="校验通过，但只能放储物箱", style="Bad.TLabel")
        else:
            self.valid_lbl.configure(text="校验通过",
                                     style="Ok.TLabel")

    # ------------------------------------------------------------ 生成入口
    def gen_to_stash(self) -> None:
        if not self.gen.ready:
            uic.warn("生成器未就绪", "请使用「更多 → 简易随机到背包」。")
            return
        try:
            params = self._params_dict()
            page = self._page_arg()
        except ValueError as exc:
            uic.warn("参数有误", str(exc))
            return
        params["page"] = page
        if self.app.tab_stash.stash is None:
            uic.warn("提示", "请先在「储物箱」页打开 stash.sv。")
            return
        if not self._preflight(params):
            return
        self._start_generate("stash", params, page=page)

    def gen_to_backpack(self) -> None:
        if not self.gen.ready:
            uic.warn("生成器未就绪", "请使用「更多 → 简易随机到背包」。")
            return
        try:
            params = self._params_dict()
        except ValueError as exc:
            uic.warn("参数有误", str(exc))
            return
        if self.app.tab_char.hero is None:
            uic.warn("提示", "请先在「角色」页选择一个角色存档。")
            return
        if params["max_ac"] or params["full_durability"]:
            ok = uic.confirm(
                "满值物品写入背包会失效",
                "满值只在生成到储物箱时生效。仍然写入背包吗？")
            if not ok:
                return
        if not self._preflight(params):
            return
        self._start_generate("bag", params)

    def _start_generate(self, target, params: dict, page=None) -> None:
        if not self.items:
            self._items_loaded(self.gen.base_items())
        if self._runner.busy():
            uic.warn("提示", "上一次生成还没结束。")
            return
        if not self.app.require_game_closed():
            return
        self.btn_stash.state(["disabled"])
        self.btn_bag.state(["disabled"])
        self.btn_cancel.state(["!disabled"])
        self._set_progress("正在生成…")
        self._suppress_refresh = True

        b = params["base"]
        ilvl = params["ilvl"]
        rarity = params["rarity"]
        seed = params["seed"]
        prefix = params["prefix"]
        suffix = params["suffix"]
        count = params["count"]
        pre_value = params["pre_value"]
        suf_value = params["suf_value"]
        tolerance = params["tolerance"]
        spell_mode = bool(params["allow_staff_spells"])

        def progress_text(i: int) -> str:
            if spell_mode:
                return (f"正在搜索法术/充能（可能需要几十秒）… 第 {i + 1}/{count} 件")
            if pre_value is not None or suf_value is not None:
                return (f"正在生成第 {i + 1}/{count} 件…（指定数值需要搜索 seed，"
                        "通常 1~3 秒）")
            return f"正在生成第 {i + 1}/{count} 件…（指定词缀需要搜索 seed）"

        def work(put, cancel):
            results = []
            for i in range(count):
                if cancel.is_set():
                    put(f"已取消（完成 {i}/{count}）")
                    break
                put(progress_text(i))
                s = seed
                if s is None:
                    s = random.SystemRandom().getrandbits(32) or 1
                elif count > 1:
                    s = (seed + i) & 0xFFFFFFFF
                res = self._call_generate(
                    base_idx=b.idx, ilvl=ilvl, rarity=rarity, seed=s,
                    prefix=prefix, suffix=suffix,
                    prefix_value=pre_value, suffix_value=suf_value,
                    value_tolerance=tolerance,
                    max_ac=params["max_ac"],
                    full_durability=params["full_durability"],
                    staff_spell=params["staff_spell"],
                    staff_charges=params["staff_charges"],
                    allow_staff_spells=params["allow_staff_spells"],
                    require_staff_spell=params["require_staff_spell"],
                    droppable=params.get("droppable", False),
                    cancel=cancel, timeout=120)
                if cancel.is_set():
                    break
                results.append(res)
            return results

        def on_progress(msg):
            self._set_progress(str(msg))

        def on_tick(elapsed):
            text = str(self.progress.cget("text")).split("（已用时")[0]
            self._set_progress(f"{text}（已用时 {elapsed:.0f}s）")

        def on_done(results):
            self._finish_buttons()
            if not results:
                self._set_progress("没有生成任何物品。")
                return
            self._show_results(results)
            bad = [v for r in results for v in (r.validation or [])]
            if bad:
                chk = classify_validation(bad)
                self._suppress_refresh = True
                uic.set_text(self.preview, "【合法性校验未通过】\n\n" + chk.text(),
                             color="#c62828")
                self._set_progress("生成结果未通过校验，未写入任何物品。")
                self.valid_lbl.configure(text=chk.title, style="Bad.TLabel")
                self._log(f"生成结果校验失败：{bad}", "err")
                uic.detail_warning("这个组合不符合游戏规则", chk.title, chk.message,
                                   chk.suggestions, chk.detail, parent=self, modal=True)
                return
            self._set_progress(f"已生成 {len(results)} 件，正在写入…")
            if target == "stash":
                ui_genops.write_to_stash(self.app, results, page=page)
            else:
                ui_genops.write_to_backpack(self.app, results)
            self._set_progress(f"完成（{len(results)} 件）")

        def on_error(exc, tb):
            self._finish_buttons()
            chk = classify_error(exc)
            if chk.code == "search_budget" and (pre_value is not None
                                                or suf_value is not None):
                chk.suggestions = list(dict.fromkeys(
                    chk.suggestions + ["把「容差」调大一点 / 只指定一个数值（前缀或后缀）"]))
            self._set_progress("生成失败。")
            self._log(f"生成失败：{exc}", "err")
            self._suppress_refresh = True
            uic.set_text(self.preview, "【无法生成】\n\n" + chk.text(), color="#c62828")
            self.valid_lbl.configure(text=chk.title, style="Bad.TLabel")
            uic.detail_warning("无法生成该物品", chk.title, chk.message, chk.suggestions,
                               chk.detail, parent=self, modal=True)

        self._runner.run(work, on_done=on_done, on_error=on_error,
                         on_progress=on_progress, on_tick=on_tick)

    def _finish_buttons(self) -> None:
        self.btn_stash.state(["!disabled"] if self.gen.ready else ["disabled"])
        self.btn_bag.state(["!disabled"] if self.gen.ready else ["disabled"])
        self.btn_cancel.state(["disabled"])

    def _cancel(self) -> None:
        self._runner.request_cancel()
        self._set_progress("正在取消…（单件生成结束后生效）")

    def _log(self, msg: str, tag: str | None = None) -> None:
        try:
            self.app.log(msg, tag)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 简易随机
    def simple_to_backpack(self) -> None:
        b = self._current_item()
        if b is None:
            uic.warn("提示", "请先选择一个基础物品。")
            return
        reason = self.gen.check_base(b)
        if reason:
            uic.warn("这个底材不能生成", reason)
            return
        hero = self.app.tab_char.hero
        if hero is None:
            uic.warn("提示", "请先在「角色」页选择一个角色存档。")
            return
        if not self.app.require_game_closed():
            return
        try:
            ilvl = self._ilvl_or_none()
            count = int(self.var_count.get())
        except ValueError:
            uic.warn("参数有误", "ilvl/数量必须是整数。")
            return
        if ilvl is None:
            uic.warn("参数有误", f"ilvl 必须是 1~{self._max_ilvl()} 的整数。")
            return
        rarity = self.var_rarity.get()
        try:
            from d1hero import HeroEdit
            before = int(hero.pack.get("_pNumInv"))
            names = []
            for _ in range(max(1, min(10, count))):
                res = self.gen.simple_backpack_item(b.idx, ilvl, rarity)
                if add_to_backpack_safe(hero.sf, res.runtime_idx, res.seed,
                                        res.create_info) is None:
                    raise ValueError(f"背包已满，或底材「{b.label}」没有可复用的 368 字节模板；"
                                     "请改用「生成到储物箱」或换底材")
                names.append(f"{b.label} seed={res.seed}")
            msg = hero.save(clear_progress=False)
            after = int(HeroEdit(hero.path).pack.get("_pNumInv"))
        except Exception as exc:  # noqa: BLE001
            uic.error("写入背包失败", f"{exc}\n（背包可能已满）")
            return
        if after - before < len(names):
            uic.warn("部分物品可能没进存档",
                     f"背包物品数 {before} → {after}，预期 +{len(names)}。\n\n"
                     "该底材在背包里没有可复用的 368 字节模板，d1save 同步失败。\n"
                     "请改用「生成到储物箱」，或换一个底材（如短剑/长剑）再试。")
            self._set_progress(f"背包只写入了 {after - before} 件。")
            return
        self._suppress_refresh = True
        uic.set_text(self.preview, "简易随机\n\n"
                                   + "\n".join(names[:10]))
        self.valid_lbl.configure(text="简易随机不做词条校验。", style="Hint.TLabel")
        self._log(f"简易随机物品已写入背包：{'；'.join(names[:6])}（{msg}）", "ok")
        self.app.refresh_all(keep_char=True)
        uic.info("成功", f"已写入 {len(names)} 件物品到「{hero.name}」的背包（seed 随机）。")


def add_to_backpack_safe(savefile, runtime_idx, seed, create_info):
    from d1itemgen_adapter import add_to_backpack
    return add_to_backpack(savefile, runtime_idx, seed, create_info)
