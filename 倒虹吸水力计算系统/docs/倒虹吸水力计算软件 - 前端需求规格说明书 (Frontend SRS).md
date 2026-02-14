# 倒虹吸水力计算软件 - 前端需求规格说明书 (Frontend SRS)

# 倒虹吸水力计算软件 - 前端需求规格说明书 (Frontend SRS)

## 1. 界面架构设计 (UI Architecture)

**采用 MVVM (Model-View-ViewModel) 或 MVC 模式，将视图逻辑与业务逻辑分离。**

**View (视图层): Windows Forms 或 WPF 窗体。**

**ViewModel (逻辑层): 负责界面数据的绑定、命令的响应以及对后端服务的调用。**

## 2. 主窗口布局 (Main Window)

窗口标题：“倒虹吸水力计算”。需包含以下三个主要区域：

### 2.1 顶部可视化区域 (Visual Area)

**控件类型: PictureBox (WinForms) 或 Canvas (WPF)。**

**背景色: 黑色 (#000000)。**

**功能:**

接收绘图数据（坐标点列表、管径、水位高程）。

绘制倒虹吸管剖面图（绿色线条）。

绘制水位线（绿色水平线 + 倒三角符号）。

绘制标尺或辅助网格（可选）。

支持简单的缩放或平移（高级需求，可选）。

### 2.2 中部参数设置区域 (Parameter Area)

包含两个 TabControl 页面。

#### Tab 1: 基本参数 (Basic Parameters)

采用左右分栏布局或分组框 (GroupBox)。

**左侧：全局水力参数**

**ComboBox 计算目标: 锁定显示 “设计截面”。**

**TextBox 设计流量 Q: 必填，浮点数校验。**

**TextBox 拟定流速 v: 必填，浮点数校验。**

**TextBox 上/下游水位: 浮点数。**

**TextBox 上游渠底高程: 用于绘图定位。**

**TextBox 糙率 n: 默认 0.014。**

**右侧：渐变段配置**

**ComboBox 进口型式: 绑定 Enum (无, 方头, 圆弧等)。触发 SelectionChanged 事件。**

**TextBox 进口系数: 绑定到后端推荐值，允许用户覆盖。**

**TextBox 进口渠道流速: 用户输入。**

**Label 进口管内流速: 只读，绑定计算结果。**

(出口配置同理)

#### Tab 2: 结构段信息 (Structure Segments)

**顶部工具栏:**

**Button [导入 DXF]: 点击调用 OpenFileDialog。**

**Button [清空]: 清空表格。**

**TextBox 结构段数: 只读或手动输入（导入DXF后自动更新）。**

**核心控件: DataGridView (WinForms) 或 DataGrid (WPF)。**

**列定义:**

序号: 自动生成。

类型: ComboBoxColumn (直管, 弯管, 折管…)。

参数1 (长度/半径): 动态标题。

参数2 (角度): 动态标题。

局部系数: TextBoxColumn (支持手动修改)。

解锁: CheckBoxColumn (控制该行是否只读)。

**交互逻辑:**

点击行时，根据类型动态改变单元格的可编辑状态。

第1行强制为“进水口”，最后一行强制为“出水口”。

**右侧说明面板: Label 或 TextBlock，显示硬编码的操作指南。**

### 2.3 底部操作区域 (Operation Area)

**左侧: Panel 显示公式图片或文字说明（谢才公式等）。**

**中间: TextBox 作业名称。**

**右侧:**

**Button [计算]: 触发核心计算流程。**

**Button [返回/关闭]: 关闭窗口。**

## 3. 前端交互逻辑 (Frontend Logic)

### 3.1 事件处理 (Event Handling)

#### A. 渐变段联动

**事件: 用户在 Tab 1 更改“进口型式”。**

**动作:**

调用后端 GetRecommendedGradientCoeff 获取系数。

更新 Tab 1 的“进口系数”文本框。

同步更新 Tab 2 第 1 行（进水口）的“局部系数”单元格。

#### B. DXF 导入

**事件: 点击 [导入 DXF]。**

**动作:**

打开文件选择器，滤镜 *.dxf。

调用后端 ParseDxf(filePath)。

获取返回的 List<StructureSegment>。

**数据绑定: 将列表绑定到 DataGridView。**

**锁定状态: 将所有导入生成的行设为“只读”（Lock Checkbox = True）。**

**反馈: 弹窗提示“导入成功，共解析 X 段…”。**

#### C. 计算执行

**事件: 点击 [计算]。**

**动作:**

**表单校验: 检查 Q, v, 水位等是否为空或非法格式。**

**构建数据: 从 UI 控件收集 GlobalParameters 对象和 List<StructureSegment>。**

**调用后端: Backend.ExecuteCalculation(...)。**

**处理结果:**

**成功:**

弹窗显示：管径 D、总损失 、校验结果。

刷新绘图区 (调用绘图方法)。

更新 Tab 1 中只读的流速字段。

**失败/警告:**

弹窗显示错误信息（如“水位差不足”）。

### 3.2 绘图实现 (Rendering)

需封装一个 DrawPipeline 方法。

**坐标转换:**

定义 WorldToScreen 转换矩阵。

世界坐标原点  映射到画布左侧适当位置。

Y轴翻转（屏幕坐标向下为正，物理坐标向上为正）。

**绘制流程:**

Graphics.Clear(Color.Black)。

**画管线:**

遍历结构段。

根据计算出的管径 ，计算中心线上下偏移量。

使用 DrawLine (直管/折管) 和 DrawArc (弯管) 绘制绿色线条。

注：对于DXF导入的数据，直接使用解析出的坐标点绘制中心线，再算法生成管壁线。

**画水位:**

使用 DrawLine 绘制上游 () 和下游 () 水位线。

绘制倒三角图标 DrawPolygon。

**画标尺/文字:**

在关键节点（进出口、变坡点）绘制文本 DrawString 显示高程或桩号。

## 4. 异常提示与用户体验

**输入错误: 使用 ErrorProvider (WinForms) 或红色边框 (WPF) 提示非法输入。**

**耗时操作: 若计算或解析耗时 > 500ms，鼠标指针变为 WaitCursor。**

**数据同步: 确保 Tab 1 的系数修改能实时反映到 Tab 2，反之亦然。**
