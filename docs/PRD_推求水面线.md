# PRD：推求水面线模块

> 版本：v1.1 | 创建：2026-02-26 | 最后更新：2026-02-26 | 状态：已实现

---

## 一、模块概述

### 1.1 定位

推求水面线模块用于计算渠道沿线各节点的水面高程，是渠系工程水力设计的核心环节。输入渠道中心线平面坐标、各建筑物断面参数和起始水位，输出沿程水位、渠底/渠顶高程、各类水头损失及桩号等完整水力成果。

### 1.2 核心能力

- 平面几何计算（转角、切线长、弧长、桩号体系）
- 多建筑物类型的沿程/局部/弯道/渐变段水头损失计算
- 倒虹吸水头损失外部导入（联动倒虹吸水力计算模块）
- 渐变段与明渠段自动识别与插入
- 多流量段支持（设计流量/加大流量列表）
- 成果导出：Excel、Word、DXF（纵断面表格/断面汇总/IP坐标表/全部合并）

---

## 二、文件结构

```
推求水面线/                         # 计算内核包
├── config/
│   ├── constants.py               # 全局常量、列定义、渐变段系数表
│   └── default_data.py            # 默认初始数据
├── core/
│   ├── calculator.py              # WaterProfileCalculator 主计算器
│   ├── geometry_calc.py           # GeometryCalculator 几何计算
│   └── hydraulic_calc.py          # HydraulicCalculator 水力计算
├── models/
│   ├── data_models.py             # ChannelNode, ProjectSettings, OpenChannelParams
│   └── enums.py                   # StructureType, InOutType
├── managers/
│   └── siphon_manager.py          # 倒虹吸数据持久化管理
├── shared/
│   └── shared_data_manager.py     # 跨模块断面参数共享（SharedDataManager）
└── utils/
    ├── siphon_extractor.py        # 倒虹吸节点提取与平面线形解析
    └── excel_io.py                # Excel 导入导出工具

渠系断面设计/water_profile/         # UI 层
├── panel.py                       # WaterProfilePanel 主面板（~4000行）
├── cad_tools.py                   # CAD 导出工具（纵断面/汇总/IP表/bzzh2/平面图）
├── formula_dialog.py              # 公式说明弹窗（表头 Tooltip + 双击详情）
├── water_profile_dialogs.py       # 渐变段/明渠段确认对话框
└── __init__.py
```

### 2.1 依赖关系

```
WaterProfilePanel
  ├── WaterProfileCalculator (calculator.py)
  │     ├── GeometryCalculator (geometry_calc.py)
  │     └── HydraulicCalculator (hydraulic_calc.py)
  ├── SharedDataManager (shared_data_manager.py)     ← 从批量计算读取
  ├── MultiSiphonDialog (siphon/multi_siphon_dialog.py) ← 倒虹吸计算
  └── SiphonDataExtractor (utils/siphon_extractor.py)
```

### 2.2 第三方依赖

| 库 | 用途 |
|----|------|
| PySide6 | UI 框架 |
| qfluentwidgets | Fluent Design 组件 |
| openpyxl | Excel 导入/导出 |
| python-docx | Word 导出 |
| ezdxf | DXF 导出 |

---

## 三、数据模型

### 3.1 ChannelNode（节点）

每行数据对应一个节点，字段分六组：

| 分组 | 关键字段 |
|------|---------|
| 基础输入 | `flow_section`, `name`, `structure_type`, `x`, `y`, `turn_radius` |
| 自动计算 | `in_out`（进/出/普通）, `ip_number` |
| 水力输入 | `flow`, `roughness`, `section_params`（底宽b/水深h/边坡m/直径D/半径R等） |
| 几何结果 | `azimuth`, `turn_angle`, `tangent_length`, `arc_length`, `station_ip/BC/MC/EC` |
| 水力结果 | `water_depth`, `water_level`, `bottom_elevation`, `top_elevation`, `velocity` |
| 水头损失 | `head_loss_friction`, `head_loss_bend`, `head_loss_local`, `head_loss_siphon`, `head_loss_reserve`, `head_loss_gate`, `head_loss_total`, `head_loss_cumulative` |
| 渐变段字段 | `is_transition`, `transition_type`, `transition_form`, `transition_length`, `head_loss_transition`, `transition_calc_details` |
| 特殊标记 | `is_diversion_gate`（闸）, `is_auto_inserted_channel`（自动插入明渠）|

