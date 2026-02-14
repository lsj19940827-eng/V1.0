# 倒虹吸水力计算软件 - 后端需求规格说明书 (Backend SRS)

# 倒虹吸水力计算软件 - 后端需求规格说明书 (Backend SRS)

## 1. 系统架构概述

后端系统主要包含以下四个核心服务模块：

**数据模型层 (Data Model)：定义全局参数和结构段的数据结构。**

**DXF 解析引擎 (DXF Parsing Engine)：负责读取CAD文件并转化为结构段数据。**

**系数查询服务 (Coefficient Service)：内置《附录L》中的查表与插值逻辑。**

**水力计算核心 (Hydraulic Core)：执行设计截面计算、水头损失求解及校验。**

## 2. 数据模型层 (Data Model)

后端需定义标准化的数据对象（Class/Struct），用于模块间传参。

### 2.1 全局参数对象 (GlobalParameters)

### 2.2 结构段对象 (StructureSegment)

## 3. DXF 解析引擎 (DXF Parsing Engine)

此模块负责将非结构化的 CAD 几何图形转换为 List<StructureSegment>。

### 3.1 输入与前置校验

**输入：DXF 文件路径。**

**校验：**

文件是否为 ASCII DXF 格式。

是否存在 LWPOLYLINE 实体。

多段线是否连续、无自相交。

### 3.2 解析逻辑 (Parsing Logic)

**顶点提取：读取 Polyline 的顶点列表  及对应的凸度 (Bulge)。**

**拓扑构建：**

**首节点：创建 Type = Inlet，坐标 。**

**遍历线段 (从  到 )：**

**弯管识别：若  到  之间 Bulge ：**

解析弧长 、弦长。

反算半径  和圆心角 。

创建 Type = Bend，存入  和 。

**直管/折管识别：若 Bulge ：**

暂存为直管段。

**折角检测：检查当前直管与上一段直管的方向向量。**

向量 ，。

若向量不共线，计算夹角 。

将前一段直管的“末端”与当前直管的“始端”合并为一个 Type = Fold 对象。

**尾节点：创建 Type = Outlet，坐标 。**

**坐标提取：返回首点 Y 坐标作为建议的 H_bottom_up (上游渠底高程)。**

### 3.3 输出

返回 List<StructureSegment>。

注意：此时弯管的阻力系数  尚未计算（因管径  未知），需标记为待计算状态。

## 4. 系数查询服务 (Coefficient Service)

负责封装《附录 L》中的静态数据表和插值算法。

### 4.1 渐变段系数库 (Table L.1.2)

提供 GetGradientCoeff(Type, IsInlet) 方法：

**输入：渐变段类型枚举，是否为进口。**

**输出：对应的  值 (例如：方头进口=0.30, 出口=0.75)。**

程序后端需硬编码以下键值对映射表。

：用于进口。

：用于出口。

### 4.2 弯管系数计算引擎 (Table L.1.4-3 & L.1.4-4)

提供 CalculateBendCoeff(R, D, Angle) 方法：

**计算比值：。**

**查表 L.1.4-3 ()：**

数据点：(0.5, 1.20), (1.0, 0.80) … (10.0, 0.24)。

逻辑：使用线性插值计算给定  的 。

**查表 L.1.4-4 ()：**

数据点：(20°, 0.40), (90°, 1.00) … (140°, 1.20)。

逻辑：使用线性插值计算给定  的 。

**计算结果：。**

**表 L.1.4-3      直角弯道损失系数表**

**表 L.1.4-4  任意角弯道损失系数修正系数γ值表**

## 5. 水力计算核心 (Hydraulic Core)

此模块为业务逻辑的核心，按顺序执行以下步骤。

### 步骤 1：几何设计 (Sizing)

**输入：。**

**计算：**

断面积 。

理论直径 。

可选：结果处理：程序保留该理论直径用于提示用户，并根据工程习惯提供取整选项（管径≤1m，按照0.05m取整；管径≤1.6m，按照0.1m取整；管径≤5m，按照0.2m取整；用户可自定义实际直径，但不得小于理论直径）。

实际流速 。

水力半径 。

### 步骤 2：阻力参数初始化 (Resistance Setup)

**沿程参数：**

输入： (糙率)。

计算谢才系数：。

**局部参数更新 (关键步骤)：**

