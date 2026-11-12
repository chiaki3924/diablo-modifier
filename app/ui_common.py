"""界面公共部件与工具。"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

HEADLESS = False


# ---------------------------------------------------------------- 消息

def info(title: str, msg: str) -> None:
    if HEADLESS:
        print(f"[INFO] {title}: {msg}")
        return
    messagebox.showinfo(title, msg)


def warn(title: str, msg: str) -> None:
    if HEADLESS:
        print(f"[WARN] {title}: {msg}")
        return
    messagebox.showwarning(title, msg)


def error(title: str, msg: str) -> None:
    if HEADLESS:
        print(f"[ERROR] {title}: {msg}")
        return
    messagebox.showerror(title, msg)


def confirm(title: str, msg: str) -> bool:
    if HEADLESS:
        print(f"[CONFIRM] {title}: {msg} -> True")
        return True
    return bool(messagebox.askyesno(title, msg))


def detail_warning(title: str, headline: str, message: str = "",
                   suggestions=(), detail: str = "", parent=None,
                   modal: bool = True):
    """「原因 + 建议」警告框（Round 3 生成失败提示）。

    比 ``messagebox.showwarning`` 更适合这里：标题/正文/建议分三段排版，
    技术细节单独用灰色小字，用户一眼能看出「是游戏规则不允许，还是没搜到」。

    ``modal=False`` 时立即返回 Toplevel（截图/自动化用）；``HEADLESS`` 时只打印。
    """
    lines = []
    if message:
        lines.append(message)
    if suggestions:
        lines.append("")
        lines.append("建议：")
        lines.extend(f"  · {s}" for s in suggestions)
    if detail:
        lines.append("")
        lines.append(f"（技术细节：{detail}）")
    body = "\n".join(lines)
    if HEADLESS or parent is None:
        print(f"[WARN] {title}: {headline}" + (f"\n{body}" if body else ""))
        return None
    top = tk.Toplevel(parent)
    top.title(title)
    top.resizable(True, False)
    try:
        top.transient(parent.winfo_toplevel())
    except Exception:  # noqa: BLE001
        pass
    frame = ttk.Frame(top, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=headline, style="Bad.TLabel",
              font=("", 11, "bold"), wraplength=620, justify="left").pack(
        anchor="w", fill="x")
    if message:
        ttk.Label(frame, text=message, wraplength=620, justify="left").pack(
            anchor="w", fill="x", pady=(8, 0))
    if suggestions:
        ttk.Label(frame, text="建议：", style="Sub.TLabel").pack(anchor="w", pady=(10, 2))
        for s in suggestions:
            ttk.Label(frame, text=f"· {s}", wraplength=600, justify="left").pack(
                anchor="w", fill="x", padx=(10, 0))
    if detail:
        ttk.Label(frame, text=f"（技术细节：{detail}）", style="Hint.TLabel",
                  wraplength=620, justify="left").pack(anchor="w", pady=(10, 0))
    ttk.Button(frame, text="知道了", command=top.destroy).pack(anchor="e", pady=(12, 0))
    top.update_idletasks()
    try:
        top.geometry(f"+{parent.winfo_rootx() + 80}+{parent.winfo_rooty() + 80}")
    except Exception:  # noqa: BLE001
        pass
    if modal:
        try:
            top.grab_set()
        except Exception:  # noqa: BLE001
            pass
        top.wait_window()
    return top



# ---------------------------------------------------------------- 样式

def setup_dpi() -> None:
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def pick_font() -> str:
    families = set(tkfont.families())
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimHei", "SimSun"):
        if name in families:
            return name
    return "TkDefaultFont"


def make_style(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    family = pick_font()
    base = 10
    root.option_add("*Font", (family, base))
    style.configure(".", font=(family, base))
    style.configure("TButton", padding=(8, 4))
    style.configure("TNotebook.Tab", padding=(16, 6), font=(family, base + 1))
    style.configure("TLabelframe.Label", font=(family, base + 1, "bold"))
    style.configure("Title.TLabel", font=(family, base + 6, "bold"))
    style.configure("Sub.TLabel", foreground="#555555")
    style.configure("Ok.TLabel", foreground="#1a7f37")
    style.configure("Bad.TLabel", foreground="#c62828")
    style.configure("Hint.TLabel", foreground="#777777")
    style.configure("TEntry", padding=3)
    style.configure("Treeview", rowheight=24, font=(family, base))
    style.configure("Treeview.Heading", font=(family, base, "bold"))
    return style


# ---------------------------------------------------------------- 日志

class LogPane(ttk.Frame):
    """窗口底部日志（只读）。"""

    def __init__(self, master, height=5, **kw):
        super().__init__(master, **kw)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled",
                            relief="flat", background="#f7f7f7", foreground="#333333")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.text.tag_configure("warn", foreground="#b26a00")
        self.text.tag_configure("err", foreground="#c62828")
        self.text.tag_configure("ok", foreground="#1a7f37")

    def write(self, msg: str, tag: str | None = None) -> None:
        ts = time.strftime("%H:%M:%S")
        self.text.configure(state="normal")
        self.text.insert("end", f"[{ts}] {msg}\n", (tag,) if tag else ())
        self.text.see("end")
        self.text.configure(state="disabled")


# ---------------------------------------------------------------- 后台任务

class TaskRunner:
    """把耗时任务放到后台线程，结果用 after() 轮询回主线程。

    每次 run() 使用独立的队列与轮询 id，避免两次任务的结果串台。
    """

    def __init__(self, widget: tk.Misc):
        self.widget = widget
        self.thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self._poll_id = None
        self._q: queue.Queue | None = None
        self._run_id = 0

    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def run(self, func, on_done=None, on_error=None, on_progress=None, on_tick=None) -> bool:
        if self.busy():
            return False
        self.cancel.clear()
        self._run_id += 1
        run_id = self._run_id
        q: queue.Queue = queue.Queue()
        self._q = q
        t0 = time.time()

        def worker():
            try:
                result = func(q.put, self.cancel)
                q.put(("__done__", result))
            except Exception as exc:  # noqa: BLE001
                import traceback
                q.put(("__error__", (exc, traceback.format_exc(limit=6))))

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

        def drain():
            if run_id != self._run_id:
                return
            try:
                while True:
                    item = q.get_nowait()
                    if isinstance(item, tuple) and item and item[0] == "__done__":
                        if on_done:
                            on_done(item[1])
                        return
                    if isinstance(item, tuple) and item and item[0] == "__error__":
                        exc, tb = item[1]
                        if on_error:
                            on_error(exc, tb)
                        return
                    if on_progress:
                        on_progress(item)
            except queue.Empty:
                pass
            if on_tick:
                on_tick(time.time() - t0)
            try:
                self._poll_id = self.widget.after(120, drain)
            except tk.TclError:
                pass

        self._poll_id = self.widget.after(120, drain)
        return True

    def _stop(self) -> None:
        if self._poll_id:
            try:
                self.widget.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001
                pass
            self._poll_id = None

    def request_cancel(self) -> None:
        self.cancel.set()


# ---------------------------------------------------------------- 小部件

def make_tree(master, columns, headings, widths=None, height=12, stretch_col=None):
    frame = ttk.Frame(master)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height,
                        selectmode="browse")
    for i, col in enumerate(columns):
        tree.heading(col, text=headings[i])
        w = widths[i] if widths and i < len(widths) else 100
        tree.column(col, width=w, anchor="w", stretch=(col == stretch_col))
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    return frame, tree


def labeled_entry(master, label, row, col=0, width=18, var=None, colspan=1):
    ttk.Label(master, text=label).grid(row=row, column=col, sticky="e", padx=(4, 6), pady=3)
    var = var if var is not None else tk.StringVar()
    ent = ttk.Entry(master, textvariable=var, width=width)
    ent.grid(row=row, column=col + 1, sticky="w", padx=(0, 10), pady=3, columnspan=colspan)
    return ent, var


def labeled_spin(master, label, row, col=0, width=8, var=None, frm=0, to=100):
    ttk.Label(master, text=label).grid(row=row, column=col, sticky="e", padx=(4, 6), pady=3)
    var = var if var is not None else tk.StringVar()
    sp = ttk.Spinbox(master, from_=frm, to=to, textvariable=var, width=width)
    sp.grid(row=row, column=col + 1, sticky="w", padx=(0, 10), pady=3)
    return sp, var


def set_text(widget: tk.Text, text: str, color: str | None = None) -> None:
    """写入只读 Text；``color`` 非空时整段上色（失败提示用红色）。"""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    if color:
        widget.tag_configure("setcolor", foreground=color)
        widget.insert("1.0", text, ("setcolor",))
    else:
        widget.insert("1.0", text)
    widget.configure(state="disabled")


def get_text(widget: tk.Text) -> str:
    return widget.get("1.0", "end").strip()
