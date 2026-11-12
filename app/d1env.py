"""暗黑破坏神1 存档修改器 v2 —— 环境适配层。

职责：
  * 定位并加载原修改器的 3.12 pyc 模块（d1save/d1codec/d1mpq/d1rng/d1items/d1spells）；
  * 定位仓库 lib/ 下的 d1stash2 / d1itemgen；
  * 存档目录扫描、游戏进程检测；
  * 写前备份 / 失败回滚（*.bak-YYYYmmdd-HHMMSS）；
  * 一些公共格式化。

本模块不依赖 tkinter，可被自检脚本单独 import。
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import time
import traceback
from pathlib import Path

APP_TITLE = "暗黑破坏神1 存档修改器 v2"
APP_VERSION = "2.6.0"

#: 允许写真实存档（%APPDATA%\diasurgical\devilution）。
#: GUI 正常使用时为 True；--selftest / 自动测试（smoke/shots）必须先置 False，
#: 这样任何代码路径误写真实存档都会直接抛异常，而不是悄悄改坏用户存档。
ALLOW_PROTECTED_WRITES = True


class ProtectedWriteError(RuntimeError):
    """试图在自动测试模式下写真实存档。"""


def is_protected_path(path) -> bool:
    """路径是否位于真实存档目录（%APPDATA%\\diasurgical\\devilution）。"""
    try:
        real = Path(path).resolve()
        base = settings_dir().resolve()
    except Exception:  # noqa: BLE001
        return False
    if real == base:
        return True
    try:
        real.relative_to(base)
        return True
    except ValueError:
        return False


def assert_writable(path) -> None:
    """写盘前的最后一道闸门（自动测试模式下禁止写真实存档）。"""
    if ALLOW_PROTECTED_WRITES:
        return
    if is_protected_path(path):
        raise ProtectedWriteError(
            f"自动测试模式禁止写入真实存档：{path}\n"
            "（请先复制到临时目录或 tests/fixtures 再操作）")

# ---------------------------------------------------------------- 路径

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """源码运行时 = 本文件所在目录；打包后 = exe 所在目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """PyInstaller 解包目录（源码模式返回 app 目录）。"""
    return Path(getattr(sys, "_MEIPASS", app_dir()))


def project_root() -> Path:
    """开发环境下的仓库根；打包后返回 app_dir。"""
    if is_frozen():
        return app_dir()
    here = Path(__file__).resolve()
    # 仓库布局：<root>/app/d1env.py 且 <root>/lib 存在。
    for parent in here.parents:
        if (parent / "app").is_dir() and (parent / "lib").is_dir():
            return parent
    return here.parents[1]


def pyc_search_dirs() -> list[Path]:
    """pyc 模块可能存在的目录，按优先级排列。"""
    dirs: list[Path] = []
    for base in (bundle_dir(), app_dir()):
        dirs.append(base / "_d1pyc")
    root = project_root()
    dirs.append(root / "_d1pyc")
    # 兼容旧工作区：原版 exe 解包目录仍可直接使用。
    dirs.append(root / "暗黑破坏神1存档修改器-by蓝色大肥鱼.exe_extracted" / "PYZ.pyz_extracted")
    dirs.append(root / "work" / "build" / "pyc")
    seen: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


def lib_search_dirs() -> list[Path]:
    """d1stash2.py / d1itemgen.py 所在目录。"""
    dirs: list[Path] = []
    for base in (bundle_dir(), app_dir()):
        dirs.append(base / "_d1lib")
        # 打包时 d1itemgen/d1tables 放在 _d1lib/py/，与源码布局一致。
        dirs.append(base / "_d1lib" / "py")
    root = project_root()
    dirs.append(root / "lib")
    dirs.append(root / "work" / "lib")
    seen: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


# ---------------------------------------------------------------- 模块加载

class ModuleBundle:
    """原修改器 pyc 模块集合。"""

    NAMES = ("d1codec", "d1mpq", "d1pkware", "d1rng", "d1items", "d1spells", "d1save")

    def __init__(self) -> None:
        self.dir: Path | None = None
        self.error: str | None = None
        self.modules: dict[str, object] = {}
        self._loaded = False

    # -- 加载 ------------------------------------------------------
    def load(self, force: bool = False) -> bool:
        if self._loaded and not force:
            return self.error is None
        self._loaded = True
        self.error = None
        self.modules = {}
        found = None
        for d in pyc_search_dirs():
            if (d / "d1save.pyc").is_file():
                found = d
                break
        if found is None:
            self.error = (
                "找不到 3.12 pyc 模块（d1save.pyc 等）。\n"
                "源码模式请确认仓库根目录存在 _d1pyc/（或原版 exe 解包目录）。"
            )
            return False
        self.dir = found
        p = str(found)
        if p not in sys.path:
            sys.path.insert(0, p)
        try:
            for name in self.NAMES:
                path = found / f"{name}.pyc"
                if not path.is_file():
                    continue
                if name in sys.modules:
                    mod = sys.modules[name]
                else:
                    mod = self._load_pyc(name, path)
                self.modules[name] = mod
        except Exception as exc:  # noqa: BLE001
            self.error = f"加载 pyc 模块失败：{exc}\n{traceback.format_exc(limit=3)}"
            return False
        if "d1save" not in self.modules:
            self.error = "d1save 模块加载失败（找不到或版本不匹配，需 Python 3.12）"
            return False
        return True

    @staticmethod
    def _load_pyc(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"无法为 {path} 建立 loader")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    # -- 便捷访问 ---------------------------------------------------
    def __getitem__(self, name: str):
        if not self._loaded:
            self.load()
        return self.modules[name]

    @property
    def d1save(self):
        return self["d1save"]

    @property
    def d1items(self):
        return self["d1items"]

    @property
    def d1codec(self):
        return self["d1codec"]

    @property
    def d1mpq(self):
        return self["d1mpq"]

    def ready(self) -> bool:
        return self.load() and "d1save" in self.modules


