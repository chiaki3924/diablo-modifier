"""「角色」标签页。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import ui_common as uic
from d1env import human_size, list_save_files, settings_dir, timestamp
from d1hero import HeroEdit, HeroError, learnable_spells
from d1names import class_name, learnable_spell_name


class CharTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=6)
        self.app = app
        self.hero: HeroEdit | None = None
        self._paths: dict[str, Path] = {}
        self._spell_rows: list[str] = []
        self._row_spell: dict[str, int] = {}
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        top = ttk.LabelFrame(self, text="存档文件", padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="角色存档：").grid(row=0, column=0, sticky="e")
        self.save_var = tk.StringVar()
        self.save_box = ttk.Combobox(top, textvariable=self.save_var, state="readonly")
        self.save_box.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.save_box.bind("<<ComboboxSelected>>", lambda e: self._on_pick())
        ttk.Button(top, text="浏览其他文件…", command=self._browse).grid(row=0, column=2, padx=3)
        ttk.Button(top, text="重新加载", command=self.reload).grid(row=0, column=3, padx=3)

        self.file_info = ttk.Label(top, text="", style="Hint.TLabel")
        self.file_info.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # ---------------- 基本信息（并进同一个框，省纵向空间） ----------------
        self.lbl_name = ttk.Label(top, text="—", style="Title.TLabel")
        self.lbl_name.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.lbl_class = ttk.Label(top, text="", style="Sub.TLabel")
        self.lbl_class.grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(8, 0))
        self.lbl_extra = ttk.Label(top, text="", style="Sub.TLabel")
        self.lbl_extra.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))

        self.warn_bar = ttk.Label(top, text="", style="Bad.TLabel")
        self.warn_bar.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # ---------------- 编辑区 ----------------
        edit = ttk.LabelFrame(self, text="数值修改", padding=8)
        edit.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for c in range(8):
            edit.columnconfigure(c, weight=0)

        # 等级 / 经验
        ttk.Label(edit, text="等级").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=3)
        self.var_level = tk.StringVar()
        self.sp_level = ttk.Spinbox(edit, from_=1, to=50, textvariable=self.var_level, width=6)
        self.sp_level.grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Label(edit, text="经验").grid(row=0, column=2, sticky="e", padx=(0, 4))
        self.var_exp = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_exp, width=14).grid(row=0, column=3, sticky="w")
        self.lbl_exp_hint = ttk.Label(edit, text="", style="Hint.TLabel")
        self.lbl_exp_hint.grid(row=0, column=4, columnspan=4, sticky="w", padx=(8, 0))

        # 四维
        self.var_str, self.var_mag, self.var_dex, self.var_vit = (tk.StringVar() for _ in range(4))
        for i, (label, var) in enumerate((("力量", self.var_str), ("魔法", self.var_mag),
                                          ("敏捷", self.var_dex), ("体质", self.var_vit))):
            ttk.Label(edit, text=label).grid(row=1, column=i * 2, sticky="e", padx=(0, 4), pady=3)
            ttk.Spinbox(edit, from_=1, to=999, textvariable=var, width=6).grid(
                row=1, column=i * 2 + 1, sticky="w", padx=(0, 14))

        ttk.Label(edit, text="剩余属性点").grid(row=2, column=0, sticky="e", padx=(0, 4), pady=3)
        self.var_pts = tk.StringVar()
        ttk.Spinbox(edit, from_=0, to=255, textvariable=self.var_pts, width=6).grid(
            row=2, column=1, sticky="w", padx=(0, 14))

        # 生命 / 法力
        ttk.Label(edit, text="生命").grid(row=2, column=2, sticky="e", padx=(0, 4))
        self.var_hp = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_hp, width=6).grid(row=2, column=3, sticky="w")
        ttk.Label(edit, text="/").grid(row=2, column=4)
        self.var_hp_max = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_hp_max, width=6).grid(row=2, column=5, sticky="w")
        ttk.Label(edit, text="法力").grid(row=2, column=6, sticky="e", padx=(10, 4))
        self.var_mp = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_mp, width=6).grid(row=2, column=7, sticky="w")
        ttk.Label(edit, text="/").grid(row=2, column=8)
        self.var_mp_max = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_mp_max, width=6).grid(row=2, column=9, sticky="w")

        ttk.Label(edit, text="角色金币").grid(row=3, column=0, sticky="e", padx=(0, 4), pady=3)
        self.var_gold = tk.StringVar()
        ttk.Entry(edit, textvariable=self.var_gold, width=14).grid(
            row=3, column=1, columnspan=2, sticky="w")
        ttk.Label(edit, text="（建议 ≤ 50000；游戏内钱包有上限）", style="Hint.TLabel").grid(
            row=3, column=3, columnspan=6, sticky="w", padx=(4, 0))

        # ---------------- 法术 ----------------
        spell = ttk.LabelFrame(self, text="法术", padding=8)
        spell.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.rowconfigure(2, weight=1)
        spell.columnconfigure(0, weight=1)
        spell.rowconfigure(0, weight=1)

        frame, self.spell_tree = uic.make_tree(
            spell, ("spell", "level"), ("法术", "等级"), widths=(260, 60), height=9,
            stretch_col="spell")
        frame.grid(row=0, column=0, columnspan=6, sticky="nsew")
        self.spell_tree.bind("<<TreeviewSelect>>", lambda e: self._on_spell_select())

        ttk.Label(spell, text="选中法术等级").grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.var_spell_lv = tk.StringVar(value="1")
        ttk.Spinbox(spell, from_=0, to=15, textvariable=self.var_spell_lv, width=6).grid(
            row=1, column=1, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Button(spell, text="应用等级", command=self._apply_spell).grid(
            row=1, column=2, sticky="w", padx=3, pady=(6, 0))
        ttk.Button(spell, text="全部学会（15 级）", command=self._learn_all).grid(
            row=1, column=3, sticky="w", padx=3, pady=(6, 0))
        ttk.Button(spell, text="遗忘全部法术", command=self._forget_all).grid(
            row=1, column=4, sticky="w", padx=3, pady=(6, 0))
        ttk.Button(spell, text="清理非原版法术", command=self._clear_non_original).grid(
            row=1, column=5, sticky="w", padx=(8, 3), pady=(6, 0))

        self.lbl_spell_note = ttk.Label(
            spell, style="Hint.TLabel", justify="left", wraplength=640,
            text="只显示 1.5.5 原版可学习法术（已隐藏地狱火/职业自带/不可学习法术）")
        self.lbl_spell_note.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.lbl_spell_hidden = ttk.Label(spell, text="", style="Hint.TLabel")
        self.lbl_spell_hidden.grid(row=3, column=0, columnspan=6, sticky="w")

        # ---------------- 操作 ----------------
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.btn_save = ttk.Button(actions, text="保存到存档", command=self.save)
        self.btn_save.grid(row=0, column=0)
        ttk.Button(actions, text="放弃修改（重载）", command=self.reload).grid(row=0, column=1, padx=8)
        self.status = ttk.Label(actions, text="", style="Hint.TLabel")
        self.status.grid(row=0, column=2, sticky="w", padx=8)

    # ------------------------------------------------------------ 存档列表
    def refresh_saves(self, select: Path | None = None) -> None:
        items = []
        self._paths = {}
        cur = self.hero.path if self.hero else None
        for p in list_save_files():
            if p.name.lower() == "stash.sv":
                continue
            try:
                label = f"{p.name} · {self.app.quick_name(p)}"
            except Exception:  # noqa: BLE001
                label = p.name
            items.append(label)
            self._paths[label] = p
        if select is not None:
            label = select.name
            if label not in self._paths:
                try:
                    label = f"{select.name} · {self.app.quick_name(select)}"
                except Exception:  # noqa: BLE001
                    label = select.name
                self._paths[label] = select
                items.insert(0, label)
        self.save_box["values"] = items
        target = None
        if cur is not None:
            for label, p in self._paths.items():
                if p == cur:
                    target = label
                    break
        if target is None and items:
            target = items[0]
        if target:
            self.save_var.set(target)

    def _on_pick(self) -> None:
        label = self.save_var.get()
        p = self._paths.get(label)
        if p:
            self.load(p)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="选择角色存档", initialdir=str(settings_dir()),
            filetypes=[("DevilutionX 存档", "*.sv *.hsv"), ("所有文件", "*.*")])
        if not path:
            return
        p = Path(path)
        if p.name.lower() in ("stash.sv",):
            uic.warn("提示", "这是储物箱文件，请到「储物箱」页打开。")
            return
        self.refresh_saves(select=p)
        self.load(p)

    # ------------------------------------------------------------ 加载/回填
    def load(self, path: Path) -> None:
        try:
            self.hero = HeroEdit(path)
        except HeroError as exc:
            self.hero = None
            uic.error("打开失败", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.hero = None
            uic.error("打开失败", f"{type(exc).__name__}: {exc}")
            return
        st = path.stat()
        import datetime
        mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        self.file_info.configure(
            text=f"{path}    {human_size(st.st_size)}    修改时间 {mtime}")
        self._fill_form()
        self.status.configure(text="")
        self.app.log(f"已载入角色存档：{path.name}（{self.hero.summary()}）")
        self.app.on_char_loaded(path)

    def reload(self) -> None:
        if self.hero:
            self.load(self.hero.path)
        else:
            self.refresh_saves()
            if self.save_var.get():
                self._on_pick()

    def _fill_form(self) -> None:
        h = self.hero
        if h is None:
            return
        self.lbl_name.configure(text=h.name or "（无名）")
        self.lbl_class.configure(text=f"{h.class_name_cn}    {h.level} 级")
        self._fill_form_extra()
        self.var_level.set(str(h.level))
        self.var_exp.set(str(h.exp))
        s = h.stats
        self.var_str.set(str(s["str"]))
        self.var_mag.set(str(s["mag"]))
        self.var_dex.set(str(s["dex"]))
        self.var_vit.set(str(s["vit"]))
        self.var_pts.set(str(h.stat_points))
        hp, hpmax = h.hp
        mp, mpmax = h.mana
        self.var_hp.set(str(hp))
        self.var_hp_max.set(str(hpmax))
        self.var_mp.set(str(mp))
        self.var_mp_max.set(str(mpmax))
        self.var_gold.set(str(h.gold))
        need = h.next_level_exp()
        self.lbl_exp_hint.configure(
            text=f"下一级需要 {need:,} 经验" if need else "已满级")
        self._fill_spells()
        self._update_banner()

    def _fill_form_extra(self) -> None:
        """刷新「生命/法力/金币/已学法术」那一行（法术改动后也要刷）。"""
        h = self.hero
        if h is None:
            return
        hp, hpmax = h.hp
        mp, mpmax = h.mana
        hidden = len(h.hidden_spell_levels)
        self.lbl_extra.configure(
            text=f"生命 {hp}/{hpmax}    法力 {mp}/{mpmax}    金币 {h.gold:,}    "
                 f"已学法术 {self._known_visible_count()}/{len(h.visible_spells)} 个"
                 + (f"（另 {hidden} 个隐藏）" if hidden else ""))

    def _known_visible_count(self) -> int:
        if not self.hero:
            return 0
        levels = self.hero.spell_levels
        return sum(1 for row in learnable_spells() if levels[int(row["index"])] > 0)

    def _fill_spells(self) -> None:
        """只列出 1.5.5 原版可学习的 22 个法术；隐藏法术不建行。"""
        keep = [iid for iid in self.spell_tree.selection()
                if iid in self._row_spell]
        self.spell_tree.delete(*self.spell_tree.get_children())
        self._spell_rows = []
        self._row_spell = {}
        if not self.hero:
            self.lbl_spell_hidden.configure(text="")
            return
        levels = self.hero.spell_levels
        for row in learnable_spells():
            sid = int(row["index"])
            name = row.get("cn") or row.get("name") or f"法术{sid}"
            iid = str(sid)
            self.spell_tree.insert("", "end", iid=iid,
                                   values=(f"{sid} · {name}", levels[sid] or ""))
            self._spell_rows.append(iid)
            self._row_spell[iid] = sid
        if keep:
            try:
                self.spell_tree.selection_set(keep[0])
            except tk.TclError:
                pass
        hidden = self.hero.hidden_spell_levels
        if hidden:
            self.lbl_spell_hidden.configure(
                text=f"存档里另隐藏 {len(hidden)} 个非原版/职业法术等级，未改动")
        else:
            self.lbl_spell_hidden.configure(
                text="存档里没有其它隐藏法术等级（地狱火/职业自带）")

    def _update_banner(self) -> None:
        if self.app.game_running:
            self.warn_bar.configure(text="⚠ 游戏正在运行：请先退出游戏，否则保存可能被游戏覆盖。")
        else:
            self.warn_bar.configure(text="")

    def _on_spell_select(self) -> None:
        idx = self._selected_spell(silent=True)
        if idx is None or not self.hero:
            return
        try:
            self.var_spell_lv.set(str(self.hero.spell_levels[idx]))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 编辑动作
    def _selected_spell(self, silent: bool = False) -> int | None:
        """选中的法术 id（来自 row->id 映射，不解析行文本）。"""
        sel = self.spell_tree.selection()
        if not sel:
            if not silent:
                uic.warn("提示", "请先在下方列表里选择一个法术。")
            return None
        iid = sel[0]
        sid = self._row_spell.get(iid)
        if sid is None:
            try:
                sid = int(iid)
            except (TypeError, ValueError):
                return None
        return int(sid)

    def _apply_spell(self) -> None:
        if not self.hero:
            return
        idx = self._selected_spell()
        if idx is None:
            return
        try:
            lvl = int(self.var_spell_lv.get())
        except ValueError:
            uic.warn("提示", "法术等级必须是 0~15 的整数。")
            return
        try:
            self.hero.set_spell_level(idx, lvl)
        except Exception as exc:  # noqa: BLE001
            uic.error("设置失败", f"{type(exc).__name__}: {exc}")
            return
        self._fill_spells()
        self._fill_form_extra()
        self.app.log(f"法术「{learnable_spell_name(idx)}」等级设为 {lvl}（尚未保存）")

    def _learn_all(self) -> None:
        if not self.hero:
            return
        try:
            self.hero.learn_all(15)
        except Exception as exc:  # noqa: BLE001
            uic.error("失败", f"{type(exc).__name__}: {exc}")
            return
        self._fill_spells()
        self._fill_form_extra()
        self.app.log(f"已学会全部 {len(learnable_spells())} 个原版法术（15 级），"
                     "隐藏法术未改动，记得点保存。")

    def _forget_all(self) -> None:
        if not self.hero:
            return
        if not uic.confirm("确认",
                           "确定遗忘该角色的全部可见法术？\n"
                           "（地狱火/职业自带/不可学习法术的隐藏等级不会改动）"):
            return
        try:
            self.hero.forget_all()
        except Exception as exc:  # noqa: BLE001
            uic.error("失败", f"{type(exc).__name__}: {exc}")
            return
        self._fill_spells()
        self._fill_form_extra()
        self.app.log("已遗忘全部可见法术（隐藏法术未改动，尚未保存）")

    def _clear_non_original(self) -> None:
        """清掉 Hellfire/不可学习法术，只留下 1.5.5 原版内容。"""
        if not self.hero:
            return
        if not uic.confirm(
                "确认",
                "确定清理非原版法术？\n"
                "只清地狱火（37~46）与不可学习法术；\n"
                "保留职业自带能力与 22 条原版法术。"):
            return
        try:
            removed = self.hero.clear_non_original_spells()
        except Exception as exc:  # noqa: BLE001
            uic.error("失败", f"{type(exc).__name__}: {exc}")
            return
        self._fill_spells()
        self._fill_form_extra()
        self.app.log(f"已清理 {len(removed)} 个非原版法术（等级与记忆位归零），"
                     "职业能力与 22 条原版法术未改动（尚未保存）")

    # ------------------------------------------------------------ 保存
    def _int(self, var: tk.StringVar, name: str, lo: int, hi: int) -> int:
        raw = var.get().strip().replace(",", "")
        try:
            val = int(raw)
        except ValueError:
            raise ValueError(f"{name} 必须是整数：{raw!r}")
        if not (lo <= val <= hi):
            raise ValueError(f"{name} 超出范围（{lo}~{hi}）：{val}")
        return val

    def save(self) -> bool:
        if not self.hero:
            uic.warn("提示", "请先选择一个角色存档。")
            return False
        if not self.app.require_game_closed():
            return False
        try:
            level = self._int(self.var_level, "等级", 1, 50)
            exp = self._int(self.var_exp, "经验", 0, 0xFFFFFFFF)
            str_ = self._int(self.var_str, "力量", 1, 999)
            mag = self._int(self.var_mag, "魔法", 1, 999)
            dex = self._int(self.var_dex, "敏捷", 1, 999)
            vit = self._int(self.var_vit, "体质", 1, 999)
            pts = self._int(self.var_pts, "剩余属性点", 0, 255)
            hp = self._int(self.var_hp, "生命", 1, 99999)
            hpmax = self._int(self.var_hp_max, "生命上限", 1, 99999)
            mp = self._int(self.var_mp, "法力", 0, 99999)
            mpmax = self._int(self.var_mp_max, "法力上限", 0, 99999)
            gold = self._int(self.var_gold, "金币", 0, 0x7FFFFFFF)
        except ValueError as exc:
            uic.warn("输入有误", str(exc))
            return False
        if hp > hpmax:
            self.var_hp.set(str(hpmax))
            hp = hpmax
        if mp > mpmax:
            self.var_mp.set(str(mpmax))
            mp = mpmax

        try:
            self.hero.set_level(level)
            self.hero.set_stats(str_=str_, mag=mag, dex=dex, vit=vit)
            self.hero.set_stat_points(pts)
            self.hero.set_exp(exp)
            gold_actual = self.hero.set_gold(gold)
            self.hero.set_pools(hp=hp, max_hp=hpmax, mana=mp, max_mana=mpmax)
            msg = self.hero.save(clear_progress=False)
        except HeroError as exc:
            self.status.configure(text="保存失败")
            uic.error("保存失败", str(exc))
            self.app.log(f"保存失败：{exc}", "err")
            return False
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text="保存失败")
            uic.error("保存失败", f"{type(exc).__name__}: {exc}")
            self.app.log(f"保存失败：{exc}", "err")
            return False

        self.status.configure(text=f"已保存 {timestamp()}")
        if gold_actual != gold:
            self.app.log(f"金币受背包空间限制：请求 {gold:,}，实际写入 {gold_actual:,}", "warn")
        self.app.log(f"角色存档已保存：{self.hero.path.name}（{msg}）", "ok")
        self.app.refresh_all(keep_char=True)
        return True
