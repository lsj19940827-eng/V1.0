# 有压管道 — 综合 PRD

> **版本**: V2.11.9
> **创建日期**: 2026-03-03  
> **最后更新**: 2026-04-07
> **状态**: 已实现

---

## 一、需求概述

有压管道在系统中有两个独立子系统：

| 子系统 | 定位 | 入口 |
|--------|------|------|
| **独立设计面板** | 管径推荐 + 批量扫描 + 绘图（源自 V9） | 左侧导航"有压管道设计" |
| **水面线集成** | 作为占位行参与批量计算与水面线推求 | 批量计算 + 水面线面板 |

---

## 二、子系统 A — 独立设计面板（V9 内核植入）

### 2.1 文件结构

| 功能 | 文件路径 |
|------|----------|
| 计算内核 | `calc_渠系计算算法内核/有压管道设计.py` |
| UI面板 | `app_渠系计算前端/pressure_pipe/panel.py` |
| 主程序接入 | `app_渠系计算前端/app.py` |

### 2.2 内核接口（有压管道设计.py）

**常量与配置**：
- `PIPE_MATERIALS`：V9 五种管材 `f/m/b` 系数
- `DEFAULT_DIAMETER_SERIES`：V9 口径序列
- `DEFAULT_Q_RANGE` / `DEFAULT_SLOPE_RANGE`：批量默认扫描参数
- `ECONOMIC_RULE` 与 `COMPROMISE_RULE`：流速/水损阈值

**数据结构**：
- `PressurePipeInput`：`Q, material_key, slope_i, n_unpr, length_m, manual_increase_percent`
- `DiameterCandidate`：`D, V_press, hf_friction_km, hf_local_km, hf_total_km, h_loss_total_m, flags`
- `RecommendationResult`：`recommended, top_candidates, category, reason, calc_steps`
- `BatchScanConfig`：`q_values, slope_values, diameter_values, materials, output_dir`
- `BatchScanResult`：`csv_path, generated_pngs, generated_pdfs, merged_pdf, logs`

**计算函数**：
- `get_flow_increase_percent(Q) -> float` — 加大流量比例
- `evaluate_single_diameter(input, D) -> DiameterCandidate` — 单管径评估
- `recommend_diameter(input) -> RecommendationResult` — 推荐管径
- `run_batch_scan(config, progress_cb, cancel_flag) -> BatchScanResult` — 批量扫描
- `build_detailed_process_text(input, recommendation) -> str` — 详细过程文本

**核心计算公式（当前程序执行）**：

$$h_f = f \times L \times \frac{Q^m}{d^b}$$

- $Q$: m³/h（需从 m³/s × 3600 换算）
- $d$: mm（需从 m × 1000 换算）
- 局部损失系数取沿程的 15%：$h_{j,km} = 0.15 \times h_{f,km}$

**双规范并列展示（文案/导出）**：
- 页面与 Word 导出并列展示两本规范：  
  - 《灌溉与排水工程设计标准》(GB 50288-2018) §6.7.2  
  - 《管道输水灌溉工程技术规范》(GB/T 20203-2017) §5.1.4 ~ §5.1.6（摘要）
- GB/T 20203 摘要纳入条款：`5.1.4.1`、表4、`5.1.4.4`、`5.1.5.1~5.1.5.3`、`5.1.6.1`、`5.1.6.2（表5）`、`5.1.6.4`。
- `5.1.6.1` 式(18)（`D = 18.8√(Q/v)`）仅在帮助页展示，不进入 Word 基础公式段。
- 球墨铸铁管 `f` 在 GB/T 表4中按区间展示（`1.899×10^5 ~ 2.232×10^5`），程序计算仍取上限值 `2.232×10^5`。
- 局部损失按 GB/T `5.1.4.4` 标注“规划阶段可按沿程损失 10%~15% 估算”；程序默认 `0.15`，可手动调整。
- 当前推荐筛选算法保持不变：仍按 GB 50288 经济/妥协/兜底规则执行。

### 2.3 推荐算法

1. **经济区**（`0.9 ≤ V ≤ 1.5` 且 `hf_total ≤ 5 m/km`）→ 取最小 D
2. **妥协区**（`0.6 ≤ V < 0.9` 且 `hf_total ≤ 5`）→ 取最小 D
3. **兜底**（`|V-0.9|` 最小 + `hf_total` 最小）→ 标记"未满足约束"
4. 输出前 5 候选供展示

### 2.4 UI面板

- 导航页："有压管道设计"
- 单次计算区：Q、管材下拉（五种）、无压参数 `i(1/x)`、`n`、管长 `L`（默认1000m）
- 输出区：推荐管径卡片 + 前5候选表 + 详细计算过程
- 批量计算区：默认值可编辑、QThread 后台执行、进度条 + 取消、输出 CSV + PNG + PDF
- 导出：单次 Word/Excel/TXT；批量 CSV + 图表 PDF

#### 2.4.1 当前实现同步说明

- 主程序启动前会先执行 `app_渠系计算前端/qfluentwidgets_compat.py`，不再直接依赖系统 `darkdetect` 成功返回；当系统主题探测异常或阻塞时，自动回退为浅色主题，避免 `qfluentwidgets` 导入卡住导致 `main.py` 无法启动。
- `app_渠系计算前端/pressure_pipe/panel.py` 中的结果视图已从“强依赖 `QWebEngineView`”调整为“优先使用 `QWebEngineView`，失败时自动降级为只读 HTML 视图”。
- 触发降级的典型场景包括 `PySide6.QtWebEngineWidgets` 导入失败、页面文件不足或当前环境缺少 WebEngine 运行条件；降级后主程序仍可打开，有压管道页会显示简化结果视图提示。
- 本次兼容修复的目标是“主程序先可启动、结果页可回退显示”，不是改变有压管道的水力计算公式、推荐逻辑或批量扫描规则。

### 2.5 依赖

