# V1.0 渠系计算工具

## 项目功能简介

这是一个本地桌面计算工具，用来处理渠系纵断面、水面线、倒虹吸、有压管道、土石方等工程计算与导出。
当前版本的明渠模块已经补齐 `复式梯形` 断面，支持在明渠设计面板中直接输入 `m1 / B1 / m2 / B2 / m3 / h1` 六个固定参数完成计算，并把同一断面同步带到批量计算和推求水面线兼容链路。
当前仓库重点包含表3水面线计算、渐变段联动、倒虹吸/有压管道结果回写，以及连续承压线路的“整线纵断面 + 中心线高程导出 + 整线弹窗”规则。
`xx渠` 末尾连续承压中的命名 `有压管道 / 定向钻 / 顶管` 现在也改成逐行正式计损：表3里每一行都会显示自己的承压段损失，并直接参与总损失、累计损失和水位递推；整组总损失仍保留在有压管道窗口里供对照。
xx管 现在已经支持“有压管道 / 定向钻 / 顶管”整线里夹带隧洞：用户仍只导入 1 份纵断面 DXF，但这份 DXF 只覆盖非隧洞段；隧洞段改为按“进口底高 + 坡降 i + 起终桩号”自动生成，并与整线 DXF 在导出和计算时按桩号拼接。
有压管道窗口现在改成按“连续承压整线”判断：`xx管` 继续支持整线卡；`xx渠` 只有在末端或跨流量段形成连续承压线时才显示整线卡。底层按整线管理，但压力管道特性表、统计摘要和结果回写继续按原来的分段和流量段表达。
支渠连续承压链现在只从首个真正的有压段开始，前置隧洞不会再被误并进整线卡、route 起点和导入锚点；`xx管` 原有夹带隧洞口径保持不变。
支渠连续承压链里的前后同名普通有压管道，现在不会再被批量计算入口误判成必须改名；只有中间被明渠、闸、倒虹吸、暗涵等真正断开时，才继续按重名拦截。
命名有压段现在也改成按“连续出现的同名段”建身份；表1导入到表3时会补齐承压行稳定身份，这样“前段普通有压 + 中间顶管/定向钻 + 后段同名普通有压”会拆成独立子段，导出和回写优先按真实身份匹配。
赛金支渠这类连续承压链现在补上了“起点前缀段 + 整线完成状态”口径：如果链首普通有压到下一段定向钻/顶管/隧洞进口之间存在真实距离，就按前缀段计入沿程损失，并写回下一段特殊承压建筑的进口行；只有拿不到有效长度时才退回起点锚点。执行计算前也会按真实应写回成员判断，不再误报“还没做有压计算”。
纵断面 DXF 导入不再盲取文件里的首条多段线，而是按图层名、坐标量级和 X 向展开长度自动优选；如果前两名候选过于接近，导入前会先弹一次确认。
连续承压 `xx渠` 的纵断面导出现在也复用 `xx管` 固定 5 项表头；如果还没导入或没完全覆盖纵断面轴线 DXF，中心高程会直接留空导出，并在软件里提示回表3补齐后重导。
普通渠道项目如果只在末尾连续进入有压管道，图2 DXF 现在会在同一个文件里上下拆成两张表：上面保留渠道表，下面把末尾有压段单独画成 `xx管` 的 5 项表头；TXT 导出保持原样。
连续承压支管如果已经导入了整线纵断面 DXF，但某个普通子段缓存只剩 1 个点，导出会自动回退整线纵断面，不会再因为这类单点占位数据误报失败。
有压管道弹窗里导入或清空整线纵断面后，现在会立刻同步到主页面导出读取的持久层，不用再靠“开始计算”这一步才生效。
双桥支管这类连续承压支管在导出时，如果同桩号节点合并后代表节点换了身份，系统会继续用同桩号节点组里的稳定 identity 回退匹配整线纵断面，不再把“identity 没对上”误说成“没导入 DXF”。
连续承压整线现在正式拆成 `route + segment` 两层模型：`route` 管整线范围、导入状态和整线纵断面，`segment` 管每一段的正式结果、DXF 名称和子段纵断面；这样赛金支渠这类“普通渠道 + 末尾连续承压”不再靠名称补丁维持。
支渠连续承压成员现在统一使用 `flow{流量段}-row{行号}` 新身份；旧 `rowsxx` 记录不再继续生成，保存时也会把同一整线范围内的旧快照一起清掉，避免前缀段再落回旧空记录。
末尾连续承压的上下分表现在也有了单独规划器：是否拆成“上方渠道表 + 下方有压表”统一按整张表判断，不再由不同导出入口各自猜一次；一旦进入真正的承压尾段，后面的普通有压、定向钻、顶管、隧洞都会一起进入下方 5 项有压表。
连续承压段的 DXF 建筑物名称现在与软件展示名彻底拆开：DXF 只显示基础名称并按整段居中，软件里仍可保留“前缀段 / 前段 / 后段”等提示，赛金支渠这类结果会稳定显示为“苟家湾 / 大石包 / 苟家湾”。
压力管道特性表里的隧洞统计现在也按渠道级别分流：`xx管` 继续按原有整线口径统计；`xx渠` 只有在同一流量段已经进入“有压管道 / 定向钻 / 顶管”之后再次出现的隧洞，才会计入隧洞座数和长度。
普通纵断面与 xx管 现在都支持单独控制导出桩号小数位：普通模式默认 2 位，且会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 这类导出结果；xx管 继续只影响自己的纵断面桩号。
表3顶部“转弯半径”现在是一个统一应用入口：导入后默认保留每一行自己的半径，只有点击“应用”才会批量覆盖真实导入行。
应用内自动更新现在只对近版本提供补丁包；更老版本会直接下载全量包。安装前会先自动清理旧 `_update_sessions` 残留，“校验安装环境”也会继续显示“正在清理上次失败残留 / 正在检查写入权限 / 正在统计安装目录大小 / 正在解压完整安装包或补丁包 / 正在校验补丁适用性（x/y）”这些细分状态；如果旧残留清不掉，窗口会直接提示先关闭软件，仍失败再重启电脑。

