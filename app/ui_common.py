"""界面公共部件与工具。"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

HEADLESS = False

# 暖白纸面、墨色正文、暗红主操作；灰色只用于辅助信息和分隔。
BG = "#F5F2EC"
SURFACE = "#FFFEFB"
TEXT = "#27231F"
MUTED = "#716A61"
BORDER = "#D8D0C4"
ACCENT = "#8A3033"
ACCENT_ACTIVE = "#6E2427"
SELECT = "#E9DED2"


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
    """生成失败的提示框：一句结论 + 必要的正文，最多带两条建议。

    ``detail`` 只为兼容旧调用保留，不再展示内部技术细节。
    ``modal=False`` 时立即返回 Toplevel（截图/自动化用）；``HEADLESS`` 时只打印。
    """
    if HEADLESS or parent is None:
        print(f"[WARN] {title}: {headline}")
        if message:
            print(message)
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
              wraplength=560, justify="left").pack(anchor="w", fill="x")
    if message:
        ttk.Label(frame, text=message, wraplength=560, justify="left").pack(
            anchor="w", fill="x", pady=(8, 0))
    tips = [str(s).strip() for s in suggestions if str(s).strip()][:2]
    if tips:
        ttk.Label(frame, text="\n".join("· " + s for s in tips), wraplength=540,
                  justify="left").pack(anchor="w", fill="x", pady=(8, 0))
    ttk.Button(frame, text="关闭", command=top.destroy).pack(anchor="e", pady=(12, 0))
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
    """紧凑的浅色桌面工具样式，主操作与选中态使用同一暗红家族。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    family = pick_font()
    base = 10
    try:
        root.configure(background=BG)
    except tk.TclError:
        pass
    root.option_add("*Font", (family, base))
    root.option_add("*Menu.background", SURFACE)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", SELECT)
    root.option_add("*Menu.activeForeground", TEXT)
    style.configure(".", font=(family, base), background=BG, foreground=TEXT)
    for name in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label",
                 "TRadiobutton", "TCheckbutton", "TNotebook"):
        style.configure(name, background=BG, foreground=TEXT)
    style.configure("TButton", padding=(11, 5), background=SURFACE,
                    bordercolor=BORDER, focuscolor=ACCENT)
    style.map("TButton", background=[("disabled", BG), ("pressed", SELECT),
                                     ("active", "#F0E8DE")],
              bordercolor=[("active", ACCENT)],
              foreground=[("disabled", "#A79E93")])
    style.configure("Primary.TButton", padding=(14, 6), background=ACCENT,
                    foreground="#FFFFFF", bordercolor=ACCENT)
    # 禁用态必须是「一眼看出不能点」：深红底 + 浅字几乎和可用态一样，
    # 只读模式下「保存金币」这类按钮会被误认为仍可点，所以背景退回浅灰。
    style.map("Primary.TButton",
              background=[("disabled", "#E7DFD5"), ("pressed", ACCENT_ACTIVE),
                          ("active", ACCENT_ACTIVE)],
              foreground=[("disabled", "#A79E93")],
              bordercolor=[("disabled", BORDER)])
    style.configure("TNotebook", borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", padding=(18, 7), background="#E9E3DA",
                    foreground=MUTED)
    style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", SELECT)],
              foreground=[("selected", ACCENT), ("active", TEXT)])
    style.configure("TLabelframe", padding=10, bordercolor=BORDER)
    style.configure("TLabelframe.Label", font=(family, base, "bold"), foreground=TEXT)
    style.configure("Title.TLabel", font=(family, base + 2, "bold"), foreground=TEXT)
    style.configure("Sub.TLabel", foreground=MUTED)
    style.configure("Ok.TLabel", foreground="#28734A")
    style.configure("Bad.TLabel", foreground="#A1262B")
    style.configure("Hint.TLabel", foreground=MUTED)
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, padding=4, fieldbackground=SURFACE,
                        background=SURFACE, bordercolor=BORDER, arrowcolor=TEXT)
        style.map(name, bordercolor=[("focus", ACCENT)],
                  fieldbackground=[("readonly", SURFACE), ("disabled", BG)])
    style.configure("Treeview", rowheight=26, font=(family, base),
                    background=SURFACE, fieldbackground=SURFACE, bordercolor=BORDER)
    style.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "#FFFFFF")])
    style.configure("Treeview.Heading", font=(family, base, "bold"),
                    background="#EEE8DF", foreground=TEXT, padding=(5, 6))
    style.map("Treeview.Heading", background=[("active", SELECT)])
    style.configure("TSeparator", background=BORDER)
    return style


def more_button(master, items) -> ttk.Menubutton:
    """功能区内的低频操作入口；items 中的 None 表示分隔线。"""
    menu = tk.Menu(master, tearoff=0, background=SURFACE, foreground=TEXT,
                   activebackground=SELECT, activeforeground=TEXT)
    for item in items:
        if item is None:
            menu.add_separator()
        else:
            label, command = item
            menu.add_command(label=label, command=command)
    return ttk.Menubutton(master, text="更多", menu=menu)


# ---------------------------------------------------------------- 日志

class LogPane(ttk.Frame):
    """窗口底部日志（只读）。"""

    def __init__(self, master, height=5, **kw):
        super().__init__(master, **kw)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled",
                            relief="flat", background=SURFACE, foreground=TEXT)
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