| 库 | 用途 |
|----|------|
| matplotlib + seaborn | 批量扫描图表绘制 |
| pypdf | 子图 PDF 合并 |

---

## 三、子系统 B — 批量计算与水面线集成

### 3.1 文件结构

```
推求水面线/
├── core/
│   ├── pressure_pipe_calc.py          # 水头损失计算核心（沿程 + 弯头 + 渐变段，含空间模式）
│   └── pressure_pipe_data.py          # 简版 PressurePipeGroup + DataExtractor（batch面板用）
├── managers/
│   └── pressure_pipe_manager.py       # 持久化管理器（.ppipe.json）
├── utils/
│   ├── pressure_pipe_extractor.py     # 完整版 PressurePipeGroup + DataExtractor（水面线用，支持多行模式）
│   └── pressure_pipe_result_helpers.py # 结果格式化/序列化辅助（含灵敏度分析）
└── models/
    ├── enums.py                       # StructureType.PRESSURE_PIPE
    └── data_models.py                 # ChannelNode.is_pressure_pipe, external_head_loss

app_渠系计算前端/
├── batch/panel.py                     # 批量计算面板（有压管道占位行）
└── water_profile/panel.py             # 水面线面板（有压管道计算按钮 + 集成）
```

### 3.2 枚举与数据模型变更

#### enums.py

- `StructureType.PRESSURE_PIPE = "有压管道"`
- `get_special_structures()` 包含 `PRESSURE_PIPE`（需要进出口标识）

#### data_models.py — ChannelNode 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_pressure_pipe` | `bool` | 是否为有压管道行 |
| `external_head_loss` | `Optional[float]` | 外部导入的水头损失（有压管道/倒虹吸共用） |

#### data_models.py — IP 显示规则

`get_ip_str()` 中有压管道缩写为 **"压"**。

- 有压管道的进口/出口行仅显示 `XX管压进`、`XX管压出`，**不再带 IP 前缀**
- 这些进出口行**不占显示用 IP 编号**
- 同一建筑物内部的普通转点，以及建筑物外部普通点，继续显示连续的 `IP{n}`

### 3.3 批量计算面板集成

#### 3.3.1 列结构

`INPUT_HEADERS` 共 22 列（col 0-21），新增 1 列：

| 列索引 | 列名 | 说明 |
|--------|------|------|
| col 21 | 管材 | 有压管道专用：HDPE管/球墨铸铁管/钢管等 |

> **隐藏参数传递机制**：`局部损失比例`（`local_loss_ratio`）、`进出口标识`（`in_out_raw`）不占表格列。从批量计算导入水面线时，通过表格行首单元格的 `Qt.UserRole` 元数据传递，最终写入 `ChannelNode.section_params`。

#### 3.3.2 结构形式选项

`SECTION_TYPES` 包含 `"有压管道"`。

#### 3.3.3 占位行处理

有压管道在批量计算中为**占位行**（不直接计算断面参数）：

```python
if section_type == "有压管道":
    # 标记为占位行
    result['success'] = True
    result['section_type'] = '有压管道'
    result['is_pressure_pipe'] = True
    # 读取管材、D、转弯半径等基础参数传递给水面线
```

#### 3.3.4 糙率列

有压管道行的糙率列（col 7）禁用编辑（`setFlags` 移除 `ItemIsEditable`），因其糙率由管材系数隐含。

### 3.4 水头损失计算核心（pressure_pipe_calc.py）

#### 3.4.1 管材参数表

`PIPE_MATERIALS` 字典键名 → 展示名映射：

| 键名（代码） | 展示名 | f | m | b |
|-------------|--------|---|---|---|
| `HDPE管` | HDPE管 | 94,800 | 1.77 | 4.77 |
| `玻璃钢夹砂管` | 玻璃钢夹砂管 | 94,800 | 1.77 | 4.77 |
| `球墨铸铁管` | 球墨铸铁管 | 223,200 | 1.852 | 4.87 |
| `预应力钢筒混凝土管` | 预应力钢筒混凝土管 (n=0.013) | 1,312,000 | 2.0 | 5.33 |
| `预应力钢筒混凝土管_n014` | 预应力钢筒混凝土管 (n=0.014) | 1,516,000 | 2.0 | 5.33 |
| `钢管` | 钢管 | 625,000 | 1.9 | 5.1 |

#### 3.4.2 渐变段型式与ζ值（表L.1.2，与倒虹吸统一）

`TRANSITION_FORMS` 字典（与 `constants.py SIPHON_TRANSITION_ZETA_COEFFICIENTS` 一致）：

| 渐变段型式 | 进口ζ₁ | 出口ζ₃ | 备注 |
|-----------|--------|--------|------|
| 反弯扭曲面 | 0.10 | 0.20 | |
| 直线扭曲面 | 0.20 | 0.40 | 取均值（范围0.05~0.30 / 0.30~0.50） |
| 1/4圆弧 | 0.15 | 0.25 | |
| 方头型 | 0.30 | 0.75 | |

#### 3.4.3 核心函数

```python
# 管内流速
calc_pipe_velocity(Q_m3s, D_m) -> float

# 沿程损失（GB 50288 §6.7.2）
calc_friction_loss(Q_m3s, D_m, L_m, material_key) -> (hf, details)

# 弯头局部损失（表L.1.4-3/L.1.4-4，复用倒虹吸 CoefficientService）
calc_bend_local_loss(D_m, turn_radius_m, turn_angle_deg, V_m_s) -> (xi, hj, details)

# 渐变段损失
calc_transition_loss(V_pipe, V_channel, zeta, is_inlet) -> (hj, details)

# 转角自动计算
calc_turn_angle(p_prev, p_curr, p_next) -> float  # 度

# 两点距离
calc_segment_length(p1, p2) -> float  # m
```

#### 3.4.4 总水头损失计算

**PressurePipeCalcResult 数据类**：

