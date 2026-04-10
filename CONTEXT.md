# 当前进度

- 当前正在做什么：补记“蒲家湾表2纵剖线2边界漏配修复”的阶段记录，收口 mixed route 第二份 DXF 边界与下方 xxpipe 表整高边界。
- 上次停在哪个位置：上一轮已修好罗家湾与蒲支 `2+739.785` 的导出误判，导出 lookup rows 已透传 route 上下文，但蒲家湾第二份纵剖线起点边界和末尾下方 xxpipe 表整高竖线口径还没统一。
- 近期关键决定和原因：
- 导入校验继续只负责判断非隧洞目标是否被 DXF 覆盖，不改已经验证通过的连续补导入与自动锚点链路。
- 导出取数统一为“优先子段，子段不足两点或覆盖不到当前行 `station_mc` 时回退整线 route”，这样首段边界行不会再被整段范围误伤。
- 隧洞节点只退出导出阶段的 `identity_mismatch / coverage` 强校验；若本身已有可用隧洞 profile / manager 数据，仍继续参与高程取数，避免把旧的隧洞导出能力一起关掉。
- 导出 lookup rows 持续透传 `station_mc / route_key / route_display_name / node_label / is_tunnel`，让共享导出链路按当前这一行的真实上下文做判断。
- 第二份纵剖线的起点边界改按当前节点桩号判断是否覆盖，避免 mixed route 后半段首个边界点被前一个有效中心线点误带偏。
- 末尾/下方 xxpipe 表的首尾整高竖线改按真实可见表格边界判断，不再跟着首个有效中心线点走，避免竖线穿到建筑物名称上边线。
- 本轮验证已完成：`tests/test_pressure_pipe_export_longitudinal_nodes_unit.py`、`tests/test_xxpipe_longitudinal_export_unit.py`、`tests/test_water_profile_combined_dxf_unit.py` 合计 `91` 通过、`0` 失败；GUI 全量文件与真实工程脚本这次还没重跑。
