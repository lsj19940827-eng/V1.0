# 当前上下文

## 正在做什么

- 正在准备发布 1.3.8，更新说明已由用户确认。
- 本轮发版前补齐发版脚本和 `.gitignore`：正式发版提交和 tag 需要同时推送 GitHub 与 Gitee；日志、工程数据、成果目录、授权工具脚本、缓存、构建产物、`.env` 和 `data/siphon_autosave.json` 仍不提交。

## 上次停在哪

- 已完成 GitHub/Gitee 仓库 README 清理，并同步到两个远端。
- 当前发版说明定稿为：多工况结果更好查看、断面图显示更稳定、结果摘要更完整。

## 关键决定

- GitHub Gist 仍是唯一正式 `version.json` 主入口，Gitee 只作为同一正式版本的备用下载源。
- `GITEE_TOKEN` 只从 `.env` 或环境变量读取，不写入代码；正式发版前缺少该令牌就提前停止。
- 客户端先尝试现有 GitHub/代理地址，失败或 SHA256 不一致时再尝试 Gitee 镜像；补丁失败回退全量包时也使用全量包候选地址列表。
- README 面向仓库访客，只保留功能、运行、测试、发版、自动更新和提交边界，不再堆叠内部过程记录。
- 发版脚本创建 Gitee Release 前，必须已把对应 release commit 和 tag 推到 Gitee，避免 Gitee Release 指到旧代码。
- `.gitignore` 需要覆盖根目录工程文件、日志、成果目录和授权快捷脚本，防止发版脚本 `git add -A` 误收本地产物。