| 属性 | 说明 |
|------|------|
| `name` | 管道名称 |
| `Q` / `D` / `material_key` | 基本参数 |
| `total_length` | 总管长 (m) |
| `pipe_velocity` | 管内流速 (m/s) |
| `friction_loss` | 沿程水头损失 (m) |
| `bend_losses` / `total_bend_loss` | 各弯头损失列表 / 合计 (m) |
| `inlet_transition_loss` / `outlet_transition_loss` | 进出口渐变段损失 (m) |
| `total_head_loss` | 总水头损失 (m) |
| `data_mode` | 数据模式（平面模式 / 空间模式（平面+纵断面）） |
| `calc_steps` | 计算过程文本 |
| `friction_details` | 沿程损失计算详情（Dict） |
| `bend_details` | 各弯头损失计算详情（List[Dict]） |
| `inlet_transition_details` | 进口渐变段计算详情（Dict） |
| `outlet_transition_details` | 出口渐变段计算详情（Dict） |

**两种计算入口**：

| 函数 | 场景 | 管长来源 | 弯道损失来源 |
|------|------|----------|-------------|
| `calc_total_head_loss()` | 仅有平面IP点 | IP点直线距离之和 | IP点转角+转弯半径查表 |
| `calc_total_head_loss_with_spatial()` | 有平面+纵断面数据 | 空间长度（SpatialMerger） | 空间弯道 θ_3D 查表 |

**总水头损失公式**：

$$\Delta H = h_f + \sum h_{j,弯} + h_{j,进口} + h_{j,出口}$$

**空间模式**调用倒虹吸的 `SpatialMerger.merge_and_compute()` 进行三维空间合并计算，获取空间长度和空间转角。对空间节点遍历查表（ARC型调用 `calculate_bend_coeff`，FOLD型调用 `calculate_fold_coeff`）。

#### 3.4.5 弯头系数查表

内置简化查表函数（备用，当 `CoefficientService` 不可用时）：

**表 L.1.4-3 直角弯道系数 ξ₉₀**：

| R/D₀ | 0.5 | 1.0 | 1.5 | 2.0 | 3.0 | 4.0 | 5.0 | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 |
|------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|------|
| ξ₉₀ | 1.20 | 0.80 | 0.60 | 0.48 | 0.36 | 0.30 | 0.29 | 0.28 | 0.27 | 0.26 | 0.25 | 0.24 |

**表 L.1.4-4 任意角修正系数 γ**：

| θ(°) | 5 | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 100 | 120 | 140 |
|------|---|----|----|----|----|----|----|----|----|-----|-----|-----|-----|
| γ | 0.125 | 0.23 | 0.40 | 0.55 | 0.65 | 0.75 | 0.83 | 0.88 | 0.95 | 1.00 | 1.05 | 1.13 | 1.20 |

### 3.5 数据提取器（两个版本）

系统存在两个 `PressurePipeDataExtractor`，分别服务不同场景：

#### 3.5.1 简版（pressure_pipe_data.py）— 批量计算面板用

**PressurePipeGroup**（简版）：

| 属性 | 说明 |
|------|------|
| `name` | 建筑物名称 |
| `inlet_node` / `outlet_node` | 进口/出口 ChannelNode |
| `inlet_row_index` / `outlet_row_index` | 行索引 |
| `diameter_D` / `roughness` / `flow` | 管径/糙率/流量 |

**提取逻辑** `extract_pressure_pipe_groups(nodes)`：
- 按 `name` 分组
- 识别 `in_out == INLET/OUTLET`
- 无名节点自动编号（"有压管道1"、"有压管道2"等）
- 从 `section_params` 提取 `D`

#### 3.5.2 完整版（pressure_pipe_extractor.py）— 水面线面板用

**PressurePipeGroup**（完整版）：

| 属性 | 说明 |
|------|------|
| `name` | 建筑物名称 |
| `route_key` / `route_display_name` | 所属流量段键值 / 展示名称（mixed route 汇总用） |
| `route_start_mc` / `route_end_mc` | 整个流量段的起止里程 |
| `segment_start_mc` / `segment_end_mc` | 当前子段的起止里程 |
| `route_member_keys` | 同一流量段下全部子段的身份键集合 |
| `rows` | 该管道所有行（进+IP+出）的 ChannelNode 列表 |
| `row_indices` | 各行在原始列表中的索引 |
| `inlet_row_index` / `outlet_row_index` / `ip_row_indices` | 进/出/IP点索引 |
| `design_flow` / `diameter` / `material_key` | 管道参数 |
| `local_loss_ratio` | 局部损失比例（默认0.15） |
| `ip_points` | IP点列表 `[{x, y, turn_radius, turn_angle}, ...]` |
| `plan_segments` / `plan_total_length` | 平面段列表 / 总长 |
| `upstream_velocity` / `downstream_velocity` | 上下游渠道流速 |
| `upstream_structure_type` / `downstream_structure_type` | 上下游结构类型（Optional[str]） |
| `upstream_section_params` / `downstream_section_params` | 上下游断面参数 |
| `inlet_transition_form` / `outlet_transition_form` | 渐变段型式 |
| `inlet_transition_zeta` / `outlet_transition_zeta` | 渐变段ζ系数 |

**提取逻辑** `extract_pipes(nodes, settings)`：
1. 识别 `structure_type == PRESSURE_PIPE` 的节点
2. 按 `name` 分组
3. 通过 `section_params['in_out_raw']` 识别进口("进")/IP点("IP")/出口("出")
4. 提取IP点坐标信息 → `_extract_ip_points()`
5. 自动计算各中间IP点转角 → `_calc_turn_angles()`
6. 计算平面段长度 → `_calc_plan_segments()`
7. 提取上下游渠道节点数据 → `_extract_adjacent_node_data()`
8. 从项目设置提取渐变段型式 → `_extract_transition_forms()`（复用倒虹吸设置）

