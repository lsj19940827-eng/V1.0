# 当前进度

- 当前正在做什么：收口 `codex/fix-pressure-pipe-reopen`，准备把“有压管道重开可恢复纵断面”等本轮改动合进主干。
- 上次停在哪个位置：已确认功能分支工作目录里的相关回归测试全绿，当前卡点转为主干收口和推送。
- 近期关键决定和原因：
- `routes[route_key].longitudinal_nodes` 继续作为 xx管 整线纵断面的事实来源；关闭返回后即使 `pipe / segment` 入口被清掉，重开弹窗也先按 `route_key` 恢复。
- `pipe / segment` 只保留为回退来源；覆盖不完整时继续保留 route 级缓存并提示补导入，不要求重复导入同一份 DXF。
- 这轮收口里出现的“2 条阻塞测试失败”并不是产品回退，而是从根目录跑测试时，`test_water_profile_transition_ready_unit.py` 会用 `Path('.')` 误加载根目录 `master` 的 `panel.py`；后续必须在功能分支 worktree 根目录原地跑这组测试。
- 根目录 `D:\V1.0` 的 `master` 当前带有另一套未提交改动，且内容与功能分支不同；主干合并和推送不能直接在这个脏工作区硬做，要避开覆盖用户现场。
