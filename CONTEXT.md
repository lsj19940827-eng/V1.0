# 当前进度

- 当前正在做什么：把 `codex/merge-tail-pressure-last-loss` 和 `codex/xxpipe-tunnel-hydraulic-mode` 两条分支继续收口进 `master`，当前处于冲突收口和最终验证阶段。
- 上次停在哪个位置：`master` 已完成蒲家湾 mixed route 第二份 DXF 边界与下方 xxpipe 表整高边界修复并推送到远端；剩余两条分支的 worktree 改动尚未正式并入主干。
- 近期关键决定和原因：
- 命名尾段出口行在旧工程恢复和静默重算时，优先把 `_pressure_pipe_display_loss` 当作正式本段损失；这样列38显示值会继续参与总损失、累计损失和水位递推，不再出现递推断层。
- `xx管` 夹带隧洞导出统一改成“上方普通渠道表 + 下方 xx管 表”双表结构；上表承接隧洞，下表只保留 `有压管道 / 定向钻 / 顶管`，让导出口径和现场理解一致。
- 隧洞参数真源统一收回表1/Excel；弹窗只保留只读摘要和缺项提示，不再新增独立录入链，避免同一数据出现多套来源。
- 已确认分支相关测试：`codex/merge-tail-pressure-last-loss` 合计 `28` 通过、`0` 失败；`codex/xxpipe-tunnel-hydraulic-mode` 合计 `139` 通过、`0` 失败。合并后还需在主干再做一次回归核对。
