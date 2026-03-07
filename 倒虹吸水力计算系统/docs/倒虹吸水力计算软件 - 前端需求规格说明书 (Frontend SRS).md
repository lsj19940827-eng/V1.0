# 倒虹吸水力计算软件 - 前端需求规格说明书 (Frontend SRS)

**版本**: v4.0  
**最后更新**: 2026-03-06  
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
| 样式 | 统一样式系统 | `app_渠系计算前端/styles.py` 提供 P/S/W/E/BG/CARD/BD/T1/T2 等颜色常量 |

### 1.2 文件结构

| 文件 | 职责 |
|------|------|
| `app_渠系计算前端/siphon/panel.py` | 主面板 `SiphonPanel`，含全部UI构建、参数联动、计算调用、导出、工况集成、示例数据管理 |
| `app_渠系计算前端/siphon/canvas_view.py` | 可视化画布 `PipelineCanvas`，纵断面/平面视图切换 |
| `app_渠系计算前端/siphon/dialogs.py` | 专业对话框（进水口形状/出水口系数/拦污栅配置/结构段编辑/断面参数/通用构件） |
| `app_渠系计算前端/siphon/multi_siphon_dialog.py` | 多标签页倒虹吸计算窗口 `MultiSiphonDialog` |
| `app_渠系计算前端/siphon/case_manager.py` | 工况管理器 `CaseManager`，工况 CRUD、文件持久化 (v4.0 新增) |
| `app_渠系计算前端/siphon/case_sidebar.py` | 工况侧边栏 `CaseSidebar`，Fluent Design 工况列表 UI (v4.0 新增) |
| `app_渠系计算前端/siphon/__init__.py` | 模块初始化 |

---

## 2. 工况管理系统 (v4.0 新增)

### 2.1 功能概述

工况管理系统支持用户同时管理多个倒虹吸设计方案进行对比。SiphonPanel 左侧嵌入工况侧边栏（宽度可调，默认 200px），右侧为设计面板主体。

### 2.2 工况管理器 (CaseManager)

**文件**: `case_manager.py`

| 类 | 说明 |
|-----|------|
| `CaseInfo` | 工况信息（name, file_path, created_time, order） |
| `CaseManager` | 工况 CRUD 管理器 |

**存储**：
- 存储位置：`data/siphon_cases/` 目录
- 文件格式：`工况名.siphon.json`（JSON，含 `case_name`、`created_time`、`order` 元数据 + SiphonPanel `to_dict()` 数据）
- 支持导入导出：`.siphon.json` 和 `.json` 格式

**方法**：

| 方法 | 说明 |
|------|------|
| `create_case(name?)` | 创建新工况，自动命名"工况1"、"工况2"等 |
| `rename_case(case, new_name)` | 重命名工况（同步重命名文件） |
| `delete_case(case)` | 删除工况文件（无需确认，文件可从系统恢复） |
| `duplicate_case(case)` | 复制工况，自动命名"原名_副本" |
| `reorder_cases(new_order)` | 重新排序工况（持久化 order 字段） |
| `save_case_data(case, data)` | 保存工况数据（附加元数据） |
| `load_case_data(case)` | 加载工况数据 |

### 2.3 工况侧边栏 (CaseSidebar)

**文件**: `case_sidebar.py`

继承 QWidget，Fluent Design 风格。

**信号**：

| 信号 | 说明 |
|------|------|
| `case_selected(object)` | 工况切换（传递 CaseInfo） |
| `case_changed()` | 工况列表变更（增删改排序） |

**UI 组件**：
- 顶部工具栏：[新建] [导入] 两个 PushButton（FluentIcon.ADD / FOLDER）
- 工况列表：QListWidget，支持拖拽排序（InternalMove）

**列表样式**：
- 圆角卡片式列表项（border-radius: 4px）
- 渐变色选中效果（#0078D4 到 #106EBE）
- 悬停半透明背景（rgba(0,0,0,0.05)）

**交互行为**：

| 操作 | 说明 |
|------|------|
| 单击 | 切换工况，发射 `case_selected` 信号 |
| 双击 | 进入重命名编辑状态（`ItemIsEditable`） |
| 右键菜单 | RoundMenu（MenuAnimationType.DROP_DOWN）：重命名(EDIT)、复制(COPY)、导出(SHARE)、删除(DELETE) |
| Delete 键 | 删除当前选中工况 |
| 拖拽 | 调整工况顺序，完成后持久化 `order` 字段 |