### 3.2 ProjectSettings（项目设置）

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `channel_name` | 渠道名称 | - |
| `channel_level` | 渠道级别 | 支渠 |
| `start_water_level` | 起始断面水位（m） | - |
| `start_station` | 起始桩号（m） | 0 |
| `design_flows` | 多流量段设计流量列表（m³/s） | [] |
| `max_flows` | 多流量段加大流量列表（m³/s） | [] |
| `roughness` | 糙率（明渠/渡槽/隧洞/暗涵） | 0.014 |
| `siphon_roughness` | 倒虹吸糙率 | 0.014 |
| `turn_radius` | 全局转弯半径（m） | 100.0 |
| `siphon_turn_radius_n` | 倒虹吸转弯半径倍数 n（R=n×D，内部常量，不对外暴露 UI） | 3.0 |
| `transition_inlet/outlet_form` | 渡槽/隧洞渐变段形式（表K.1.2） | 曲线形反弯扭曲面 |
| `transition_inlet/outlet_zeta` | 渡槽/隧洞渐变段 ζ | 0.10 / 0.20 |
| `open_channel_transition_form` | 明渠渐变段形式 | 曲线形反弯扭曲面 |
| `open_channel_transition_zeta` | 明渠渐变段 ζ | 0.10 |
| `siphon_transition_inlet/outlet_form` | 倒虹吸渐变段形式（表L.1.2） | 反弯扭曲面 |
| `siphon_transition_inlet/outlet_zeta` | 倒虹吸渐变段 ζ | 0.10 / 0.20 |

> **注**：`siphon_turn_radius_n` 固定为常量 `DEFAULT_SIPHON_TURN_RADIUS_N=3.0`，界面上无对应输入框（2026-02-26 删除冗余 UI，原因见§十二变更日志）。

### 3.3 OpenChannelParams（明渠段参数）

渐变段插入时用于描述相邻明渠断面，字段包含 `structure_type`, `bottom_width`, `water_depth`, `side_slope`, `roughness`, `slope_inv`, `flow`, `flow_section`, `arc_radius`, `theta_deg`。

---

## 四、结构形式支持

| 分类 | 结构类型 | 备注 |
|------|---------|------|
| 明渠 | 明渠-梯形、明渠-矩形、明渠-圆形 | `config/constants.py STRUCTURE_TYPE_OPTIONS` 中的正式选项 |
| 明渠 | 明渠-U形 | **不在 `constants.py` 的下拉列表中**，但可通过双击结构形式列弹出的 `StructureTypeSelector` 选择，计算引擎完全支持；`panel.py` 导入 fallback 和渐变段对话框均列有此类型 |
| 渡槽 | 渡槽-U形、渡槽-矩形 | |
| 隧洞 | 隧洞-圆形、隧洞-圆拱直墙型、隧洞-马蹄形Ⅰ型、隧洞-马蹄形Ⅱ型 | |
| 暗涵 | 矩形暗涵 | |
| 倒虹吸 | 倒虹吸 | |
| 闸 | 分水闸、分水口、节制闸、泄水闸 | |

---

## 五、计算内核

### 5.1 平面几何计算（GeometryCalculator）

输入每个节点的 `(x, y, turn_radius)`，逐节点计算：

| 字段 | 公式 |
|------|------|
| 方位角 | $\alpha = \arctan2(\Delta X, \Delta Y)$（测量方位角） |
| 转角 | $\Delta\alpha$（相邻方位角差，取0~180°） |
| 切线长 | $T = R \times \tan(\alpha/2)$ |
| 弧长 | $L = R \times \alpha$（弧度） |
| BC/MC/EC桩号 | $S_{BC} = S_{IP} - T$，$S_{MC} = S_{BC} + L/2$，$S_{EC} = S_{BC} + L$ |
| 复核弯前/弯后/总长度 | 检查前后 IP 夹直线长度是否合理 |

自动跳过渐变段行（`is_transition=True`）和自动插入明渠行（`is_auto_inserted_channel=True`）。

### 5.2 水力计算（HydraulicCalculator）

#### 5.2.1 结构高度估算

| 结构类型 | 结构高度来源 |
|---------|------------|
| 明渠-圆形 / 隧洞-圆形 | 直径 D |
| 隧洞-马蹄形 | 2 × r（等效直径） |
| 明渠-U形 | `section_params['h_prime']` |
| 其他（梯形/矩形/渡槽/暗涵）| 必须从批量计算导入 |
| 倒虹吸 | 不计算渠顶高程，跳过 |

