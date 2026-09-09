# 产业朝闻 Skill

用于抓取、核验和编排《产业朝闻》，输出可用于135编辑器的公众号HTML、完整HTML源码和新闻来源链接核查表。

## 安装

将本仓库上传到GitHub后，在Claude Code中执行：

```text
/plugin marketplace add 你的GitHub用户名/你的仓库名
/plugin install chanye-zaowen@industry-morning-brief
```

安装完成后，可用自然语言调用；也可以使用命名技能：

```text
/chanye-zaowen:chanye-zaowen 制作9月10日的产业朝闻
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