### 2.4 工况集成（panel.py）

**关键方法**：

| 方法 | 说明 |
|------|------|
| `_on_case_selected(case)` | 切换工况：自动保存当前 -> 加载目标 -> 刷新 UI |
| `_mark_dirty()` | 标记数据修改 |
| `_do_autosave()` | 执行自动保存到当前工况文件 |

**自动保存触发时机**：
- 切换工况时自动保存当前工况
- 参数修改后 2 秒自动保存
- 计算完成后自动保存
- 关闭面板时自动保存

**首次打开**：自动创建"工况1"

### 2.5 示例数据系统 (v4.0 新增)

#### 概述

新工况或空工况自动添加纵断面示例数据（13 个节点），帮助用户直观了解界面。示例数据通过灰色斜体样式和黄色提示标签与用户数据区分。

#### 示例数据来源

DXF 示例文件：`倒虹吸水力计算系统/resources/导入纵断面dxf示例.dxf`

| 特征 | 数值 |
|------|------|
| 桩号范围 | 0.00m ~ 249.87m（已归零处理） |
| 竖曲线 | 4 个 ARC（R=5m） |
| 折点 | 1 个 FOLD |
| 高程范围 | 48.87m ~ 113.84m |
| 结构段 | 12 个（含进出水口） |

#### 状态管理

| 变量 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `_longitudinal_is_example` | bool | False | 是否为示例数据 |

#### 行为规则

| 场景 | 行为 |
|------|------|
| 首次打开 / 新建工况 | 自动调用 `_add_example_longitudinal()` 添加示例数据 |
| 从推求水面线进入（有平面无纵断面） | 自动添加示例数据 |
| 从 `from_dict()` 加载空工况 | 自动添加示例数据 |
| 工况切换时无纵断面数据 | 自动添加示例数据 |
| 用户编辑纵断面节点表 | 自动清除示例标志 |
| 用户编辑纵断面结构段 | 自动清除示例标志 |
| 保存工况（`to_dict()`） | 示例数据不保存（`_longitudinal_is_example=True` 时跳过节点） |
| 保存时标记 | `longitudinal_is_example: true` 标记到 JSON |

#### 视觉标识