**连续承压链补充规则**：
- `xx管` 继续沿用原有 mixed route 口径，前置隧洞仍可作为整线起点存在。
- `支渠` 连续承压链只从首个真正的 `有压管道 / 定向钻 / 顶管` 开始；出现在这之前的前置隧洞不再进入链成员。
- 一旦已经进入真正的有压段，后续紧接的隧洞仍可保留在同一条连续承压链中。
- `支渠` 的 `route_start_row_index`、`route_ip_points` 与整线导入锚点，都跟随这条收紧后的链范围生成，不能再落到前置隧洞上。

### 3.6 持久化管理器（pressure_pipe_manager.py）

**PressurePipeConfig 数据类**：

| 属性 | 说明 |
|------|------|
| `name` / `Q` / `D` / `material_key` | 基本参数 |
| `local_loss_ratio` | 局部损失比例 |
| `inlet_transition_form` / `outlet_transition_form` | 渐变段型式 |
| `inlet_transition_zeta` / `outlet_transition_zeta` | 渐变段ζ系数 |
| `upstream_velocity` / `downstream_velocity` / `pipe_velocity` | 流速参数 |
| `ip_points` | IP点列表 |
| `plan_total_length` | 总管长 |
| `longitudinal_nodes` | 纵断面变坡点节点（可选，DXF导入） |
| `profile_segments` | 按流量段保存的纵断面片段列表（mixed route 优先使用） |
| `friction_loss` / `total_bend_loss` / `inlet_transition_loss` / `outlet_transition_loss` / `total_head_loss` | 计算结果 |
| `data_mode` | 数据模式 |
| `calculated_at` | 计算时间 |

**PressurePipeManager**：
- 配置文件：`{项目文件名}.ppipe.json`
- `set_pipe_config(name, config)` / `get_pipe_config(name)` — 配置读写
- `set_result(name, total_head_loss, ...)` — 保存计算结果
- `get_result(name)` / `get_all_results()` — 获取水头损失
- `has_result(name)` — 检查是否有结果
- `clear_all()` — 清空
- `routes[route_key].longitudinal_nodes` 继续兼容纯普通有压管道整线
- `routes[route_key].profile_segments` 作为 mixed route 的统一几何真源，优先供计算与导出采样使用
- 普通有压子段若只剩 1 个纵断面点，只视为边界占位；导出时应回退整线 `routes[route_key].longitudinal_nodes`，隧洞生成段除外
- 整线卡里导入或清空纵断面 DXF 后，需要立即同步到 `routes[route_key].longitudinal_nodes`，不能等到“开始计算”后才落盘

### 3.7 结果辅助函数（pressure_pipe_result_helpers.py）

| 函数 | 说明 |
|------|------|
| `make_pressure_pipe_identity(flow_section, name)` | 构造稳定身份键 `"流量段::名称"` |
| `empty_pressure_pipe_calc_records()` | 空记录结构 |
| `normalize_pressure_pipe_calc_records(raw)` | 规范化/兼容旧数据 |
| `format_pressure_pipe_record_detail(record)` | 单条记录 → 文本 |
| `format_pressure_pipe_calc_batch_text(batch)` | 批次记录 → 章节文本 |
| `append_pressure_pipe_calc_batch_text(existing_text, batch)` | 追加到详细过程 |

**灵敏度分析字段**（球墨铸铁管 f 上下限对比，管材为球墨铸铁管时自动计算）：

| 字段 | 说明 |
|------|------|
| `sensitivity_material` | 对比管材 |
| `sensitivity_main_f` / `sensitivity_low_f` | 主值 f / 下限 f |
| `sensitivity_low_friction_loss` / `sensitivity_low_total_head_loss` | 下限 f 的沿程/总损失 |
| `sensitivity_delta_total_head_loss` | ΔH(下限−主值) |

### 3.8 水面线面板集成（water_profile/panel.py）

#### 3.8.1 基础设置区

| 控件 | 说明 |
|------|------|
| `pressure_pipe_roughness_chips` | 有压管道参数展示芯片（`SiphonRoughnessChipContainer`，显示管材和 f/m/b 系数） |

#### 3.8.2 节点数据表工具栏

| 按钮 | 功能 |
|------|------|
| **有压管道水力计算** | `PrimaryPushButton`，调用 `_open_pressure_pipe_calculator()`，打开有压管道计算窗口 |

按钮在有压管道节点存在时高亮提示。

#### 3.8.3 有压管道计算流程

`_open_pressure_pipe_calculator()` 执行：
1. 从节点表提取有压管道分组和连续承压链
2. `xx渠` 只有在末端或跨流量段形成连续承压线时，才进入“整线卡 + 分段计算”入口；非连续场景继续按当前有压管道分组逐组弹窗
3. `xx管` 流量段继续进入“整线卡 + 隧洞分段卡”混合弹窗；整线仍只导入 1 份 DXF，但只要求覆盖非隧洞区间
4. 一旦进入连续承压整线模式，底层按整线管理 DXF、route context 和 mixed route 几何；但压力管道特性表、统计摘要和结果回写继续按原有分段和流量段表达
5. 若流量段起点就是隧洞，DXF 第一点评到第一段非隧洞子段起点里程，而不是整线起点
6. 普通有压段继续使用 DXF 裁切后的纵断面；隧洞段按“进口底高 + 坡降 i + 起终里程”生成理论纵断面，并做交界高差提醒
7. 对每个管道或链成员执行水头损失计算（`calc_total_head_loss()` 或 `calc_total_head_loss_with_spatial()`）；隧洞成员继续复用既有隧洞计算口径参与承压链累计
8. 结果回写到节点表的 `head_loss_siphon` 列；隧洞行仍按自身既有规则回写，避免 route 结果重复覆盖
9. mixed route 的拼接结果持久化到 `PressurePipeManager.routes[route_key].profile_segments`
10. 更新详细过程文本区
11. 整线卡导入/清空纵断面 DXF 后，先立即同步到 `PressurePipeManager`，保证主页面导出与弹窗预览读取同一份数据

