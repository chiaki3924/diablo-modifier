"""角色存档（HeroPack）读写封装。

原修改器 d1save 的 HeroPack 字段布局：
  pHPBase(63) / pMaxHPBase(67) / pManaBase(71) / pMaxManaBase(75) 均为“1/64 单位”，
  即真实数值 = 字段值 >> 6。
  pHitPoints / pMaxHP 等只是内存态字段，不在 .sv 的 PlayerPack 里。

本模块只依赖 d1save 的公开/半公开接口（pack.get/set/set_*），
并用 d1save._OFFSETS 作为兜底直接读写 1266 字节缓冲。
"""
from __future__ import annotations

import struct
from pathlib import Path

from d1env import MODULES, WriteGuard, assert_writable, safe_name


class HeroError(RuntimeError):
    pass


def _tables():
    """``d1tables``（法术白名单、id->位图规则都在那里，懒加载）。"""
    try:
        import d1tables  # noqa: WPS433 - work/lib 通常已在 sys.path
        return d1tables
    except ImportError:
        pass
    from d1env import lib_module  # 打包/源码两种布局都由 d1env 定位
    mod, err = lib_module("d1tables")
    if mod is None:
        raise HeroError(f"无法加载 d1tables：{err}")
    return mod


def learnable_spells(multiplayer: bool = False) -> list[dict]:
    """1.5.5 原版可学习法术白名单（单人 22 条，多人 23 条）。"""
    return _tables().learnable_spells(multiplayer=multiplayer)


def spell_bitmask(spell: int) -> int:
    """``pMemSpells`` 里某个法术的位：id 1 -> bit 0，即 ``1 << (id-1)``。"""
    return _tables().spell_bitmask(spell)


def non_original_spells() -> list[int]:
    """不属于 1.5.5 单人法术书的 id（Hellfire 37~46 + 不可学习法术）。"""
    return [int(sid) for sid in _tables().non_original_spells()]


#: 单机存档的 ``game`` 块里保存着完整 ``Player``（LoadGame→LoadPlayer），
#: 其中 ``_pSplLvl[64]`` 位于角色名之前 127 字节。原版编辑器按 ``_pSplLvl[52]``
#: 算成 “名字-115”，导致法术等级整体错位 12 字节（游戏里表现为：新法术显示
#: 0 级不可用、已有法术不升级）。
GAME_SPELLS_BEFORE_NAME = 127
GAME_SPELL_SLOTS = 52          # 1.5.5 MAX_SPELLS

_GAME_FIX_FLAG = "_d1_game_spell_sync_fixed"


def _install_game_spell_sync_fix() -> None:
    """修正原版编辑器写 ``game`` 块时的法术偏移（只能运行时猴补）。"""
    cls = getattr(MODULES.d1save, "SaveFile", None)
    if cls is None or getattr(cls, _GAME_FIX_FLAG, False):
        return
    original = cls.build_game_payload
    off = _offsets()
    hero_spell = int(off["pSplLvl"])
    hero_spell2 = int(off.get("pSplLvl2", hero_spell + 1143))

    def build_game_payload(self):
        ok, payload, note = original(self)
        if not ok or not payload:
            return ok, payload, note
        try:
            raw, pw = self.read_named_file("game")
            if not raw or not pw:
                return ok, payload, note
            rec = self._locate_player_record(raw)
            if rec is None:
                return ok, payload, note
            hero = bytes(self.pack.buf)
        except Exception:  # noqa: BLE001 - 没有 game 块/非角色存档
            return ok, payload, note
        buf = bytearray(MODULES.d1save.codec_decode(payload, pw))
        start = int(rec) - GAME_SPELLS_BEFORE_NAME
        if start < 0 or start + GAME_SPELL_SLOTS > len(buf):
            return ok, payload, note
        for i in range(37):
            buf[start + i] = hero[hero_spell + i]
        for i in range(10):
            buf[start + 37 + i] = hero[hero_spell2 + i]
        for i in range(47, GAME_SPELL_SLOTS):
            buf[start + i] = 0
        return ok, MODULES.d1save.codec_encode(bytes(buf), pw), note

    cls.build_game_payload = build_game_payload
    setattr(cls, _GAME_FIX_FLAG, True)


def _offsets() -> dict:
    d1save = MODULES.d1save
    off = getattr(d1save, "_OFFSETS", None)
    if isinstance(off, dict) and "pHPBase" in off:
        return off
    # 兜底：从 _SCALARS 拼
    out = {}
    for item in getattr(d1save, "_SCALARS", []):
        try:
            name, fmt, o = item
            out[name] = o
        except Exception:
            continue
    return out