MODULES = ModuleBundle()


def lib_module(name: str):
    """加载 lib/ 下的模块（d1stash2 / d1itemgen）。

    返回 (module, error)。模块不存在时 module=None、error 为说明文字。
    """
    if name in sys.modules:
        return sys.modules[name], None
    for d in lib_search_dirs():
        path = d / f"{name}.py"
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, str(path))
            if spec is None or spec.loader is None:
                continue
            # 先加搜索路径：库可能 import 同目录的兄弟模块（如 d1tables）
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod, None
        except Exception as exc:  # noqa: BLE001
            sys.modules.pop(name, None)
            return None, f"加载 {path} 失败：{exc}"
    return None, f"未找到 {name}.py（应位于仓库 lib/）"


# ---------------------------------------------------------------- 存档目录

def settings_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "diasurgical" / "devilution"
    return Path.home() / "AppData" / "Roaming" / "diasurgical" / "devilution"


SAVE_SUFFIXES = (".sv", ".hsv")


def is_save_file(p: Path) -> bool:
    n = p.name.lower()
    return n.endswith(SAVE_SUFFIXES) and not n.endswith(".bak")


def list_save_files(directory: Path | None = None) -> list[Path]:
    directory = directory or settings_dir()
    if not directory.is_dir():
        return []
    out = [p for p in directory.iterdir() if p.is_file() and is_save_file(p)]
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def kind_of_save(p: Path) -> str:
    n = p.name.lower()
    if n.startswith("single_"):
        return "单人"
    if n.startswith("multi_"):
        return "多人"
    if n.startswith("spawn_"):
        return "Spawn"
    if n == "stash.sv":
        return "储物箱"
    return "其它"


def is_stash_path(p: Path) -> bool:
    n = p.name.lower()
    return n in ("stash.sv",) or "stash" in n


def detect_stash_multiplayer(p: Path) -> bool:
    """根据同目录下的角色存档粗略判断储物箱是单人还是多人。

    规则：存��里带 mpstashitems 块 → 多人。这里用最小 MPQ 解析避免依赖。
    """
    try:
        raw = p.read_bytes()
        if len(raw) < 32 or raw[:4] != b"MPQ\x1a":
            return False
        for token in (b"mpstashitems", b"spstashitems"):
            if token in raw:
                # 词表里的名字是加密的，命中概率低；作为额外线索
                return token == b"mpstashitems"
        import struct as _s
        hash_off, block_off = _s.unpack_from("<II", raw, 16)
        if not (0 < hash_off < len(raw)) or not (0 < block_off < len(raw)):
            return False
        return False
    except Exception:
        return False


# ---------------------------------------------------------------- 游戏进程

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def is_game_running() -> bool:
    """检查 devilutionx.exe（及旧版 Diablo.exe）是否在运行。"""
    if os.name != "nt":
        return False
    for image in ("devilutionx.exe", "DevilutionX.exe", "diablo.exe", "Diablo.exe"):
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                capture_output=True, text=True, timeout=8,
                creationflags=CREATE_NO_WINDOW,
                encoding="mbcs", errors="ignore",
            )
        except Exception:
            return False
        text = (out.stdout or "").lower()
        if image.lower() in text:
            return True
    return False


# ---------------------------------------------------------------- 备份/写保护

def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_file(path: Path | str, suffix: str | None = None) -> Path:
    """把 path 复制成同目录的 *.bak-YYYYmmdd-HHMMSS（重名自动加序号）。"""
    path = Path(path)
    suffix = suffix or f"bak-{timestamp()}"
    dst = path.with_name(f"{path.name}.{suffix}")
    i = 1
    while dst.exists():
        dst = path.with_name(f"{path.name}.{suffix}-{i}")
        i += 1
    shutil.copy2(path, dst)
    return dst


class WriteGuard:
    """写操作保护：进入时备份，异常时可用 rollback() 还原。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.backup: Path | None = None

    def __enter__(self) -> "WriteGuard":
        if self.path.is_file():
            self.backup = backup_file(self.path)
        return self

    def rollback(self) -> bool:
        if not self.backup or not self.backup.is_file():
            return False
        shutil.copy2(self.backup, self.path)
        return True

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def write_bytes_atomic(path: Path | str, data: bytes) -> None:
    """先写 .tmp 再替换，避免半截文件。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- 杂项

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def safe_name(x) -> str:
    if isinstance(x, bytes):
        try:
            return x.decode("utf-8", "ignore").strip("\x00").strip()
        except Exception:
            return x.hex()
    return str(x or "").strip("\x00").strip()


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v)