**纵断面 DXF 自动选线补充规则**：
- 导入时不再盲取 DXF 里的首条多段线，而是先对全部多段线做候选排序。
- 候选排序优先级固定为：图层名命中 `JQX / 纵剖 / 纵断 / 纵剖面` → 更像局部坐标而非工程大坐标 → `xspan` 更大 → 路径总长更长 → 顶点数更多。
- 只有“非闭合、横向展开明显、`x` 向跨度足够大”的多段线才进入主比较池；若没有合格候选，再回退到全量候选里取最像的一条。
- `get_longitudinal_profile_start_x()` 与 `parse_longitudinal_profile()` 必须共用同一套选线逻辑，避免“算偏移时取一条线、解析节点时又取另一条线”。
- 当头两名候选非常接近时，界面层会在正式导入前弹一次确认，提醒用户按推荐候选继续或取消导入。

#### 3.8.4 灵敏度分析

球墨铸铁管的 f 系数在规范中为区间取值（主值 223,200 / 下限 189,900）。当检测到管材为球墨铸铁管时，系统自动计算并展示两种 f 下的水头损失对比结果，无需手动开启。

#### 3.8.5 水面线递推中的处理

有压管道节点在水力计算中的处理逻辑与倒虹吸一致：
- `is_pressure_pipe = True` → 不另行计算沿程/弯道/局部损失
- 总水头损失直接使用 `external_head_loss`（外部导入值）
- 水位递推时整体扣减总水头损失

---

## 四、渐变段处理

有压管道的渐变段处理与倒虹吸一致（详见 `PRD_渐变段与明渠段插入算法.md`）：

| 项目 | 规则 |
|------|------|
| 渐变段长度 | 进口 = 5h_上游，出口 = 6h_下游（GB 50288 §10.2.4，不使用基础公式 L=k×|B₁-B₂|） |
| 渐变段ζ系数 | 复用倒虹吸渐变段设置（表L.1.2） |
| 与闸穿透 | 有压管道出口→闸 / 闸→有压管道进口 均插入渐变段（skip_loss=True） |
| 占位渐变段 | 有压管道侧的渐变段标记 `transition_skip_loss=True`（水损已含在有压管道计算中） |

---

## 五、CAD 导出规则

- 断面汇总表中，有压管道单独输出为"有压管道断面尺寸及水力要素表"，列结构与倒虹吸一致
- "导出全部DXF"调用统一参数对话框；其中有压管道参数按“流量段主行 + 顶管/定向钻单独行”显示，普通有压管道同一流量段只显示 1 行
- 有压管道参数弹窗只负责录入展示，确认后仍需把“流量段主行”重新展开回该流量段下全部普通有压管道原始分组；顶管/定向钻仅回写到各自对应分组
- 压力管道特性表里的`长度`和`设计流速`必须按流量段逐行输出；其中主长度统一以该流量段在表3里的连续桩号累计值为准，普通有压管道段也必须参与统计，不能退化成隧洞/定向钻/顶管等建筑物长度小计，也不能因为“普通段接命名建筑物”或“跨流量段边界”漏算或串段。同一流量段最终只保留 1 行摘要，但匿名普通有压管道也必须沿用行级 `identity`、`Q`、`plan_total_length` 和子段起止桩号参加汇总，不能只靠“流量段 + 名称”回填；其中 `segment_start_mc / segment_end_mc` 只用于表达原始分组自身范围和兜底场景，不再作为主长度首选口径。若下一流量段首行桩号正好是上一流量段终点，则这段边界长度记入上一流量段，不得截短到上一段最后一个同段节点。整条支管所有转弯半径都为 `0` 时，该长度应与 IP 桩号口径一致；只要任一处转弯半径非 `0`，就应与里程桩号口径一致
- 压力管道特性表里的`设计流速`只调整展示精度：DXF 和 Excel 都固定保留 2 位小数，底层计算值与缓存值不改，避免影响已有水力计算和回写链路
- 顶管/定向钻在弹窗里可单独设置材质和 DN，但最终压力管道特性表仍只按流量段输出 1 行；顶管/定向钻只进入对应摘要列，不额外生成主行。`隧洞 / 定向钻 / 顶管` 的摘要长度统一按每组“出口里程MC - 进口里程MC”统计，中间 IP 点只用于识别整组，不得把出口后紧邻的普通有压管道并入建筑物长度
- 压力管道特性表里的`渠首水位 / 渠末水位`也必须按流量段逐行输出：默认仍取各流量段自己的首个有效水位和最后一个有效水位；但若后一流量段首个有压类节点正好是前一流量段的连续终点，则上一段`渠末水位`与下一段`渠首水位`都统一取这个切段点水位。若中间存在断点、缺口或非连续节点，则继续按各段自己的首末有效水位输出；多流量段场景下不得回退到整条管线的总起点/总终点水位
- `xx渠` 下的隧洞摘要需要再加一道口径过滤：只有同一流量段已经进入 `有压管道 / 定向钻 / 顶管` 之后再次出现的隧洞，才计入压力管道特性表；出现在首个有压类结构之前的隧洞，不进入这张表的隧洞座数和长度
- `xx管` 夹带隧洞的 mixed route 仍只导入 1 份纵断面 DXF，这份 DXF 只覆盖非隧洞子段；隧洞子段允许在 DXF 中留空，由系统按参数自动补齐
- `xx渠` 在末端或跨流量段形成连续承压整线时，纵断面导出复用 `xx管` 固定 5 项表头：`建筑物名称 / IP点名称 / 里程桩号 / 管中心线高程 / 管材（管径）`；单独 TXT、单独 DXF、合并 DXF 三个入口口径一致
- 连续承压 `xx渠` 中，普通“有压管道”第 1 行优先显示用户填写名称；名称为空时回退显示“有压管道”；`定向钻 / 顶管 / 隧洞` 继续沿用原有命名拼装口径
- 连续承压 `xx渠` 缺少纵断面轴线 DXF 或已导入但覆盖不全时，导出不再阻断；第 4 行对应中心高程位置直接留空，并在软件内提示用户回到表3“有压管道水力计算”中导入/补全纵断面轴线 DXF 后重导；严格 `xx管` 继续保留原有阻断规则
- `xx管` / 倒虹吸导入纵断面 DXF 时，若图里的顶点方向是反的（X 从大到小），系统应先自动归正到桩号递增方向，再计算导入偏移；不能因为用户重画轴线方向就把整条桩号区间算成负值，进而误报“未覆盖节点桩号”
- 纵断面 DXF 导入时，不允许再默认使用“文件里的第一条多段线”；应先按候选规则自动优选真正的纵断面，避免把工程坐标辅助线、框线或短折线误当纵断面
- 纵断面"坡降"行对有压管道留空（按有压流处理）
- `xx管` 纵断面第 4 行标题继续保持“管中心线高程（米）”；普通有压段填中心线高程，隧洞段填底高，不额外改标题
- `xx管` 纵断面第 5 行在隧洞段改为输出断面参数文本，例如“圆形隧洞 D=2.4m”；普通有压段继续显示材质和 DN
- 纵断面导出采样优先读取 `routes[route_key].profile_segments`；若命中的普通有压子段只有 1 个纵断面点，则视为边界占位并自动回退整线 `longitudinal_nodes`；只有纯普通有压整线或这类单点子段回退场景才使用旧的 `longitudinal_nodes`，隧洞生成段继续沿用自己的分段结果
- 连续承压整线跨流量段延续时，新流量段首个匿名普通有压行的自身范围可能退化为单点边界；只要该行已挂到整线 `route_key` 且上下游 `flow_section` 发生切换，导出就应直接继承整线 `longitudinal_nodes`，不能再按单点范围裁切
- 连续承压整线导出在同桩号合并节点后，不能只信任最终代表节点的单一 identity；若代表节点命不中整线纵断面，需要继续按节点组里的稳定 identity 候选重试，优先级为 `pressure_pipe_row_identity` → 当前分组 identity / route 起点锚点 identity → 旧的 `flow_section + name` 口径
- route 级整线纵断面导出映射除了主 identity，还要同步补齐起点锚点、单行成员和旧口径 identity；只要整线 DXF 已存在，这些别名 identity 也必须能拿到同一份 route 纵断面
- IP 点名称中，有压管道进/出口采用"压"缩写（示例：`XX管压进`、`XX管压出`）
- bzzh2 导出与建筑物名称上平面图均纳入有压管道进/出口识别