class HeroEdit:
    """一个角色存档的编辑会话。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise HeroError(f"文件不存在：{self.path}")
        d1save = MODULES.d1save
        _install_game_spell_sync_fix()
        try:
            self.sf = d1save.SaveFile(str(self.path))
        except Exception as exc:  # noqa: BLE001
            raise HeroError(f"无法解析角色存档：{exc}") from exc
        self.pack = self.sf.pack
        self._orig = self._snapshot()

    # ---------------------------------------------------------- 读取
    def _snapshot(self) -> dict:
        return {
            "name": self.name,
            "level": self.level,
            "exp": self.exp,
            "gold": self.gold,
        }

    @property
    def name(self) -> str:
        return safe_name(getattr(self.pack, "name", ""))

    @property
    def hero_class(self) -> int:
        return int(getattr(self.pack, "hero_class", 0) or 0)

    @property
    def class_name_cn(self) -> str:
        names = getattr(MODULES.d1save, "CLASS_NAMES_CN", None) or []
        try:
            return names[self.hero_class]
        except Exception:
            return f"职业{self.hero_class}"

    @property
    def level(self) -> int:
        return int(self.pack.level)

    @property
    def exp(self) -> int:
        return int(self.pack.get("pExperience"))

    @property
    def gold(self) -> int:
        return int(self.pack.gold)

    @property
    def stat_points(self) -> int:
        return int(self.pack.get("pStatPts"))

    @property
    def stats(self) -> dict:
        s = self.pack.stats
        return {"str": int(s.get("str", 0)), "mag": int(s.get("mag", 0)),
                "dex": int(s.get("dex", 0)), "vit": int(s.get("vit", 0))}

    @property
    def hp(self) -> tuple[int, int]:
        return (int(self.pack.get("pHPBase")) >> 6, int(self.pack.get("pMaxHPBase")) >> 6)

    @property
    def mana(self) -> tuple[int, int]:
        return (int(self.pack.get("pManaBase")) >> 6, int(self.pack.get("pMaxManaBase")) >> 6)

    @property
    def spell_levels(self) -> list[int]:
        """全部 ``pSplLvl`` 等级：0~36 + Hellfire 的 37~46（共 47 个）。"""
        levels = [int(x) for x in self.pack.spell_levels]
        while len(levels) < 47:
            levels.append(0)
        return levels

    @property
    def visible_spells(self) -> list[dict]:
        """法术页可见的白名单（1.5.5 原版单人 22 条）。"""
        return learnable_spells()

    @property
    def known_spells(self) -> list[tuple[int, int]]:
        return [(i, lvl) for i, lvl in enumerate(self.spell_levels) if lvl > 0]

    @property
    def hidden_spell_levels(self) -> list[tuple[int, int]]:
        """存档里有等级、但不在白名单里的法术（地狱火/职业自带/不可学习）。

        界面只用于只读提示，绝不修改它们。
        """
        white = {int(row["index"]) for row in self.visible_spells}
        return [(sid, lvl) for sid, lvl in enumerate(self.spell_levels)
                if sid > 0 and lvl > 0 and sid not in white]

    @property
    def max_level(self) -> int:
        try:
            return int(MODULES.d1save.MAX_CHARACTER_LEVEL)
        except Exception:
            return 50

    def next_level_exp(self) -> int:
        """升到下一级所需经验；满级返回 0。"""
        try:
            exp_lvls = MODULES.d1save.EXP_LVLS
        except Exception:
            return 0
        lvl = self.level
        if lvl >= len(exp_lvls) - 1:
            return 0
        return int(exp_lvls[lvl])

    # ---------------------------------------------------------- 修改
    def set_level(self, lvl: int) -> None:
        lvl = max(1, min(self.max_level, int(lvl)))
        self.pack.set_level(lvl)

    def set_stats(self, str_=None, mag=None, dex=None, vit=None, recalc: bool = True) -> None:
        self.pack.set_stats(str_=str_, mag=mag, dex=dex, vit=vit, clamp=True,
                            full=bool(recalc))

    def set_stat_points(self, pts: int) -> None:
        self.pack.set("pStatPts", max(0, min(255, int(pts))))

    def set_exp(self, exp: int) -> None:
        exp = max(0, min(0xFFFFFFFF, int(exp)))
        self.pack.set_experience(exp)

    def set_gold(self, amount: int) -> int:
        """设置角色金币，返回实际生效的数值。

        d1save 会把金币拆成一堆堆（每堆 ≤5000）放进背包，背包格子不够时
        会**少放**。返回值和请求值不同就说明被空间限制了。
        """
        amount = max(0, min(0x7FFFFFFF, int(amount)))
        self.pack.set_gold(amount)
        return self.gold

    def set_pools(self, hp=None, max_hp=None, mana=None, max_mana=None) -> None:
        """直接写 1/64 单位字段。调用前应先完成等级/属性修改。"""
        set_ = self.pack.set
        if max_hp is not None:
            set_("pMaxHPBase", max(1, int(max_hp)) * 64)
        if hp is not None:
            set_("pHPBase", max(1, int(hp)) * 64)
        if max_mana is not None:
            set_("pMaxManaBase", max(0, int(max_mana)) * 64)
        if mana is not None:
            set_("pManaBase", max(0, int(mana)) * 64)
        cur_hp, max_hp2 = self.hp
        if cur_hp > max_hp2:
            set_("pHPBase", max_hp2 * 64)
        cur_mp, max_mp = self.mana
        if cur_mp > max_mp:
            set_("pManaBase", max_mp * 64)

    def set_spell_level(self, spell: int, level: int) -> None:
        """原子地设置单个法术等级（0 = 遗忘）。

        读出全部 47 个等级 → 只改目标 → 写回全部字节；``pMemSpells`` 只更新
        目标法术自己的位。其它法术（含隐藏的 Hellfire/职业法术）的等级和位
        保持不变，因此职业自带技能那种「位=1、等级=0」的状态不会被抹掉。
        """
        sid = int(spell)
        levels = self.spell_levels
        if not (0 <= sid < len(levels)):
            raise HeroError(f"法术编号超出范围（0~{len(levels) - 1}）：{sid}")
        levels[sid] = max(0, min(15, int(level)))
        self._write_spell_levels(levels, changed={sid})

    def set_spell_levels(self, levels: dict) -> None:
        """一次设置多个法术等级（``{spell_id: level}``），其余法术不动。"""
        cur = self.spell_levels
        changed = set()
        for key, value in dict(levels).items():
            sid = int(key)
            if not (0 <= sid < len(cur)):
                raise HeroError(f"法术编号超出范围（0~{len(cur) - 1}）：{sid}")
            cur[sid] = max(0, min(15, int(value)))
            changed.add(sid)
        self._write_spell_levels(cur, changed=changed)

    def _write_spell_levels(self, levels: list[int], changed=None) -> None:
        """写回全部 ``pSplLvl`` 字节，并按 ``1 << (id-1)`` 更新 ``pMemSpells``。

        ids 0~36 在 ``pSplLvl``（offset 79），Hellfire 的 37~46 在
        ``pSplLvl2``（offset 1222）。

        ``changed`` 是「本次真的改了等级」的法术 id 集合；位图**只**动这些位，
        其它位（隐藏/职业法术、以及超出 47 的 Hellfire 位）原样保留。不传
        ``changed`` 时才按全部 1..46 的等级重算（仅供显式全量重建）。
        """
        off = _offsets()
        try:
            start = int(off["pSplLvl"])
            mem = int(off["pMemSpells"])
        except KeyError:
            return
        buf = self.pack.buf
        values = [max(0, min(255, int(x))) for x in levels]
        first = min(len(values), 37)
        for i in range(first):
            if start + i < len(buf):
                buf[start + i] = values[i]
        start2 = off.get("pSplLvl2")
        if start2 is None:
            start2 = start + 1143
        start2 = int(start2)
        for i in range(37, min(len(values), 47)):
            pos = start2 + (i - 37)
            if pos < len(buf):
                buf[pos] = values[i]
        if changed is None:
            changed = range(1, len(values))
        bits = struct.unpack_from("<Q", buf, mem)[0]
        for sid in changed:
            sid = int(sid)
            if not (1 <= sid < len(values)):
                continue
            mask = 1 << (sid - 1)
            if values[sid] > 0:
                bits |= mask
            else:
                bits &= ~mask
        struct.pack_into("<Q", buf, mem, bits & 0xFFFFFFFFFFFFFFFF)

    def spell_bit_mismatches(self) -> list[tuple[int, int, int]]:
        """只读诊断：等级与 ``pMemSpells`` 位不一致的 ``(spell, level, bit)``。

        正确规则是 ``bit = 1 << (id-1)``（id 1 = Firebolt = bit 0）。诊断范围：

        * 白名单（可见）法术：位和等级必须一致，两个方向都报；
        * 隐藏/职业法术：**只报**「等级>0 但位=0」。反向的「位=1、等级=0」是
          正常的职业技能状态（游戏靠位授予），不能当成错误。

        返回空列表说明存档位图自洽。
        """
        levels = self.spell_levels
        try:
            mem = int(_offsets()["pMemSpells"])
        except (KeyError, TypeError):
            return []
        bits = struct.unpack_from("<Q", self.pack.buf, mem)[0]
        visible = {int(row["index"]) for row in self.visible_spells}
        out = []
        for sid in range(1, len(levels)):
            bit = (bits >> (sid - 1)) & 1
            lvl = int(levels[sid])
            if sid in visible:
                if (lvl > 0) != bool(bit):
                    out.append((sid, lvl, bit))
            elif lvl > 0 and not bit:
                out.append((sid, lvl, bit))
        return out

    def learn_all(self, level: int = 15) -> None:
        """把白名单里的 22 个原版法术设为 ``level`` 级，隐藏法术不动。"""
        lvl = max(1, min(15, int(level)))
        levels = self.spell_levels
        changed = set()
        for row in self.visible_spells:
            sid = int(row["index"])
            levels[sid] = lvl
            changed.add(sid)
        self._write_spell_levels(levels, changed=changed)

    def forget_all(self) -> None:
        """只遗忘白名单里的可见法术；隐藏/职业法术的等级与位都保留。"""
        levels = self.spell_levels
        changed = set()
        for row in self.visible_spells:
            sid = int(row["index"])
            levels[sid] = 0
            changed.add(sid)
        self._write_spell_levels(levels, changed=changed)

    def clear_non_original_spells(self) -> list[int]:
        """清理“非 1.5.5 原版”法术：Hellfire 37~46 + 单人不可学习法术。

        把这些法术的等级置 0、``pMemSpells`` 对应位清 0，返回被清理的 id。
        22 条原版白名单和 26/27/28 三个职业自带能力（位与等级）保持不动。
        """
        targets = [sid for sid in non_original_spells()
                   if 0 <= sid < len(self.spell_levels)]
        levels = self.spell_levels
        for sid in targets:
            levels[sid] = 0
        # 全部目标都进 changed：即使等级已经是 0，残留的位也要清掉
        self._write_spell_levels(levels, changed=set(targets))
        return targets

    # ---------------------------------------------------------- 保存
    def save(self, clear_progress: bool = False, sync_game: bool = False) -> str:
        """写回存档。写前做两层备份；失败自动回滚并抛 HeroError。"""
        assert_writable(self.path)      # 自动测试模式下禁止写真实存档
        msg = ""
        with WriteGuard(self.path) as guard:
            try:
                res = self.sf.save(out_path=str(self.path), backup=True,
                                   sync_game=sync_game, clear_progress=clear_progress)
                if isinstance(res, tuple):
                    msg = str(res[1]) if len(res) > 1 else ""
                elif res:
                    msg = str(res)
                self._verify()
            except Exception as exc:  # noqa: BLE001
                restored = guard.rollback()
                hint = "已回滚到备份" if restored else "回滚失败，请手动用 .bak 恢复"
                raise HeroError(f"保存失败：{exc}\n{hint}") from exc
        return msg or "保存成功"

    def _verify(self) -> None:
        d1save = MODULES.d1save
        sf = d1save.SaveFile(str(self.path))
        check = sf.pack
        if safe_name(getattr(check, "name", "")) != self.name:
            raise HeroError("写后校验失败：角色名不一致")
        if int(check.level) != self.level:
            raise HeroError("写后校验失败：等级不一致")
        self._verify_game_spells(sf)

    def _verify_game_spells(self, sf) -> None:
        """``game`` 块里也有一份 ``_pSplLvl``（进游戏后以它为准），必须同步。"""
        try:
            # read_named_file 已经解过码，返回的是明文 game 块
            data, pw = sf.read_named_file("game")
            if not data or not pw:
                return
            rec = sf._locate_player_record(data)
            if rec is None:
                return
        except Exception:  # noqa: BLE001 - 老版本存档可能没有 game 块
            return
        start = int(rec) - GAME_SPELLS_BEFORE_NAME
        if start < 0 or start + GAME_SPELL_SLOTS > len(data):
            return
        want = bytes(max(0, min(255, int(x)))
                     for x in self.spell_levels[:GAME_SPELL_SLOTS])
        want += b"\x00" * (GAME_SPELL_SLOTS - len(want))
        got = bytes(data[start:start + GAME_SPELL_SLOTS])
        if got == want:
            return
        bad = [i for i in range(GAME_SPELL_SLOTS) if got[i] != want[i]][:6]
        raise HeroError(
            "写后校验失败：game 块法术等级未同步（"
            + ", ".join(f"{i}:{got[i]}→{want[i]}" for i in bad) + "）")

    # ---------------------------------------------------------- 展示
    def summary(self) -> str:
        return f"{self.name} · {self.class_name_cn} · {self.level} 级"

    def reload(self) -> None:
        self.__init__(self.path)
