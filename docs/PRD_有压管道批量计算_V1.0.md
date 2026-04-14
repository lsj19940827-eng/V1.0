# 有压管道 — 综合 PRD

> **版本**: V2.12.11
> **创建日期**: 2026-03-03  
> **最后更新**: 2026-04-14
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
- `app_渠系计算前端/webengine_diagnostics.py` 的启动预检不再调用 `platform.platform()`；Windows 下改为直接拼装系统版本字段，避免该接口在个别环境阻塞后把 `main.py` 卡在主窗口出现之前。
- `app_渠系计算前端/pressure_pipe/panel.py` 的右侧初始帮助页不再在主程序启动时同步渲染，而是延后到用户第一次真正打开“有压管道设计”页面时再加载；这样主窗口可以先出来，不会再被该页面的 Web 帮助内容拖住。
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

`get_ip_str()` 中有压管道同类保留各自结构名称。

- 命名普通有压管道的进口/出口行仅显示 `XX管有压管道进`、`XX管有压管道出`，**不再带 IP 前缀**
- 命名定向钻 / 顶管的进口/出口行分别显示 `XX管定向钻进/出`、`XX管顶管进/出`
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

#### 3.3.5 支渠连续承压链重名口径

- 批量计算入口不再把所有“同名普通有压管道”一律判成失败。
- 内部重名结果拆成两桶：`hard_duplicates`（真正风险重名）与 `allowed_chain_duplicates`（允许放开的连续承压链重名）。
- 仅当渠道级别为 `支渠`，且前后重复的是普通 `有压管道`，中间只经过 `有压管道 / 定向钻 / 顶管 / 隧洞` 等连续承压链成员时，才允许放开。
- 若中间被 `明渠 / 闸 / 倒虹吸 / 暗涵 / 分水` 等非连续承压结构断开，则仍视为真正重名，继续拦截。
- `顶管 / 定向钻 / 隧洞` 这类命名建筑物本身仍要求唯一，不在放开范围内。

#### 3.3.6 同名隧洞跨闸重名口径

- 同名隧洞若只被 `分水闸 / 分水口 / 节制闸 / 泄水闸 / 退水闸` 这类闸点打断，前后仍按同一条隧洞处理，不计入真正重名。
- 该规则适用于所有渠道级别，只对隧洞生效；非隧洞建筑即使中间夹着闸点，仍保持原有重名拦截口径。

#### 3.3.6 赛金支渠连续承压身份与导出口径

- `支渠` 连续承压链里的命名父组继续保留 `flow_section::name::rows...` 身份，只负责窗口汇总；真正参与表3写回、链内统计、`route / segment` 持久化和 xx管 纵断面导出的正式成员，统一使用 `flow{流量段}-row{行号}`。
- 节点窗口覆盖、链成员写回、`route / segment` 持久化、xx管 纵断面导出，全部以正式逐行成员 identity 为准；父组不再和任何子成员共用同一个 identity。
- 若 `xx渠` / `支渠` 连续承压链里的命名 `有压管道 / 定向钻 / 顶管` 已真正进入连续承压链，且本体至少覆盖 2 行，就统一拆成逐行成员正式计损；表3按逐段值正式递推，窗口汇总仍保留整组总损失。
- 拆分后的展示名只取基础名称再统一加“前段 / 中段N / 后段”，不再继承已经带后缀的父组展示名，避免出现 `苟家湾（后段）（中段1）` 这类双后缀。
- 链成员展示名只用于链内结果展示，不参与底层 `named_row_segment` 逐段小分组校验；逐段小分组校验标签固定取基础名称，避免 `前缀段 / 中段N` 这类后缀串到失败原因里。
- 末尾拆分后的逐行成员会同时保留三类 source aliases：原父组的 `identity / storage_key`、兼容用的 `legacy_identity / legacy_storage_key`，以及当前 `flow-row` 身份；这样 fresh dialog 分组、chain source lookup 和执行前校验都能认出“这组已经拆成逐行成员”。
- `extract_dialog_pipe_groups()` 返回的父命名组继续保留原 `flow_section::name::rows...` 身份，并稳定标记 `split_to_row_members=True`；父组只负责窗口汇总，不再作为表3正式写回口，也不再参与“执行计算前是否已完成”的判定。
- 连续承压结果保存改成“当前整线快照覆盖活动范围”，同一整线范围内旧的 `route / segment / pipe` 残留会被一起清掉。
- xx管 导出查找先按新身份找正式分段；若先撞到没有有效纵断面的旧记录，会继续按 `route_key` 回退整线纵断面。
- mixed route 严格导出时，隧洞行不要求匹配导入轴线；像 `蒲支2+739.785` 这类刚好落在第二份 DXF 起点边界的首段行，也改为按当前行自己的 `station_mc` 判断是否退回整线 route，不再拿整段左边界去误判覆盖不足。
- mixed route 第二份 DXF 的起点边界与下方 `xxpipe` 表整高边界统一按真实当前节点/可见表格边界判断；像 `蒲支1+950.37` 这类边界点不再漏掉“管中心线高程（米）”，`蒲支1+981.79` 的首尾整高竖线也不会再被首个有效中心线点带偏后穿到建筑物名称上边线。
- 在“前渠道 + 末尾连续有压链”的 mixed route 导出里，标准纵断面高程线若遇到中途回到起点的无效断点，必须跳过坏点或按有效连续段分段绘制，不能把后续折线整段回拉到起点。
- 连续承压链汇总只认成员自己的正式 identity；若某个成员存在但没匹配到自己的计算记录，会单独提示“未匹配到本成员计算记录”，不再复用前缀段或父组的失败文案。
- `named_row_segment` 路径返回失败时，界面层必须把失败原因抬头同步为当前链成员自己的展示名；只替换抬头，不改原因正文。
- 链起点锚点、前缀段这类 `status=success + writeback_enabled=False` 的成员继续按成功处理，只说明“本行不写回”，不再归到失败统计。
- 本次口径的目标，是修掉赛金支渠 `赛支3+968.95 / 405m` 被留空的问题；`IP点名称 / 里程桩号` 的现有视觉排版不在本次改动范围内。

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
| `storage_key` / `identity` | 当前连续段优先的稳定键 |
| `legacy_storage_key` / `legacy_identity` | 旧口径兼容键（名称 / `flow_section::name`） |
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
2. 按“连续出现的同名段”分组；同名普通有压段夹带命名 `顶管 / 定向钻 / 隧洞` 时，拆成多个连续成员
3. 通过 `section_params['in_out_raw']` 识别进口("进")/IP点("IP")/出口("出")
4. 提取IP点坐标信息 → `_extract_ip_points()`
5. 自动计算各中间IP点转角 → `_calc_turn_angles()`
6. 计算平面段长度 → `_calc_plan_segments()`
7. 提取上下游渠道节点数据 → `_extract_adjacent_node_data()`
8. 从项目设置提取渐变段型式 → `_extract_transition_forms()`（复用倒虹吸设置）
9. 当前连续段的 `identity / storage_key` 优先使用连续段键；旧 `flow_section::name` 只保留到 `legacy_identity / legacy_storage_key`

