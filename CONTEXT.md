# 当前上下文

## 正在做什么

- 已在 `codex/experimental-spillway-steep-chute` 分支完成“泄水渠与陡坡”第二版正式模块改造，并继续处理用户反馈的界面对齐问题。
- 本轮已修复 3 个用户可见问题：加大流量输入方式对齐明渠/渡槽，计算原理来源不再暴露内部 PRD 口径，纵断面图右侧不再因固定画布宽度被裁切。
- 本轮追加修复 `main.py` 启动时弹出 Qt WebEngine 诊断框的问题：标准 WebEngine 冷启动实际可成功，但原 8 秒预检预算过短，会误判为超时。
- 本轮已把旧公式页改为“计算原理”，并将该页签和 Word/Excel 导出章节放到“结果汇总”之前。
- 本轮追加修复计算原理页源码露出与英文残留：不再因不支持的分段公式回退显示 LaTeX 源码，断面类型、起点控制来源、水面线模式和公式下标均改为中文可见口径；Word/Excel 的计算原理“公式”列改用中文可读公式文本。
- 本轮追加修正计算原理中的湿周符号：参照明渠设计展示口径，湿周统一用 \(\chi\)，水力半径写为 \(R=A/\chi\)，不再用 \(P\) 表示湿周。
- 本轮追加完成泄水渠输入栏组件体系对齐：灰底不是单纯颜色问题，根因是泄水渠仍使用原生输入框和透明容器；现已改为与明渠/渡槽一致的 Fluent 输入框和白色输入卡片。
- 本轮追加修正泄水渠“分级流量”提示：用户不再手填分级流量，程序先按设计流量的 10% 到 100% 初筛，再在控制区间按 1% 设计流量加密，加大流量自动作为额外工况加入。
- 本轮追加修正泄水渠导出和清空入口：补齐“清空”按钮，“导出文档”改为“导出计算书”，计算书和表格导出时自动预填工程/工况相关文件名，仍允许用户自行修改；导出后询问是否直接打开，并修复表格导出缺少 `.xlsx` 后缀的问题。
- 本轮追加完成计算前“计算原理”预览：未点击计算前也展示完整流程、公式、变量、来源和当前输入，正式结果位置统一显示“计算后生成”。
- 本轮追加修正泄水渠首个默认工况名：新建和重置后默认显示“工况1”，未手动重命名的工况按序号自动显示，导出默认文件名同步使用当前工况名。

## 上次停在哪

- 计算内核 `calc_渠系计算算法内核/泄水渠与陡坡设计.py` 已扩展到第二版，支持水面线型识别、起点控制水深、上游缓坡自由衔接、下游水跃、掺气侧墙、消力池初步尺寸、出口整流、多流量控制和表3轻量接口。
- 前端包 `app_渠系计算前端/spillway_steep_chute/` 已按渡槽/隧洞风格重做，包含新手/专业模式、正式输入分组、工况条、结果导航、计算原理页、网页结果页、沿程水面线、纵断面图、规范校核、双表工况对比、项目保存恢复和文档/表格导出。
- 本轮将加大流量输入改为复用 `increase_input_helper`，支持“按比例 / 按Q加大”、比例留空自动查表、旧项目字段恢复和非法输入明确提示。
- 本轮将旧公式页统一升级为审查级“计算原理”：界面、Word 和 Excel 均展示计算流程、公式、变量含义、本次代入、结果、原理说明和来源，并继续清洗内部 `PRD` 字样。
- 本轮补强计算原理安全展示：界面公式渲染失败只显示中文提示，不显示原始源码；计算原理共享数据新增导出用中文可读公式，避免 Word/Excel 展示 `\frac`、`\quad` 等源码格式。
- 本轮将纵断面图接入共享断面图画布布局，切页和窄窗口下会按可视区域刷新画布。
- 本轮将泄水渠输入栏从原生 `QLineEdit` + 透明 `QFrame` 改为 qfluentwidgets `LineEdit` + `QGroupBox` 输入卡片，只对齐左侧输入栏，不改变右侧结果页、计算、保存和导出逻辑。
- 本轮将隐藏的“分级流量列表”改为纯兼容字段：界面不再展示，旧项目中的 `flow_cases_text` 不再参与计算；面板参数组装层自动生成 `0.1Q` 到 `1.0Q` 的初筛流量、传入 `flow_case_refinement`，并去重加入 \(Q_{\text{加大}}\)。
- 本轮将泄水渠“清空”定义为只清除计算结果、结果导航、表格、图形和导出缓存，不恢复默认输入、不删除多工况；导出计算书和导出表格会按当前工程名或当前工况名预填文件名，多工况导出会标注“等N个工况”，用户在保存对话框里改名后仍以用户选择为准；导出计算书固定补 `.docx`，导出表格固定补 `.xlsx`，保存成功后复用明渠已有的打开询问。
- 本轮将泄水渠未重命名工况改为按“工况1、工况2……”自动显示；工况按钮和导出默认文件名不再用“设计工况”或“未命名工程”作为默认工况名。
- 本轮将计算原理页拆成计算前预览态和计算后正式态：预览态只读当前输入、不调用内核；正式态继续复用正式计算结果和导出口径。
- 本轮补齐多流量控制的细化口径：前端传入 `flow_case_refinement`，内核先按 10% 初筛，再在控制流量邻近区间按 1% 设计流量加密并重新选择控制工况。
- 已同步更新 `docs/PRD_泄水渠与陡坡水力计算.md`，记录本轮对齐修复和最新验收结果。
- 已将 Qt WebEngine 标准预检外层超时从 8 秒调整为 20 秒，并补充启动诊断回归测试；`tools/qt_webengine_doctor.py` 当前返回标准模式可用。

