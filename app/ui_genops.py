"""生成结果写入（储物箱 / 角色背包）—— 「装备生成」与「暗金图鉴」共用。

安全流程（两条路径都一样）：
  1. 游戏运行检测；
  2. 写入前 `.bak-时间戳` 备份（由 d1stash2 / d1save 与本模块共同保证）；
  3. 写入后重新打开文件校验（物品数必须 +N，逐字节比对）；
  4. 任何失败 → 用备份回滚并给出中文原因。
"""
from __future__ import annotations

import random

import ui_common as uic
from d1itemgen_adapter import add_to_backpack, friendly_error
from d1stash_adapter import StashUnavailable


def write_to_stash(app, results, label: str = "装备", page: int | None = None) -> bool:
    """把生成结果写进储物箱（每件一个 368 字节记录），写后重开校验 +N。

    ``page`` 是 **1-based** 页号（``None`` = 自动从最低页找空位/新建页）：
    逐件调 ``d1stash2.add_record(record, page=page-1)``——指定页放不下时
    d1stash2 会按页号顺序继续找，最后新建页；实际落到别的页时这里会给中文提示。
    """
    results = [r for r in (results or []) if r is not None]
    if not results:
        uic.warn("提示", "没有可写入的物品。")
        return False
    tab = app.tab_stash
    if tab.stash is None:
        uic.warn("提示", "请先在「储物箱」页打开 stash.sv。")
        return False
    if getattr(tab.stash, "is_readonly", False):
        uic.error("只读模式", "当前不能写入储物箱。")
        return False
    if not app.require_game_closed():
        return False
    page0 = None
    if page is not None:
        try:
            page0 = int(page) - 1
        except (TypeError, ValueError):
            uic.warn("页码有误", "「写入页码」必须是整数（留空 = 自动找空位/新建页）。")
            return False
        if page0 < 0:
            uic.warn("页码有误", "「写入页码」从 1 开始（1 = 第 1 页）。")
            return False
        if page0 >= 100:
            uic.warn("页码有误", "「写入页码」超出上限（最多 100 页）。")
            return False
    before = int(tab.stash.item_count())
    pages_before = sorted(tab.stash.pages())
    placed = []
    try:
        for r in results:
            if not r.record:
                raise StashUnavailable("生成结果没有 368 字节记录")
            pg, x, y = tab.add_record(r.record, r.name, page=page0)
            placed.append((r.name_cn or r.name or "?", pg, x, y))
        tab.flush()                      # 保存 + 写后逐字节校验 + 重新载入
    except Exception as exc:  # noqa: BLE001
        uic.error("写入储物箱失败", f"{friendly_error(exc)}\n\n（已尝试回滚，物品未丢失）")
        app.log(f"写入储物箱失败：{exc}", "err")
        return False
    after = int(tab.stash.item_count()) if tab.stash is not None else -1
    if after != before + len(results):
        uic.error("写入校验失败",
                  f"写入后储物箱物品数 {before} → {after}，预期 {before + len(results)}。\n\n"
                  "已保留写前备份（.bak-时间戳），请勿再写入，先反馈这个情况。")
        app.log(f"储物箱写入数量不符：{before} → {after}", "err")
        return False
    desc = "；".join(f"{n} → 第{p + 1}页({x},{y})" for n, p, x, y in placed[:6])
    app.log(f"{label}已写入储物箱（{len(results)} 件，{before} → {after}）：{desc}", "ok")
    want = f"第 {page0 + 1} 页" if page0 is not None else "自动空位"
    actual = sorted({p for _, p, _, _ in placed})
    extra = ""
    if page0 is not None and actual and page0 not in actual:
        detail = "、".join(f"第 {p + 1} 页" for p in actual)
        extra = (f"\n\n注意：指定的第 {page0 + 1} 页放不下（不存在或已满），"
                 f"这些物品被顺序放到了 {detail}。想固定页请先腾空该页，"
                 f"或把「写入页码」留空让程序自动找空位。")
        app.log(f"指定第 {page0 + 1} 页不可用，已顺延到 {detail}", "warn")
    elif page0 is not None and len(actual) > 1:
        extra = (f"\n\n注意：第 {page0 + 1} 页放不下全部 {len(results)} 件，"
                 f"余下的顺延到了后面几页（{ '、'.join(f'第{p+1}页' for p in actual) }）。")
    if page0 is not None and page0 not in pages_before and page0 not in actual:
        app.log(f"第 {page0 + 1} 页此前不存在", "warn")
    uic.info("成功",
             f"已生成 {len(results)} 件{label}到储物箱（物品数 {before} → {after}，已重开校验）。\n\n"
             f"写入位置（目标：{want}）：\n{desc}{extra}\n\n进游戏打开储物箱即可看到。")
    return True


def write_to_backpack(app, results) -> bool:
    """把生成结果写进角色背包（HeroPack.add_item + SaveFile.save）。"""
    results = [r for r in (results or []) if r is not None]
    if not results:
        uic.warn("提示", "没有可写入的物品。")
        return False
    hero = app.tab_char.hero
    if hero is None:
        uic.warn("提示", "请先在「角色」页选择一个角色存档。")
        return False
    if not app.require_game_closed():
        return False
    try:
        from d1hero import HeroEdit
        before = int(hero.pack.get("_pNumInv"))
        names = []
        for r in results:
            idx = r.runtime_idx
            if idx is None:
                idx = (r.fields or {}).get("idx")
            if idx is None:
                raise ValueError("生成结果缺少运行时 idx")
            seed = r.seed if r.seed is not None else (
                (r.fields or {}).get("iSeed") or random.SystemRandom().getrandbits(32))
            ci = r.create_info
            if ci is None:
                ci = (r.fields or {}).get("iCreateInfo", 0)
            if add_to_backpack(hero.sf, idx, seed, ci) is None:
                raise ValueError("背包已满，或该底材无法写入背包；请改用「生成到储物箱」")
            names.append(r.name_cn or r.name or (r.fields or {}).get("iName") or f"物品{idx}")
        msg = hero.save(clear_progress=False)
        after = int(HeroEdit(hero.path).pack.get("_pNumInv"))
    except Exception as exc:  # noqa: BLE001
        uic.error("写入背包失败", f"{friendly_error(exc)}\n\n存档未被修改。")
        app.log(f"写入背包失败：{exc}", "err")
        return False
    if after - before < len(results):
        app.log(f"背包写入不完整：{before} -> {after}（预期 +{len(results)}）", "warn")
        uic.warn("部分物品可能没进存档",
                 f"写入 {after - before} 件，预期 {len(results)} 件。请改用「生成到储物箱」。")
        return False
    app.log(f"已写入背包 {after - before} 件：{'、'.join(names)}（{msg}）", "ok")
    app.refresh_all(keep_char=True)
    uic.info("成功",
             f"已生成 {len(results)} 件装备到「{hero.name}」的背包"
             f"（物品数 {before} → {after}）。\n\n"
             "游戏会按 seed 自己重建物品；进游戏打开背包即可看到。")
    return True
