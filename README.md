# 产业朝闻 Skill

用于抓取、核验和编排《产业朝闻》，输出可用于135编辑器的公众号HTML、完整HTML源码和新闻来源链接核查表。

## 安装

本仓库同时提供 Claude 插件入口、通用 Skill 目录和 WorkBuddy 导入包。不同 AI 平台使用同一份 `SKILL.md` 和配套资源，不需要重新编写 Skill。

### Claude Code

将本仓库上传到 GitHub 后执行：

```text
/plugin marketplace add 你的GitHub用户名/你的仓库名
/plugin install chanye-zaowen@industry-morning-brief
```

安装完成后，可用自然语言调用；也可以使用命名技能：

```text
/chanye-zaowen:chanye-zaowen 制作9月10日的产业朝闻
```

### WorkBuddy

下载 `dist/chanye-zaowen-workbuddy-v1.2.0.zip`，在 WorkBuddy 的“添加技能”中导入这个 zip。压缩包内的顶层目录是 `chanye-zaowen/`，包含 `SKILL.md`、`references/`、`scripts/` 和 `assets/`。

### 其他支持通用 Skill 的 AI

使用 `skills/chanye-zaowen/` 作为 Skill 目录，入口文件是其中的 `SKILL.md`。保留同级的 `references/`、`scripts/` 和 `assets/`，不要只复制单独的 Markdown 文件。

通用 Skill 源码位于：

```text
skills/chanye-zaowen/
```

WorkBuddy 导入包位于：

```text
dist/chanye-zaowen-workbuddy-v1.2.0.zip
```

## 本地测试

```text
claude --plugin-dir ./plugins/chanye-zaowen
```

然后执行：

```text
/chanye-zaowen:chanye-zaowen 制作9月10日的产业朝闻
```

## 规则

硬性最低数量为：热点至少3条、国际至少3条、国内至少4条、企业至少6条、宏观至少3条；这些是最低数量，不是固定配额，也不是上限。

企业动态优先纳入苹果、台积电、小米等大公司及其领导人的产业相关新闻。宏观政策必须核对官方网站；来源不能全部依赖财联社。
