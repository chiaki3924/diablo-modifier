# 开发与打包

## 环境

- Windows x64 + **Python 3.12**（`_d1pyc` 内是 3.12 字节码）
- 运行时只用标准库和 tkinter；打包需要 PyInstaller

```bat
python -m pip install -r requirements.txt
```

## 从源码运行

```bat
python app\d1editor2.py
python app\d1editor2.py --selftest
```

`--selftest` 只读校验 `%APPDATA%` 下的真实存档，不写盘。自动测试模式
（`--selftest`、`D1_READONLY=1`）会拒绝写入真实存档。

## 打包单文件 exe

```bat
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
```

默认使用 PATH 里的 `python`；也可指定解释器：

```bat
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 -Python C:\Python312\python.exe
```

产物在 `dist\暗黑破坏神1存档修改器-v2.exe`，脚本末尾会自动跑 `--selftest`。
PyInstaller 会嵌入构建时间戳，重新打包的 SHA256 通常会变化，功能以自检为准。

## 测试

```bat
python tools\run_tests.py
```

部分测试需要存档样本，放在 `tests\fixtures\saves\`，或用环境变量指定：

```bat
set D1_TEST_SAVES=D:\saves-backup
```

缺少样本时相关测试打印 `SKIP` 并以 0 退出；其余测试照常运行。

## 目录结构

```
app\                   GUI 与适配层（入口 d1editor2.py）
lib\                   储物箱 / 物品生成 / 数据表 / 中文翻译
  data\zh_CN.json      游戏中文翻译缓存
_d1pyc\                Python 3.12 字节码模块（存档/编码/MPQ/RNG）
data\game-tables\      DevilutionX 1.5.5 数据表
tests\                 单元测试
tools\                 打包、中文兜底表生成、测试入口
docs\                  使用说明、测试报告、开发记录、截图
```

## 数据表

`lib\d1tables.py` 解析 `data/game-tables/DevilutionX-1.5.5/Source` 下的
1.5.5 源码表，而不是 1.6.0 的 TSV。两版数值不同（例如 Short Sword 耐久
20/价值 50 对 24/120），1.6.0 TSV 只用于交叉校验。

表的作用、版本差异和更新流程见 `最终定稿版/03-游戏数据表/README.md`。

## 许可

代码 MIT。`data/game-tables/` 下的 DevilutionX 源码和数据表按 GPL-3.0
授权，详见 `data/game-tables/LICENSE-DevilutionX.md` 和 `NOTICE.md`。