#### 5.2.2 各结构水深/面积/湿周

对圆形断面采用角度积分精确算法；马蹄形隧洞分标准Ⅰ/Ⅱ型各自的解析公式；其余均用常规解析式。

#### 5.2.3 沿程水头损失

有效计算长度 $L$ 为两节点 MC 桩号差，扣除渐变段长度和两端弧长各半：

$$L_{eff} = \Delta S_{MC} - L_{tr} - \frac{L_{arc,1}}{2} - \frac{L_{arc,2}}{2}$$

**主方法（优先）**：有底坡 $i$ 时直接用：

$$h_f = i \times L_{eff}$$

**备用方法（底坡缺失时）**：曼宁公式，取两端平均水力坡降：

$$J = \frac{n^2 v^2}{R^{4/3}}, \quad h_f = \frac{J_1 + J_2}{2} \times L_{eff}$$

#### 5.2.4 弯道水头损失

$$h_w = \frac{n^2 \cdot L_{arc} \cdot v^2}{R^{4/3}} \times \frac{3}{4}\sqrt{\frac{B}{R_c}}$$

仅当节点 `arc_length > 0` 时计算（有平面转弯）。$R_c$ 优先取节点 `turn_radius`，为0则取全局 `settings.turn_radius`。

#### 5.2.5 局部水头损失

| 结构类型 | 计算方式 |
|---------|---------|
| **倒虹吸** | 直接返回外部导入的总水头损失（`inverted_siphon_losses[name]`），不另行计算弯管/沿程 |
| 闸类（分水闸/节制闸等） | 返回 0（过闸损失在 `head_loss_gate` 中单独计算） |
| 其他 | 查表 `LOCAL_LOSS_COEFFICIENTS`，按进出口标识查进口/出口系数 |

#### 5.2.6 水位递推公式

$$Z_i = Z_{i-1} - h_f - h_j - h_w - h_{tr}$$

$$h_{total,i} = h_f + h_j + h_w + h_{reserve} + h_{gate} + h_{siphon}$$

- $h_{tr}$：上一节点到当前节点之间所有渐变段损失之和（累计）
- 闸类节点：$Z_i = Z_{i-1} - h_{gate}$（仅扣过闸损失）
- 首节点：$Z_0 =$ 用户输入起始水位（不参与递推）

#### 5.2.7 倒虹吸出口渠底高程（公式10.3.6）

$$H_d = H_u + h_u - h_d - \Delta Z$$

- $H_u$：上游渠道末端渠底高程
- $h_u$：上游渠道设计水深
- $h_d$：下游渠道设计水深
- $\Delta Z$：倒虹吸水损 + 渐变段损失

### 5.3 渐变段与明渠段插入算法

详见独立文档 `docs/PRD_渐变段与明渠段插入算法.md`。

---

## 六、UI 面板（WaterProfilePanel）

### 6.1 整体布局

```
┌──────────────────────────────────────────────────────┐
│  基础设置区（可折叠）                                    │
│  渐变段设置区（可折叠）                                   │
│  ─── 节点数据表工具栏 ───                               │
│  节点数据表（FrozenColumnTableWidget，前4列冻结）          │
├──────────────────────────────────────────────────────┤
│  计算结果区工具栏（导出Excel / 导出Word）                  │
│  CAD工具栏                                             │
│  计算结果摘要（持久显示）                                 │
│  详细过程文本框（只读，初始显示操作帮助）                   │
└──────────────────────────────────────────────────────┘
```

### 6.2 基础设置区（可折叠，第1行+第2行网格）

| 控件 | 字段 | 说明 |
|------|------|------|
| 渠道名称 | `channel_name_edit` | 生成桩号前缀（如"南峰寺支渠"→"南支"） |
| 级别 | `channel_level_combo` | 总干渠/干渠/支渠等 |
| 起始水位(m) | `start_wl_edit` | 首节点水位 |
| 渠道糙率 | `roughness_edit` | 明渠/渡槽/隧洞/暗涵 |
| 倒虹吸糙率 | `siphon_roughness_chips` | 倒虹吸管道专用糙率（SiphonRoughnessChipContainer） |
| 设计流量(m³/s) | `design_flow_edit` | 支持逗号分隔的多流量段（如"4.6, 4.5, 4.3"）；`editingFinished` 触发 `_on_design_flow_changed` 自动按加大流量表推算对应加大流量 |
| 加大流量(m³/s) | `max_flow_edit` | 支持多值，留空则自动计算；也可手动覆盖 |
| 起始桩号(m) | `start_station_edit` | 格式：`前缀+公里+米`，如 `0+000.000`；`editingFinished` 触发 `_format_start_station` 自动格式化 |
| 转弯半径(m) | `turn_radius_edit` + "自动"按钮 | 全局转弯半径；自动按钮遍历所有节点，按下表规则计算各结构最小半径，取最大值填入 |