## 关键决定

- 第二版采用“独立正式模块 + 表3轻量接口”，先完整解决专项计算和成果导出，避免扰动现有明渠、倒虹吸、有压管道和表3水面线主链路。
- 加大流量输入沿用明渠、渡槽等设计面板的共享口径：默认按比例，空值自动查表；按Q加大时反算比例并要求 \(Q_{\text{加大}}>Q\)。
- 消力池多流量控制不再要求用户理解或录入“分级流量列表”；默认每 10% 自动初筛并按 1% 加密控制区间，是为了符合规范“按数值分级”要求，同时减少新手模式下的输入负担。
- 泄水渠输入栏对齐按“组件体系对齐”处理，不只改输入框背景色；右侧结果页本轮保持原结构，避免扩大影响面。
- 计算原理来源里的内部 PRD 表述只在用户界面和导出结果中隐藏，内部 PRD 文档本身保留。
- 计算前原理预览不自动执行正式水力计算；依赖计算的正常水深、临界水深、水面线、消能和校核结论统一显示“计算后生成”，避免误导用户把预览当作结果。
- 计算原理页签固定放在“结果汇总”之前；导出也按“计算原理 → 结果汇总”的顺序组织，避免界面和成果口径不一致。
- 计算原理的“不要出现英文”按用户可见内容处理：工程常用数学符号可保留，内部英文枚举、英文单词和英文公式下标必须中文化。
- 计算原理中的湿周符号采用明渠模块一致的 \(\chi\) 展示口径；内核字段名可继续保留原实现，不影响数值计算。
- 纵断面图继续使用现有滚动承载结构，但画布尺寸由共享布局工具按当前可视区域控制，不新增横向滚动条。
- WebEngine 预检仍保留标准模式优先和失败诊断弹窗，但冷启动预算需要覆盖首次创建 `QWebEngineView` 的真实耗时，避免把可用环境误判为不可启动。
- 标准自由陡坡继续按 GB 50288-2018 第 12.3.3 条计算 \(b_2\) 型水面线；非标准工况先识别水面线型并给出衔接与风险提示。
- 熊启钧棱柱体陡坡算例作为教学算例和回归验收口径，当前末端水深容差按 `±0.08m` 控制。
- 当前 `.venv` 的 `hypothesispytest` 插件会让原样 pytest 进程卡住；本轮验证继续使用 `-p no:hypothesispytest`。
- 本轮验证结果：`101` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_increase_input_helper_unit.py tests/test_increase_input_mode_panels_unit.py tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_plotting_unit.py tests/test_spillway_steep_chute_export_unit.py tests/test_spillway_steep_chute_v2_unit.py tests/test_section_plot_layout_unit.py -q --basetemp=.pytest_tmp\spillway-three-fixes`。
- 启动修复验证结果：`15` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_webengine_diagnostics_unit.py -q --basetemp=.pytest_tmp\webengine-diagnostics-final`；诊断脚本 `.\.venv\Scripts\python.exe tools\qt_webengine_doctor.py` 返回 `ok: True`。
- 计算原理增强阶段验证结果：`40` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py tests/test_spillway_steep_chute_v2_unit.py -q --basetemp=.pytest_tmp\spillway-principles`。
- 输入栏组件体系对齐验证结果：相关回归 `38` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_increase_input_mode_panels_unit.py -q --basetemp=.pytest_tmp\spillway-ui-align`；泄水渠专项回归 `56` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests -q -k spillway_steep_chute --basetemp=.pytest_tmp\spillway-ui-align-full`。
- 自动分级流量与提示修正验证结果：`43` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_v2_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-auto-flow-final`。
- 多流量控制区间自动加密验证结果：`50` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_v2_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-flow-refine-final`。
- 导出和清空入口修正验证结果：计划内导出/面板回归 `26` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-export-buttons`；泄水渠专项回归 `59` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests -q -k spillway_steep_chute --basetemp=.pytest_tmp\spillway-export-buttons-full`。
- 计算原理源码与英文残留修复验证结果：`50` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py tests/test_spillway_steep_chute_v2_unit.py -q --basetemp=.pytest_tmp\spillway-principles-cn`。
- 导出默认文件名修正验证结果：计划内面板/导出回归 `30` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-default-name`；泄水渠专项回归 `66` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests -q -k spillway_steep_chute --basetemp=.pytest_tmp\spillway-default-name-full`。
- 计算前原理预览与多流量细化验证结果：`50` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_v2_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-principle-preview`。
- 首个默认工况命名修正验证结果：计划内面板/导出回归 `31` 个测试通过；命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py -q --basetemp=.pytest_tmp\spillway-case-default-name`；泄水渠专项回归 `67` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests -q -k spillway_steep_chute --basetemp=.pytest_tmp\spillway-case-default-name-full`。
- 湿周符号修正验证结果：先跑数据与导出回归 `26` 个测试通过；最终面板、导出、计算原理专项回归 `51` 个测试通过，命令为 `.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_spillway_steep_chute_panel_unit.py tests/test_spillway_steep_chute_export_unit.py tests/test_spillway_steep_chute_v2_unit.py -q --basetemp=.pytest_tmp\spillway-chi-panel`。