## 技术架构

- 前端界面：`PySide6`，主要代码在 `app_渠系计算前端/`。
- 计算内核：Python 纯计算模块，主要代码在 `推求水面线/`、`calc_渠系计算算法内核/`。
- 明渠断面：`calc_渠系计算算法内核/明渠设计.py` 统一承接梯形、复式梯形、矩形、圆形、U 形；`app_渠系计算前端/open_channel/` 负责单断面设计页与 DXF/Word 导出；`app_渠系计算前端/batch/panel.py` 负责批量页与 Excel。
- 专项模块：`倒虹吸水力计算系统/`、`有压管道/` 提供专项计算能力。
- 自动化验证：`pytest`，测试文件集中在 `tests/`，其中 xx管 整线纵断面会同时覆盖界面、持久化、计算和导出链路。
- 更新链路：`updater.py`、`update_helper.py`、`tools/build.py`、`tools/release.py` 共同负责版本检查、补丁/全量选择、旧会话残留清理、独立安装窗口、补丁兜底和正式发版；其中 `tools/build.py` 现在还会在打包前按分组校验关键依赖，并单独拦截 Word 导出依赖缺失。
- 导出精度：普通模式导出桩号使用 `station_decimals`，xx管 导出桩号使用 `xxpipe_station_decimals`；两者都在导出链路单独格式化，不改主界面的通用桩号显示函数。
- mixed route 持久化：`PressurePipeManager` 现同时保存 route 级 `longitudinal_nodes` 与 `profile_segments`，用来承接“非隧洞 DXF + 隧洞生成段”的混合整线。
- 连续承压正式存储：`PressurePipeManager` 现在同时维护 `pipes / routes / segments` 三层数据；旧入口继续兼容，新导出与回读优先使用 `routes / segments`。
- 尾段逐行计损：`xx渠` 末尾连续承压中的命名有压段，会先拆成逐段成员，再统一按行回写和递推；窗口汇总仍保留整组结果。
- 连续承压快照保存：同一整线范围内的旧 `route / segment / pipe` 残留会在保存新结果前先清掉，避免新旧两套记录同时参与导出。
- 末尾分表规划：`cad_tools.py` 新增统一的尾段分表规划阶段，所有连续承压相关导出都先走这一步，再决定是否生成上下双表。
- 隧洞参数缓存：`PressurePipeManager` 也会保存隧洞段的进口底高、坡降、断面类型和断面参数，保证窗口重开后还能继续编辑。

