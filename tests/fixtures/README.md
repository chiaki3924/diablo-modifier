# 测试存档样本

出于隐私与体积考虑，仓库不包含真实存档。需要跑完整测试时，把样本放到：

```
tests/fixtures/saves/stash.sv      # 储物箱样本（约 96 件物品即可）
tests/fixtures/saves/single_2.sv   # 角色存档样本（35 级角色）
```

也可以把整个目录指到别处：

```bat
set D1_TEST_SAVES=D:\my-saves-backup
```

缺少样本时，相关测试会打印 `SKIP` 并以退出码 0 结束；其余测试照常运行。

注意：测试只读写副本，不会改动真实 `%APPDATA%\diasurgical\devilution`
（`d1env.ALLOW_PROTECTED_WRITES=False`）。