**连续承压链补充规则**：
- `xx管` 继续沿用原有 mixed route 口径，前置隧洞仍可作为整线起点存在。
- `支渠` 连续承压链只从首个真正的 `有压管道 / 定向钻 / 顶管` 开始；出现在这之前的前置隧洞不再进入链成员。
- 一旦已经进入真正的有压段，后续紧接的隧洞仍可保留在同一条连续承压链中。
- `支渠` 的 `route_start_row_index`、`route_ip_points` 与整线导入锚点，都跟随这条收紧后的链范围生成，不能再落到前置隧洞上。
- `支渠` 链首若是“单点、仅进口、后续同链仍有同名普通有压段”的命名普通有压，则优先识别为链起点前缀段：只要到下一段 `定向钻 / 顶管 / 隧洞` 进口之间存在有效长度，就按沿程损失参与计算，并把结果写回下一段特殊承压建筑的进口行。
- 只有当前缀长度无效、无法裁出可用纵断面或拿不到有效参数时，链首成员才回退为链起点锚点：成员状态记成功，但 `writeback_enabled=False`、`total_head_loss=None`，不单独计损。
- `支渠` 末尾连续承压中的命名 `有压管道 / 定向钻 / 顶管`，若本身是连续尾段且内部有 `进 / 中间 / 出` 三行及以上，则改为按“上一承压/普通行 -> 当前行”拆成逐行成员；表3列38、总损失、累计损失和水位都按这些逐段结果递推，出口行只保留最后一段结果。
- 所有 `xx管`（`总干管 / 分干管 / 干管 / 支管 / 分支管`）连续承压链中的命名 `有压管道 / 定向钻 / 顶管`，只要已经真正进入连续承压链，也允许拆成逐行成员；父命名组继续保留窗口汇总，但不再参与表3正式累计。
- 同一条连续承压链里若出现重名成员，展示名按出现顺序追加后缀：`前缀段 / 起点锚点 / 前段 / 中段N / 后段`；只改展示，不改稳定身份键。
- 连续承压正式对象统一拆成四类：`PressureRoute`（整线）、`PressureSegment`（子段）、`PressureResult`（正式结果）、`ProfileCoverageState`（纵断面覆盖状态）。链识别、结果保存、导出与提示都围绕这四类对象运行，不再由不同模块临时拼名字或猜身份。
- 名称口径正式拆分：`base_name` 只负责业务归属，`member_display_name` 负责软件内展示，`route_display_name` 负责整线卡与提示，`dxf_display_name` 只负责 DXF 建筑物名称行。DXF 不再拼“名称 + 结构类型”，像赛金支渠这类结果会稳定显示为 `苟家湾 / 大石包 / 苟家湾`。
- 末尾双表判断正式抽成独立规划阶段 `TailPressureSplitPlan`：统一输入整张表 `full_nodes`，统一输出 `channel_nodes / channel_valid_nodes / tail_route / tail_segments / tail_lookup_nodes / tail_export_mode`；单独 DXF、单独 TXT、合并 DXF 三个入口必须共用它，不能再各自裁节点后再判断。

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
- 对 `xx管` 整线与连续承压整线重开场景，`routes[route_key].longitudinal_nodes / profile_segments` 也是纵断面状态的事实来源；只要 route 级缓存仍在，就应优先从这里恢复
- `routes[route_key]` 现还会正式保存 `profile_state / entered_pressurized_at_row / segment_identities`
- `segments[identity]` 作为连续承压正式存储桶，保存 `base_name / member_display_name / dxf_display_name / member_role / start_mc / end_mc / status / friction_loss / bend_loss / local_loss / total_loss / computed_from_profile_source`
- 旧 `pipes` 保留兼容镜像；新导出、新提示、新回读优先使用 `routes / segments`
- `PressurePipeConfigDialog` 重开时，恢复顺序固定为：先按 `route_key` 读取 `routes`，只有 route 级拿不到时才回退 `segments / pipes`
- 末尾命名承压尾段若已拆成逐行成员，则 `segments` 保存逐段正式结果；整组总损失只保留在窗口汇总和兼容镜像里，不再要求表3出口行同时保留整组值
- 普通有压子段若只剩 1 个纵断面点，只视为边界占位；导出时应回退整线 `routes[route_key].longitudinal_nodes`，隧洞生成段除外
- 整线卡里导入或清空纵断面 DXF 后，需要立即同步到 `routes[route_key].longitudinal_nodes`，不能等到“开始计算”后才落盘
- 现有结果清理策略 `remove_pipe` 不修改：计算完成后若它清掉 `pipe / segment` 入口，route 级纵断面缓存仍视为可恢复草稿，不能一起当成“未导入”

### 3.7 结果辅助函数（pressure_pipe_result_helpers.py）

| 函数 | 说明 |
|------|------|
| `make_pressure_pipe_identity(flow_section, name)` | 构造稳定身份键 `"流量段::名称"` |
| `empty_pressure_pipe_calc_records()` | 空记录结构 |
| `normalize_pressure_pipe_calc_records(raw)` | 规范化/兼容旧数据 |
| `format_pressure_pipe_record_detail(record)` | 单条记录 → 文本 |
| `format_pressure_pipe_calc_batch_text(batch)` | 批次记录 → 章节文本 |
| `append_pressure_pipe_calc_batch_text(existing_text, batch)` | 追加到详细过程 |

**连续承压链汇总补充字段**：

| 字段 | 说明 |
|------|------|
| `chain_complete` | 整条连续承压链是否完整成功 |
| `chain_status` | `complete / incomplete` |
| `member_results[].writeback_enabled` | `False` 表示纯锚点或失败成员不回表；前缀段成功时为 `True` |

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

- 用户在结果汇总窗点击“关闭并将总水头损失返回至水面线计算表格”后，只要当前表3节点仍有效、渐变段拓扑仍在，就必须允许再次直接打开“有压管道水力计算”；不能再要求先清空表3、回表1重算、重新插入渐变段。
- 用户再次打开“有压管道水力计算”时，若此前已导入过纵断面 DXF，则应直接回填已持久化的 route 级纵断面状态；不能因为窗口关闭重开就要求重复导入同一份纵断面 DXF。
- 打开前的门禁以当前表3现场为准：若 `_section_sync_ready` / `_transition_topology_prepared` 只是旧状态残留，但当前表3节点与渐变段拓扑仍满足要求，应先在内存里自修复后再继续打开；只有表3真的为空或渐变段拓扑真的不存在时，才继续拦截。
- 结果汇总窗按“关闭即销毁”处理：面板只保留当前活动汇总窗引用，窗口销毁后同步清空引用，避免隐藏旧窗残留导致再次点击无反应。

