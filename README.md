# V1.0 渠系计算工具

## 项目功能简介

这是一个本地桌面计算工具，用来处理渠系纵断面、水面线、倒虹吸、有压管道、土石方等工程计算与导出。
当前仓库重点包含表3水面线计算、渐变段联动、倒虹吸/有压管道结果回写，以及 `xx管` 连续承压链规则。

## 技术架构

- 前端界面：`PySide6`，主要代码在 `app_渠系计算前端/`。
- 计算内核：Python 纯计算模块，主要代码在 `推求水面线/`、`calc_渠系计算算法内核/`。
- 专项模块：`倒虹吸水力计算系统/`、`有压管道/` 提供专项计算能力。
- 自动化验证：`pytest`，测试文件集中在 `tests/`。

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
- 运行本次连续承压链回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_config_dialog_sizing_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_external_head_loss_unit.py`

## 搜索记录

- 2026-03-31：本次为现有功能修正和范围收口，未新增外部方案搜索，直接基于仓库现有逻辑与测试完成实现。

## 已完成功能列表

- 表3普通行、渐变段行、累计损失和水位递推的基础链路已接通。
- 倒虹吸和命名有压管道组支持外部专项计算后回写总损失。
- 空名称普通有压管道行现在可在 xx管 渠道级别下独立显示沿程损失、承压弯头损失和本行承压段总损失。
- 空名称普通有压管道行现在也会进入“有压管道水力计算配置”窗口，按“流量段+行号”显示独立卡片并参与窗口计算。
- 匿名普通有压管道段的窗口结果会回写到当前行，并在后续静默重算中继续作为主来源，表3列38会锁定避免混改。
- 相关双击说明已经补齐，且总损失、水位、累计损失说明不会再把同一笔承压段损失重复展示。
- 隧洞沿程损失继续保持原有“底坡 × 有效长度”口径，没有被承压管道逻辑带偏。
- `xx管` 现在会把连续出现的有压管道、定向钻、顶管和隧洞识别成一条连续承压链，在结果窗口显示“总览 + 逐成员明细”。
- 连续承压链支持首行有压管道作为锚点，不再因为缺少上一普通行而整条链计算失败。
- 配置窗口现在会按连续承压链分组展示，同链内的隧洞成员会显示为只读提示，不再误当成要填写 R / D 的有压卡片。

## 待办事项

- 继续补充命名有压管道组、匿名普通有压管道和渐变段混合场景的回归样例。
