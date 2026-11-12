# 文档索引

| 文件 | 内容 |
|---|---|
| `使用说明.txt` | 面向玩家的操作说明（安装、备份、四页功能、Q&A） |
| `测试报告.md` | Round 1~7 的根因、测试数字、游戏内验证、已知限制 |
| `PROJECT_BRIEF.md` | 项目目标、存档格式、模块边界 |
| `ROUND7_BRIEF.md` | v2.5.0 的接口合同与验收记录 |
| `HANDOVER-ROUND7.md` | 最后一轮交接：改动文件、测试、已知限制 |
| `reports/` | 各子任务的技术报告（储物箱、物品生成、i18n、GUI、验证） |
| `shots/` | 界面截图（包含测试角色名，公开前可自行替换） |

## 路径说明

这些文档写于开发期，里面的 `work\app`、`work\lib`、`work\tests`、
`work\docs`、`work\build` 是当时的目录。对应现在的仓库布局：

```
work\app          -> app\
work\lib          -> lib\
work\tests        -> tests\
work\docs         -> docs\
work\build        -> tools\
work\backup_saves -> tests\fixtures\saves\（样本不入库）
work\tmp          -> tests\tmp\（临时目录，不入库）
```