**自动转弯半径规则（`_auto_calc_turn_radius`）**：

| 结构类型 | 控制尺寸 | 公式 |
|---------|---------|------|
| 隧洞（圆形/马蹄形） | 洞径 D=2r | R ≥ D × 5 |
| 隧洞（圆拱直墙/矩形类） | 洞宽 B | R ≥ B × 5 |
| 明渠（梯形/矩形） | 水面宽 B+2mh | R ≥ 水面宽 × 5 |
| 明渠-U形 | 水面宽（弧区/直线段分支计算） | R ≥ 水面宽 × 5 |
| 渡槽 | 连接明渠渠底宽 B | R ≥ B × 5 |
| 矩形暗涵 | 涵宽 B | R ≥ B × 5 |
| 倒虹吸 | — | 跳过（不参与自动计算） |

遍历所有节点后取各结构最小允许半径中的最大值，弹窗展示逐节点推算过程，用户确认后写入 `turn_radius_edit`。

> **已删除**：原"倒虹吸 R=n×D, n="输入框（`siphon_n_edit`）已于 v1.1 删除，改为内部固定常量 `DEFAULT_SIPHON_TURN_RADIUS_N=3.0`（见§十二变更日志）。

### 6.3 渐变段设置区（可折叠，3行网格）

| 行 | 建筑物类型 | 内容 |
|----|-----------|------|
| 第1行 | 渡槽/隧洞 | 进口形式+ζ₁（表K.1.2）、出口形式+ζ₂ |
| 第2行 | 明渠 | 渐变段形式+ζ（明渠不同子类型间的过渡） |
| 第3行 | 倒虹吸 | 进口形式+ζ₁（表L.1.2）、出口形式+ζ₂、"参考系数表"按钮 |

点击"参考系数表"弹出 `TransitionReferenceDialog`，展示 K.1.2（渡槽/隧洞）和 L.1.2（倒虹吸）的系数图表（含示意图缩略图，支持点击放大）。

### 6.4 节点数据表工具栏按钮

| 按钮 | 类型 | 功能 |
|------|------|------|
| **从批量计算导入** | PrimaryPushButton | 从 SharedDataManager 读取批量计算结果，自动填充节点表 |
| **插入渐变段** | PrimaryPushButton | 调用 `_insert_transitions()` 自动插入渐变段/明渠段行 |
| **倒虹吸水力计算** | PrimaryPushButton | 打开 MultiSiphonDialog，计算完毕后回写水头损失和管径 |
| **执行计算** | PrimaryPushButton | 几何 + 水力全链路计算，结果写回节点表 |
| 导入Excel | PushButton | 从 Excel 文件导入节点数据；识别列名（模糊匹配）：流量段、建筑物名称、结构形式、X/E坐标、Y/N坐标、转弯半径、底宽B、直径D、半径R、边坡m、糙率n、底坡1/i、流量Q、水深h、流速v；旧版简写"梯形/矩形/圆形"自动映射为"明渠-×" |
| 添加/插入/删除/复制节点 | PushButton | 节点行操作 |
| 清空 | PushButton | 清空全部节点 |

### 6.5 节点数据表列定义（NODE_ALL_HEADERS，共 44 列）

| 列组 | 列索引 | 列名 | 可编辑 |
|------|--------|------|--------|
| 基础输入 | 0–7 | 流量段、建筑物名称、结构形式、进出口判断、IP、X、Y、转弯半径 | ✓ |
| 几何结果 | 8–19 | 转角、切线长、弧长、弯道长度、IP直线间距、IP点桩号、弯前BC、里程MC、弯末EC、复核弯前/弯后/总长度 | 只读 |
| 水力输入 | 20–26 | 底宽B、直径D、半径R、边坡系数m、糙率n、底坡1/i、流量Q设计 | ✓ |
| 水力结果 | 27–31 | 水深h设计、面积A、湿周X、水力半径R、流速v设计 | 只读 |
| 水头损失 | 32–40 | 渐变段长度L、渐变段水头损失、弯道水头损失、沿程水头损失、预留水头损失(✓)、过闸水头损失(✓)、倒虹吸水头损失(✓)、总水头损失、累计总水头损失 | 部分可编辑 |
| 高程 | 41–43 | 水位、渠底高程、渠顶高程 | 只读 |

