# 当前上下文

## 正在做什么

- 正在做 Gitee 镜像与 GitHub/Gitee 双下载源更新方案。
- 本轮只提交代码、测试、PRD/项目文档和必要上下文；日志、工程数据、成果目录、授权工具脚本、缓存、构建产物、`.env` 和 `data/siphon_autosave.json` 不提交。

## 上次停在哪

- 已完成更新器候选 URL 列表、Gitee Release 上传、镜像字段写入和相关单元测试。
- 接下来需要跑计划中的回归测试，再把本地 `master` 推到 GitHub，并用镜像方式覆盖 Gitee `master`。

## 关键决定

- GitHub Gist 仍是唯一正式 `version.json` 主入口，Gitee 只作为同一正式版本的备用下载源。
- `GITEE_TOKEN` 只从 `.env` 或环境变量读取，不写入代码；正式发版前缺少该令牌就提前停止。
- 客户端先尝试现有 GitHub/代理地址，失败或 SHA256 不一致时再尝试 Gitee 镜像；补丁失败回退全量包时也使用全量包候选地址列表。
