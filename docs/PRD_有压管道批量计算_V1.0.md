# 有压管道 — 综合 PRD

> **版本**: V2.1  
> **创建日期**: 2026-03-03  
> **最后更新**: 2026-03-06  
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

**GB 50288 公式**：

$$h_f = f \times L \times \frac{Q^m}{d^b}$$

- $Q$: m³/h（需从 m³/s × 3600 换算）
- $d$: mm（需从 m × 1000 换算）
- 局部损失系数取沿程的 15%：$h_{j,km} = 0.15 \times h_{f,km}$

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

`get_ip_str()` 中有压管道缩写为 **"压"**，示例：`IP42 XX管压进`、`IP43 XX管压出`。

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
1. 从节点表提取有压管道分组（`PressurePipeDataExtractor.extract_pipes()`）
2. 对每个管道执行水头损失计算（`calc_total_head_loss()` 或 `calc_total_head_loss_with_spatial()`）
3. 结果回写到节点表的 `head_loss_siphon` 列
4. 持久化保存到 `PressurePipeManager`
5. 更新详细过程文本区

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
- "导出全部DXF"调用统一参数对话框，按建筑物名称分别设置管道材质和 DN
- 纵断面"坡降"行对有压管道留空（按有压流处理）
- IP 点名称中，有压管道进/出口采用"压"缩写（示例：`XX管压进`、`XX管压出`）
- bzzh2 导出与建筑物名称上平面图均纳入有压管道进/出口识别

---

## 六、关键算法

### 6.1 转角自动计算

$$\theta_i = 180° - \arccos\left(\frac{\vec{v}_{in} \cdot \vec{v}_{out}}{|\vec{v}_{in}| \cdot |\vec{v}_{out}|}\right)$$

其中 $\vec{v}_{in} = P_i - P_{i-1}$，$\vec{v}_{out} = P_{i+1} - P_i$。

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

---

## 九、变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| V1.0 | 2026-03-03 | 初始版本（需求确认稿） |
| V2.0 | 2026-03-06 | **全面重写**：合并 `有压管道/PLAN.md`（V9设计面板实施方案）；整理为独立设计面板（子系统A）+ 水面线集成（子系统B）两部分；数据模型、函数接口、文件结构全部对齐已实现代码；新增空间模式计算（`calc_total_head_loss_with_spatial`）；新增灵敏度分析（球墨铸铁管 f 上下限对比）；新增结果辅助函数说明；新增完整版数据提取器（多行模式：进口+IP点+出口）；新增持久化管理器说明；更新批量计算列结构（22列，仅新增1列"管材"，隐藏参数通过Qt.UserRole传递）；新增CAD导出规则；新增渐变段处理引用；新增测试文件索引（16个）；状态从"待实现"更新为"已实现" |
| V2.1 | 2026-03-06 | **校验修正**：§3.4.1管材参数表改为键名→展示名双列映射；§3.4.2渐变段ζ值对齐 `constants.py SIPHON_TRANSITION_ZETA_COEFFICIENTS`（直线扭曲面出口0.30→0.40，1/4圆弧进口0.25→0.15/出口0.35→0.25），同步修正 `pressure_pipe_calc.py` 代码；§3.4.4补充4个detail字段；§3.5.2补充 `upstream/downstream_structure_type`；§3.7补充 `sensitivity_enabled`；§3.3.1补充隐藏参数Qt.UserRole传递机制说明；§8测试文件扩展为完整16个 |
| V2.2 | 2026-03-06 | **灵敏度分析全自动化**：球墨铸铁管 f 上下限对比改为自动检测并计算，删除 `sensitivity_enabled` 开关字段；配置对话框删除勾选框；结果对话框删除勾选框和开关，对比列/摘要卡片根据数据自动显示 |