---

## 六、关键算法

### 6.1 转角自动计算

$$\theta_i = \arccos\left(\frac{\vec{v}_{in} \cdot \vec{v}_{out}}{|\vec{v}_{in}| \cdot |\vec{v}_{out}|}\right)$$

其中 $\vec{v}_{in} = P_i - P_{i-1}$，$\vec{v}_{out} = P_{i+1} - P_i$，$\theta_i$ 为两方向向量的夹角，取值范围为 $0° \le \theta_i \le 180°$。

- 工程实现中，当计算得到的 $\theta_i < 0.1°$ 时视为直线通过（坐标噪声），统一按 $0°$ 处理，不参与弯头损失计算。
- 当 $0.1° \le \theta_i < 180°$ 且设置了有效转弯半径 $R>0$ 时，才按第 6.3 节进行弯头损失计算。

### 6.2 管长计算

$$L_{total} = \sum_{i=0}^{n-1} \sqrt{(X_{i+1}-X_i)^2 + (Y_{i+1}-Y_i)^2}$$

空间模式下使用 `SpatialMerger` 计算的空间长度（含高程差）。

### 6.3 弯管局部损失系数

1. 计算 R/D 比值
2. 查表 L.1.4-3 → ξ₉₀（线性插值）
3. 查表 L.1.4-4 → γ（线性插值）
4. ξ_弯 = ξ₉₀ × γ
5. $h_j = \xi_{弯} \times V^2 / (2g)$

### 6.4 沿程损失

$$h_f = f \times L \times \frac{Q_{m^3/h}^m}{d_{mm}^b}$$

### 6.5 渐变段损失

进口（收缩）：$h_{j1} = \zeta_1 \times \frac{V_{管道}^2 - V_{渠道}^2}{2g}$

出口（扩散）：$h_{j3} = \zeta_3 \times \frac{V_{渠道}^2 - V_{管道}^2}{2g}$

负值取零。

---

## 七、相关代码文件索引

| 功能 | 文件路径 |
|------|----------|
| 有压管道设计内核（V9） | `calc_渠系计算算法内核/有压管道设计.py` |
| 有压管道设计面板 | `app_渠系计算前端/pressure_pipe/panel.py` |
| 水头损失计算核心 | `推求水面线/core/pressure_pipe_calc.py` |
| 简版数据提取器（batch用） | `推求水面线/core/pressure_pipe_data.py` |
| 完整版数据提取器（水面线用） | `推求水面线/utils/pressure_pipe_extractor.py` |
| 持久化管理器 | `推求水面线/managers/pressure_pipe_manager.py` |
| 结果辅助函数 | `推求水面线/utils/pressure_pipe_result_helpers.py` |
| 批量计算面板 | `app_渠系计算前端/batch/panel.py` |
| 水面线面板 | `app_渠系计算前端/water_profile/panel.py` |
| 枚举定义 | `推求水面线/models/enums.py` |
| 数据模型 | `推求水面线/models/data_models.py` |
| 倒虹吸系数服务（复用） | `倒虹吸水力计算系统/siphon_coefficients.py` |
| 空间合并引擎（复用） | `倒虹吸水力计算系统/spatial_merger.py` |
| 共享数据管理 | `推求水面线/shared/shared_data_manager.py` |

