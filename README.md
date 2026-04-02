# V1.0 渠系计算工具

## 项目功能简介

这是一个本地桌面计算工具，用来处理渠系纵断面、水面线、倒虹吸、有压管道、土石方等工程计算与导出。
当前仓库重点包含表3水面线计算、渐变段联动、倒虹吸/有压管道结果回写，以及 xx管 的“整线纵断面 + 中心线高程导出 + 整线弹窗”规则。
普通纵断面与 xx管 现在都支持单独控制导出桩号小数位：普通模式默认 2 位，且会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 这类导出结果；xx管 继续只影响自己的纵断面桩号。
表3顶部“转弯半径”现在是一个统一应用入口：导入后默认保留每一行自己的半径，只有点击“应用”才会批量覆盖真实导入行。

## 技术架构

- 前端界面：`PySide6`，主要代码在 `app_渠系计算前端/`。
- 计算内核：Python 纯计算模块，主要代码在 `推求水面线/`、`calc_渠系计算算法内核/`。
- 专项模块：`倒虹吸水力计算系统/`、`有压管道/` 提供专项计算能力。
- 自动化验证：`pytest`，测试文件集中在 `tests/`，其中 xx管 整线纵断面会同时覆盖界面、持久化、计算和导出链路。
- 导出精度：普通模式导出桩号使用 `station_decimals`，xx管 导出桩号使用 `xxpipe_station_decimals`；两者都在导出链路单独格式化，不改主界面的通用桩号显示函数。

## 本地运行方法

1. 若本地还没有虚拟环境，先执行 `python -m venv .venv`。
2. Windows 环境可直接运行 `install_deps.bat` 安装依赖。
3. 启动程序使用 `D:\V1.0\.venv\Scripts\python.exe main.py`。

## 部署方法和命令

当前项目主要作为本地桌面工具使用，日常开发通常不做云端部署。
正式发版按仓库约定使用 `D:\V1.0\.venv\Scripts\python.exe tools/release.py`，也可通过 `发版工具.bat` 进入标准发版流程。

## 测试方法和常用命令

- 运行针对性测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py -q`
- 运行界面口径测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py -q`
- 运行本次相关回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_channel_level_options_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次窗口联动回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_window_override_unit.py tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 整线回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_longitudinal_utils_unit.py tests/test_pressure_pipe_spatial_calc_unit.py tests/test_xxpipe_export_context_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 弹窗与导出回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py -q`
- 运行本次普通纵断面桩号精度回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_text_export_settings_dialog_ui_unit.py tests/test_water_profile_longitudinal_scale_unit.py tests/test_water_profile_ip_table_export_unit.py tests/test_water_profile_bzzh2_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_water_profile_longitudinal_dedup_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行本次连续承压链回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_config_dialog_sizing_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_external_head_loss_unit.py`

## 搜索记录

- 2026-03-31：本次为现有功能修正和范围收口，未新增外部方案搜索，直接基于仓库现有逻辑与测试完成实现。

## 已完成功能列表

- 表3普通行、渐变段行、累计损失和水位递推的基础链路已接通。
- 倒虹吸和命名有压管道组支持外部专项计算后回写总损失。
- 空名称普通有压管道行现在可在 xx管 渠道级别下独立显示沿程损失、承压弯头损失和本行承压段总损失。
- 断面汇总弹窗里的有压管道参数现在按“流量段主行 + 顶管/定向钻单独行”显示；普通有压管道同一流量段只显示 1 行，确认后会自动同步到该流量段下全部普通有压管道原始分组。
- 匿名普通有压管道段的窗口结果会回写到当前行，并在后续静默重算中继续作为主来源，表3列38会锁定避免混改。
- 相关双击说明已经补齐，且总损失、水位、累计损失说明不会再把同一笔承压段损失重复展示。
- 隧洞沿程损失继续保持原有“底坡 × 有效长度”口径，没有被承压管道逻辑带偏。
- xx管 模式下，匿名普通有压管道紧邻定向钻、顶管或另一条匿名普通有压管道时，不再误弹补段；匿名普通有压管道与隧洞相邻时仍会保留前后两处渐变段。
- 普通有压管道/定向钻/顶管的渐变段长度详情，现已和插入阶段统一按 `5h/6h` 显示；当长度被压缩时，也会继续明确标出物理上限和最终采用值。
- xx管 有压管道窗口现在只保留整线卡：同一条纯“有压管道 / 定向钻 / 顶管”线路只导入一份平面/纵断面，弹窗里不再编辑子段 `R / D`。
- xx管 整线纵断面现按 `route_key` 持久化，空间长度、导出中心线高程和材料/建筑物分段都会先找整线数据，再按子段桩号裁切。
- 多个空名称 xx管 子段现在会优先使用 `pressure_pipe_row_identity` 区分，避免导出和纵断面取值时相互串用。
- 压力管道特性表里的设计流速和长度现在会按流量段逐行输出；其中长度会按该流量段下全部原始分组的起止桩号累计，普通有压管道段也会参与统计，不再误把定向钻、顶管、隧洞等建筑物长度小计当成整段总长。整条支管全为 `0` 转弯半径时，这个长度会与 IP 桩号口径一致；只要存在非 `0` 转弯半径，就会与里程桩号口径一致。
- 压力管道特性表里的隧洞、定向钻、顶管摘要长度，现统一按每组“出口里程MC - 进口里程MC”统计；出口后的普通有压管道首段不再误并进建筑物长度。
- xx管 弹窗里的纵断面 DXF 现在会在导入时立即校验整线导出节点是否都被覆盖，覆盖不足会直接拦截，不再“先导入、导出时再发现缺口”。
- 夹带隧洞的 xx管 整线当前不再进入有压管道水力计算，窗口会直接提示“暂不支持”并跳过该整线。
- 图2“管中心线高程（米）”继续在导出时按当前平面桩号现算；节点 `station_MC` 缺失时只对个别节点按平面累计距离回退，整线都没有有效桩号锚点时直接报错。
- 普通纵断面导出现在新增 `station_decimals`，默认保留 2 位小数；同一设置会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 的桩号输出，但不会改表3和说明文字的原有显示。
- 表3顶部“转弯半径”改成“待应用统一值”：导入混合半径时保持空白，点击“自动”只填栏位，点击“应用”才统一覆盖真实导入行。

## 待办事项

- 结合真实工程样表继续做界面联调，确认后续要不要恢复“有压管道夹带隧洞”的半兼容计算。
- 继续补充 route 覆盖不足、圆弧边界裁切、连续承压链，以及更多匿名子段组合场景的回归样例。
