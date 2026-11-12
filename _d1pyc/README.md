# `_d1pyc` — Python 3.12 字节码模块

这些 `.pyc` 是存档/编码/MPQ/随机数底层模块：

```
d1save     .sv / .hsv 存档读写
d1codec    存档字段编解码
d1mpq      MPQ 容器读写
d1pkware   PKWARE 压缩/解压
d1rng      游戏同款随机数
d1items    物品尺寸/属性辅助
d1spells   法术表辅助
```

注意事项：

- 只能被 **Python 3.12** 加载；3.13/3.11 会报 magic number 不匹配。
- `d1stash2.py` 和 `d1env.py` 会在仓库根优先查找本目录。
- 打包脚本 `tools/build_exe.ps1` 会把本目录整体放进 exe 的 `_d1pyc`。
- 请保留为二进制 `.pyc`，不要当文本编辑；`.gitignore` 已显式放行本目录。
