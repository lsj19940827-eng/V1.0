# 当前进度

- 当前正在做什么：已完成“在线更新全面加固方案”的主线代码、测试和相关文档同步，并已执行线上止损，把 `v1.3.0` 的 Gist patch 入口撤下，只保留全量更新。
- 上次停在哪个位置：更新链路已补上运行时文件排除、下载包 checksum、补丁落地后目标验收、备份失败回收、回滚状态区分，以及发版快照/回补 patch 脚本；当前线上已先停用高风险 patch，后续如需恢复，只能按快照规则重新回补。
- 近期关键决定和原因：
- 运行时文件（如 `siphon_autosave.json`、`data/autosave/`、`*_autosave.qxproj`）统一视为用户数据：不再进 manifest、patch 严格哈希校验，也会在成功安装后保留，避免用户正常使用后被误判成“补丁不适用”。
- 下载链路统一补上发布级 checksum：全量包和 patch 都会先验包再安装；补丁应用完成后还会按 `target_files` 再做一次目标版本验收，避免“旧文件对了，但新文件没真正落到位”。
- 正式发版新增不可变快照：`tag / full zip / patch zip / manifest / version.json` 会一起固化到 `.release-snapshots/`；后续回补 patch 必须基于快照，不再依赖可能漂移的本地 `dist` 或手工改过的 manifest。
- 线上处理先止损后修复：现网 `v1.3.0` patch 仍是高风险旧链路产物，因此先只撤 Gist 中的 patch 字段，不删 Release 资产；等带 checksum 和快照约束的新发版链路真正上线后，再决定是否按快照回补 patch。
