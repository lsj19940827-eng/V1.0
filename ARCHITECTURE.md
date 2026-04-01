# 架构说明

## 主要文件/模块职责

- `main.py`：桌面程序入口，负责启动主界面。
- `app_渠系计算前端/`：界面层，负责表格编辑、按钮动作、结果展示和导出。
- `app_渠系计算前端/water_profile/panel.py`：表3水面线页面主控，负责把节点数据和界面单元格互相同步。
- `app_渠系计算前端/water_profile/water_profile_dialogs.py`：有压管道配置窗口，负责 xx管 整线卡、分段卡、平面/纵断面数据、R/D 应用状态和窗口返回载荷。
- `app_渠系计算前端/water_profile/cad_tools.py`：纵断面导出与 xx管 中心线高程采样，负责把窗口/manager 中的有压管道数据整理成导出主数据。
- `app_渠系计算前端/water_profile/formula_dialog.py`：表头说明和双击公式弹窗，负责把计算详情解释给用户看。
- `推求水面线/core/calculator.py`：整表计算总调度，串起预处理、渐变段、水力计算、累计损失和高程递推。
- `推求水面线/core/hydraulic_calc.py`：水头损失和水位递推核心，负责沿程、弯道、局部损失及水位更新。
- `推求水面线/core/pressure_pipe_calc.py`：有压管道专项公式库，提供 FMB 沿程损失和承压弯头局部损失计算。
- `推求水面线/managers/pressure_pipe_manager.py`：有压管道结果与纵断面持久化，负责 `pipes` 与 `routes` 两层存储。
- `推求水面线/models/data_models.py`：节点和项目设置的数据结构定义。
- `推求水面线/models/enums.py`：结构类型、进出口标记和相关判断规则。
- `推求水面线/utils/pressure_pipe_extractor.py`：保留命名组提取入口，同时提供窗口专用入口，把 xx管 匿名普通有压管道段和整线路由信息一起提出来。
- `推求水面线/utils/pressure_pipe_longitudinal_utils.py`：纵断面裁切与按桩号采样工具，负责把整线纵断面切成子段可用数据。
- `tests/`：回归测试与规则测试，覆盖计算口径、界面说明和范围边界。

## 模块之间的调用关系

- `panel.py` 负责收集表格数据并生成 `ChannelNode`、`ProjectSettings`。
- `panel.py` 调用 `calculator.py` 进入整表计算流程。
- `calculator.py` 调用 `hydraulic_calc.py` 计算水头损失和水位，并在需要时结合渐变段处理。
- `hydraulic_calc.py` 在 xx管 匿名普通有压管道场景下复用 `pressure_pipe_calc.py` 的 FMB 和承压弯头公式。
- `pressure_pipe_extractor.py` 先给 xx管 有压对象补上 `route_key`、整线范围和子段范围，再交给 `panel.py` 和 `water_profile_dialogs.py` 使用。
- `water_profile_dialogs.py` 把整线纵断面按 `route_key` 收集后返回给 `panel.py`。
- `panel.py` 在计算和导出前调用 `pressure_pipe_longitudinal_utils.py`，先按 `route_key` 找整线纵断面，再按 `segment_start_mc / segment_end_mc` 裁切子段。
- `panel.py` 计算完成后通过 `pressure_pipe_manager.py` 把整线纵断面写入 `routes`，把子段结果写入 `pipes`。
- `panel.py` 与 `formula_dialog.py` 配合，把 `ChannelNode` 上保存的详情展示为双击弹窗和表头说明。
- `panel.py` 会先按当前渠道级别判断是否属于 xx管 匿名普通有压管道，再决定列38显示值、窗口卡片、结果回写和静默重算口径，避免前后端各用一套规则。
- `panel.py` 打开有压管道窗口时会同时处理两类对象：命名组继续走整组专项算法，匿名普通有压管道段走段级专项算法。
- 命名有压管道组由专项模块先算出总损失，再回写到表3对应出口行。

## 关键设计决定和原因

- 空名称普通有压管道行按“独立承压管段”处理，而不是复制相邻定向钻/顶管整组结果，这样表3红框单元格、总损失和水位递推才一致。
- 该独立承压口径只在 xx管 渠道级别下启用，避免把 xx管 的规则扩散到普通渠系项目。
- 命名的有压管道/定向钻/顶管继续保留“外部整组计算 + 出口行回写”的边界，避免与现有专项模块重复计损。
- 匿名普通有压管道段在窗口里使用 `pressure_pipe_row_identity` 作为存储键，界面显示名单独放在 `display_name`，这样空名称行不会互相覆盖。
- 匿名普通有压管道段一旦应用窗口结果，就把该结果持久化到节点覆盖载荷里，并由 `hydraulic_calc.py` 优先识别，保证静默重算和详情展示继续沿用窗口结果。
- 表3列38对 xx管 匿名普通有压管道只是展示值，因此总损失、水位和累计说明里不能再把它当作单独一项重复相加。
- `calculator.py` 在 xx管 模式下会把“匿名普通有压管道 ↔ 定向钻/顶管/匿名普通有压管道”视为同一段承压占位链路，不再额外插渐变段；但遇到隧洞时仍保留渐变段，避免批量补段弹窗和实际插入结果不一致。
- `hydraulic_calc.py` 里的普通有压管道渐变段正式计算，和 `calculator.py` 插入阶段统一按 `5h/6h` 处理；这样表3长度详情、拓扑插入和最终采用值使用同一口径，不再出现“公式值 0/2.5、最终却沿用 10”的错位。
- 隧洞沿程损失继续保留原有“底坡 × 有效长度”口径，不混用承压管道公式。
- xx管 纵断面改为“整线只存一份、子段按范围裁切”的双层口径：几何来源统一，损失仍按子段独立计算。
- `pressure_pipe_manager.py` 同时保留旧的单段纵断面兼容读取和新的 `routes` 桶写入，避免旧项目打不开。
- xx管 导出和中心线高程采样继续按子段 identity 分段，但匿名子段优先使用 `pressure_pipe_row_identity`，避免同一流量段多个空名称子段撞键。