- 前4列（流量段、建筑物名称、结构形式、进出口判断）冻结（`FrozenColumnTableWidget`）
- 结构形式列双击弹出 `StructureTypeSelector` 分类选择面板
- 表头悬停弹出 LaTeX 公式 Tooltip（`FormulaTooltipWidget`）
- Ctrl+Z 撤销水头损失手动编辑（最多 20 步）
- **首行锁定**：第一个节点（水位起点）的预留/过闸/倒虹吸水头损失列（col 36/37/38）不可编辑（`FIRST_ROW_LOCKED_LOSS_COLS = {36,37,38}`），因为首节点水位由用户直接输入，不参与递推

### 6.6 双击详情弹窗

| 双击列 | 弹出内容 |
|--------|---------|
| 渐变段长度L | 渐变段长度计算过程（包括各约束条件） |
| 弯道水头损失 | 弯道损失公式逐项展开 |
| 沿程水头损失 | 沿程损失曼宁公式展开 |
| 渐变段水头损失 | 渐变段局部+沿程损失详情 |
| 总水头损失 | 各分项汇总（弯道+渐变段+沿程+局部+预留+过闸+倒虹吸） |
| 累计总水头损失 | 逐行明细列表 |
| 水位 | 水位递推公式展开（含前一节点水位） |
| 渠底高程 | 渠底高程计算（水位−水深）；倒虹吸出口显示公式10.3.6 |
| 渠顶高程 | 渠顶高程=渠底+结构高度 |

### 6.7 结果区

| 控件 | 说明 |
|------|------|
| 计算结果摘要（持久显示） | 显示节点总数、水位范围、总水头损失、流量、糙率等摘要信息 |
| "建筑物长度统计"按钮 | 弹出各建筑物起止桩号和长度汇总表 |
| 详细过程文本框 | 显示每个节点的水力计算过程文字（曼宁公式展开等） |

---

## 七、CAD 导出工具（cad_tools.py）

| 按钮 | 功能 | 输出格式 |
|------|------|---------|
| **生成纵断面表格** | 线框+渠底/渠顶/水面折线+高程文字+桩号+建筑物名称+坡降+IP点名称 | DXF（支持TXT备选） |
| **生成断面汇总表** | 明渠/隧洞/渡槽/暗涵/倒虹吸等各断面尺寸及水力要素汇总 | DXF |
| **IP坐标及弯道参数表** | IP点坐标、桩号、转角、半径、切线长、弧长、底高程 | DXF + Excel |
| **导出全部DXF** | 以上三表合并到同一DXF文件，分图层管理 | DXF |
| **生成bzzh2命令内容** | 提取建筑物进出口数据，生成ZDM用的 bzzh2 命令 | TXT（复制到剪贴板） |
| **建筑物名称上平面图** | 生成 AutoCAD `-TEXT` 命令，将建筑物名称平行轴线放置 | 复制到剪贴板 |

---

## 八、成果导出

### 8.1 导出 Excel

文件名：`{渠道名称}{渠道级别}_水面线计算结果.xlsx`（如 `南峰寺支渠_水面线计算结果.xlsx`）

内容：节点数据表全部 44 列（`NODE_ALL_HEADERS`），第1行=项目信息、第2行=渠道信息、第3行=表头，第4行起=数据。

### 8.2 导出 Word（工程报告格式）

文件名：`{渠道名称}_水面线计算书.docx`

章节结构（`_build_word_report`）：

| 章 | 来源 | 内容 |
|----|------|------|
| 1–4 | `create_engineering_report_doc` 模板自动生成 | 封面/项目信息/计算依据/计算目的（工程产品运行卡格式） |
| 5 | 手动 | 基本计算参数表（渠道名称/级别/起始水位/起始桩号/流量/糙率/渐变段设置） |
| 6 | 手动 | 详细计算过程（从 `detail_text` 读取，LaTeX 公式渲染） |
| 7 | 手动（条件性） | 建筑物长度汇总表（序号/名称/结构形式/长度(m)/起始桩号/终止桩号），仅当有建筑物统计数据时输出 |

依赖：`python-docx`；导出前弹出 `ExportConfirmDialog` 让用户填写项目元信息（项目名称、建设单位等）和选择规范引用。

