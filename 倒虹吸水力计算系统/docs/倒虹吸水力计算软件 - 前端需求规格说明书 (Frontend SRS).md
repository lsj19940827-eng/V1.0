# 倒虹吸水力计算软件 - 前端需求规格说明书 (Frontend SRS)

**版本**: v3.0
**最后更新**: 2026-03-02
**状态**: 已实现
**技术栈**: PySide6 + qfluentwidgets (Fluent Design) + QPainter + QWebEngineView (KaTeX)

---

## 1. 界面架构设计

### 1.1 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| UI框架 | PySide6 (Qt6) | QWidget 体系 |
| 设计风格 | qfluentwidgets | Fluent Design 控件（PushButton, LineEdit, ComboBox, InfoBar） |
| 可视化画布 | QPainter | 自绘管道纵断面/平面视图，支持缩放/平移 |
| 公式渲染 | QWebEngineView + KaTeX | 亚克力毛玻璃风格 + LaTeX 公式静态渲染 |
| 样式 | 统一样式系统 | `渠系断面设计/styles.py` 提供 P/S/W/E/BG/CARD/BD/T1/T2 等颜色常量 |

### 1.2 文件结构

| 文件 | 职责 |
|------|------|
| `渠系断面设计/siphon/panel.py` | 主面板 `SiphonPanel`，含全部UI构建、参数联动、计算调用、导出 |
| `渠系断面设计/siphon/canvas_view.py` | 可视化画布 `PipelineCanvas`，纵断面/平面视图切换 |
| `渠系断面设计/siphon/dialogs.py` | 专业对话框（进水口形状/出水口系数/拦污栅配置/结构段编辑/断面参数/通用构件） |
| `渠系断面设计/siphon/multi_siphon_dialog.py` | 多标签页倒虹吸计算窗口 `MultiSiphonDialog` |

---

## 2. 主面板布局 (SiphonPanel)

SiphonPanel 继承 QWidget，作为渠系断面设计Tab系统中的一个页面。

### 2.1 区域 A：可视化画布