#### 3.8.2.1 状态回收与恢复规则

- 本轮根因口径固定为：计算完成后关闭返回，会按现有结果清理流程清掉 `pipe / segment` 入口，但 `route` 级 `longitudinal_nodes` 仍保留。
- `PressurePipeConfigDialog` 重开时，先按 `route_key` 恢复 `routes[route_key].longitudinal_nodes / profile_segments`；只有 route 级缓存不存在时，才回退 `pipe / segment` 兼容入口。
- 只要 route 级缓存还在，用户重开“有压管道水力计算”就不需要重新导入 DXF；界面应直接恢复已导入的预览、统计和覆盖状态。
- 若已导入结果覆盖不完整，系统继续保留现有 route 级缓存，并明确提示“继续补导入”；不把当前状态回退成“未导入”。
- 本轮不修改现有 `remove_pipe` 清理策略；文档只补充“route 级缓存优先恢复”的规则，不新增新的结果删除动作。

#### 3.8.3 有压管道计算流程

`_open_pressure_pipe_calculator()` 执行：
1. 从节点表提取有压管道分组和连续承压链
2. `xx渠` 只有在末端或跨流量段形成连续承压线时，才进入“整线卡 + 分段计算”入口；非连续场景继续按当前有压管道分组逐组弹窗
3. `xx管` 流量段继续进入“整线卡 + 隧洞只读摘要”入口；需要导入几次 DXF 按“有压连续段数”决定，但每张整线卡仍只要求覆盖自己的非隧洞区间
4. 一旦进入连续承压整线模式，底层按整线管理 DXF、route context 和 mixed route 几何；但压力管道特性表、统计摘要和结果回写继续按原有分段和流量段表达
5. 若流量段起点就是隧洞，DXF 第一点评到第一段非隧洞子段起点里程，而不是整线起点
6. 普通有压段继续使用 DXF 裁切后的纵断面；隧洞参数统一只认表1手填或 Excel 导入的现有值，弹窗只做只读摘要和缺项提示，不再新增弹窗录入口；圆拱直墙型只认 `B`，不再使用 `H`
7. 对每个管道或链成员执行水头损失计算（`calc_total_head_loss()` 或 `calc_total_head_loss_with_spatial()`）；隧洞成员继续复用既有隧洞计算口径参与承压链累计
8. 结果回写到节点表的 `head_loss_siphon` 列；隧洞行仍按自身既有规则回写，避免 route 结果重复覆盖；赛金支渠这类起点前缀段则写回下一段特殊承压建筑的进口行
9. mixed route 的拼接结果持久化到 `PressurePipeManager.routes[route_key].profile_segments`
10. 更新详细过程文本区
11. 整线卡导入/清空纵断面 DXF 后，先立即同步到 `PressurePipeManager`，保证主页面导出与弹窗预览读取同一份数据
12. `PressurePipeConfigDialog` 重开时先按 `route_key` 恢复 route 级 `longitudinal_nodes / profile_segments`；只有 route 级拿不到时，才回退 `segments / pipes`
13. 只要 route 级缓存仍在，用户再次打开窗口时不需要重新导入 DXF；界面直接恢复已导入的纵断面草稿
14. 整线卡的“部分导入”也属于可保留草稿：覆盖不完整时继续保留已导入节点、预览和统计，只提示“继续补导入”，不自动清空旧结果；但在用户点击“开始计算/确定”时仍按原规则拦截
15. 结果保存不得用空载荷覆盖已有纵断面缓存：若本轮没有新的 route 纵断面或 `profile_segments` 几何，只更新损失结果，不改已导入的纵断面草稿
16. 现有 `remove_pipe` 结果清理策略保持不变；即使关闭返回后清掉 `pipe / segment` 入口，也不能据此判定 route 级纵断面已失效

**连续承压链汇总补充规则**：
- 链首若能形成前缀段，就只计沿程损失，不补渐变损失和额外接头局部损失，并把结果写回下一段特殊承压建筑的进口行。
- 只有拿不到有效前缀长度时，链首成员才按纯锚点记成功；纯锚点不回写本行，也不参与整线总损失求和。
- 连续承压链只要还有真实子段失败，就把整线状态标成 `未完成`，并隐藏整线总损失数字；成功子段仍保留各自结果与回写。
- 普通有压与 `定向钻 / 顶管 / 隧洞` 的相邻边界默认视为同一条连续承压链内部衔接，不额外新增一笔接头局部损失。
- “执行计算”前只检查当前真正需要写回的承压成员；纯锚点不再触发“尚未执行有压管道水力计算”的黄色误提示。
- 若当前表3根本没有真实 `有压管道 / 定向钻 / 顶管` 分组，即使连续承压链里还残留 `隧洞` 成员描述，“执行计算”也不得再单独弹出“请先做有压管道水力计算”的提示；这一步的门禁口径必须与“有压管道水力计算”按钮入口完全一致。
- 已按 `chain_row_member / chain_tunnel_member / chain_prefix_member` 这类实际回写模式写回成功的链内成员，在“执行计算”前也必须按同一口径认定为已完成；不能再退回旧的“出口行有无 `head_loss_siphon`”规则误拦。
- 有压结果进入静默重算后，`pressure_pipe_window_override` 里的 `group_mode / identity / storage_key / display_name / data_mode / target_row_index / upstream_row_index / applied_at / calc_steps` 等元数据必须原样保留，不能在水力计算阶段退化成只剩损失值的简化结构；否则后续表格重建会把已回写成员误认成未完成。
- `pressure_pipe_window_override` 驱动的逐行承压成员，其 col 38 展示值、总损失、累计总损失和水位递推必须统一以这份 override 为正式来源重建；split 父组 summary-only 结果与命名隐藏整组结果只保留窗口汇总用途，不再重复参与正式累计。
- `_apply_pressure_pipe_results(...)` 必须按“本轮先清旧、再写新”执行：凡是本轮记录覆盖到的 `identity / storage_key`，都要先清掉旧 `pressure_pipe_window_override`、旧命名组隐藏结果、旧 `_pressure_pipe_display_loss`、旧 `_pressure_pipe_calc_done` 和 manager 持久化结果，再写回本轮成功项。
- 若本轮是“部分成功”，失败项必须保持未成功状态，不能继续沿用上一轮成功值；提示文案仍可保留“部分成功”，但表3和持久层只能反映本轮真正成功的记录。
- “导出全部DXF”在 `xx管` 或 `支渠` 连续承压 5 项模式下，纵断面部分必须先裁成当前承压 route 节点后，再进入 `xx管` 结构校验与绘制；断面汇总和 IP 表仍按当前表3快照输出，不能把整张表的明渠节点直接带进 `xx管` 纵断面校验。
- 这次 route 节点裁切真正落在 `cad_tools.py` 的共享 resolver 上：先取当前表3快照；纯 `xx管` 继续返回整张承压表；`支渠 / xx渠` 连续承压 route 模式则只返回 `route_import_targets` 里的真实 route 节点，并过滤 `transition / auto_inserted` 辅助行。单独 TXT、单独 DXF、合并 DXF 三个入口必须共用这套取数口径。
- 若连续承压导出进入“上方渠道表 + 下方末尾承压表”的上下双表布局，上方渠道表的宽度与全宽水平线终点必须按最后一个可见导出节点计算；尾部隐藏的 `transition / auto_inserted` 辅助行只允许参与分表边界识别，不能再把水平线压成零长度。

