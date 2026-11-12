"""「暗金图鉴」标签页（Round 2 / Round 3）。

* 左侧：89 件暗金（序号 + 中文名 + 底材 + 需求等级 + 价值），可按底材/等级/关键字过滤；
  **点任意表头排序**（再点一次反向），序号 = 当前显示顺序（排序后自动重编号）；
* 右侧：固定词条（中文说明）、底材/需求/价值，一键「生成到储物箱 / 角色背包」，
  可选写入页码（1-based，留空 = 自动）；
* 暗金没有前缀/后缀，生成时用 **普通底材（或该暗金的任务底材）+ unique_id**。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_common as uic
import ui_genops
from d1itemgen_adapter import (ItemGen, classify_error, classify_validation)

#: 列 -> (表头文字, 宽度, 对齐, 是否可伸展)
COLUMNS = (
    ("no", "序号", 52, "center", False),
    ("name", "暗金名称", 220, "w", True),
    ("base", "底材", 150, "w", False),
    ("lvl", "需等级", 70, "center", False),
    ("value", "价值", 90, "e", False),
)


#: 丢地上合法（IsDungeonItemValid）的最高 ilvl（Round 5）
MAX_DROP_ILVL = 34


class UniqueTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.gen = ItemGen()
        self.items = []
        self._filtered = []
        self._row_map: dict[str, object] = {}
        self._sort_col = ""          # "" = 暗金表原始顺序
        self._sort_rev = False
        self._runner = uic.TaskRunner(self)
        self._build()
        self.after(300, self._load)

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.banner = ttk.Label(self, text="正在载入暗金表…", style="Hint.TLabel",
                                wraplength=1080, justify="left")
        self.banner.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        flt = ttk.LabelFrame(left, text="暗金图鉴（词条固定，无需选词缀）", padding=6)
        flt.grid(row=0, column=0, sticky="ew")
        flt.columnconfigure(1, weight=1)
        ttk.Label(flt, text="搜索").grid(row=0, column=0, sticky="e")
        self.var_search = tk.StringVar()
        e = ttk.Entry(flt, textvariable=self.var_search, width=18)
        e.grid(row=0, column=1, sticky="w", padx=(4, 10))
        e.bind("<KeyRelease>", lambda ev: self._refresh_list())
        ttk.Label(flt, text="底材").grid(row=0, column=2, sticky="e")
        self.var_base = tk.StringVar(value="全部")
        self.cb_base = ttk.Combobox(flt, textvariable=self.var_base, state="readonly", width=14)
        self.cb_base.grid(row=0, column=3, sticky="w", padx=(4, 10))
        self.cb_base.bind("<<ComboboxSelected>>", lambda ev: self._refresh_list())
        ttk.Label(flt, text="最低等级 ≥").grid(row=0, column=4, sticky="e")
        self.var_minlvl = tk.StringVar(value="1")
        ttk.Spinbox(flt, from_=1, to=50, textvariable=self.var_minlvl, width=4,
                    command=self._refresh_list).grid(row=0, column=5, sticky="w", padx=(4, 0))

        self.lbl_count = ttk.Label(left, text="", style="Hint.TLabel")
        self.lbl_count.grid(row=1, column=0, sticky="w", pady=(4, 2))

        frame, self.tree = uic.make_tree(
            left, tuple(c[0] for c in COLUMNS), tuple(c[1] for c in COLUMNS),
            widths=tuple(c[2] for c in COLUMNS), height=18, stretch_col="name")
        frame.grid(row=2, column=0, sticky="nsew")
        for col, _text, _w, anchor, stretch in COLUMNS:
            self.tree.column(col, anchor=anchor, stretch=stretch)
            self.tree.heading(col, text=_text, command=lambda c=col: self.sort_by(c))
        self.tree.bind("<<TreeviewSelect>>", lambda ev: self._on_select())

        # ---------------- 右侧明细 ----------------
        right = ttk.LabelFrame(self, text="属性明细 / 生成", padding=8)
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.preview = tk.Text(right, wrap="word", width=52, height=18, state="disabled",
                               relief="flat", background="#fbfbfb")
        psb = ttk.Scrollbar(right, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=psb.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        psb.grid(row=0, column=1, sticky="ns")

        opts = ttk.Frame(right)
        opts.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._opts = opts
        ttk.Label(opts, text="物品等级 ilvl").grid(row=0, column=0, sticky="e")
        self.var_ilvl = tk.StringVar(value="20")
        self.sp_ilvl = ttk.Spinbox(opts, from_=1, to=MAX_DROP_ILVL,
                                   textvariable=self.var_ilvl, width=5)
        self.sp_ilvl.grid(row=0, column=1, sticky="w", padx=(4, 10))
        # Round 5/6：默认勾选 = 保证生成物可丢地上（ilvl<=34）
        self.var_drop_safe = tk.BooleanVar(value=True)
        self.chk_drop_safe = ttk.Checkbutton(
            opts, text="可丢地上（≤34）", variable=self.var_drop_safe,
            command=self._on_drop_safe)
        self.chk_drop_safe.grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Label(opts, text="数量").grid(row=0, column=3, sticky="e")
        self.var_count = tk.StringVar(value="1")
        ttk.Spinbox(opts, from_=1, to=10, textvariable=self.var_count, width=4).grid(
            row=0, column=4, sticky="w", padx=(4, 12))
        ttk.Label(opts, text="写入页码").grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.var_page = tk.StringVar(value="1")
        self.sp_page = ttk.Spinbox(opts, from_=1, to=100, width=5,
                                   textvariable=self.var_page)
        self.sp_page.grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(6, 0))
        ttk.Label(opts, text="1 = 第 1 页；留空 = 自动空位（只对「生成到储物箱」有效）",
                  style="Hint.TLabel").grid(row=1, column=2, columnspan=3, sticky="w",
                                            pady=(6, 0))
        self.lbl_drop_hint = ttk.Label(opts, text="", style="Hint.TLabel",
                                       wraplength=470, justify="left")
        self.lbl_drop_hint.grid(row=2, column=0, columnspan=5, sticky="w",
                                pady=(4, 0))
        self.var_drop_safe.trace_add("write", lambda *a: self._on_drop_safe())

        btns = ttk.Frame(right)
        btns.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.btn_stash = ttk.Button(btns, text="生成到储物箱", command=self.gen_to_stash)
        self.btn_stash.grid(row=0, column=0, padx=(0, 6))
        self.btn_bag = ttk.Button(btns, text="生成到角色背包", command=self.gen_to_backpack)
        self.btn_bag.grid(row=0, column=1, padx=(0, 6))
        self.btn_cancel = ttk.Button(btns, text="取消", command=self._cancel)
        self.btn_cancel.grid(row=0, column=2)
        self.btn_cancel.state(["disabled"])

        self.valid_lbl = ttk.Label(right, text="", wraplength=470, justify="left")
        self.valid_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.progress = ttk.Label(right, text="", style="Hint.TLabel", wraplength=470,
                                  justify="left")
        self.progress.grid(row=4, column=0, columnspan=2, sticky="w")

    # ------------------------------------------------------------ 数据
    def _load(self) -> None:
        if self.items:
            return
        if self._runner.busy():
            return
        self.progress.configure(text="正在载入暗金表…")
        self._runner.run(
            lambda put, cancel: self.gen.uniques(),
            on_done=self._loaded,
            on_error=lambda exc, tb: self.progress.configure(text=f"载入暗金表失败：{exc}"),
        )

    def _loaded(self, items) -> None:
        self.items = list(items or [])
        self.progress.configure(text="")
        bases = sorted({u.base_cn for u in self.items if u.base_cn})
        self.cb_base["values"] = ["全部"] + bases
        self.cb_base.set("全部")
        hidden = len(self.gen.uniques(include_unavailable=True)) - len(self.items)
        text = f"共 {len(self.items)} 件可用暗金（非 Hellfire）"
        if hidden:
            text += f"；另有 {hidden} 件（如 Bovine Plate）底材在此版本不可用，已隐藏"
        self.banner.configure(text=text + "。点左侧任意一件 → 右侧显示固定词条 → 一键生成。",
                              style="Hint.TLabel")
        self._refresh_list()

    def _refresh_list(self) -> None:
        # 记住当前选中的暗金（排序/过滤后要把选中项和右侧详情留住）
        cur = self._current()
        keep_uid = getattr(cur, "uid", None)
        kw = self.var_search.get().strip().lower()
        base = self.var_base.get()
        try:
            minlvl = int(self.var_minlvl.get() or 1)
        except ValueError:
            minlvl = 1
        items = [
            u for u in self.items
            if (base == "全部" or u.base_cn == base)
            and u.min_level >= minlvl
            and (not kw or kw in u.cn.lower() or kw in u.en.lower()
                 or kw in u.base_cn.lower() or kw in u.base_en.lower())
        ]
        if self._sort_col:
            items.sort(key=lambda u: self._sort_value(u, self._sort_col),
                       reverse=self._sort_rev)
        self._filtered = items
        self.tree.delete(*self.tree.get_children())
        self._row_map = {}
        for i, u in enumerate(items):
            # 序号 = 当前显示顺序：排序/过滤后重新编号 1..N
            row = self.tree.insert("", "end", values=(
                i + 1, u.cn, u.base_cn, u.min_level, f"{u.value:,}"))
            self._row_map[row] = u
        self._update_headings()
        total = f"显示 {len(items)} / {len(self.items)} 件"
        if self._sort_col:
            arrow = "▼ 降序" if self._sort_rev else "▲ 升序"
            name = dict((c[0], c[1]) for c in COLUMNS).get(self._sort_col, self._sort_col)
            total += f"（按「{name}」{arrow}；再次点表头反转）"
        else:
            total += "（点表头排序）"
        self.lbl_count.configure(text=total)
        target = None
        if keep_uid is not None:
            for row, u in self._row_map.items():
                if getattr(u, "uid", None) == keep_uid:
                    target = row
                    break
        if target is None and self._row_map:
            target = next(iter(self._row_map))
        if target is not None:
            self.tree.selection_set(target)
            self.tree.see(target)
        self._on_select()

    # ------------------------------------------------------ 排序（Round 3）
    def sort_by(self, col: str) -> None:
        """点表头排序：同一列再点一次反向；序号列 = 暗金表原始顺序。"""
        if col == self._sort_col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        self._refresh_list()

    def _update_headings(self) -> None:
        for col, text, _w, _anchor, _stretch in COLUMNS:
            mark = ""
            if col == self._sort_col:
                mark = " ▼" if self._sort_rev else " ▲"
            self.tree.heading(col, text=f"{text}{mark}")

    def _sort_value(self, u, col: str):
        if col == "no":
            try:
                return self.items.index(u)
            except ValueError:
                return 0
        if col == "name":
            return (u.cn or "", u.en or "")
        if col == "base":
            return (u.base_cn or "", u.cn or "")
        if col == "lvl":
            return int(u.min_level or 0)
        if col == "value":
            return int(u.value or 0)
        return 0

    def _current(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._row_map.get(sel[0])

    def _drop_safe_on(self) -> bool:
        """「保证可丢地上」是否勾选（默认 True）。"""
        var = getattr(self, "var_drop_safe", None)
        try:
            return bool(var.get()) if var is not None else True
        except Exception:  # noqa: BLE001
            return True

    def _max_ilvl(self) -> int:
        """当前允许的最高 ilvl：勾选=34，取消=50。"""
        return MAX_DROP_ILVL if self._drop_safe_on() else 50

    def _apply_drop_range(self) -> None:
        try:
            self.sp_ilvl.configure(from_=1, to=self._max_ilvl())
        except (AttributeError, tk.TclError):
            pass

    def _on_drop_safe(self) -> None:
        """勾选/取消丢地保护；min_level>34 的暗金自动取消勾选并提示。"""
        if not hasattr(self, "sp_ilvl"):
            return
        if getattr(self, "_selecting", False) or getattr(self, "_drop_sync", False):
            self._apply_drop_range()
            return
        self._drop_sync = True
        try:
            u = self._current()
            safe = bool(self.var_drop_safe.get())
            if safe and u is not None and int(u.min_level) > MAX_DROP_ILVL:
                # 勾选状态下不允许生成 >34：自动取消勾选
                self.var_drop_safe.set(False)
                safe = False
                self.lbl_drop_hint.configure(
                    text=(f"该暗金需要 ilvl {int(u.min_level)}（>{MAX_DROP_ILVL}），"
                          "只能放储物箱，不能丢地上"),
                    style="Bad.TLabel")
            elif safe:
                self.lbl_drop_hint.configure(
                    text=f"勾选：ilvl 1~{MAX_DROP_ILVL}，生成物可丢地上/捡起",
                    style="Hint.TLabel")
            else:
                self.lbl_drop_hint.configure(
                    text=(f"未勾选：ilvl 1~50；ilvl>{MAX_DROP_ILVL} 只能放储物箱，"
                          "丢地上会提示「无效的数据包」并消失"),
                    style="Bad.TLabel")
            self._apply_drop_range()
        finally:
            self._drop_sync = False
        if self._current() is not None:
            self._on_select()

    def _on_select(self) -> None:
        self._selecting = True
        try:
            self._render_selection()
        finally:
            self._selecting = False

    def _render_selection(self) -> None:
        u = self._current()
        if u is None:
            return
        # 勾选丢地保护时 ilvl 必须 <=34；min_level>34 的暗金自动取消勾选。
        if self._drop_safe_on() and int(u.min_level) > MAX_DROP_ILVL:
            self.var_drop_safe.set(False)
            self._apply_drop_range()
        # ilvl 自动抬到该暗金的最低需求，避免“物品等级不够”
        try:
            ilvl = int(self.var_ilvl.get() or 1)
        except ValueError:
            ilvl = 1
        if ilvl < u.min_level:
            self.var_ilvl.set(str(u.min_level))
            ilvl = u.min_level
        drop_ok = ilvl <= MAX_DROP_ILVL
        if not self._drop_safe_on():
            self._apply_drop_range()
        if u.min_level > MAX_DROP_ILVL:
            self.lbl_drop_hint.configure(
                text=(f"该暗金需要 ilvl {int(u.min_level)}（>{MAX_DROP_ILVL}），"
                      "只能放储物箱，不能丢地上"),
                style="Bad.TLabel")
        elif not self._drop_safe_on():
            self.lbl_drop_hint.configure(
                text=(f"未勾选：ilvl 1~50；ilvl>{MAX_DROP_ILVL} 只能放储物箱，"
                      "丢地上会提示「无效的数据包」并消失"),
                style="Bad.TLabel" if not drop_ok else "Hint.TLabel")
        else:
            self.lbl_drop_hint.configure(
                text=f"勾选：ilvl 1~{MAX_DROP_ILVL}，生成物可丢地上/捡起",
                style="Hint.TLabel" if drop_ok else "Bad.TLabel")
        dropable = "" if u.base_available else "（底材在 1.5.5 非 Hellfire 不可用）"
        base_note = "（任务暗金底材）" if u.base_unique_only else "（普通底材）"
        lines = [
            f"{u.cn}（{u.en}）",
            f"底材：{u.base_cn or '?'}（{u.base_en or '?'}，idx={u.base_idx}）{base_note}{dropable}",
            f"需求物品等级：{u.min_level}    价值：{u.value:,}",
            "",
            "固定词条：",
        ]
        rows = u.to_rows()
        if not rows:
            lines.append("  （无，或该暗金只有外观/底材效果）")
        for _, text in rows:
            lines.append(f"  · {text}")
        if u.note:
            lines.append("")
            lines.append(f"说明：{u.note}")
        lines.append("")
        if drop_ok:
            lines.append(f"可丢地上：是（ilvl {ilvl} ≤ {MAX_DROP_ILVL}）")
        else:
            lines.append(f"可丢地上：否（ilvl {ilvl} > {MAX_DROP_ILVL}，只能放储物箱）")
        if u.min_level > MAX_DROP_ILVL:
            lines.append(f"  ⚠ 该暗金需要 ilvl {int(u.min_level)}（>{MAX_DROP_ILVL}），"
                         "只能放储物箱，不能丢地上")
        elif not drop_ok:
            lines.append(f"  ⚠ ilvl>{MAX_DROP_ILVL} 只能放储物箱；"
                         "丢地上会提示「无效的数据包」并消失")
        lines.append("")
        lines.append("暗金不需要选前缀/后缀/数值：词条由 unique_id 决定，"
                     "程序会按游戏规则重建（d1itemgen.validate 校验）。")
        uic.set_text(self.preview, "\n".join(lines))
        if not drop_ok:
            self.valid_lbl.configure(
                text=(f"⚠ ilvl>{MAX_DROP_ILVL}：只能放储物箱，"
                      "丢地上会提示「无效的数据包」并消失"),
                style="Bad.TLabel")
        else:
            self.valid_lbl.configure(text="", style="Sub.TLabel")
        ok = u.base_available and self.gen.ready
        self.btn_stash.state(["!disabled"] if ok else ["disabled"])
        self.btn_bag.state(["!disabled"] if ok else ["disabled"])

    # ------------------------------------------------------------ 生成
    def gen_to_stash(self) -> None:
        self._start("stash")

    def gen_to_backpack(self) -> None:
        self._start("bag")

    def _params(self):
        u = self._current()
        if u is None:
            raise ValueError("请先在左侧列表里选择一件暗金。")
        if not self.gen.ready:
            raise ValueError("生成器未就绪（d1itemgen 缺失）。")
        if not u.base_available:
            raise ValueError(f"「{u.cn}」的底材在 1.5.5 非 Hellfire 中不可用，不能生成。")
        if u.base_idx < 0:
            raise ValueError(f"「{u.cn}」找不到对应底材，不能生成。")
        try:
            ilvl = int(self.var_ilvl.get())
        except ValueError:
            raise ValueError("ilvl 必须是整数。")
        if self._drop_safe_on() and int(u.min_level) > MAX_DROP_ILVL:
            raise ValueError(
                f"「{u.cn}」需要 ilvl {int(u.min_level)}（>{MAX_DROP_ILVL}），"
                "只能放储物箱，不能丢地上；请取消「保证可丢地上」后再生成。")
        max_ilvl = self._max_ilvl()
        if not (1 <= ilvl <= max_ilvl):
            raise ValueError(f"ilvl 范围 1~{max_ilvl}（"
                             + ("已勾选保证可丢地上" if self._drop_safe_on()
                                else "未勾选保证可丢地上")
                             + "）。")
        if ilvl < u.min_level:
            ilvl = u.min_level
            self.var_ilvl.set(str(ilvl))
        try:
            count = int(self.var_count.get())
        except ValueError:
            raise ValueError("数量必须是整数。")
        if not (1 <= count <= 10):
            raise ValueError("一次最多生成 10 件。")
        return u, ilvl, count

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

    def _start(self, target: str) -> None:
        try:
            u, ilvl, count = self._params()
            page = self._page_arg() if target == "stash" else None
        except ValueError as exc:
            uic.warn("参数有误", str(exc))
            return
        if target == "stash" and self.app.tab_stash.stash is None:
            uic.warn("提示", "请先在「储物箱」页打开 stash.sv。")
            return
        if target == "bag" and self.app.tab_char.hero is None:
            uic.warn("提示", "请先在「角色」页选择一个角色存档。")
            return
        if self._runner.busy():
            uic.warn("提示", "上一次生成还没结束。")
            return
        if not self.app.require_game_closed():
            return
        droppable = self._drop_safe_on()
        self.btn_stash.state(["disabled"])
        self.btn_bag.state(["disabled"])
        self.btn_cancel.state(["!disabled"])
        self.progress.configure(text=f"正在生成暗金「{u.cn}」…")

        def work(put, cancel):
            out = []
            for i in range(count):
                if cancel.is_set():
                    put(f"已取消（完成 {i}/{count}）")
                    break
                put(f"正在生成第 {i + 1}/{count} 件：{u.cn}…")
                res = self.gen.generate(u.base_idx, ilvl, rarity="unique", unique=u.uid,
                                        droppable=droppable,
                                        cancel=cancel, timeout=60)
                if cancel.is_set():
                    break
                out.append(res)
            return out

        def on_progress(msg):
            self.progress.configure(text=str(msg))

        def on_tick(elapsed):
            text = str(self.progress.cget("text")).split("（已用时")[0]
            self.progress.configure(text=f"{text}（已用时 {elapsed:.0f}s）")

        def on_done(results):
            self._finish()
            if not results:
                self.progress.configure(text="没有生成任何物品。")
                return
            res = results[0]
            bad = [v for r in results for v in (r.validation or [])]
            if bad:
                chk = classify_validation(bad)
                self.valid_lbl.configure(text=f"✘ {chk.title}", style="Bad.TLabel")
                uic.set_text(self.preview, "【合法性校验未通过】\n\n" + chk.text(),
                             color="#c62828")
                self.progress.configure(text="生成结果未通过校验，未写入。")
                self.app.log(f"暗金生成校验失败：{bad}", "err")
                uic.detail_warning("无法生成该暗金", chk.title, chk.message,
                                   chk.suggestions, chk.detail, parent=self, modal=True)
                return
            self.valid_lbl.configure(
                text=f"✔ 校验通过：{res.name_cn or u.cn}（Uid={u.uid}，seed={res.seed}）",
                style="Ok.TLabel")
            self.progress.configure(text=f"已生成 {len(results)} 件，正在写入…")
            if target == "stash":
                ui_genops.write_to_stash(self.app, results, label="暗金", page=page)
            else:
                ui_genops.write_to_backpack(self.app, results)
            self.progress.configure(text=f"完成（{len(results)} 件）")

        def on_error(exc, tb):
            self._finish()
            chk = classify_error(exc)
            self.progress.configure(text="生成失败。")
            self.app.log(f"暗金生成失败：{exc}", "err")
            self.valid_lbl.configure(text=f"✘ {chk.title}", style="Bad.TLabel")
            uic.set_text(self.preview, "【无法生成】\n\n" + chk.text(), color="#c62828")
            uic.detail_warning("无法生成该暗金", chk.title, chk.message, chk.suggestions,
                               chk.detail, parent=self, modal=True)

        self._runner.run(work, on_done=on_done, on_error=on_error,
                         on_progress=on_progress, on_tick=on_tick)

    def _finish(self) -> None:
        u = self._current()
        ok = bool(u is not None and u.base_available and self.gen.ready)
        self.btn_stash.state(["!disabled"] if ok else ["disabled"])
        self.btn_bag.state(["!disabled"] if ok else ["disabled"])
        self.btn_cancel.state(["disabled"])

    def _cancel(self) -> None:
        self._runner.request_cancel()
        self.progress.configure(text="正在取消…")
