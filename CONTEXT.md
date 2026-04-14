# 当前进度

- 当前正在做什么：已完成“有压管道重开可恢复纵断面”这一轮主干收口，当前停在 `master`，等待下一项任务。
- 上次停在哪个位置：刚在 `master` 上复跑本轮相关回归，并清理掉本地整理分支 `codex/master-merge-pressure-pipe-reopen`。
- 近期关键决定和原因：
- `routes[route_key].longitudinal_nodes` 继续作为 xx管 整线纵断面的事实来源；关闭返回后即使 `pipe / segment` 入口被清掉，重开弹窗也先按 `route_key` 恢复。
- `pipe / segment` 只保留为回退来源；覆盖不完整时继续保留 route 级缓存并提示补导入，不要求重复导入同一份 DXF。
- 本轮主干验证已在 `master` 上通过，当前 `master` 与 `origin/master` 保持同一提交，可直接从主干继续后续工作。
