"""「储物箱」标签页（使用 d1stash2 修正版写入）。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import ui_common as uic
from d1env import (backup_file, human_size, is_stash_path, list_save_files,
                   settings_dir, timestamp)
from d1names import item_category, item_cn, item_size
from d1stash_adapter import (StashUnavailable, open_stash, record_fields,
                             record_is_unique, record_label_cn, record_name_cn,
                             record_runtime_idx, stash_backend_ready)


class StashTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.stash = None
        self._paths: dict[str, Path] = {}
        self._rows: dict[str, int] = {}
        self._multi = False
        self._issues: list[tuple[int, str, str, str]] = []   # (index, name, severity, reason)
        self._gen = None
        self._runner = uic.TaskRunner(self)
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(4, 2, 4, 10))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="储物箱").grid(row=0, column=0, sticky="e")
        self.file_var = tk.StringVar()
        self.file_box = ttk.Combobox(top, textvariable=self.file_var, state="readonly")
        self.file_box.grid(row=0, column=1, sticky="ew", padx=(8, 6))
        self.file_box.bind("<<ComboboxSelected>>", lambda e: self._on_pick())
        ttk.Button(top, text="浏览…", command=self._browse).grid(row=0, column=2, padx=3)
        ttk.Button(top, text="重载", command=self.reload).grid(row=0, column=3, padx=3)

        self.mode_var = tk.StringVar(value="单人")
        mode = ttk.Frame(top)
        mode.grid(row=0, column=4, sticky="e", padx=(12, 0))
        ttk.Radiobutton(mode, text="单人", value="单人",
                        variable=self.mode_var, command=self._on_mode).grid(row=0, column=0)
        ttk.Radiobutton(mode, text="多人", value="多人",
                        variable=self.mode_var, command=self._on_mode).grid(row=0, column=1, padx=8)
        self.backend_lbl = ttk.Label(top, text="", style="Bad.TLabel")
        self.backend_lbl.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.backend_lbl.grid_remove()
        self.file_info = ttk.Label(top, text="", style="Hint.TLabel")
        self.file_info.grid_remove()

        ttk.Label(top, text="金币").grid(row=1, column=0, sticky="e", pady=(10, 0))
        gold = ttk.Frame(top)
        gold.grid(row=1, column=1, columnspan=4, sticky="ew", pady=(10, 0))
        self.var_gold = tk.StringVar(value="0")
        ttk.Entry(gold, textvariable=self.var_gold, width=16).pack(side="left")
        self.btn_gold = ttk.Button(gold, text="保存金币", style="Primary.TButton",
                                   command=self.save_gold)
        self.btn_gold.pack(side="left", padx=(8, 18))
        self.lbl_count = ttk.Label(gold, text="物品 —", style="Sub.TLabel")
        self.lbl_count.pack(side="left", padx=(0, 14))
        self.lbl_pages = ttk.Label(gold, text="页数 —", style="Sub.TLabel")
        self.lbl_pages.pack(side="left")

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="物品", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.lbl_issues = ttk.Label(bar, text="", style="Hint.TLabel")
        self.lbl_issues.grid(row=0, column=1, sticky="w", padx=10)
        self.btn_check = ttk.Button(bar, text="检查异常物品", command=self.check_items)
        self.btn_check.grid_remove()
        uic.more_button(bar, (("检查异常物品", self.check_items),)).grid(
            row=0, column=2, padx=(0, 6))
        self.btn_delete = ttk.Button(bar, text="删除选中", command=self.delete_selected)
        self.btn_delete.grid(row=0, column=3)
        self.btn_delete.state(["disabled"])
        self.status = ttk.Label(bar, text="", style="Hint.TLabel")
        self.status.grid_remove()

        frame, self.tree = uic.make_tree(
            self, ("page", "pos", "name", "type", "unique", "idx"),
            ("页", "位置", "名称", "类型", "暗金", "序号"),
            widths=(50, 90, 420, 130, 60, 70), height=18, stretch_col="name")
        frame.grid(row=2, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_tree_select())

        self.warn_lbl = ttk.Label(self, text="", style="Bad.TLabel", wraplength=1080,
                                  justify="left")
        self.warn_lbl.grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _on_tree_select(self) -> None:
        self.btn_delete.state(["!disabled"] if self.tree.selection() else ["disabled"])

    # ------------------------------------------------------------ 文件列表
    def refresh_files(self, select: Path | None = None) -> None:
        items = []
        self._paths = {}
        cur = Path(self.stash.path) if self.stash is not None else None
        for p in list_save_files():
            if not is_stash_path(p):
                continue
            items.append(p.name)
            self._paths[p.name] = p
        if select is not None:
            if select.name not in self._paths:
                items.insert(0, select.name)
            self._paths[select.name] = select
        if not items:
            default = settings_dir() / "stash.sv"
            if default.is_file():
                items = [default.name]
                self._paths[default.name] = default
        self.file_box["values"] = items
        target = cur.name if cur and cur.name in self._paths else (items[0] if items else "")
        if target:
            self.file_var.set(target)

    def _on_pick(self) -> None:
        p = self._paths.get(self.file_var.get())
        if p:
            self.load(p)

    def _on_mode(self) -> None:
        self._multi = self.mode_var.get() == "多人"
        if self.stash is not None:
            self.load(Path(self.stash.path), multiplayer=self._multi)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="选择储物箱文件", initialdir=str(settings_dir()),
            filetypes=[("DevilutionX 储物箱", "*.sv"), ("所有文件", "*.*")])
        if not path:
            return
        self.refresh_files(select=Path(path))
        self.load(Path(path))

    # ------------------------------------------------------------ 加载
    def load(self, path: Path, multiplayer: bool | None = None) -> None:
        multi = self._multi if multiplayer is None else multiplayer
        tried = [multi] if multiplayer is not None else [multi, not multi]
        last_exc = None
        for m in tried:
            try:
                stash = open_stash(path, multiplayer=m)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
            self.stash = stash
            self._multi = m
            self.mode_var.set("多人" if m else "单人")
            break
        else:
            self.stash = None
            uic.error("打开储物箱失败", str(last_exc))
            self.app.log(f"储物箱打开失败：{last_exc}", "err")
            return
        readonly = (getattr(self.stash, "writes_blocked", False)
                    or getattr(self.stash, "is_readonly", False))
        if readonly:
            self.backend_lbl.configure(text="只读模式，不能保存", style="Bad.TLabel")
            self.backend_lbl.grid()
            self.btn_gold.state(["disabled"])
        else:
            self.backend_lbl.grid_remove()
            self.btn_gold.state(["!disabled"])
        st = path.stat()
        import datetime
        mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        self.file_info.configure(text=f"{path}")
        self.var_gold.set(str(self.stash.gold))
        self._fill_list()
        self.status.configure(text="")
        self.app.log(f"已载入 {path.name}")
        self.app.on_stash_loaded(path)

    def reload(self) -> None:
        if self.stash is not None:
            self.load(Path(self.stash.path), multiplayer=self._multi)
        else:
            self.refresh_files()
            if self.file_var.get():
                self._on_pick()

    def _positions(self) -> dict[int, tuple[int, int, int]]:
        """物品序号(index+1) -> (page, x, y)，取左上角。"""
        out: dict[int, tuple[int, int, int]] = {}
        for page in sorted(self.stash.grids):
            grid = self.stash.grids[page]
            for y, row in enumerate(grid):
                for x, cell in enumerate(row):
                    if cell and cell not in out:
                        out[cell] = (page, x, y)
        return out

    def _fill_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        if self.stash is None:
            return
        pos = self._positions()
        for i, rec in enumerate(self.stash.records):
            fields = record_fields(rec)
            page, x, y = pos.get(i + 1, (-1, -1, -1))
            w, h = item_size(record_runtime_idx(rec))
            idx = record_runtime_idx(rec)
            name = record_name_cn(rec) or item_cn(idx)
            page_s = str(page) if page >= 0 else "?"
            pos_s = f"{x},{y} {w}x{h}" if x >= 0 else "—"
            unique = "★" if (fields.get("magical") or 0) >= 2 else ""
            row = self.tree.insert("", "end", values=(
                page_s, pos_s, name, item_category(idx), unique, i))
            self._rows[row] = i
        self.lbl_count.configure(text=f"物品 {self.stash.item_count()}")
        self.lbl_pages.configure(text=f"页数 {len(self.stash.pages())}")
        # 列表重建后选中项已清空，删除按钮同步回到禁用态
        self.btn_delete.state(["disabled"])

    # ------------------------------------------------------------ 异常物品
    def _gen_adapter(self):
        """延迟创建 ItemGen（避免与生成页重复加载；只读用它做体检）。"""
        if self._gen is None:
            try:
                from d1itemgen_adapter import ItemGen
                self._gen = ItemGen()
            except Exception:  # noqa: BLE001
                self._gen = False
        return None if self._gen is False else self._gen

    def scan_issues(self, deep: bool = False) -> list[tuple[int, str, str, str]]:
        """扫描当前储物箱里的可疑物品：[(0 基序号, 名称, 级别, 原因)]。"""
        out: list[tuple[int, str, str, str]] = []
        if self.stash is None:
            return out
        gen = self._gen_adapter()
        for i, rec in enumerate(self.stash.records):
            name = record_name_cn(rec) or item_cn(record_runtime_idx(rec))
            if gen is None:
                # 没有生成器时至少查 starter（运行时 166/1/2/5 这类）
                issues = self._fallback_check(rec)
            else:
                issues = gen.check_record(rec, deep=deep)
            for severity, reason in issues:
                out.append((i, name, severity, reason))
        return out

    def _fallback_check(self, rec: bytes) -> list[tuple[str, str]]:
        issues: list[tuple[str, str]] = []
        try:
            idx = record_runtime_idx(rec)
        except Exception:  # noqa: BLE001
            return issues
        if idx in (1, 2, 3, 4, 5, 166):
            issues.append(("fatal", f"运行时编号 {idx} 是初始装备（starter），"
                                    "写进存档会导致进游戏崩溃"))
        return issues

    def report_issues(self, issues: list[tuple[int, str, str, str]] | None = None) -> None:
        """更新横幅/计数（load 之后调用）。"""
        if issues is None:
            try:
                issues = self.scan_issues(deep=False)
            except Exception:  # noqa: BLE001
                issues = []
        self._issues = issues
        fatal = sum(1 for i in issues if i[2] == "fatal")
        if not issues:
            self.warn_lbl.configure(text="")
            self.lbl_issues.configure(text="")
            return
        names = "、".join(dict.fromkeys(i[1] for i in issues[:5]))
        self.warn_lbl.configure(
            text=f"发现 {len(issues)} 处可疑物品"
                 + (f"（{fatal} 处会让游戏崩溃）" if fatal else "")
                 + f"：{names}")
        self.lbl_issues.configure(text="", style="Bad.TLabel")
        self.app.log(f"储物箱体检：发现 {len(issues)} 处可疑物品（{names}）",
                     "err" if fatal else "warn")

    def check_items(self) -> None:
        """「检查异常物品」：后台深度校验（含 d1itemgen.validate），列出来。"""
        if self.stash is None:
            uic.warn("提示", "请先打开储物箱。")
            return
        if self._runner.busy():
            uic.warn("提示", "正在检查中，请稍候…")
            return
        self.btn_check.state(["disabled"])
        self.lbl_issues.configure(text="正在检查…", style="Hint.TLabel")

        def work(put, cancel):
            put("正在逐件校验（含 seed 重放）…")
            return self.scan_issues(deep=True)

        def on_done(issues):
            self.btn_check.state(["!disabled"])
            self.report_issues(issues)
            if not issues:
                uic.info("检查完成", "没有发现异常物品。")
                return
            self._show_issue_dialog(issues)

        def on_error(exc, tb):
            self.btn_check.state(["!disabled"])
            self.lbl_issues.configure(text="检查失败", style="Bad.TLabel")
            uic.error("检查失败", f"{type(exc).__name__}: {exc}")

        self._runner.run(work, on_done=on_done, on_error=on_error)

    def _show_issue_dialog(self, issues) -> None:
        top = tk.Toplevel(self)
        top.title("储物箱异常物品")
        top.geometry("900x460")
        top.transient(self.winfo_toplevel())
        ttk.Label(top, text="下列物品不合法，标为「致命」的会让游戏崩溃。删除前会自动备份。",
                  wraplength=860, justify="left", style="Bad.TLabel").pack(
            anchor="w", padx=10, pady=(10, 4))
        frame = ttk.Frame(top)
        frame.pack(fill="both", expand=True, padx=10)
        columns = ("sel", "idx", "name", "level", "reason")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=12,
                            selectmode="extended")
        for col, text, width in (("sel", "选择", 50), ("idx", "序号", 60),
                                 ("name", "名称", 220), ("level", "级别", 60),
                                 ("reason", "原因", 480)):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w",
                        stretch=(col == "reason"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        rows = {}
        for i, name, severity, reason in issues:
            level = "致命" if severity == "fatal" else "警告"
            row = tree.insert("", "end", values=("☑", i, name, level, reason))
            rows[row] = i
            if severity == "fatal":
                tree.item(row, tags=("fatal",))
        tree.tag_configure("fatal", foreground="#c62828")
        for row in tree.get_children():
            tree.selection_add(row)

        btns = ttk.Frame(top)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="全选", command=lambda: tree.selection_set(tree.get_children())
                   ).pack(side="left")
        ttk.Button(btns, text="全不选", command=lambda: tree.selection_remove(tree.get_children())
                   ).pack(side="left", padx=6)
        ttk.Button(btns, text="关闭", command=top.destroy).pack(side="right")

        def do_delete():
            sel = tree.selection()
            indices = sorted({rows[r] for r in sel if r in rows}, reverse=True)
            if not indices:
                uic.warn("提示", "请先选择要删除的物品。")
                return
            fatal_names = [n for (i, n, sev, _) in issues if i in indices and sev == "fatal"]
            extra = ("\n其中包含会导致进游戏崩溃的物品：\n  " + "\n  ".join(fatal_names[:6])
                     if fatal_names else "")
            if not uic.confirm("确认删除",
                               f"要从储物箱删除 {len(indices)} 件物品？{extra}\n\n"
                               "（会先备份 .bak-时间戳，删完重开校验物品数）"):
                return
            top.destroy()
            self.delete_indices(indices)

        ttk.Button(btns, text="删除选中", command=do_delete).pack(side="right", padx=6)

    def delete_indices(self, indices: list[int]) -> bool:
        """按 0 基序号批量删除（从大到小删，避免序号错位），写后校验物品数。"""
        if self.stash is None or not indices:
            return False
        if getattr(self.stash, "is_readonly", False):
            uic.error("只读模式", "当前不能删除物品。")
            return False
        if not self.app.require_game_closed():
            return False
        path = Path(self.stash.path)
        before = int(self.stash.item_count())
        doomed = [bytes(self.stash.records[i]) for i in indices
                  if 0 <= i < len(self.stash.records)]
        expect = [bytes(r) for r in self.stash.records
                  if not any(bytes(r) == d for d in doomed)]
        try:
            backup = backup_file(path)
            for i in sorted(indices, reverse=True):
                self.stash.remove_record(i)
            self.stash.save(out_path=str(path), backup=True)
            check = open_stash(path, multiplayer=self._multi)
            after = [bytes(r) for r in check.records]
            if len(after) != before - len(doomed):
                raise StashUnavailable(
                    f"写后校验失败：物品数 {before} → {len(after)}，"
                    f"预期 {before - len(doomed)}，已回滚")
            if after != expect:
                raise StashUnavailable("写后校验失败：剩余物品与预期不一致，已回滚")
        except Exception as exc:  # noqa: BLE001
            try:
                import shutil
                shutil.copy2(backup, path)
            except Exception:  # noqa: BLE001
                pass
            uic.error("删除失败", f"{exc}\n\n已回滚到 {backup.name}")
            self.app.log(f"批量删除失败：{exc}", "err")
            self.reload()
            return False
        self.app.log(f"已从储物箱删除 {len(doomed)} 件异常物品（{before} → "
                     f"{before - len(doomed)}），备份 {backup.name}", "ok")
        self.reload()
        uic.info("已删除", f"删除了 {len(doomed)} 件物品，剩余 {before - len(doomed)} 件"
                          f"（已重开校验）。\n\n备份：{backup.name}")
        return True

    # ------------------------------------------------------------ 保存
    def save_gold(self) -> bool:
        if self.stash is None:
            uic.warn("提示", "请先打开储物箱。")
            return False
        if getattr(self.stash, "is_readonly", False):
            uic.error("只读模式", "当前不能保存储物箱。")
            return False
        if not self.app.require_game_closed():
            return False
        raw = self.var_gold.get().strip().replace(",", "")
        try:
            gold = int(raw)
        except ValueError:
            uic.warn("输入有误", "金币必须是整数。")
            return False
        if not (0 <= gold <= 0x7FFFFFFF):
            uic.warn("输入有误", "金币范围 0 ~ 2147483647。")
            return False

        path = Path(self.stash.path)
        before = [bytes(r) for r in self.stash.records]
        grids_before = {p: [row[:] for row in g] for p, g in self.stash.grids.items()}
        try:
            self.stash.gold = gold
            backup = backup_file(path)
            self.stash.save(out_path=str(path), backup=True)
            # 复读校验：物品必须逐字节不变
            check = open_stash(path, multiplayer=self._multi)
            after = [bytes(r) for r in check.records]
            if after != before:
                raise StashUnavailable("写后校验失败：物品记录发生变化，已回滚")
            if int(check.gold) != gold:
                raise StashUnavailable("写后校验失败：金币没有正确写入，已回滚")
        except Exception as exc:  # noqa: BLE001
            try:
                import shutil
                shutil.copy2(backup, path)
            except Exception:  # noqa: BLE001
                pass
            self.app.log(f"储物箱保存失败：{exc}", "err")
            uic.error("保存失败", f"{exc}\n\n已尝试回滚到 {backup.name}")
            self.status.configure(text="保存失败")
            self.reload()
            return False

        self.status.configure(text=f"已保存 {timestamp()}")
        self.app.log(f"储物箱金币已保存为 {gold:,}；{len(before)} 件物品逐字节未变。"
                     f"备份：{backup.name}", "ok")
        self.reload()
        return True

    def delete_selected(self) -> None:
        if self.stash is None:
            return
        if getattr(self.stash, "is_readonly", False):
            uic.error("只读模式", "当前不能删除物品。")
            return
        sel = self.tree.selection()
        if not sel:
            uic.warn("提示", "请先在列表里选择一个物品。")
            return
        index = self._rows.get(sel[0])
        if index is None:
            return
        rec = self.stash.records[index]
        name = record_label_cn(rec)
        if not uic.confirm("确认删除", f"确定从储物箱删除「{name}」？\n（会先备份）"):
            return
        if not self.app.require_game_closed():
            return
        path = Path(self.stash.path)
        before = [bytes(r) for r in self.stash.records if bytes(r) != bytes(rec)]
        try:
            backup = backup_file(path)
            self.stash.remove_record(index)
            self.stash.save(out_path=str(path), backup=True)
            check = open_stash(path, multiplayer=self._multi)
            after = [bytes(r) for r in check.records]
            if after != before:
                raise StashUnavailable("写后校验失败：删除后记录不一致，已回滚")
        except Exception as exc:  # noqa: BLE001
            try:
                import shutil
                shutil.copy2(backup, path)
            except Exception:  # noqa: BLE001
                pass
            uic.error("删除失败", f"{exc}\n\n已尝试回滚到 {backup.name}")
            self.reload()
            return
        self.app.log(f"已删除储物箱物品「{name}」，备份 {backup.name}", "ok")
        self.reload()

    # ------------------------------------------------------------ 供生成页调用
    def add_record(self, record: bytes, name: str = "",
                   page: int | None = None) -> tuple[int, int, int]:
        """加一条记录；``page`` 是 **0-based** 页号（None = 自动找空位）。

        生成页把用户填的「写入页码」（1-based）减 1 后传进来；d1stash2 在指定页
        放不下时会按页号顺序继续找，最后新建页。
        """
        if self.stash is None:
            raise StashUnavailable("请先在「储物箱」页打开 stash.sv")
        try:
            return self.stash.add_record(record, page=page)
        except TypeError:
            # 兼容没有 page 参数的旧 d1stash2
            return self.stash.add_record(record)

    def flush(self) -> None:
        """保存并校验（生成页批量写入后调用）。"""
        path = Path(self.stash.path)
        before = [bytes(r) for r in self.stash.records]
        backup = backup_file(path)
        try:
            self.stash.save(out_path=str(path), backup=True)
            check = open_stash(path, multiplayer=self._multi)
            if [bytes(r) for r in check.records] != before:
                raise StashUnavailable("写后校验失败：物品记录不一致，已回滚")
        except Exception as exc:  # noqa: BLE001
            try:
                import shutil
                shutil.copy2(backup, path)
            except Exception:  # noqa: BLE001
                pass
            raise StashUnavailable(f"{exc}（已回滚到 {backup.name}）") from exc
        self.app.log(f"储物箱已保存（{len(before)} 件物品，校验通过），备份 {backup.name}", "ok")
        self.reload()

    @property
    def backend_ready(self) -> bool:
        ok, _ = stash_backend_ready()
        return ok