**表1同步到表3补充规则**：
- 表1断面结果导入表3时，承压类行会主动补齐 `pressure_pipe_row_identity` 元数据，不再只透传 `use_increase / pipe_material / in_out_raw / local_loss_ratio`。
- 后续导出和结果回写优先按这类真实行身份命中；只有旧工程缺少这类身份时，才回退到连续段 identity 或旧的 `flow_section::name`。
- `xx管` 夹带隧洞参数统一以表1/Excel 为真源；弹窗不新增一套独立录入字段，只读取当前行已有的 `断面类型 / 断面尺寸 / 坡降 i / 糙率 n` 做摘要展示和缺项提示。
- 如果同一条 `xx管` 夹带隧洞同时存在表1当前值和 manager 缓存，重新计算时必须始终优先用表1当前值；manager 只能在当前 group 缺值时兜底，弹窗 `tunnel payload` 不再回写主表。
- 圆拱直墙型隧洞在这条链路里只认 `B`，不再使用 `H`。

**纵断面 DXF 自动选线补充规则**：
- 导入时不再盲取 DXF 里的首条多段线，而是先对全部多段线做候选排序。
- 候选排序优先级固定为：图层名命中 `JQX / 纵剖 / 纵断 / 纵剖面` → 更像局部坐标而非工程大坐标 → `xspan` 更大 → 路径总长更长 → 顶点数更多。
- 只有“非闭合、横向展开明显、`x` 向跨度足够大”的多段线才进入主比较池；若没有合格候选，再回退到全量候选里取最像的一条。
- `get_longitudinal_profile_start_x()` 与 `parse_longitudinal_profile()` 必须共用同一套选线逻辑，避免“算偏移时取一条线、解析节点时又取另一条线”。
- 当头两名候选非常接近时，界面层会在正式导入前弹一次确认，提醒用户按推荐候选继续或取消导入。
- 导入按钮下方固定显示“导入前说明”，统一提示用户准备合格的纵断面管道中心线 DXF：建议只保留 1 根中心线多段线、按 `1:1` 绘制、`Y` 为真实高程（米）、多候选时系统会二次确认，并建议放在“纵断 / 纵剖”等清晰图层。

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
| 有压同类相邻 | 若相邻两边都属于 `有压管道 / 定向钻 / 顶管`，则直接视为同类承压结构内部衔接，不插渐变段，也不插连接段；不再区分名称和管径 |
| 与闸穿透 | 有压管道出口→闸 / 闸→有压管道进口 均插入渐变段（skip_loss=True） |
| 占位渐变段 | 有压管道侧的渐变段标记 `transition_skip_loss=True`（水损已含在有压管道计算中） |

---

## 五、CAD 导出规则