---

## 九、跨模块集成

### 9.1 从批量计算导入（SharedDataManager）

1. 批量计算完成后调用 `SharedDataManager.register_batch_results()`，将各节点断面参数写入共享管理器
2. 水面线面板点击"从批量计算导入"后调用 `_import_from_batch()`：
   - 自动同步渠道名称、级别、起始水位、流量等基础设置
   - 自动填充节点表的底宽/水深/糙率/底坡/边坡等参数
   - 自动计算推荐转弯半径（按规范取大值原则）
   - 触发几何重算（`_recalculate_geometry_impl`）

### 9.2 倒虹吸水力计算（MultiSiphonDialog）

1. 点击"倒虹吸水力计算"调用 `_open_siphon_calculator()`
2. 通过 `SiphonDataExtractor` 从节点表提取倒虹吸分组
3. 打开 `MultiSiphonDialog`，传入：
   - 倒虹吸分组（`siphon_groups`）
   - 倒虹吸转弯半径倍数 n（固定为常量 `DEFAULT_SIPHON_TURN_RADIUS_N=3.0`）
   - 回调函数 `import_losses_callback`
4. 计算完毕后回调写入：
   - `node.head_loss_siphon`：总水头损失
   - `node.section_params["D"]`：管径（用于后续节点几何重算）

### 9.3 向土石方计算模块提供数据

水面线面板的 `calculated_nodes` 属性对外暴露，土石方模块通过父链访问 `water_profile_panel.calculated_nodes`，提取 `station_MC` + `bottom_elevation` 作为设计纵坡（跳过 `is_transition=True` 行）。

---

## 十、规范引用

| 规范 | 条文 | 用途 |
|------|------|------|
| GB 50288-2018 | §10.2.4 | 倒虹吸渐变段长度（进口5倍h，出口6倍h） |
| GB 50288-2018 | §10.3.6 | 倒虹吸出口渠底高程计算公式 |
| GB 50288-2018 | 附录K 表K.1.2 | 渡槽/隧洞渐变段局部损失系数 |
| GB 50288-2018 | 附录L 表L.1.2 | 倒虹吸渐变段局部损失系数 |
| SL 18 / 规范 | - | 弯道水头损失公式 |

---

## 十一、设计决策记录

### DDR-1：倒虹吸水头损失不在水面线内核单独计算

倒虹吸涉及多管段、弯管、渐变段等复杂因素，由专用的倒虹吸水力计算模块（MultiSiphonDialog）统一计算总水头损失后回写。水面线内核的 `calculate_local_loss` 对倒虹吸节点直接返回外部导入值，不走局部损失公式。

### DDR-2：倒虹吸节点不计算弯道水头损失（hw=0）

弯道水头损失仅在 `arc_length > 0` 时触发。实际使用中倒虹吸在水面线节点表中作为黑箱整体出现（无显式平面转角），故 `arc_length=0`，`hw=0`，与倒虹吸面板已包含的弯管损失不重复计算。

### DDR-3：`siphon_turn_radius_n` 不对外暴露 UI

见 DDR-1/DDR-2：该系数仅用于在几何重算时给倒虹吸节点自动填充转弯半径列的初始值，属于内部参数。固定为常量 3.0 已满足需求，无需用户设置。

---

## 十二、变更日志

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-02-26 | 初始版本，基于已实现代码整理 |
| v1.1 | 2026-02-26 | **代码**：删除"倒虹吸 R=n×D, n="UI输入框（`siphon_n_edit`），改为固定常量 `DEFAULT_SIPHON_TURN_RADIUS_N=3.0`；同步更新 `_recalculate_geometry_impl`、`_build_settings`、`_open_siphon_calculator`、结果摘要文本共4处引用；列弹性由 `[1,3,5,7,9]` 改为 `[1,3,5,7]`。**PRD修订**：修正§3.2/§6.2变更日志引用（§九→§十二）；修正Excel文件名格式；修正Word章节编号（1-4章由模板生成，手动章节从5开始）；修正§5.2.3沿程损失公式（补充主方法 h_f=i×L，曼宁为备用）；§四补充明渠-U形不在constants.py下拉列表的说明；§九修正SharedDataManager方法名为 `register_batch_results()`；§6.5补充首行锁定机制；§6.2补充自动转弯半径各结构规则表、设计流量联动说明、起始桩号格式化说明；§6.4补充Excel导入识别列名说明 |