---

## 八、测试文件

| 文件 | 覆盖范围 |
|------|----------|
| `tests/test_pressure_pipe_kernel.py` | 有压管道设计内核（V9）单元测试 |
| `tests/test_pressure_pipe_batch.py` | 批量扫描输出测试 |
| `tests/test_pressure_pipe_spatial_calc_unit.py` | 空间模式水头损失计算 |
| `tests/test_pressure_pipe_validation_unit.py` | 数据验证单元测试 |
| `tests/test_pressure_pipe_validation_property.py` | 数据验证属性测试 |
| `tests/test_pressure_pipe_data_extraction_unit.py` | 数据提取器单元测试 |
| `tests/test_pressure_pipe_data_extraction_property.py` | 数据提取器属性测试 |
| `tests/test_pressure_pipe_preprocessing_unit.py` | 预处理单元测试 |
| `tests/test_pressure_pipe_identification_property.py` | 有压管道识别属性测试 |
| `tests/test_pressure_pipe_transition_coefficients_unit.py` | 渐变段系数查表单元测试 |
| `tests/test_pressure_pipe_transition_insertion_unit.py` | 渐变段插入单元测试 |
| `tests/test_pressure_pipe_transition_property.py` | 渐变段属性测试 |
| `tests/test_pressure_pipe_result_report_unit.py` | 结果报告格式化测试 |
| `tests/test_pressure_pipe_result_persistence_unit.py` | 结果持久化测试 |
| `tests/test_pressure_pipe_result_identity_unit.py` | 结果身份键测试 |
| `tests/test_pressure_pipe_persistence_with_long_unit.py` | 纵断面数据持久化测试 |
| `tests/test_pressure_pipe_export_longitudinal_nodes_unit.py` | mixed route 纵断面导出取数测试 |
| `tests/test_pressure_pipe_canvas_viewer_gui_unit.py` | mixed route 弹窗与导入覆盖校验测试 |
| `tests/test_water_profile_transition_ready_unit.py` | mixed route 预处理与计算入口测试 |
| `tests/test_xxpipe_longitudinal_export_unit.py` | `xx管` 隧洞纵断面表格行输出测试 |
| `tests/test_qfluentwidgets_compat.py` | 启动兼容层测试（`darkdetect` 超时/缺失兜底） |

---