- 断面汇总表中，有压管道单独输出为"有压管道断面尺寸及水力要素表"，列结构与倒虹吸一致
- "导出全部DXF"调用统一参数对话框；其中有压管道参数按“流量段主行 + 顶管/定向钻单独行”显示，普通有压管道同一流量段只显示 1 行
- 有压管道参数弹窗只负责录入展示，确认后仍需把“流量段主行”重新展开回该流量段下全部普通有压管道原始分组；顶管/定向钻仅回写到各自对应分组
- 压力管道特性表里的`长度`和`设计流速`必须按流量段逐行输出；其中主长度只服务于有压管道本体，必须优先取该流量段内有压管道起点和终点的 IP 点桩号差，也就是优先使用有压管道子段的 `segment_start_mc / segment_end_mc` 取最小起点与最大终点后相减，不得再按整个流量段的渠道节点连续桩号重新累计。普通有压管道段也必须参与统计，但不能退化成隧洞/定向钻/顶管等建筑物长度小计，也不能因为“普通段接命名建筑物”或“跨流量段边界”漏算或串段。同一流量段最终只保留 1 行摘要，但匿名普通有压管道也必须沿用行级 `identity`、`Q`、`plan_total_length` 和子段起止桩号参加汇总，不能只靠“流量段 + 名称”回填；缺少 `segment_start_mc / segment_end_mc` 的旧工程，才允许回退到旧的节点扫描口径，保证历史工程仍可导出
- `支管` 这类严格 `xx管` 口径下，主长度虽然仍先取当前流量段有压边界的 `segment_start_mc / segment_end_mc`，但若同一条承压整线前面还挂着无压隧洞，则必须把“前置隧洞长度 + 隧洞出口到首段有压入口之间的空档”一并补回；切回 `支管` 后，压力管道特性表总长度必须恢复为整线口径，不能只剩纯有压边界长度
- 压力管道特性表里的`设计流速`只调整展示精度：DXF 和 Excel 都固定保留 2 位小数，底层计算值与缓存值不改，避免影响已有水力计算和回写链路
- 顶管/定向钻在弹窗里可单独设置材质和 DN，但最终压力管道特性表仍只按流量段输出 1 行；顶管/定向钻只进入对应摘要列，不额外生成主行。`隧洞 / 定向钻 / 顶管` 的摘要长度统一按每组“出口里程MC - 进口里程MC”统计，中间 IP 点只用于识别整组，不得把出口后紧邻的普通有压管道并入建筑物长度
- 压力管道特性表里的`渠首水位 / 渠末水位`也必须按流量段逐行输出：优先取该流量段有压管道起点和终点对应节点水位，也就是 `upstream_row_index / target_row_index` 指向的边界水位；只有当相邻流量段的有压边界本身连续时，才允许上一段`渠末水位`与下一段`渠首水位`共用同一个切段点水位。若中间存在断点、缺口或非连续节点，则继续按各段自己的有压起终点水位输出；多流量段场景下不得回退到整条管线的总起点/总终点水位
- `xx渠` 下的隧洞摘要需要再加一道口径过滤：其中 `支渠` 场景只有同一流量段已经进入 `有压管道 / 定向钻 / 顶管` 之后再次出现、且仍处在同一条连续承压链内部的中间隧洞，才计入压力管道特性表；出现在首个有压类结构之前的前置隧洞，以及最后一个有压类结构之后的末尾隧洞，都不进入这张表的隧洞座数和长度
- 压力管道特性表、断面汇总弹窗和 DXF 导出必须共用同一份流量段汇总结果；DXF 主长度优先直接复用 `panel.py` 已算好的 `total_length`，旧分组范围或历史缓存长度只能在拿不到摘要的旧工程里兜底，不能把 `支渠` 已过滤掉的前置/末尾隧洞，或 `支管` 已补回的前缀长度改回旧口径
- 启用整线导入模式的 `xx管 / 连续承压 xx渠`，需要导入几次纵断面 DXF 统一按“有压连续段数”计算：前置无压隧洞、尾置无压隧洞都不单独形成一次导入；只有无压隧洞把前后两段 `有压管道 / 定向钻 / 顶管` 从中间切开时，才新增一次导入
- 因此像“前置隧洞 + 后续一路有压”这类场景只导入 1 次；像“有压 + 中间隧洞 + 有压”这类 mixed route，需要拆成前后两条整线分别导入 2 次。导出时仍按结构拆成上下两张表：上方普通渠道表继续跟随当前 `7/扩展项` 配置并承接隧洞，下方 `xx管` 表只保留 `有压管道 / 定向钻 / 顶管`
- 对单条整线卡本身，仍允许在同一次弹窗里连续补导入多份纵断面 DXF；后导入文件按桩号并入当前整线，不再把前一次结果整份替换掉。每次导入默认对齐当前这条整线里“第一个未覆盖的非隧洞目标”起点，避免补导入再次贴回前半段
- 单条整线卡关闭后再次打开时，已保存的补导入结果和覆盖状态必须按 route 级数据恢复；未覆盖完整时继续提示缺口，但不删除已导入的节点草稿
- 连续承压 mixed route 的纵断面覆盖校验需要前后一致：弹窗导入校验与“导出全部DXF”都只把非隧洞节点当作必须覆盖目标；隧洞节点继续参与绘图和参数生成，但不参与这份 DXF 的强校验
- 当 mixed route 还没补导入完整时，整线卡需要保留当前已导入结果并继续显示详细缺口；此时“开始计算/确定”不再退回“还没导入”，而是直接复用同一套范围不足提示
- `xx渠` 在末端或跨流量段形成连续承压整线时，纵断面导出复用 `xx管` 固定 5 项表头：`建筑物名称 / IP点名称 / 里程桩号 / 管中心线高程 / 管材（管径）`；单独 TXT、单独 DXF、合并 DXF 三个入口口径一致
- 连续承压 `xx渠` 中，普通“有压管道”第 1 行优先显示用户填写名称；名称为空时保持留空；`定向钻 / 顶管 / 隧洞` 继续沿用原有命名拼装口径
- 严格 `xx管` 模式下，普通“有压管道”如果用户已经填写建筑物名称，纵断面表格第 1 行也必须显示这个名称；不能只让中间 `顶管 / 定向钻 / 隧洞` 有名字、把前后普通有压段误留空。名称本身为空时也保持留空，不再回退成“有压管道”
- 连续承压 `xx渠` 缺少纵断面轴线 DXF 或已导入但覆盖不全时，导出不再阻断；第 4 行对应中心高程位置直接留空，并在软件内提示用户回到表3“有压管道水力计算”中导入/补全纵断面轴线 DXF 后重导；严格 `xx管` 继续保留原有阻断规则
- `xx管` / 倒虹吸导入纵断面 DXF 时，若图里的顶点方向是反的（X 从大到小），系统应先自动归正到桩号递增方向，再计算导入偏移；不能因为用户重画轴线方向就把整条桩号区间算成负值，进而误报“未覆盖节点桩号”
- `xx管` 整线在导入纵断面 DXF 或导出全部 DXF 时，若因覆盖不足而失败，提示必须直接告诉用户“需要覆盖到哪一桩号、当前只到哪一桩号、还差多少、程序允许的 1 mm 误差是多少、哪些节点没覆盖、应去 CAD 把纵断面末端延长到哪里后再重导”；导入与导出复用同一套详细提示模板，不再退回“未覆盖节点桩号”或“未覆盖整线全部桩号”这类笼统提示
- 纵断面 DXF 导入时，不允许再默认使用“文件里的第一条多段线”；应先按候选规则自动优选真正的纵断面，避免把工程坐标辅助线、框线或短折线误当纵断面
- 纵断面"坡降"行对有压管道留空（按有压流处理）
- `xx管` 下方专用表的第 4 行和第 5 行现在只对应 `有压管道 / 定向钻 / 顶管`；隧洞不再在这张表里单独展示底线或断面参数
- 隧洞如需复核，继续回表1或 Excel；对外提示只强调“表1/Excel 为唯一真源、弹窗只读摘要”
- 纵断面导出采样优先读取 `routes[route_key].profile_segments`；若命中的普通有压子段只有 1 个纵断面点，则视为边界占位并自动回退整线 `longitudinal_nodes`；只有纯普通有压整线或这类单点子段回退场景才使用旧的 `longitudinal_nodes`，隧洞生成段继续沿用自己的分段结果
- 连续承压整线跨流量段延续时，新流量段首个匿名普通有压行的自身范围可能退化为单点边界；只要该行已挂到整线 `route_key` 且上下游 `flow_section` 发生切换，导出就应直接继承整线 `longitudinal_nodes`，不能再按单点范围裁切
- 连续承压整线导出在同桩号合并节点后，不能只信任最终代表节点的单一 identity；若代表节点命不中整线纵断面，需要继续按节点组里的稳定 identity 候选重试，优先级为 `pressure_pipe_row_identity` → 当前分组 identity / route 起点锚点 identity → 旧的 `flow_section + name` 口径
- route 级整线纵断面导出映射除了主 identity，还要同步补齐起点锚点、单行成员和旧口径 identity；只要整线 DXF 已存在，这些别名 identity 也必须能拿到同一份 route 纵断面
- 赛金支渠这类连续承压 `xx渠` 单点漏配场景中，导出前构造 lookup rows 时还要同时带上 `route_key / route_display_name / station_text / node_label`；若当前行 alias 没命中，但 `routes[route_key].longitudinal_nodes` 可用，则允许按 route 级纵断面兜底，不再把“已导入整线、只漏 1 个点”误判成整线未导入
- 连续承压 `xx渠` 的按结构分表导出现在统一走 `TailPressureSplitPlan`：上方继续是渠道表，下方固定是 5 项有压表；一旦进入真正承压尾段，后续普通有压、定向钻、顶管都归下方有压表，隧洞继续保留在上方渠道表
- 下方有压表中的建筑物名称只按 `dxf_display_name` 居中绘制一次，居中范围按子段真实 `start_mc / end_mc` 计算，不再按单点或临时文本推断
- 连续承压 `xx渠` 的宽松提示必须保留真实原因明细：真正没导入 route 纵断面时，继续提示去表3导入/补全；已导入但只是节点未匹配时，提示“已导入纵断面DXF，但有个别节点未匹配，已留空”；已导入但桩号超出覆盖范围时，提示“已导入纵断面DXF，但有个别桩号超出覆盖范围”。提示中优先展示“桩号 + 行标签/建筑物标签 + 整线名”，不再直接展示 `flow1-row73` 这类内部标识
- IP 点名称中，有压管道同类的进/出口保留各自结构名称（示例：`XX管有压管道进`、`XX管定向钻出`、`XX管顶管进`）
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
| V2.11 | 2026-04-02 | **xx管 夹带隧洞 mixed route 支持**：取消“夹带隧洞暂不支持”拦截；整线 DXF 只覆盖非隧洞子段，并引入 `profile_segments` 作为 mixed route 的统一几何真源。后续参数与导出口径已在 `V2.12 / V2.12.1` 收口。 |
| V2.11.1 | 2026-04-02 | **mixed route 收口修正**：当整线起点先经过隧洞且首个非隧洞节点没有显式桩号时，DXF 导入会按该节点的回退桩号对齐，不再误回到整线起点；当 mixed route 后续改回纯有压整线时，会显式清空 route 级 `profile_segments`，避免历史隧洞纵断面残留影响导出。 |
| V2.11.2 | 2026-04-06 | **连续承压整线口径修正**：保留开始计算时 route 分段组装的 helper 修复；`xx渠` 在末端或跨流量段形成连续承压线时，也可进入整线卡；非连续场景仍只显示当前分组；压力管道特性表继续按原有分段和流量段表达，其中 `xx渠` 的隧洞只在已进入 `有压管道 / 定向钻 / 顶管` 之后才计入摘要。 |
| V2.11.3 | 2026-04-07 | **多流量段水位口径修正**：压力管道特性表中的“渠首水位 / 渠末水位”改为按各流量段自己的首个有效水位和最后一个有效水位输出；没有有效水位时保持空值，不再误用整条管线的总起点/总终点水位。 |
| V2.11.4 | 2026-04-07 | **多流量段主长度口径修正**：压力管道特性表主列长度改为优先使用流量段连续桩号累计值；普通有压管道接命名建筑物前的短段不再漏算，跨流量段边界不再误并入下一段；匿名普通有压段的 `segment_start_mc` 也会避开跨段上游参考点。 |
| V2.11.5 | 2026-04-07 | **跨流量段终点口径补正**：压力管道流量段摘要总长度改为按“当前节点到下一节点”的连续桩号累加；当下一流量段首行就是上一流量段终点时，上一流量段长度会延伸到该起点，不再停在上一段最后一个同段节点。 |
| V2.12 | 2026-04-10 | **xx管 隧洞口径收口**：`xx管` 隧洞参数统一只认表1手填或 Excel 导入的现有值；弹窗改为只读摘要和缺项提示，不再新增弹窗录入；圆拱直墙型只认 `B`，不再使用 `H`；本轮文档口径不承诺旧项目迁移保证。 |
| V2.12.1 | 2026-04-10 | **xx管 夹带隧洞按结构分表**：导出改成按结构拆成上下两张表；上方普通渠道表继续跟随当前 `7/扩展项` 配置并承接隧洞，下方 `xx管` 表只保留 `有压管道 / 定向钻 / 顶管`；隧洞不再在下方 `xx管` 表里单独展示底线或断面参数。 |
| V2.12.5 | 2026-04-11 | **旧项目误锁二次兼容补修**：在上一轮“缺少 `sync_ready` 也能恢复”的基础上，继续兼容一类更隐蔽的旧项目脏状态：项目里其实已经保存了表3节点和断面结果，但 `merged_section.sync_ready` 被历史状态写成了 `false`。现在恢复时会结合表3/计算结果是否已恢复，以及状态文字是否仍属于“未就绪/请重算/已变更”等明确失效口径来判断；若属于“成功项目被旧门禁误锁”，则直接恢复为可继续打开有压管道水力计算窗口，不再要求用户先清空表3再回表1重算。 |
| V2.12.6 | 2026-04-11 | **表3 有压同类插段口径统一**：当相邻两边都属于 `有压管道 / 定向钻 / 顶管` 时，表3 现在统一视为同类承压结构内部衔接，不再插入渐变段或中间连接段，也不再区分名称和管径；该口径已与 `pressure_pipe_extractor` 的“紧邻有压同类结构，无渐变段”说明保持一致。 |
| V2.12.7 | 2026-04-12 | **压力管道特性表支管/支渠长度收口**：`支渠` 只统计被 `有压管道 / 定向钻 / 顶管` 前后夹住的中间隧洞，前置隧洞和末尾隧洞不再进入主长度或隧洞栏；`支管` 主长度继续按整线口径，并在有压边界长度基础上补回前置无压隧洞及其到首段有压结构之间的空档；DXF 主长度改为优先复用 `panel.py` 的流量段汇总结果，旧缓存只做兜底。 |
| V2.12.8 | 2026-04-13 | **示例二有压门禁口径统一**：表3“执行计算”前的有压校验现在先与“有压管道水力计算”按钮入口对齐；如果当前表里没有真实 `有压管道 / 定向钻 / 顶管` 分组，即使连续承压链里还残留 `隧洞` 成员描述，也不再误弹“请先点击【有压管道水力计算】”提示。 |
| V2.12.9 | 2026-04-13 | **同名隧洞跨闸重名放行**：表1“建筑物重名”校验新增隧洞跨闸口径；同名隧洞若只被 `分水闸 / 分水口 / 节制闸 / 泄水闸 / 退水闸` 这类闸点打断，前后仍按同一条隧洞处理，不再误报重名；该规则适用于所有渠道级别，非隧洞建筑仍保持原有重名拦截。 |
| V2.12.10 | 2026-04-13 | **连续承压链失败归属收口**：`named_row_segment` 底层校验固定使用基础名称，链成员展示后缀不再反向污染校验标签；逐段成员失败返回时，界面层会把失败原因抬头同步为当前成员名称，避免“前缀段失败原因挂到中段”。 |
| V2.12.11 | 2026-04-14 | **有压窗口重开与纵断面草稿保留补修**：表3“有压管道水力计算”结果汇总窗改为关闭即销毁；按钮再次点击前会按当前表3节点和渐变段拓扑自修复旧门禁标记，不再因为历史 `sync_ready/topology` 脏状态误拦。结果回写也改为“先清旧、再写新”，本轮失败项会同步清掉旧 override、隐藏结果、显示缓存和 manager 残留。根因收口为“关闭返回会清掉 `pipe / segment` 入口，但 route 级 `longitudinal_nodes` 仍在”；因此重开 `PressurePipeConfigDialog` 时改为优先按 `route_key` 恢复 route 级纵断面，`pipe / segment` 只做回退来源。连续承压整线的纵断面导入继续保持“完整导入、部分导入都即时持久化”；覆盖不完整时只提示继续补导入，不再自动清空旧缓存。计算保存里新增“`None` 表示保留已有几何缓存”语义，且不修改现有 `remove_pipe` 清理策略。 |
| V2.12.4 | 2026-04-11 | **有压窗口入口恢复兼容补修**：表3“有压管道水力计算”按钮在断面结果失效时继续保持可点击，由入口前置校验统一提示，不再直接表现为“点了没反应”；同时，项目恢复时若 `merged_section` 已存在但历史数据里缺少 `sync_ready`，只要表3已有节点行，就按旧项目兼容口径恢复为“可继续计算”，避免必须先清空表3再回表1重算才能打开窗口。 |
| V2.12.3 | 2026-04-11 | **表3 黄色提示误报补齐**：在上一轮承压类节点排除基础上，继续把自动插入的补段辅助行一并排除出“缺少结构总高”黄色提示；`main` 源码运行场景下，`name = "-"` 的辅助行不再误报成“渠顶高程未计算”。本轮根因补全为两层：旧提示既没有排除承压类节点，也没有排除自动补段辅助行；真正缺少 `H_total` 的普通渠道/隧洞仍继续提示，不新增承压行 `top_elevation` 自动补算。 |
| V2.12.2 | 2026-04-11 | **表3 黄色提示误报收口**：表3计算完成后，“缺少结构总高”黄色提示统一复用现有承压类节点识别口径；`xx管`/连续承压场景下的 `有压管道 / 定向钻 / 顶管` 边界行不再误报。根因是旧提示只按 `bottom_elevation` 有值且 `top_elevation` 为空判断，没有排除承压类节点；本轮只收口提示口径，真正缺少 `H_total` 的普通渠道/隧洞仍继续提示，不新增承压行 `top_elevation` 自动补算。 |
| V2.11.5 | 2026-04-07 | **连续承压 xx渠 导出放宽**：连续承压整线的 `xx渠` 纵断面现在复用 `xx管` 固定 5 项表头；普通有压段第 1 行优先显示用户名称；当纵断面轴线 DXF 缺失或覆盖不全时，TXT / DXF / 合并 DXF 继续允许导出，第 4 行中心高程留空，并统一弹出“回表3导入/补全纵断面轴线 DXF 后重导”的提示。 |
| V2.11.6 | 2026-04-07 | **流量段边界水位统一**：压力管道流量段摘要在识别到连续承压线跨流量段切换时，会把后一流量段首个边界点水位同时写成前一流量段的渠末水位和后一流量段的渠首水位；非连续场景仍保持各段各自的首末有效水位。 |
| V2.11.7 | 2026-04-07 | **整线纵断面导入即时保存**：有压管道弹窗里整线卡导入或清空纵断面 DXF 后，会立刻同步到 `PressurePipeManager.routes[route_key].longitudinal_nodes`；这样弹窗预览和主页面导出读取同一份数据，不再出现“图2已导入、图1仍提示没导入”。 |
| V2.11.8 | 2026-04-07 | **双桥支管 identity 误判修复**：连续承压整线导出时，同桩号合并后的代表节点若命不中整线纵断面，会继续按节点组 identity 候选回退匹配；route 级导出映射也补齐起点锚点、单行成员和旧口径 identity，并把“真没导入”和“identity 没匹配上”拆成两类提示。 |
| V2.11.9 | 2026-04-07 | **双桥支管跨流量段边界行修复**：连续承压整线跨流量段延续时，新流量段首个匿名普通行即使只对应单点桩号，也会在导出阶段直接继承整线 `routes.longitudinal_nodes`，不再因为单点裁切把已导入的整线 DXF 误判成“未导入”。 |
| V2.11.10 | 2026-04-07 | **三清支渠纵断面与链路修复**：纵断面 DXF 导入改为按候选规则自动优选，不再盲取首条多段线；当头两名候选非常接近时，导入前会先弹确认。`支渠` 连续承压链与 route 上下文改为从首个真正有压段开始，前置隧洞不再误入整线卡、导入锚点和 route 起点。 |
| V2.11.11 | 2026-04-08 | **末尾分表与坡降文字口径补充**：末尾上下分表里的下方有压表只新增“从尾段首个真正有压节点开始”的横向显示起点，桩号文字不改，中心线高程仍复用整线纵断面与 route 级回退链；普通纵断面的坡降文字恢复按真实边界居中，不再简单按 `start/end` 平均。 |
| V2.11.12 | 2026-04-08 | **普通有压组导入对齐与特殊建筑坡降补修**：普通命名有压组的 `ip_points` 现在也保留 `station_mc`，导入纵断面 DXF 时优先按项目桩号对齐，不再误退回原始 `x`；导入后若识别到结果仍停留在原始工程坐标空间，会直接拦下并提示重导。隧洞、倒虹吸和有压占位的坡降行则统一改为与建筑物名称行共用真实单元格边界，包含 `-` 占位在内都按同一中心位置显示。 |
| V2.11.14 | 2026-04-08 | **压力管道边界口径修正**：压力管道特性表主长度改为优先取有压管道起终 IP 点桩号差，`渠首水位 / 渠末水位`改为优先取有压管道起点和终点水位；DXF、Excel 与断面汇总弹窗共用同一套边界摘要，旧工程缺少边界元数据时继续回退旧口径。 |
| V2.11.13 | 2026-04-08 | **主窗口无反应热修**：确认“终端一直挂着但窗口不出现”的根因不是 `main.py` 本身，而是有压管道页在启动阶段就同步渲染右侧 Web 帮助页。现已改为首次真正进入该页面时再渲染，主窗口会先正常显示；同时补了回归测试，防止这段同步预渲染再次被带回启动链路。 |
| V2.11.15 | 2026-04-08 | **xx渠 连续承压同名段放开**：批量入口把重名拆成 `hard_duplicates / allowed_chain_duplicates` 两桶，只放开 `支渠` 连续承压链里的同名普通有压管道；命名有压段改为按连续出现的同名段分组，连续段 `identity / storage_key` 优先使用行段键，旧 `flow_section::name` 仅保留兼容别名；表1导入表3时承压类行会主动补齐 `pressure_pipe_row_identity`，后续导出和回写优先按真实身份匹配。 |
| V2.11.16 | 2026-04-08 | **赛金支渠连续承压链计损与展示收口**：`支渠` 链首单点命名普通有压在后续仍有同名普通有压段时，会优先识别为起点前缀段；同链重名成员统一追加“前缀段 / 起点锚点 / 前段 / 中段 / 后段”后缀；整条连续承压链只要有真实子段失败，就改标“未完成”并隐藏整线总损失数字。 |
| V2.11.17 | 2026-04-08 | **赛金支渠前缀段写回口径修正**：`苟家湾起点 -> 大石包定向钻进口` 这类真实前缀距离改按沿程损失计入，并写回下一段特殊承压建筑的进口行，而不是写回起点行；“执行计算”前的检查也改成只看真实应写回成员，纯锚点不再误报“尚未执行有压管道水力计算”。 |
| V2.11.18 | 2026-04-08 | **执行前误提示补修**：连续承压链里的命名 `隧洞 / 定向钻 / 顶管` 成员如果已经按 `row override` 模式成功写回，`执行计算` 前检查会直接认定为已完成，不再退回旧的出口行口径误弹黄色提示。 |
| V2.11.19 | 2026-04-08 | **静默重算元数据保真补修**：源码运行场景下，有压结果写回后如果立刻触发静默重算，`pressure_pipe_window_override` 的 `group_mode / storage_key / display_name / target_row_index` 等元数据也会一起保留，不再被水力计算阶段洗成简化结构；这样表格重建后，“执行计算”不会再把已完成的前缀段、隧洞段或命名链成员误判成未完成。 |
| V2.11.20 | 2026-04-08 | **连续承压导出共享 resolver 补修**：`支渠` 连续承压场景下，`导出全部DXF`、单独纵断面 DXF、单独 TXT 现在共用同一套 route 节点取数；纵断面部分会先裁成承压 route 节点，再进入 `xx管` 的 5 项导出口径；不再把整张表里的明渠节点带进 `xx管模式仅允许有压管道/定向钻/顶管/隧洞` 的冲突校验。 |
| V2.11.21 | 2026-04-08 | **旧纵断面缓存兼容清理**：有压管道弹窗载入命名整线时，会先按当前导出桩号校验已保存纵断面；若发现历史缓存覆盖不全，会直接标记为“需要重新导入”并同步清空整线与子段旧副本，避免第一次打开就误把旧缓存当成有效 DXF。`导出全部DXF` 的非阻断提示也改为明确提醒“先清空后重新导入同一份纵断面 DXF”。 |
| V2.11.22 | 2026-04-09 | **赛金支渠单点漏配与提示改准**：连续承压 `xx渠` 导出前的 lookup rows 现在会补齐 `route_key / route_display_name / station_text / node_label` 等 route 上下文；当单行 alias 没命中但整线 `routes[route_key].longitudinal_nodes` 已导入时，会直接按 route 级纵断面兜底，补齐像 `赛支3+968.95` 这类单点中心高程。宽松提示同时改为区分“未导入整线”“已导入但节点未匹配”“已导入但覆盖范围不足”，不再把单点漏配误说成整线未导入。 |
| V2.11.23 | 2026-04-09 | **赛金支渠连续承压整线重构**：连续承压正式模型统一为 `PressureRoute / PressureSegment / PressureResult / ProfileCoverageState`；`PressurePipeManager` 新增 `segments` 正式存储桶；DXF 建筑物名称与软件展示名正式拆开；末尾双表判断抽成 `TailPressureSplitPlan` 并在单独 DXF、TXT、合并 DXF 三个入口共用。赛金支渠这类“前明渠、后连续承压”场景下，上方渠道表不再空白，下方有压表固定 5 项表头，建筑物名称稳定按 `苟家湾 / 大石包 / 苟家湾` 居中输出。 |
| V2.11.24 | 2026-04-10 | **连续承压混合整线覆盖口径统一**：`有压管道 + 隧洞 + 有压管道` 这类 mixed route 的纵断面覆盖校验，现统一为“导入/导出都只强校验非隧洞节点”；导出全部 DXF 若仍覆盖不足，会直接复用导入侧的详细缺口提示，明确显示整线名、需要覆盖到的桩号、当前终点、缺口值和未覆盖节点预览。 |
| V2.11.25 | 2026-04-10 | **支管 mixed route 严格导出补修**：`支管` 这类严格 xx管 模式下，只要整线属于“有压 + 隧洞 + 有压”的 mixed route，导出全部 DXF 也改为只强校验非隧洞节点；真实覆盖缺口仍继续阻断并显示详细缺口提示，但不会再因为隧洞节点被误翻译成“当前导出节点没有匹配到对应整线”。 |
| V2.11.26 | 2026-04-10 | **蒲家湾支管补导入锚点修复**：mixed route 整线卡现支持在同一次弹窗内连续补导入多份 DXF；第一份仍对齐首个非隧洞段，后续文件会自动对齐到当前第一个未覆盖非隧洞段起点并按桩号合并。未补完整前会继续保留已导入结果并显示详细缺口，不再退回“还没导入”或旧的粗粒度导出失败提示。 |
| V2.11.27 | 2026-04-10 | **罗家湾与蒲支导出口径收口**：导出 lookup rows 继续透传 `station_mc / route_key / route_display_name / node_label / is_tunnel`；导出取数改为“先用子段，子段不足或不覆盖当前行桩号就退回整线 route”；导入侧仍只校验非隧洞覆盖。隧洞行退出 `identity_mismatch / coverage` 强校验，同名隧洞不再重复报缺口，但已有可用隧洞 profile 时仍照常参与高程取数。 |
| V2.11.28 | 2026-04-11 | **整线导入次数统一到有压连续段**：`route_key` 切分、弹窗整线卡、缺失提示、覆盖校验和 route 持久化统一改为按“有压连续段数”计算。前置/尾置无压隧洞不再单独占一次导入；只有中间无压隧洞把前后两段 `有压管道 / 定向钻 / 顶管` 切开时，才新增新的整线导入目标。 |
| V2.11.29 | 2026-04-11 | **xx管 普通有压段建筑物名称补显**：严格 xx管 导出时，普通“有压管道”若已填写建筑物名称，纵断面表格第 1 行也改为显示该名称；名称为空时保持留空，不再回退成“有压管道”，也不再出现“中间顶管有名字、前后普通有压段全空”的情况。 |
| V2.12.7 | 2026-04-12 | **连续承压 xx管 逐行正式计损放开**：所有 `xx管`（`总干管 / 分干管 / 干管 / 支管 / 分支管`）连续承压链里的命名 `有压管道 / 定向钻 / 顶管` 现支持逐行正式计损；`pressure_pipe_window_override` 同步成为 col 38、总损失、累计总损失和水位递推的统一正式来源。 |
| V2.12.8 | 2026-04-14 | **赛金支渠前缀段 identity 冲突修复**：`支渠` 连续承压链在把链首命名普通有压改记为“前缀段”时，成员 identity 现优先继承原始行上的 `pressure_pipe_row_identity`，不再按插入渐变段后的当前位置重建 `flow-row`。这样 `苟家湾（前缀段）` 不会再与 `苟家湾（中段8）` 这类正式子成员撞到同一个 identity，真实样表复跑已恢复为整链 33 条全部成功。 |
| V2.11.28 | 2026-04-10 | **蒲家湾表2纵剖线2边界漏配修复**：mixed route 第二份 DXF 的起点边界改按当前节点桩号判断覆盖，`蒲支1+950.37` 不再漏“管中心线高程（米）”；末尾/下方 `xxpipe` 表的首尾整高竖线改按真实可见表格边界判断，`蒲支1+981.79` 不再贯穿到建筑物名称上边线。根因同步收口为 mixed route 第二份 DXF 边界与下方 `xxpipe` 表整高边界口径统一。 |
