# 当前进度

- 当前正在做什么：把剩余两条分支的有效改动继续收口进 `master`；本步先并入“命名尾段显示损失递推修复”，随后处理 `xx管` 夹带隧洞结构分表导出。
- 上次停在哪个位置：`master` 已收口蒲家湾 mixed route 第二份 DXF 边界与下方 xxpipe 表整高边界，并已推送到远端；但 `codex/merge-tail-pressure-last-loss`、`codex/xxpipe-tunnel-hydraulic-mode` 两个 worktree 里的未提交改动还没正式并入主干。
- 近期关键决定和原因：
- 命名尾段出口行在旧工程恢复和静默重算时，优先把 `_pressure_pipe_display_loss` 当作“本行正式承压损失”；原因是它代表列38里真正的本段值，不能只显示不参与递推。
- 总损失重建、累计损失和水位递推现在统一共用同一条本行损失口径；原因是要彻底消除“列38有值、列39是 `-`、累计值停在上一行”的错位。
- 已确认 `codex/merge-tail-pressure-last-loss` 相关测试 `28` 通过、`0` 失败；`codex/xxpipe-tunnel-hydraulic-mode` 相关测试 `139` 通过、`0` 失败，后续按“先提交分支、再合入主干”的方式收口。