遍历所有 StructureSegment。

**若为弯管 (Bend)：调用 CoefficientService.CalculateBendCoeff(Segment.R, D, Segment.Angle)，更新该段的系数。**

**若为进出口：调用 GetGradientCoeff 获取 。**

**其他段：使用用户预设值。**

### 步骤 3：水头损失求解 (Head Loss Calculation)

采用全线伯努利方程形式求解总水头损失 。

**统计总量：**

：所有直管、折管及弯管弧长的总和。

：除进出口外，所有中间段（弯管、折管、拦污栅等）的系数和。

：进口系数。

：出口系数。

**计算总损失  (依据伯努利方程推导)：**

### 步骤 4：校验与结果生成 (Verification)

**计算所需水位差： 利用能量方程，计算维持流速所需的上下游水位差。**

(注： 为渠道流速；若忽略动能差异，则 )

**生成结果对象 (Result Object)：**

Diameter ()

Velocity ()

Loss_Friction ()

Loss_Local ()

Total_Head_Loss ()

Is_Verified (Bool): 判断 。

Message: 校验通过或失败的具体提示信息。

## 6. 接口定义 (API Definition)

后端向前端暴露的主要接口方法：以C#为例，实际编程采用Python。

// 1. 解析 DXF
public List<StructureSegment> ParseDxf(string filePath);

// 2. 获取推荐的进出口系数
public double GetRecommendedGradientCoeff(GradientType type, bool isInlet);

// 3. 执行核心计算
public CalculationResult ExecuteCalculation(
    GlobalParameters globalParams, 
    List<StructureSegment> segments
);


### 表格 1

| 属性名 | 数据类型 | 说明 |
| --- | --- | --- |
| Q | Double | 设计流量 () |
| v_guess | Double | 拟定流速 () |
| H_up | Double | 上游水位 () |
| H_down | Double | 下游水位 () |
| Roughness_n | Double | 糙率 |
| Inlet_Type | Enum | 进口型式 (无/反弯/方头等) |
| Outlet_Type | Enum | 出口型式 |
| V_channel_in | Double | 进口渠道流速 |
| V_channel_out | Double | 出口渠道流速 |



### 表格 2

| 属性名 | 数据类型 | 说明 |
| --- | --- | --- |
| Type | Enum | 类型 (Inlet, Straight, Bend, Fold, TrashRack, Other, Outlet) |
| Length | Double | 长度 (直管长或折管左+右) |
| Radius | Double | 弯管半径  (仅弯管有效) |
| Angle | Double | 弯管圆心角 或 折管折角 (度) |
| Xi_User | Double | 用户手动输入的局部阻力系数 (若有) |
| Xi_Calc | Double | 程序计算出的局部阻力系数 (仅弯管/渐变段有效) |
| Coordinates | List | 几何坐标点集合 (用于绘图数据输出) |



### 表格 3

| 选项名称(UI显示) | 对应(进口系数默认值) | 对应(出口系数默认值) | 备注/适用条件(Tooltip提示) |
| --- | --- | --- | --- |
| 无 | 0.00 | 0.00 | 无渐变段 |
| 反弯扭曲面 | 0.10 | 0.20 | 最优水力性能 |
| 1/4圆弧 | 0.15 | 0.25 | 水面收敛角θ1/扩散角θ1 |
| 方头型 | 0.30 | 0.75 | 阻力最大 |
| 直线扭曲面 | 0.15(取均值) | 0.40(取均值) | 表中范围：进口0.05~0.30；出口0.30~0.50。θ1=150~370
θ2=100~170
注意：选中此项时，程序填入推荐值，但应高亮提示用户根据具体角度修正。 |



### 表格 4

| R/D₀ | 0.5 | 1.0 | 1.5 | 2.0 | 3.0 | 4.0 | 5.0 | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 | 11.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | 1.20 | 0.80 | 0.60 | 0.48 | 0.36 | 0.30 | 0.29 | 0.28 | 0.27 | 0.26 | 0.25 | 0.24 | 0.23 |



### 表格 5

| θ(°) | 5 | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 100 | 120 | 140 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Y | 0.125 | 0.23 | 0.40 | 0.55 | 0.65 | 0.75 | 0.83 | 0.88 | 0.95 | 1.00 | 1.05 | 1.13 | 1.20 |