## 本地运行方法

1. 若本地还没有虚拟环境，先执行 `python -m venv .venv`。
2. Windows 环境可直接运行 `install_deps.bat` 安装依赖；该脚本现在会覆盖 Word 导出所需的 `python-docx`、`latex2mathml`、`lxml`。
3. 启动程序使用 `D:\V1.0\.venv\Scripts\python.exe main.py`。

## 部署方法和命令

当前项目主要作为本地桌面工具使用，日常开发通常不做云端部署。
正式发版按仓库约定使用 `D:\V1.0\.venv\Scripts\python.exe tools/release.py`，也可通过 `发版工具.bat` 进入标准发版流程；正式打包和发版前会先校验 Word 导出依赖，缺失时直接中止并提示安装命令。

## 测试方法和常用命令

- 运行针对性测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py -q`
- 运行界面口径测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py -q`
- 运行本次相关回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_channel_level_options_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次窗口联动回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_window_override_unit.py tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 整线回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_longitudinal_utils_unit.py tests/test_pressure_pipe_spatial_calc_unit.py tests/test_xxpipe_export_context_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 弹窗与导出回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py -q`
- 运行本次 xx管 夹带隧洞回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_water_profile_transition_ready_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py -q`
- 运行本次连续承压 xx渠 导出回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_xxpipe_profile_rows_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressurized_dxf_rules_unit.py -q`
- 运行本次末尾有压段分表回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_xxpipe_profile_rows_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressurized_dxf_rules_unit.py -q`
- 运行本次本地分支收口回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressurized_dxf_rules_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_xxpipe_export_context_unit.py -q`
- 运行本次赛金支渠重构回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_*unit.py tests/test_xxpipe_*unit.py tests/test_water_profile_combined_dxf_unit.py -q`
- 运行本次普通纵断面桩号精度回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_text_export_settings_dialog_ui_unit.py tests/test_water_profile_longitudinal_scale_unit.py tests/test_water_profile_ip_table_export_unit.py tests/test_water_profile_bzzh2_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_water_profile_longitudinal_dedup_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行本次连续承压链回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_config_dialog_sizing_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_external_head_loss_unit.py`
- 运行本次 xx渠 末尾逐行计损回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_external_head_loss_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py -q`
- 运行本次连续承压整线回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_pressurized_dxf_rules_unit.py tests/test_external_head_loss_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_window_override_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py -q`
- 运行本次三清支渠纵断面/链路回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_longitudinal_dxf_reverse_import_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py -q`
- 运行本次同名连续承压链回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_batch_panel_dialog_parent_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_pressure_pipe_export_results_unit.py -q`
- 运行本次赛金支渠连续承压链回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_export_results_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行更新链路回归：`$env:PYTEST_ADDOPTS='--basetemp=D:\V1.0\.pytest_tmp\update-regression'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_build_patch_floor_unit.py tests/test_updater_install_flow_unit.py tests/test_update_helper_unit.py -q`
- 运行本次构建依赖回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_build_patch_floor_unit.py -q --basetemp=D:\V1.0\.pytest_tmp\build-plan`
- 运行本次复式梯形回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_open_channel_compound_trapezoid_kernel_unit.py tests/test_open_channel_compound_trapezoid_panel_unit.py tests/test_open_channel_compound_trapezoid_dxf_unit.py tests/test_batch_compound_trapezoid_unit.py tests/test_compound_trapezoid_type_support_unit.py tests/test_compound_trapezoid_shared_hydraulic_unit.py tests/test_water_profile_coord_precision_unit.py -q`

## 搜索记录

- 2026-03-31：本次为现有功能修正和范围收口，未新增外部方案搜索，直接基于仓库现有逻辑与测试完成实现。
- 2026-04-09：本次为既有明渠体系内新增断面类型，README 已有搜索记录，继续按仓库现有明渠/批量/水面线架构扩展，未重复执行外部方案搜索。

## 已完成功能列表

- 明渠设计面板已新增“复式梯形”断面，支持 6 个固定几何参数、分段公式、断面图、DXF 和 Word 导出。
- 批量计算已新增“明渠-复式梯形”，主表、参数弹窗、Excel 导入导出和结果说明全部支持新断面。
- 推求水面线已补上“明渠-复式梯形”的最小兼容，能保留 `m1/B1/m2/B2/m3/h1` 并按新公式参与水力计算。
- 构建和发版现在会在进入 PyInstaller 前先校验 Word 导出依赖，缺失 `python-docx / latex2mathml / lxml` 时直接中止并提示安装命令，避免再发出缺件安装包。
- 表3普通行、渐变段行、累计损失和水位递推的基础链路已接通。
- 倒虹吸和命名有压管道组支持外部专项计算后回写总损失。
- 空名称普通有压管道行现在可在 xx管，以及已形成连续承压整线的 xx渠 场景下，独立显示沿程损失、承压弯头损失和本行承压段总损失。
- 断面汇总弹窗里的有压管道参数现在按“流量段主行 + 顶管/定向钻单独行”显示；普通有压管道同一流量段只显示 1 行，确认后会自动同步到该流量段下全部普通有压管道原始分组。
- 匿名普通有压管道段的窗口结果会回写到当前行，并在后续静默重算中继续作为主来源，表3列38会锁定避免混改。
- 相关双击说明已经补齐，且总损失、水位、累计损失说明不会再把同一笔承压段损失重复展示。
- 隧洞沿程损失继续保持原有“底坡 × 有效长度”口径，没有被承压管道逻辑带偏。
- xx管 模式下，匿名普通有压管道紧邻定向钻、顶管或另一条匿名普通有压管道时，不再误弹补段；匿名普通有压管道与隧洞相邻时仍会保留前后两处渐变段。
- 普通有压管道/定向钻/顶管的渐变段长度详情，现已和插入阶段统一按 `5h/6h` 显示；当长度被压缩时，也会继续明确标出物理上限和最终采用值。
- xx管 有压管道窗口现在只保留整线卡：同一条纯“有压管道 / 定向钻 / 顶管”线路只导入一份平面/纵断面，弹窗里不再编辑子段 `R / D`。
- xx管 整线纵断面现按 `route_key` 持久化，空间长度、导出中心线高程和材料/建筑物分段都会先找整线数据，再按子段桩号裁切。
- 多个空名称 xx管 子段现在会优先使用 `pressure_pipe_row_identity` 区分，避免导出和纵断面取值时相互串用。
- 压力管道特性表里的设计流速和长度现在会按流量段逐行输出；其中主长度只看该流量段里有压管道自身的边界桩号范围，优先取有压管道起点和终点的 IP 点桩号差，不再按整段渠道节点重新累计。`segment_start_mc / segment_end_mc` 作为主口径，缺失时才回退旧的整段扫描结果，避免旧工程导出失败。
- 压力管道特性表里的渠首水位和渠末水位，也会跟着流量段逐行输出；现在优先取有压管道起点和终点对应节点水位。只有连续承压线跨流量段且边界本身连续时，前一段末值和后一段首值才会共用同一个切段点水位；中间有断点时仍各算各的。
- 压力管道特性表里的隧洞、定向钻、顶管摘要长度，现统一按每组“出口里程MC - 进口里程MC”统计；出口后的普通有压管道首段不再误并进建筑物长度。
- `xx渠` 的压力管道特性表里，隧洞只在同一流量段已进入“有压管道 / 定向钻 / 顶管”之后才统计；前置隧洞不再误显示到有压管道特性表里。
- 支渠连续承压整线现在只会从首个真正有压段起算；前置隧洞不会再被误串进整线卡、route 起点或纵断面导入锚点，但进入有压段后的后续隧洞仍会保留。
- 支渠连续承压链里的前后同名普通有压管道现在允许直接通过批量校验；真正被明渠、闸、倒虹吸、暗涵等断开的同名段仍会继续拦截，避免把后续结果串到一起。
- 命名有压段现在按连续出现的同名段分别建 `identity / storage_key`，并保留旧 `flow_section::name` 兼容别名；表1导入到表3时也会给承压类行补齐稳定身份，后续导出和回写优先按真实身份命中。
- 赛金支渠这类“普通有压 + 定向钻/顶管 + 同名普通有压”的连续承压链，现在会先判断链首到下一段特殊承压建筑进口之间是否存在真实距离；有长度时生成“前缀段”并把沿程损失写回下一段特殊承压建筑的进口行，无有效长度时才退回“起点锚点”。同链重名成员会自动显示为“前缀段 / 起点锚点 / 前段 / 后段”，整条链未完整成功时也会明确标成“未完成”并隐藏整线总损失。
- 赛金支渠 `赛支3+968.95 / 405m` 这类前缀段导出，现在会优先按新身份找分段；若先碰到旧空记录，也会继续按 `route_key` 回退整线纵断面，不再被误判成“已导入 DXF 但未匹配”。
- xx管 弹窗里的纵断面 DXF 现在会在导入时立即校验整线导出节点是否都被覆盖，覆盖不足会直接拦截，不再“先导入、导出时再发现缺口”。
- 纵断面 DXF 导入现在会先自动筛掉闭合线、工程坐标辅助线和横向展开不足的候选，再按优先规则选中真正的纵断面；当前两名候选非常接近时，导入前会先提醒确认。
- xx管 夹带隧洞整线现在可以继续进入有压管道窗口：整线卡继续负责 1 份 DXF 导入，隧洞段保留独立分段卡；导入覆盖校验只检查非隧洞桩号，起点若是隧洞则自动对齐到第一段非隧洞桩号。
- xx渠 在末端或跨流量段形成连续承压线时，也会进入整线底座；非连续场景仍只看当前分组，同时点击“开始计算”时不再因为 identity helper 调用方式错误而报 `group` 参数缺失。
- `xx渠` 末尾连续承压中的命名 `有压管道 / 定向钻 / 顶管` 现在按逐行正式计损：列38、总损失、累计损失和水位都改用逐段值递推，出口行只保留本段损失，整组总损失继续保留在有压管道窗口汇总里。
- 如果旧工程或静默重算时，命名尾段出口行只剩列38里的本段显示值，系统现在也会自动把这笔值补回总损失、累计总损失和水位递推，不再出现“列38有值、列39还是 `-`、累计值停在上一行”。
- 连续承压 `xx渠` 的图2导出现在复用 `xx管` 固定 5 项表头；普通有压管道第 1 行优先显示用户名称；缺少或未覆盖完整的纵断面轴线 DXF 时，第 4 行会留空并给出补导提示，但严格 `xx管` 仍保持原来的拦截规则。
- 普通渠道项目如果只在末尾连续进入有压管道，图2 DXF 现在会在同一个文件里拆成上下两张表：上面继续按渠道表头输出，下面把末尾有压段单独改成 `xx管` 固定 5 项表头；合并 DXF 里的断面汇总表和 IP 表也会一起下移，避免压到新增的有压子表。
- 连续承压支管在导出时，如果普通子段缓存里只剩 1 个纵断面点，会自动回退整线 DXF；跨流量段时新流量段首个匿名普通行就算只对应单点边界，也会直接继承整线纵断面，不再把“整线已导入”误报成“点不够”。
- 整线卡里导入或清空纵断面 DXF 后，会立即写入持久层；主页面导出和弹窗预览现在读取的是同一份整线数据，不再出现“窗口里看得到、导出里却说没导入”。
- 连续承压支管在导出时，如果同桩号合并后的代表节点 identity 没命中整线纵断面，系统会继续按同桩号节点组、route 锚点和旧口径 identity 回退重试，不再把“identity 没匹配上”误报成“还没导入 DXF”。
- 连续承压 `xx渠` 的末尾双表和建筑物名称现在都走正式分段模型：上方渠道表不再整块空白，下方有压表固定 5 项表头，建筑物名称按整段范围只画一次并居中。
- xx管 隧洞分段卡现在可以直接录入“进口底高 / 坡降 i / 出口底高校核 / 断面类型 / 断面参数”，并会写进项目缓存，重新打开窗口后仍会带回。
- xx管 mixed route 会把 route 级几何拆成 `profile_segments`：普通有压段继续从整线 DXF 裁切，隧洞段按“进口底高 + 坡降 i”生成；导出和结果持久化都会优先复用这份分段结果。
- xx管 图2第 4 行标题继续保留“管中心线高程（米）”，但隧洞段实际取底高程；第 5 行在隧洞段改为输出断面参数文字，例如“圆形隧洞 D=2.4m”。
- 图2“管中心线高程（米）”继续在导出时按当前平面桩号现算；节点 `station_MC` 缺失时只对个别节点按平面累计距离回退，整线都没有有效桩号锚点时直接报错。
- 普通纵断面导出现在新增 `station_decimals`，默认保留 2 位小数；同一设置会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 的桩号输出，但不会改表3和说明文字的原有显示。
- 表3顶部“转弯半径”改成“待应用统一值”：导入混合半径时保持空白，点击“自动”只填栏位，点击“应用”才统一覆盖真实导入行。
- 自动更新补丁策略已收紧到近版本链路：当前只给 `1.1.9+` 提供补丁；如果补丁删除文件过多或总覆盖量过大，构建阶段会直接跳过补丁，只发布全量包。安装前会先自动清理旧 `_update_sessions` 残留，“校验安装环境”也会继续显示“正在清理上次失败残留 / 正在检查写入权限 / 正在统计安装目录大小 / 正在解压完整安装包或补丁包 / 正在校验补丁适用性（x/y）”这些细分状态；如果旧残留清不掉，窗口会直接提示先关闭软件，仍失败再重启电脑。
- 明渠设计面板现已支持 `复式梯形`：输入 `m1 / B1 / m2 / B2 / m3 / h1` 后可直接反算设计水深、加大流量水深、断面图、TXT/Word/DXF 导出。
- 批量计算现已支持 `明渠-复式梯形`：主表、参数弹窗、Excel 导入导出和结果文本均已补齐 6 个专用参数列。
- 推求水面线已补上 `明渠-复式梯形` 的最小兼容：能识别类型、保留 6 个参数，并按新几何公式完成开放渠道面积、湿周和水力半径计算。

## 待办事项

- 结合真实工程样表继续验收隧洞参数卡的字段命名、默认值和提示文案是否还需要再收口。
- 继续补充 route 覆盖不足、接点高差告警、连续承压链，以及更多匿名子段组合场景的回归样例。
