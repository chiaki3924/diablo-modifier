# 来源与版权说明

## 1. 代码来源

本仓库代码由项目发起人提出需求、制定规则并验收，DeepSeek（对话中的昵称
「蓝色大肥鱼」）作为 AI 协作者生成代码草稿和文档。双方的关系是「人类主导 +
AI 辅助」，不是 AI 独立创作。

## 2. 版权归谁

- 著作权归**项目发起人（人类作者）**所有。
- AI 工具（DeepSeek / 蓝色大肥鱼）不作为著作权主体，也不拥有代码版权。
- 项目发起人对需求取舍、规则设计、测试验收和最终文本负责；这些人类选择构成
  代码可版权性的基础。
- 仓库按 MIT 许可证发布，版权人为 GitHub 账号 `chiaki3924`（项目发起人）。

如果所在地区对 AI 生成内容的版权另有规定，以当地法律为准；本说明不构成法律意见。

## 3. `_d1pyc/`

`_d1pyc/` 是本项目早期编译出的 Python 3.12 字节码模块，用于读取
`.sv`/`.hsv` 存档与 MPQ 容器，属于本项目的一部分，随仓库按 MIT 发布。
它们只能被 Python 3.12 加载。

## 4. 游戏数据表

`data/game-tables/DevilutionX-1.5.5/` 与 `data/game-tables/devilutionX/`
来自 DevilutionX 源码树，版权归 DevilutionX 项目，按 **GPL-3.0** 授权。
这些文件未作修改，仅作为解析输入；完整许可证见
`data/game-tables/LICENSE-DevilutionX.md`。

DevilutionX 项目：<https://github.com/diasurgical/devilutionX>

## 5. 中文翻译

`lib/data/zh_CN.json` 与 `app/zh_fallback.json` 由 DevilutionX 1.5.5 的
`Translations/zh_CN.po` 生成；PO 文件同样属于 DevilutionX 项目（GPL-3.0）。
