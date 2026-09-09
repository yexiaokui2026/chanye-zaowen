# 产业朝闻 Skill 安装说明

本项目采用平台无关的 Skill 核心格式：`SKILL.md` 加上同级资源目录。平台插件清单只是可选适配层，不是 Skill 本体。

## 通用目录

```text
skills/chanye-zaowen/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

## WorkBuddy

下载 `dist/chanye-zaowen-workbuddy-v1.2.0.zip`，在 WorkBuddy 的“添加技能”中导入。导入包的顶层目录为 `chanye-zaowen/`。

## Claude Code

使用仓库中的 `.claude-plugin/marketplace.json` 和 `plugins/chanye-zaowen/` 插件入口，在 Claude Code 中按 README 的命令安装。

## 其他 AI

将 `skills/chanye-zaowen/` 作为本地 Skill 安装目录，确保 `SKILL.md`、`references/`、`scripts/` 和 `assets/` 保持相对路径不变。
