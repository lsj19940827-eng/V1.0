# 当前进度

- 当前正在做什么：把 `xx管` 的 `纵断面_管中心线` 改成“导入原线直出”，并把平面桩号采样与未来工程折点接口彻底拆开；代码、文档和真实样例回归都已补齐。
- 上次停在哪个位置：已经确认旧导出仍会回落到“平面桩号采样点硬连”，并补齐了 route 级 `raw_profile_polyline` 持久化、导出读取和画线优先级；随后新增了九龙右支管真实样例回归，验证当前绘图链路会按导入原线顶点序列出图。
- 近期关键决定和原因：
- `xx管` 纵断面画线改按用户导入时选中的原始纵断面多段线走；当前表格文字仍按 `centerline_records` 在平面桩号位置取值，`profile_breakpoint_records` 继续只表示工程折点接口。
- route 级新增 `raw_profile_polyline` 持久化字段，专门保存已套 `chainage_offset` 后的原线几何；这样重开弹窗、再次计算和导出都不再依赖原始 DXF 文件路径。
- `centerline_draw_segments` 现在优先由 `raw_profile_polyline` 裁切得到；`centerline_records` 继续给当前文字取值，`profile_breakpoint_records` 继续从 `longitudinal_nodes` 生成，三者不再混用。
- 新增 `tests/test_xxpipe_real_sample_unit.py`，用 `data/九龙右支管纵剖面图.dxf` 固化真实样例：当前代码内导出的 `纵断面_管中心线` 已按 395 个原线顶点出图，不再回退成旧导出文件里的 65 点采样折线。
- `routes[route_key].longitudinal_nodes` 仍是高程采样、coverage 判断和工程折点接口的事实来源；`routes[route_key].raw_profile_polyline` 则是原线画图事实来源，二者并存。
- 表3里的矩形暗涵继续保留旧兼容显示口径，避免已有 donor / 渐变段判断和历史断面引用被新名称误伤。
- `暗涵-圆拱直墙型` 在节点层显式保留家族类型与 `H_total + theta_deg`，水力公式走圆拱直墙型，渐变段、补段、建筑物长度和邻接规则统一按有效暗涵子类型处理。
- `xx管` 下方专表、隧洞摘要、隧洞覆盖校验和整线规则继续只认隧洞/管道链；暗涵家族仅进入上方普通表，避免混入 `xx管` 专链。
- 表3里的 `暗涵-圆拱直墙型` 只允许表1/共享结果带入，不提供手工新建入口；这样可以避免缺少 `theta_deg` 时被误算成不完整圆拱断面。
- 暗涵单页输入区的用户文案统一用“断面类型”，不再使用“子类型”，避免和表1/表3里的结构口径混淆。
- `routes[route_key].longitudinal_nodes` 继续作为 xx管 整线纵断面的事实来源；关闭返回后即使 `pipe / segment` 入口被清掉，重开弹窗也先按 `route_key` 恢复。
- 表3工具栏的 `插入渐变段 / 倒虹吸水力计算 / 有压管道水力计算 / 执行计算` 已决定保持原生禁用态，原因是必须保留按钮原生内核风格，并避免解锁后残留自定义灰样式。