| 元素 | 样式 |
|------|------|
| 纵断面节点表行 | 灰色斜体（示例标志为 True 时） |
| 结构段表纵断面行 | 灰绿色底色 (#F0F4F0) |
| 纵断面节点表提示标签 | `long_hint_label`：浅黄底+橙字 "当前显示示例数据，可导入DXF替换" |
| 结构段表提示标签 | `seg_hint_label`：浅黄底+橙字 "当前纵断面为示例数据" |
| 提示标签控制 | 示例标志为 True 时显示，False 时隐藏 |

#### DXF 导入确认

导入纵断面DXF时检查是否有现有数据，如有则弹出确认对话框，用户确认后才执行导入。

---

## 3. 主面板布局 (SiphonPanel)

SiphonPanel 继承 QWidget，作为app_渠系计算前端Tab系统中的一个页面。左侧嵌入工况侧边栏（CaseSidebar，宽度可调，默认 200px），右侧为设计面板主体。

### 3.1 区域 A：可视化画布

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

### 3.2 区域 B：参数设置区域（QTabWidget，4个Tab）

#### Tab 1: 基本参数

采用左右分栏布局（QGridLayout），分为4个参数卡片（QGroupBox）。

**卡片1：设计参数**

| 控件 | 类型 | 说明 |
|------|------|------|
| 名称 | LineEdit | 作业名称，默认"倒虹吸" |
| 设计流量 Q | LineEdit | 必填 (m3/s) |
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
- 导入平面DXF / 导入纵断面DXF / 撤回平面 / 清空平面
- 添加管身段 / 添加通用构件 / 添加管道渐变段
- 删除 / 上移 / 下移
- 清空纵断面 / 默认构件

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

### 3.3 区域 C：底部操作栏

| 按钮 | 说明 |
|------|------|
| 计算 | PrimaryPushButton，触发核心计算 |
| 导出Word | PushButton，工程产品运行卡格式 |
| 导出Excel | PushButton，openpyxl |
| 导出TXT | PushButton，纯文本 |

### 3.4 数据状态栏

位于画布下方，实时显示当前计算模式：
- "平面+纵断面（空间合并）" -- 绿色
- "仅平面估算" -- 橙色
- "仅纵断面" -- 橙色
- "传统模式（仅平面总长度）" -- 橙色
- "无平面/纵断面数据" -- 红色

附加数据计数：结构段数、节点数、IP点数、平面长度、**平面来源标记（DXF/水面线）**

---

## 3.5 平面DXF导入子系统（v3.0）

### 3.5.1 概述

平面DXF导入功能允许用户独立于纵断面导入平面工程坐标多段线，支持三种计算模式：
- **平面-only**：仅有平面数据，使用平面独立计算
- **纵断面-only**：仅有纵断面数据
- **平面+纵断面（空间合并）**：同时拥有两种数据，三维空间合并计算

### 3.5.2 状态管理

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `_plan_source` | str | `'none'` | 平面数据来源追踪：`'none'`/`'dxf'`/`'water_profile'` |
| `_plan_undo_stack` | list | `[]` | 平面数据撤回栈（深拷贝快照） |

### 3.5.3 导入流程 (`_import_plan_dxf()`)

1. 校验DXF解析器可用性
2. 冲突保护：检测已有平面数据，弹窗显示现有数据来源，用户取消则中止
3. QFileDialog 选择 .dxf 文件（默认resources目录）
4. 调用 DxfParser.parse_plan_polyline(filepath)
5. 失败：InfoBar.error 显示错误消息
6. 成功：保存撤回快照 -> 替换数据 -> 设置来源 -> 刷新UI -> InfoBar.success

### 3.5.4 撤回功能

- `_push_plan_undo()`：深拷贝当前数据为快照，压入栈（深度限制20）
- `_undo_plan_import()`：弹出最新快照恢复，刷新UI

### 3.5.5 清空功能 (`_clear_plan_data()`)

确认对话框 -> 保存快照 -> 清空数据 -> 重置来源 -> 刷新UI

### 3.5.6 半径保护

| 数据来源 | 弯管段半径 | 特征点turn_radius |
|----------|-----------|-------------------|
| DXF (`locked=True`) | 跳过，保留DXF实际半径 | 跳过 |
| 推求水面线 (`locked=False`) | 更新为 `n * D_design` | 更新为 `siphon_radius` |

### 3.5.7 数据冲突保护 (`set_params()`)

推求水面线传入平面数据时：检测冲突 -> 弹窗确认 -> 用户拒绝则跳过 -> 覆盖时先保存快照

### 3.5.8 删除策略

| 平面数据来源 | 平面段行为 |
|-------------|-----------|
| `_plan_source == 'water_profile'` | 拒绝删除 |
| `_plan_source == 'dxf'` | 允许删除 |

---

## 4. 对话框体系 (dialogs.py)

### 4.1 InletShapeDialog（进水口形状设置）

- 显示表L.1.4-2三种形状及对应xi范围
- 用户选择形状后自动设置xi值（取范围中值或用户指定）

### 4.2 OutletShapeDialog（出水口系数设置）

- 根据下游渠道参数（类型/B/h/m/D/R）计算出口系数
- 支持手动输入

### 4.3 TrashRackConfigDialog（拦污栅详细配置）

**继承**: `QDialog`  
**窗口尺寸**: 900x750（最小 820x660）  
**规范依据**: GB 50288-2018 附录L，公式 L.1.4-2 / L.1.4-3，表 L.1.4-1

#### 总体布局

左右双栏（`QHBoxLayout`，各占 stretch=1）：
- **左侧**：参数录入区（基础参数 -> 栅条参数 -> 支墩参数 -> 计算结果）
- **右侧**：规范参考区（栅条形状示意图 + 形状系数表）

#### 左侧：参数录入区

**分组一：基础参数**

| 控件 | 说明 |
|------|------|
| 栅面倾角 (度) | `LineEdit`，默认 90，范围 0~180 |
| 计算模式 | `QButtonGroup` + 两个 `QRadioButton` |
| - 无独立支墩 (公式L.1.4-2) | 默认选中 |
| - 有独立支墩 (公式L.1.4-3) | 选中后激活分组三 |

**分组二：栅条参数**

| 控件 | 说明 |
|------|------|
| 栅条形状 | `ComboBox`，选项格式 `"矩形 (beta=2.42)"` |
| 选择形状->右侧表格高亮 | `_on_bar_changed()` -> `_sync_table_highlight()` |
| 栅条厚度 s1 (mm) | `LineEdit` |
| 栅条间距 b1 (mm) | `LineEdit` |
| s1/b1 动态显示 | 实时计算阻塞比 |

**分组三：支墩参数**（仅有独立支墩时激活，否则 `setEnabled(False)`）

| 控件 | 说明 |
|------|------|
| 支墩形状 | `ComboBox`，格式同栅条形状 |
| 支墩厚度 s2 (mm) | `LineEdit` |
| 支墩净距 b2 (mm) | `LineEdit` |
| s2/b2 动态显示 | 实时计算阻塞比 |

**分组四：计算结果**

| 控件 | 说明 |
|------|------|
| 强制手动输入 | `CheckBox`，勾选后禁用分组二/三全部输入框 |
| 手动 xs 输入框 | 仅勾选时可编辑；切换时自动预填公式计算值 |
| xs 结果显示 | 20px 粗体主色调，实时更新 |
| 公式渲染卡片 | `QWebEngineView` + KaTeX SVG 实时展开公式；手动模式下隐藏 |

#### 右侧：规范参考区

**上部：栅条形状示意图 (图L.1.4-1)**
- `QPixmap(图L.1.4-1.png)`，`KeepAspectRatio`，固定高度240px
- `resizeEvent` 自适应缩放
- 双击弹出独立 `QDialog` 放大查看（屏幕 80%）

**下部：形状系数表 (表L.1.4-1)**
- 两列 QTableWidget（7行）：形状名称 / 系数beta，只读
- 列宽 `SectionResizeMode.Stretch`，无水平滚动条
- 点击行->同步左侧栅条/支墩 ComboBox
- 双色高亮（蓝=栅条、琥珀=支墩、紫=重叠）
- `_active_target` 追踪当前活跃目标（'bar' / 'support'），根据焦点分发表格点击

#### 主表格集成

双击拦污栅行 -> 弹出 `TrashRackConfigDialog` -> 确定后写回 `trash_rack_params` + `xi_calc`。

类型列显示配置状态："拦污栅(已配置)" / "拦污栅(未配置)"。序列化/反序列化保存恢复 `trash_rack_params`。

### 4.4 SegmentEditDialog（管身段编辑）

- 编辑/新增直管、弯管、折管
- 弯管自动查表计算xi

### 4.5 InletSectionDialog（进口断面参数设置）

- 输入 B(底宽)、h(水深)、m(坡比)
- 计算 v2 = Q / [(B + m*h) * h]

### 4.6 CommonSegmentAddDialog / CommonSegmentEditDialog / SimpleCommonEditDialog

- 添加/编辑通用构件（名称 + xi值）

### 4.7 L12CoeffRefDialog（渐变段系数参考表）

- 只读表格，显示表L.1.2数据

---

## 5. 多标签页窗口 (MultiSiphonDialog)

### 5.1 功能

- 从推求水面线表格自动提取倒虹吸分组数据（`SiphonDataExtractor`）
- 每个倒虹吸独立标签页（`SiphonPanel` 实例）
- 参数自动导入（Q/n/v/渐变段/断面参数/平面段等）
- 全部计算并导出水头损失到主表格
- `SiphonManager` 持久化（保存/加载历史配置）

### 5.2 接口

```python
MultiSiphonDialog(
    parent,
    siphon_groups: List[SiphonGroup],
    manager: SiphonManager = None,
    on_import_losses: Callable = None,
    siphon_turn_radius_n: float = 0.0,
    auto_run: bool = False
)
```

---

## 6. 交互逻辑

### 6.1 参数联动

| 触发 | 联动动作 |
|------|----------|
| Q 或 v 变更 | 200ms防抖 -> 更新D理论值、弯管半径R |
| 渐变段型式变更 | 自动查表填充 xi1/xi2 |
| v1 变更 | v2策略为"v1+0.2"时联动v2 |
| 弯管半径倍数 n 变更 | 联动R值显示、更新平面弯管半径 |
| 弯管半径 R 变更 | 反推 n = R / D设计 |
| 管道根数变更 | 联动Q/v理论值 |
| 指定管径勾选 | 显示/隐藏管径输入框 |

### 6.2 计算流程

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
13. **自动保存当前工况（v4.0）**

### 6.3 导出功能

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

### 6.4 序列化接口

```python
to_dict() -> dict   # 保存：Q/v/n/v1/v3/渐变段/管径/根数/结构段/节点/平面数据/plan_source
from_dict(d)        # 恢复：UI状态完全还原
```

**v3.0 持久化字段**：`plan_source`（平面数据来源）

**v4.0 新增持久化字段**：`longitudinal_is_example`（纵断面是否为示例数据）

**`from_dict()` 兼容策略**：
- 存在 `plan_source` 字段 -> 直接恢复
- 无 `plan_source` 但有平面数据 -> 默认 `'water_profile'`（兼容旧数据）
- 无 `plan_source` 且无平面数据 -> `'none'`
- 无纵断面节点数据 -> 自动添加示例数据

---

## 7. 可视化画布 (canvas_view.py)

### 7.1 PipelineCanvas

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

## 8. 异常处理与用户体验

- **输入错误**：qfluentwidgets InfoBar（红色ERROR/黄色WARNING/绿色SUCCESS），定位到窗口顶部
- **防抖机制**：Q/v参数联动200ms防抖、画布更新100ms防抖
- **确认交互**：拟定流速/管道根数/弯管半径倍数分别有独立确认机制
- **冲突保护（v3.0）**：平面DXF导入/推求水面线传入平面数据时检测冲突，弹窗确认覆盖
- **撤回机制（v3.0）**：平面数据支持栈式撤回（深度20）
- **DXF半径保护（v3.0）**：DXF导入的弯管段（`locked=True`）保留实际几何半径
- **示例数据提示（v4.0）**：纵断面示例数据灰色斜体+黄色提示标签，首次手动编辑自动清除
- **DXF导入确认（v4.0）**：导入纵断面DXF前检测已有数据，弹窗确认
- **工况自动保存（v4.0）**：参数修改2秒后、计算完成后、切换/关闭工况时自动保存
- **空表格引导**：无数据时显示"点击导入DXF或手动添加"提示
- **文件占用处理**：Word/Excel导出捕获PermissionError

---

## 9. 面板外部接口（与推求水面线联动）

```python
set_params(**kwargs)          # 从外部设置参数（Q, v_guess, n, v1, v3, 平面数据等）
get_result() -> CalculationResult
get_total_head_loss() -> float
to_dict() -> dict             # 序列化（项目保存）
from_dict(d: dict)            # 反序列化（项目加载）
```

---

## 10. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|------|
| v1.0 | 2026-02-15 | 初始版本（WinForms/WPF架构描述） |
| v2.0 | 2026-02-25 | 全面重写：PySide6+Fluent UI实现；新增4Tab布局、三区表格、纵断面节点双向同步、多标签页窗口、确认交互机制、v2策略联动、导出体系、可视化画布、对话框体系 |
| v3.0 | 2026-03-02 | **平面DXF独立导入**：新增平面DXF导入按钮及完整工作流（导入/撤回/清空）；数据来源追踪（`_plan_source`）；冲突保护弹窗；差异化删除策略；DXF半径保护；撤回栈（深度20）；`to_dict/from_dict` 新增 `plan_source` 字段；数据状态栏新增平面来源标记 |
| v4.0 | 2026-03-06 | **工况管理系统**：新增 `case_manager.py`（CaseManager/CaseInfo，工况CRUD、文件持久化）和 `case_sidebar.py`（CaseSidebar，Fluent Design工况列表，拖拽排序/右键菜单/导入导出）；主面板集成左侧工况侧边栏；自动保存机制。**示例数据系统**：新工况自动添加13节点纵断面示例（DXF解析）；灰色斜体+黄色提示标签视觉标识；用户编辑自动清除示例标志；示例数据不保存到工况文件；DXF导入确认机制。**拦污栅配置整合**：TrashRackConfigDialog详细规格整合入主文档（原 `PRD_拦污栅配置.md` 归档） |