## 九、变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| V1.0 | 2026-03-03 | 初始版本（需求确认稿） |
| V2.0 | 2026-03-06 | **全面重写**：合并 `有压管道/PLAN.md`（V9设计面板实施方案）；整理为独立设计面板（子系统A）+ 水面线集成（子系统B）两部分；数据模型、函数接口、文件结构全部对齐已实现代码；新增空间模式计算（`calc_total_head_loss_with_spatial`）；新增灵敏度分析（球墨铸铁管 f 上下限对比）；新增结果辅助函数说明；新增完整版数据提取器（多行模式：进口+IP点+出口）；新增持久化管理器说明；更新批量计算列结构（22列，仅新增1列"管材"，隐藏参数通过Qt.UserRole传递）；新增CAD导出规则；新增渐变段处理引用；新增测试文件索引（16个）；状态从"待实现"更新为"已实现" |
| V2.1 | 2026-03-06 | **校验修正**：§3.4.1管材参数表改为键名→展示名双列映射；§3.4.2渐变段ζ值对齐 `constants.py SIPHON_TRANSITION_ZETA_COEFFICIENTS`（直线扭曲面出口0.30→0.40，1/4圆弧进口0.25→0.15/出口0.35→0.25），同步修正 `pressure_pipe_calc.py` 代码；§3.4.4补充4个detail字段；§3.5.2补充 `upstream/downstream_structure_type`；§3.7补充 `sensitivity_enabled`；§3.3.1补充隐藏参数Qt.UserRole传递机制说明；§8测试文件扩展为完整16个 |
| V2.2 | 2026-03-06 | **灵敏度分析全自动化**：球墨铸铁管 f 上下限对比改为自动检测并计算，删除 `sensitivity_enabled` 开关字段；配置对话框删除勾选框；结果对话框删除勾选框和开关，对比列/摘要卡片根据数据自动显示 |
| V2.3 | 2026-03-08 | **双规范展示恢复**：有压管道页面与 Word 导出并列展示 GB 50288 + GB/T 20203 摘要；新增 GB/T 20203 §5.1.4~§5.1.6 条文摘要（含表4、表5、式14/17、式18仅页面）；补充“当前算法仍按 GB 50288 执行”说明；`report_meta.py` 中 `pressure_pipe` 参考文献与计算目的模板改为双规范并列。 |
| V2.4 | 2026-03-09 | **导出规则修复**：修复 `导出全部DXF` 中倒虹吸/有压管道断面汇总“复读机”问题；同流量段按 `Q`、`n`、`DN_mm`、`pipe_material` 判定一致性，一致则去重为单行，不一致则保留多行并显示"建筑物名称-流量段"；并修复 `overrides.name` 覆盖显示名称的问题。 |
| V2.5 | 2026-03-13 | **启动兼容修复**：新增 `qfluentwidgets_compat.py`，在主程序导入 `qfluentwidgets` 前为 `darkdetect` 提供超时/缺失兜底，避免系统主题探测阻塞导致程序无法启动；`pressure_pipe/panel.py` 的结果视图改为优先 `QWebEngineView`、失败自动降级为只读 HTML 视图，解决 `QtWebEngineWidgets` 因页面文件不足等环境问题导致主程序启动失败。 |
| V2.6 | 2026-04-01 | **流量段导出补链**：有压管道断面汇总弹窗改为优先复用窗口分组对象，匿名普通有压管道的 `identity / Q / plan_total_length` 会一路保留到 CAD 导出；压力管道特性表中的设计流速现按流量段逐行输出，长度改为取对应流量段总长，不再误用单个子段长度。 |
| V2.7 | 2026-04-01 | **弹窗展示压缩**：断面汇总里的有压管道参数弹窗改为“流量段主行 + 顶管/定向钻单独行”；普通有压管道同一流量段只显示 1 行，确认后再自动展开回原始分组，保证最终导出仍沿用原始 identity 和流量段汇总口径。 |
| V2.8 | 2026-04-01 | **流量段长度口径修正**：压力管道特性表主列长度不再直接复用建筑物摘要总长，改为按该流量段下全部原始分组的起止桩号累计；普通有压管道段也纳入总长统计，多个流量段相加需与整条支管总桩号一致。 |
| V2.9 | 2026-04-02 | **建筑物长度口径修正**：压力管道特性表中的隧洞、定向钻、顶管摘要长度改为按每组“出口里程MC - 进口里程MC”统计；中间 IP 点仅用于识别整组，不再把出口后紧邻的普通有压管道长度误并进建筑物摘要。 |
| V2.10 | 2026-04-02 | **设计流速显示精度修正**：压力管道特性表中的“设计流速”在 DXF 与 Excel 中统一按两位小数展示，例如 `0.7954` 显示为 `0.80`；内部计算值与缓存值保持原始精度。 |
| V2.11 | 2026-04-02 | **xx管 夹带隧洞 mixed route 支持**：取消“夹带隧洞暂不支持”拦截；`xx管` 弹窗改为“整线卡 + 隧洞分段卡”；整线 DXF 只覆盖非隧洞子段，隧洞纵断面按“进口底高 + 坡降 i + 起终里程”生成；新增 `profile_segments` 作为 mixed route 的统一几何真源；纵断面第 4 行隧洞段输出底高，第 5 行输出隧洞断面参数文本。 |
| V2.11.1 | 2026-04-02 | **mixed route 收口修正**：当整线起点先经过隧洞且首个非隧洞节点没有显式桩号时，DXF 导入会按该节点的回退桩号对齐，不再误回到整线起点；当 mixed route 后续改回纯有压整线时，会显式清空 route 级 `profile_segments`，避免历史隧洞纵断面残留影响导出。 |
| V2.11.2 | 2026-04-06 | **连续承压整线口径修正**：保留开始计算时 route 分段组装的 helper 修复；`xx渠` 在末端或跨流量段形成连续承压线时，也可进入整线卡；非连续场景仍只显示当前分组；压力管道特性表继续按原有分段和流量段表达，其中 `xx渠` 的隧洞只在已进入 `有压管道 / 定向钻 / 顶管` 之后才计入摘要。 |
| V2.11.3 | 2026-04-07 | **多流量段水位口径修正**：压力管道特性表中的“渠首水位 / 渠末水位”改为按各流量段自己的首个有效水位和最后一个有效水位输出；没有有效水位时保持空值，不再误用整条管线的总起点/总终点水位。 |
| V2.11.4 | 2026-04-07 | **多流量段主长度口径修正**：压力管道特性表主列长度改为优先使用流量段连续桩号累计值；普通有压管道接命名建筑物前的短段不再漏算，跨流量段边界不再误并入下一段；匿名普通有压段的 `segment_start_mc` 也会避开跨段上游参考点。 |
| V2.11.5 | 2026-04-07 | **跨流量段终点口径补正**：压力管道流量段摘要总长度改为按“当前节点到下一节点”的连续桩号累加；当下一流量段首行就是上一流量段终点时，上一流量段长度会延伸到该起点，不再停在上一段最后一个同段节点。 |
| V2.11.5 | 2026-04-07 | **连续承压 xx渠 导出放宽**：连续承压整线的 `xx渠` 纵断面现在复用 `xx管` 固定 5 项表头；普通有压段第 1 行优先显示用户名称；当纵断面轴线 DXF 缺失或覆盖不全时，TXT / DXF / 合并 DXF 继续允许导出，第 4 行中心高程留空，并统一弹出“回表3导入/补全纵断面轴线 DXF 后重导”的提示。 |
| V2.11.6 | 2026-04-07 | **流量段边界水位统一**：压力管道流量段摘要在识别到连续承压线跨流量段切换时，会把后一流量段首个边界点水位同时写成前一流量段的渠末水位和后一流量段的渠首水位；非连续场景仍保持各段各自的首末有效水位。 |
| V2.11.7 | 2026-04-07 | **整线纵断面导入即时保存**：有压管道弹窗里整线卡导入或清空纵断面 DXF 后，会立刻同步到 `PressurePipeManager.routes[route_key].longitudinal_nodes`；这样弹窗预览和主页面导出读取同一份数据，不再出现“图2已导入、图1仍提示没导入”。 |
| V2.11.8 | 2026-04-07 | **双桥支管 identity 误判修复**：连续承压整线导出时，同桩号合并后的代表节点若命不中整线纵断面，会继续按节点组 identity 候选回退匹配；route 级导出映射也补齐起点锚点、单行成员和旧口径 identity，并把“真没导入”和“identity 没匹配上”拆成两类提示。 |
| V2.11.9 | 2026-04-07 | **双桥支管跨流量段边界行修复**：连续承压整线跨流量段延续时，新流量段首个匿名普通行即使只对应单点桩号，也会在导出阶段直接继承整线 `routes.longitudinal_nodes`，不再因为单点裁切把已导入的整线 DXF 误判成“未导入”。 |
| V2.11.10 | 2026-04-07 | **三清支渠纵断面与链路修复**：纵断面 DXF 导入改为按候选规则自动优选，不再盲取首条多段线；当头两名候选非常接近时，导入前会先弹确认。`支渠` 连续承压链与 route 上下文改为从首个真正有压段开始，前置隧洞不再误入整线卡、导入锚点和 route 起点。 |