**控件**：`PipelineCanvas`（自绘 QWidget）  
**背景色**：深色 (#14141E)

**功能**：
- 绘制管道纵断面视图（绿色管线，弯管/折管高亮橙色）
- 绘制平面视图（IP点、转弯半径、方位角箭头）
- 自动视图切换（有纵断面数据则纵断面，有平面数据则平面）
- 鼠标滚轮缩放 + 拖拽平移
- 高程标注、节点编号、示例数据灰显

**工具栏**：
- 视图切换按钮（纵断面/平面）
- 缩放百分比标签
- 重置视图按钮

**信号**：`view_changed(str)`、`zoom_changed(float)`

### 2.2 区域 B：参数设置区域（QTabWidget，4个Tab）

#### Tab 1: 基本参数

采用左右分栏布局（QGridLayout），分为4个参数卡片（QGroupBox）。

**卡片1：设计参数**

| 控件 | 类型 | 说明 |
|------|------|------|
| 名称 | LineEdit | 作业名称，默认"倒虹吸" |
| 设计流量 Q | LineEdit | 必填 (m³/s) |
| 拟定流速 v | LineEdit | 必填 (m/s)，方案D确认交互 |
| 糙率 n | LineEdit | 默认 0.014 |
| 管道根数 N | _NumPipesWidget | 自定义 [-] 数字 [+] 控件，1~10 |
| 弯管半径倍数 n | LineEdit | R = n * D |
| 弯管半径 R | LineEdit | 计算值或手动输入，双向联动 |
| D理论 | Label（只读） | D = sqrt(4Q/(N*pi*v))，实时更新 |
| 指定管径 | CheckBox + LineEdit | 可选覆盖 |

**确认交互机制**：
- **方案D（拟定流速）**：用户手动编辑触发"未确认"状态（黄色边框），Enter/失焦确认后变绿色边框，计算前强制验证
- **方案B（弯管半径倍数）**：温和提醒，计算时弹出黄色InfoBar警告（不阻断）
- **管道根数**：值变化时重置确认状态，[+]/[-]点击视为确认

**卡片2：渐变段配置**

| 控件 | 说明 |
|------|------|
| 进口渐变段型式 | ComboBox（无/反弯扭曲面/1/4圆弧/方头型/直线扭曲面） |
| 进口系数 xi1 | LineEdit，型式变更自动联动 |
| 出口渐变段型式 | ComboBox |
| 出口系数 xi2 | LineEdit，型式变更自动联动 |
| 参考表按钮 | 弹出 L12CoeffRefDialog（表L.1.2参考表） |

**卡片3：流速参数**

| 控件 | 说明 |
|------|------|
| 进口始端流速 v1 | LineEdit (m/s) |
| v2策略 | ComboBox（自动/v1+0.2/断面参数计算/指定输入） |
| 进口末端流速 v2 | LineEdit，根据策略可读/只读 |
| 出口始端流速 v_out | LineEdit (= 管道流速) |
| 出口末端流速 v3 | LineEdit (m/s) |

**v2策略联动**：
- **自动**：v2只读，计算后回填管道流速
- **v1+0.2**：v1变化时自动联动v2
- **断面参数**：双击提示标签打开 `InletSectionDialog`
- **指定输入**：v2可编辑

**卡片4：高级选项**

| 控件 | 说明 |
|------|------|
| 水损阈值 | LineEdit，计算完成后对比告警 |
| 考虑加大流量 | CheckBox + 百分比输入 |
| 显示详细过程 | CheckBox |

#### Tab 2: 结构段信息

**三区表格**（QTableWidget，12列）：

| 列 | 标题 | 说明 |
|----|------|------|
| 0 | 序号 | 自动编号 |
| 1 | 分类 | 通用/平面/纵断面(示例) |
| 2 | 类型 | 段类型（附加状态如"拦污栅(已配置)"） |
| 3 | 方向 | SegmentDirection |
| 4 | 长度(m) | -- |
| 5 | 半径R(m) | 弯管有效 |
| 6 | 角度theta(deg) | 弯管/折管角度 |
| 7 | 起点高程 | 纵断面段有效 |
| 8 | 终点高程 | 纵断面段有效 |
| 9 | 空间长度 | sqrt(L^2+dH^2) |
| 10 | 局部系数 | xi值 |
| 11 | 锁定 | 是/否 |

**三色分区**：
- 浅黄色 (#FFF8E1)：通用构件
- 浅蓝色 (#E8F0FE)：平面段
- 浅绿色 (#E8F5E9)：纵断面段
- 灰绿色 (#F0F4F0)：纵断面示例数据

**工具栏按钮**：
- 导入平面DXF -> `_import_plan_dxf()`（工程坐标多段线，X=东, Y=北）
- 导入纵断面DXF -> `_import_dxf()`
- 撤回平面 -> `_undo_plan_import()`（撤回上一次平面导入，栈式回退）
- 清空平面 -> `_clear_plan_data()`（清空全部平面数据）
- 添加管身段 -> `SegmentEditDialog`
- 添加通用构件 -> `CommonSegmentAddDialog`
- 添加管道渐变段 -> 快速插入
- 删除、上移、下移
- 清空纵断面、默认构件

**交互规则**：
- 双击行打开对应编辑对话框
- 进水口 -> `InletShapeDialog`
- 出水口 -> `OutletShapeDialog`
- 拦污栅 -> `TrashRackConfigDialog`
- 闸门槽/旁通管/管道渐变段 -> `SimpleCommonEditDialog`
- 其他(通用) -> `CommonSegmentEditDialog`
- 管身段 -> `SegmentEditDialog`
- **平面段删除策略（差异化）**：
  - DXF导入的平面段（`_plan_source == 'dxf'`）：可删除
  - 推求水面线提取的平面段（`_plan_source == 'water_profile'`）：不可手动删除
- 进出水口不可删除

#### Tab 3: 纵断面节点

**表格**（QTableWidget，5列）：

| 列 | 标题 | 说明 |
|----|------|------|
| 0 | 桩号(m) | -- |
| 1 | 高程(m) | -- |
| 2 | 竖曲线半径(m) | 0=折线 |
| 3 | 转弯类型 | QComboBox（无/圆弧/折线） |
| 4 | 转角(deg) | -- |

**工具栏**：添加/删除节点、导入纵断面DXF、清空

**双向同步**：
- 正向：节点表编辑 -> `_sync_nodes_to_segments()` -> 重建管身段
- 反向：管身段编辑 -> `_sync_segments_to_nodes()` -> 重建节点表
- 防递归：`_syncing` 标志

**纵断面DXF导入流程**：
1. 选择纵断面DXF文件
2. 计算桩号偏移量（对齐平面IP点起始桩号或归零）
3. 调用 `DxfParser.parse_longitudinal_profile()`
4. 同时用 `parse_dxf()` 生成结构段表格
5. 保留已有通用构件（进出水口形状/系数设置不丢失）
6. 切换画布为纵断面视图
7. 显示模式提示（三维空间合并 / 纵断面独立）

#### Tab 4: 计算结果

**子TabWidget**（结果汇总 + 详细过程 + 公式展示）：
- 结果汇总：QTextEdit（只读），显示 `format_result(show_steps=False)`
- 详细过程：QTextEdit（只读），显示 `format_result(show_steps=True)`
- 公式展示：QWebEngineView，KaTeX渲染（亚克力毛玻璃风格）

### 2.3 区域 C：底部操作栏

| 按钮 | 说明 |
|------|------|
| 计算 | PrimaryPushButton，触发核心计算 |
| 导出Word | PushButton，工程产品运行卡格式 |
| 导出Excel | PushButton，openpyxl |
| 导出TXT | PushButton，纯文本 |

### 2.4 数据状态栏

位于画布下方，实时显示当前计算模式：
- "平面+纵断面（空间合并）" -- 绿色
- "仅平面估算" -- 橙色
- "仅纵断面" -- 橙色
- "传统模式（仅平面总长度）" -- 橙色
- "无平面/纵断面数据" -- 红色

附加数据计数：结构段数、节点数、IP点数、平面长度、**平面来源标记（DXF/水面线）**

---

## 2.5 平面DXF导入子系统（v3.0 新增）

### 2.5.1 概述

平面DXF导入功能允许用户独立于纵断面导入平面工程坐标多段线，支持三种计算模式：
- **平面-only**：仅有平面数据，使用平面独立计算
- **纵断面-only**：仅有纵断面数据
- **平面+纵断面（空间合并）**：同时拥有两种数据，三维空间合并计算

### 2.5.2 状态管理

**新增成员变量**（`__init__` 方法）：

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `_plan_source` | str | `'none'` | 平面数据来源追踪：`'none'`/`'dxf'`/`'water_profile'` |
| `_plan_undo_stack` | list | `[]` | 平面数据撤回栈（深拷贝快照） |

### 2.5.3 导入流程 (`_import_plan_dxf()`)

```
1. 校验DXF解析器可用性
2. 冲突保护：
   - 检测已有平面数据（plan_feature_points 或 plan_segments）
   - 弹窗显示现有数据来源（"DXF导入"/"推求水面线提取"/"已有"）
   - 用户取消则中止
3. QFileDialog 选择 .dxf 文件（默认resources目录）
4. 调用 DxfParser.parse_plan_polyline(filepath)
5. 失败：InfoBar.error 显示错误消息
6. 成功：
   a. _push_plan_undo() 保存撤回快照
   b. 替换 plan_feature_points, plan_segments
   c. 计算 plan_total_length（末端特征点桩号）
   d. 设置 _plan_source = 'dxf'
   e. 刷新UI：_refresh_seg_table, _update_segment_coefficients, _update_canvas, _update_data_status
   f. InfoBar.success 显示详细结果：
      - 特征点数、平面段数、平面总长
      - 弯管/折管数量
      - 三维模式检测（有/无纵断面数据）
```

### 2.5.4 撤回功能

**`_push_plan_undo()`**：
- 深拷贝当前 `plan_segments`、`plan_feature_points`、`plan_total_length`、`_plan_source` 为快照
- 压入 `_plan_undo_stack`
- 栈深度限制：20（超出时移除最早快照 `pop(0)`）

**`_undo_plan_import()`**：
- 栈空：InfoBar.warning 提示
- 栈非空：弹出最新快照，恢复所有平面数据字段
- 刷新UI组件

### 2.5.5 清空功能 (`_clear_plan_data()`)

1. 校验是否有平面数据
2. `fluent_question()` 确认对话框
3. `_push_plan_undo()` 保存快照（可撤回）
4. 清空 `plan_segments`、`plan_feature_points`
5. 重置 `plan_total_length = 0.0`、`_plan_source = 'none'`
6. 刷新UI

### 2.5.6 半径保护 (`_update_plan_bend_radius()`)

弯管半径联动时的差异化处理：

| 数据来源 | 弯管段半径 | 特征点turn_radius |
|----------|-----------|-------------------|
| DXF (`locked=True`) | 跳过，保留DXF实际半径 | 跳过（`_plan_source=='dxf'` 且 `turn_radius>0`） |
| 推求水面线 (`locked=False`) | 更新为 `n * D_design` | 更新为 `siphon_radius` |

### 2.5.7 数据冲突保护 (`set_params()`)

当推求水面线通过 `set_params()` 传入平面数据时：
1. 检测是否有传入的平面数据（`plan_segments` 或 `plan_feature_points` in kwargs）
2. 检测是否已有平面数据
3. 如两者同时存在，弹出确认对话框：
   - 显示现有数据来源（"DXF导入"/"推求水面线提取"）
   - 用户选择是否覆盖
4. 如用户拒绝覆盖，跳过平面数据设置（`_plan_skip = True`）
5. 覆盖时，先 `_push_plan_undo()` 保存快照，设置 `_plan_source = 'water_profile'`

### 2.5.8 删除策略 (`_del_segment()` 差异化)

| 平面数据来源 | 平面段行为 |
|-------------|-----------|
| `_plan_source == 'water_profile'` | 拒绝删除，InfoBar提示"由推求水面线表格自动提取，不可手动删除" |
| `_plan_source == 'dxf'` | 允许删除，与通用段/纵断面段一样执行删除流程 |

删除实现：
- 分别收集 `to_remove`（通用/纵断面段在 `self.segments` 中的索引）和 `plan_to_remove`（平面段在 `self.plan_segments` 中的索引）
- 按索引逆序删除，避免索引偏移

---

## 3. 对话框体系 (dialogs.py)

### 3.1 InletShapeDialog（进水口形状设置）

- 显示表L.1.4-2三种形状及对应xi范围
- 用户选择形状后自动设置xi值（取范围中值或用户指定）

### 3.2 OutletShapeDialog（出水口系数设置）

- 根据下游渠道参数（类型/B/h/m/D/R）计算出口系数
- 支持手动输入

### 3.3 TrashRackConfigDialog（拦污栅详细配置）

- 左侧：参数录入区（栅面倾角/是否有支墩/栅条形状/厚度间距等）
- 右侧：规范参考区（图L.1.4-1形状示意图 + 表L.1.4-1系数表）
- 实时预览xi计算结果
- 支持手动输入模式
- 详见 `PRD_拦污栅配置.md`

### 3.4 SegmentEditDialog（管身段编辑）

- 编辑/新增直管、弯管、折管
- 弯管自动查表计算xi

### 3.5 InletSectionDialog（进口断面参数设置）

- 输入 B(底宽)、h(水深)、m(坡比)
- 计算 v2 = Q / [(B + m*h) * h]

### 3.6 CommonSegmentAddDialog / CommonSegmentEditDialog / SimpleCommonEditDialog

- 添加/编辑通用构件（名称 + xi值）

### 3.7 L12CoeffRefDialog（渐变段系数参考表）

- 只读表格，显示表L.1.2数据

---

## 4. 多标签页窗口 (MultiSiphonDialog)

### 4.1 功能

- 从推求水面线表格自动提取倒虹吸分组数据（`SiphonDataExtractor`)
- 每个倒虹吸独立标签页（`SiphonPanel` 实例）
- 参数自动导入（Q/n/v/渐变段/断面参数/平面段等）
- 全部计算并导出水头损失到主表格
- `SiphonManager` 持久化（保存/加载历史配置）

### 4.2 接口

```python
MultiSiphonDialog(
    parent,
    siphon_groups: List[SiphonGroup],
    manager: SiphonManager = None,
    on_import_losses: Callable = None,  # 回调：results -> 写入主表
    siphon_turn_radius_n: float = 0.0,
    auto_run: bool = False
)
```

---

## 5. 交互逻辑

### 5.1 参数联动

| 触发 | 联动动作 |
|------|----------|
| Q 或 v 变更 | 200ms防抖 -> 更新D理论值、弯管半径R |
| 渐变段型式变更 | 自动查表填充 xi1/xi2 |
| v1 变更 | v2策略为"v1+0.2"时联动v2 |
| 弯管半径倍数 n 变更 | 联动R值显示、更新平面弯管半径 |
| 弯管半径 R 变更 | 反推 n = R / D设计 |
| 管道根数变更 | 联动Q/v理论值 |
| 指定管径勾选 | 显示/隐藏管径输入框 |

### 5.2 计算流程

1. 验证拟定流速已确认（方案D）
2. 验证管道根数已确认
3. 收集 GlobalParameters
4. 同步纵断面节点
5. 弯管半径倍数未确认警告（方案B，不阻断）
6. v2校验（非阻断警告）
7. 调用 `HydraulicCore.execute_calculation()`
8. 回填流速值（v1/v2/v_out/v3），标注来源
9. 水损阈值检查
10. 显示结果（自动切换到结果Tab）
11. 更新画布和数据状态
12. 触发回调（如有）

### 5.3 导出功能

| 格式 | 依赖 | 内容 |
|------|------|------|
| Word (.docx) | python-docx, latex2mathml, lxml | 工程产品运行卡格式：基础公式+设计参数+计算结果+详细过程 |
| Excel (.xlsx) | openpyxl | 参数+结果表格 |
| TXT | 无 | 纯文本计算报告 |

Word导出特性：
- 若当前结果无详细步骤，自动以verbose模式重新计算
- 使用 `ExportConfirmDialog` 确认报告元数据
- 公式使用 LaTeX->MathML 渲染
- 支持自动更新目录（via COM）

### 5.4 序列化接口

```python
to_dict() -> dict   # 保存：Q/v/n/v1/v3/渐变段/管径/根数/结构段/节点/平面数据/plan_source
from_dict(d)        # 恢复：UI状态完全还原
```

**v3.0 新增持久化字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan_source` | str | 平面数据来源（`'none'`/`'dxf'`/`'water_profile'`） |

**`from_dict()` 兼容策略**：
- 存在 `plan_source` 字段 → 直接恢复
- 无 `plan_source` 但有平面数据 → 默认 `'water_profile'`（兼容旧数据）
- 无 `plan_source` 且无平面数据 → `'none'`

---

## 6. 可视化画布 (canvas_view.py)

### 6.1 PipelineCanvas

继承 QWidget，自绘引擎。

**颜色体系**：

| 常量 | 颜色 | 用途 |
|------|------|------|
| C_BG | #14141E | 背景 |
| C_PIPE | #00FF00 | 管线 |
| C_BEND | #FFAA00 | 弯管/折管 |
| C_INLET | #00FFFF | 进出口 |
| C_NODE | #00FF00 | 节点 |
| C_ELEV | #AAAAAA | 高程标注 |

**视图模式**：
- profile（纵断面）：绘制管线轮廓+高程标注+弯管角度
- plan（平面）：绘制IP点连线+转弯半径+方位角箭头

**交互**：
- 鼠标滚轮：缩放（centered on cursor）
- 鼠标拖拽：平移
- auto_select_view()：根据数据自动切换视图

---

## 7. 异常处理与用户体验

- **输入错误**：qfluentwidgets InfoBar（红色ERROR/黄色WARNING/绿色SUCCESS），定位到窗口顶部
- **防抖机制**：Q/v参数联动200ms防抖、画布更新100ms防抖
- **确认交互**：拟定流速/管道根数/弯管半径倍数分别有独立确认机制，避免误操作
- **冲突保护（v3.0 新增）**：
  - 平面DXF导入时检测已有平面数据，弹窗确认覆盖
  - 推求水面线传入平面数据时检测冲突，弹窗确认覆盖
  - 弹窗显示现有数据来源（DXF导入/推求水面线提取），帮助用户决策
- **撤回机制（v3.0 新增）**：
  - 平面数据支持栈式撤回（深度20），每次导入/清空前自动保存快照
  - "撤回平面"按钮可逐步回退到上一状态
- **DXF半径保护（v3.0 新增）**：DXF导入的弯管段（`locked=True`）保留实际几何半径，不被弯管半径倍数n×D联动覆盖
- **示例数据提示**：纵断面示例数据灰色显示，首次手动添加自动清除
- **空表格引导**：无数据时显示"点击导入DXF或手动添加"提示
- **文件占用处理**：Word/Excel导出捕获PermissionError，提示关闭已打开的文件

---

## 8. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-02-15 | 初始版本（WinForms/WPF架构描述） |
| v2.0 | 2026-02-25 | 全面重写：PySide6+Fluent UI实现；新增4Tab布局、三区表格、纵断面节点双向同步、多标签页窗口、确认交互机制、v2策略联动、导出体系、可视化画布、对话框体系 |
| v3.0 | 2026-03-02 | **平面DXF独立导入**：新增平面DXF导入按钮及完整工作流（导入/撤回/清空）；数据来源追踪（`_plan_source`）；冲突保护弹窗（DXF vs 推求水面线）；差异化删除策略（DXF段可删/水面线段不可删）；DXF半径保护（locked段跳过n×D覆盖）；撤回栈（深度20）；`to_dict/from_dict` 新增 `plan_source` 持久化字段及旧数据兼容；数据状态栏新增平面来源标记（DXF/水面线） |
