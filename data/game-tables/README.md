# 游戏数据表

`lib/d1tables.py` 在运行时从这里读取 DevilutionX 1.5.5 的源码数据表：

- `DevilutionX-1.5.5/Source/*.cpp|*.h`：物品、词缀、暗金、法术、背包占格
- `DevilutionX-1.5.5/Translations/zh_CN.po`：重建中文缓存时使用
- `devilutionX/assets/txtdata/items/*.tsv`：1.6.0 对照表，仅用于交叉校验
- `zh_CN.json`：`lib/data/zh_CN.json` 的参考副本

这些文件来自 DevilutionX 源码树，按 **GPL-3.0** 授权，详见
`LICENSE-DevilutionX.md` 与仓库根目录的 `NOTICE.md`。

打包脚本 `tools/build_exe.ps1` 会把本目录的 7 个 1.5.5 源码文件、
TSV 和 `lib/data/zh_CN.json` 一起放进 exe。

表的作用、版本差异和更新流程见 `最终定稿版/03-游戏数据表/README.md`
（仓库外单独保存的同一份资料）。
