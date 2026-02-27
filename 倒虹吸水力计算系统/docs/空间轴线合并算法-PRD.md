# 空间轴线合并算法 — 产品需求规格文档

> **版本**: 3.0（基于代码全面同步重写，算法部分详尽化）  **日期**: 2026-02-27  
> **代码文件**：  
> - `倒虹吸水力计算系统/spatial_merger.py` — 三维空间合并引擎（`SpatialMerger` 类，779行）  
> - `倒虹吸水力计算系统/dxf_parser.py` — DXF 解析引擎（`DxfParser` 类，590行）  
> - `倒虹吸水力计算系统/siphon_models.py` — 数据模型定义（`PlanFeaturePoint`, `LongitudinalNode`, `SpatialNode`, `SpatialMergeResult`）  
> **跨模块**：  
> - `推求水面线/utils/siphon_extractor.py` — 从 `ChannelNode` 提取 `PlanFeaturePoint`（`SiphonDataExtractor._extract_plan_feature_points()`）  
> - `推求水面线/core/geometry_calc.py` — 方位角计算（`calculate_azimuth()` → `atan2(ΔX,ΔY)` → 测量方位角）

---

## 0. 背景与算法目标

倒虹吸管道是一条三维空间曲线，由两组**坐标系不同、独立采集**的数据描述：

| 数据源 | 坐标系 | 内容 | 来源 |
|---|---|---|---|
| **平面图** | X-Y 水平面 | IP 点坐标 (X,Y)、水平转角 α、平面圆曲线半径 R_h | 推求水面线表格 → `siphon_extractor` 提取 |
| **纵断面** | 桩号 S - 高程 Z | 变坡点 (S,Z)、坡角 β、竖曲线半径 R_v | AutoCAD DXF 文件 → `dxf_parser` 解析 |

**核心前提**：桩号 s（chainage）是**平面轴线弧长参数**，即沿水平面轴线的累计弧长。
- 直线段上：`Δs = 弦长 = √(ΔX² + ΔY²)`
- 圆弧段上：`Δs = R_h · Δφ`（弧长），**不等于** XY 弦长

**算法目标**：
1. 按桩号将平面 IP 点和纵断面变坡点合并为统一的三维节点序列 `SpatialNode[]`
2. 为每个节点计算精确的空间坐标 (X, Y, Z)、前后方位角 α、前后坡角 β
3. 计算全线**空间总长度** L_spatial = Σ√(Δs² + ΔZ²)
4. 计算每个转弯节点的**三维空间转角** θ_3D = arccos(T_before · T_after)
5. 对重叠弯道（平面+纵断面同位置转弯），合成**有效曲率半径** R_3D
6. 输出 `SpatialMergeResult` 供下游水力计算（沿程损失 hf + 局部损失 hj）

---

## 1. 数据结构说明

### 1.1 PlanFeaturePoint（平面 IP 特征点）

**定义位置**：`siphon_models.py` 第350–411行

**来源**：`siphon_extractor._extract_plan_feature_points()` 遍历 `SiphonGroup.rows`（`ChannelNode` 列表），逐行提取 `station_MC`、`x`、`y`、`azimuth`、`turn_radius`、`turn_angle`、`ip_number`，构建为 `dict` 列表存入 `SiphonGroup.plan_feature_points`。UI 面板在 `set_params()` 中通过 `PlanFeaturePoint.from_dict()` 反序列化为对象。

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `chainage` | float | m | MC 桩号（平面轴线弧长参数）。ARC 型时 = QZ 弧中点桩号 |
| `x` | float | m | 工程坐标 X（东方向） |
| `y` | float | m | 工程坐标 Y（北方向） |
| `azimuth_meas_deg` | float | 度 | **测量方位角**（正北=0°，顺时针），0\~360°。由 `geometry_calc.calculate_azimuth()` 输出的 `atan2(ΔX,ΔY)` 转换。**仅用于 UI 显示和上游数据传递**，不参与几何公式 |
| `azimuth_math_rad` | @property float | 弧度 | **数学方位角**（正东=0°，逆时针）。计算属性，公式：`α_math = π/2 - radians(azimuth_meas_deg)`，归一化到 (-π, π]。**T 向量公式必须使用此字段** |
| `turn_angle` | float | 度 | 水平转角（首尾 IP 为 0） |
| `turn_radius` | float | m | 平面圆曲线半径 R_h |
| `turn_type` | TurnType | — | `ARC`（有半径圆弧）/ `FOLD`（折线）/ `NONE`（无转弯） |
| `ip_index` | int | — | IP 编号（供 UI 显示，计算不使用） |

**`azimuth` 向后兼容属性**（第379–381行）：返回 `azimuth_meas_deg`。新代码应显式使用 `azimuth_meas_deg` 或 `azimuth_math_rad`。

**`from_dict()` 字段映射**（第396–411行）：JSON 键 `'azimuth'` → 映射到 `azimuth_meas_deg`。

> **角度体系硬隔离约束**：
> - 上游 `siphon_extractor` 和 `geometry_calc` 输出的方位角是**测量方位角**（`atan2(ΔX,ΔY)`，正北=0°，顺时针）。
> - 三维切向量公式 `T = (cosβ·cosα, cosβ·sinα, sinβ)` 要求 α 为**数学方位角**（`atan2(ΔY,ΔX)`，正东=0°，逆时针）。
> - 字段名 `azimuth_meas_deg` 与 `azimuth_math_rad` 在数据结构层面强制区分，不靠注释记忆。
> - 转换公式：`α_math_rad = π/2 - radians(α_meas_deg)`，归一化到 (-π, π]。

> **ARC 型桩号定义约束**：
> - 当 `turn_type == ARC` 时，`pp.chainage` 必须等于该弧中点 QZ 的桩号（而非交点 PI 的桩号）。
> - `pp.x`, `pp.y` 对于 ARC 型仍存储 IP（交点）坐标（用于计算 BC/EC/弧心几何），但在合并时使用 QZ 坐标。
> - 这保证了 `chainage ↔ (X,Y)` 在轴线上的一致性：节点的桩号 s 与其空间坐标 (X(s), Y(s)) 指向同一个几何位置。

### 1.2 LongitudinalNode（纵断面变坡点）

**定义位置**：`siphon_models.py` 第299–347行

**来源**：`dxf_parser._build_longitudinal_nodes()` 解析 DXF LWPOLYLINE 多段线的顶点和凸度。

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `chainage` | float | m | DXF 顶点 X + chainage_offset |
| `elevation` | float | m | DXF 顶点 Y（高程） |
| `vertical_curve_radius` | float | m | 竖曲线半径 R_v，0 表示折线型或无转弯 |
| `turn_type` | TurnType | — | `ARC`（竖曲线）/ `FOLD`（折线变坡）/ `NONE`（无转弯） |
| `turn_angle` | float | 度 | 竖向转角（前后坡角差绝对值） |
| `slope_before` | float | 弧度 | 进入该点的坡角 β，由 `atan2(ΔZ, Δs)` 或弧心公式计算 |
| `slope_after` | float | 弧度 | 离开该点的坡角 β |
| `arc_center_s` | Optional[float] | m | 竖曲线弧心桩号坐标 Sc（仅 ARC 型有效，供 Z 精确插值） |
| `arc_center_z` | Optional[float] | m | 竖曲线弧心高程坐标 Zc（仅 ARC 型有效） |

### 1.3 SpatialNode（三维空间节点）

**定义位置**：`siphon_models.py` 第414–447行

由 `SpatialMerger` 按桩号合并 `PlanFeaturePoint` 和 `LongitudinalNode` 后生成。

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `chainage` | float | m | 桩号 |
| `x`, `y`, `z` | float | m | 三维空间坐标 |
| `azimuth_before` | float | 度 | 节点前方位角（**数学方位角**，正东=0°，逆时针） |
| `azimuth_after` | float | 度 | 节点后方位角（同上） |
| `slope_before` | float | 弧度 | 节点前坡角 β |
| `slope_after` | float | 弧度 | 节点后坡角 β |
| `has_plan_turn` | bool | — | 是否有平面转弯 |
| `has_long_turn` | bool | — | 是否有纵断面转弯 |
| `plan_turn_radius` | float | m | 平面转弯半径 R_h |
| `long_turn_radius` | float | m | 纵断面竖曲线半径 R_v |
| `plan_turn_angle` | float | 度 | 平面转角 |
| `long_turn_angle` | float | 度 | 纵断面转角 |
| `plan_turn_type` | TurnType | — | 平面转弯类型 |
| `long_turn_type` | TurnType | — | 纵断面转弯类型 |
| `spatial_turn_angle` | float | 度 | θ_3D（空间转角，由 `_compute_spatial_angles` 计算） |
| `effective_radius` | float | m | 有效半径（查表用，可能是 R_h、R_v 或合成的 R_3D） |
| `effective_turn_type` | TurnType | — | 有效转弯类型（查表用） |
| `has_turn` | @property bool | — | `has_plan_turn or has_long_turn` |

### 1.4 SpatialMergeResult（合并计算结果）

**定义位置**：`siphon_models.py` 第450–464行

| 字段 | 类型 | 说明 |
|---|---|---|
| `nodes` | List[SpatialNode] | 三维空间节点序列 |
| `total_spatial_length` | float | 空间总长度 L_spatial (m) |
| `segment_lengths` | List[float] | 各段空间长度 |
| `xi_spatial_bends` | float | 空间弯道损失系数总和（预留，实际由 `siphon_hydraulics` 按管径 D 逐弯查表计算） |
| `computation_steps` | List[str] | 详细计算过程文本 |
| `has_plan_data` | bool | 是否有平面数据 |
| `has_longitudinal_data` | bool | 是否有纵断面数据 |

---

## 2. DXF 纵断面解析

**入口函数**：`DxfParser.parse_longitudinal_profile(file_path, chainage_offset)` → `(List[LongitudinalNode], str)`

### 2.1 DXF 多段线读取（第311–380行）

```python
# 1. 用 ezdxf 打开 DXF 文件
doc = ezdxf.readfile(file_path)
msp = doc.modelspace()

# 2. 查找多段线（优先 LWPOLYLINE，其次 POLYLINE）
polylines = list(msp.query('LWPOLYLINE'))
if not polylines:
    polylines = list(msp.query('POLYLINE'))

# 3. 取第一条多段线，提取顶点 (x,y) 和凸度 bulge
polyline = polylines[0]
for point in polyline.get_points(format='xyseb'):
    x, y, start_width, end_width, bulge = point
    vertices.append((x, y))     # x=桩号(局部), y=高程
    bulges.append(bulge)         # bulge=0 直线, ≠0 圆弧
```

**多段线坐标约定**：
- X 坐标 = 桩号（局部值，需加 `chainage_offset` 对齐到实际 MC 桩号）
- Y 坐标 = 高程 (m)
- **X:Y 比例必须 1:1**（真实坐标），否则 R_v 反算将产生偏差

### 2.2 弧段参数反算（第382–410行，公式亦见第437–450行）

AutoCAD 凸度定义：`bulge = tan(θ/4)`，θ = 圆心角。

```
θ (rad) = 4 × atan(|bulge|)          ← |bulge| 仅用于圆心角大小
chord   = √(Δs² + ΔZ²)              ← Δs=桩号差, ΔZ=高程差
R_v     = chord / (2 × sin(θ/2))     ← 反算竖曲线半径
arc_len = R_v × θ                    ← 竖曲线弧长
```

**弧心坐标计算** `_compute_arc_center(p1, p2, bulge)` → `(Sc, Zc)`（第382–400行）：

```python
S1, Z1 = p1;  S2, Z2 = p2
dS, dZ = S2 - S1, Z2 - Z1
chord = √(dS² + dZ²)
angle_rad = 4 × atan(|bulge|)
radius = chord / (2 × sin(angle_rad/2))

# 弦中点
Sm, Zm = (S1+S2)/2, (Z1+Z2)/2

# 弦的单位法向量（逆时针旋转90°）
perp_S = -dZ / chord
perp_Z =  dS / chord

# 弧心到弦中点的距离（勾股定理）
d = √(radius² - (chord/2)²)

# bulge 符号决定弧心在弦的哪一侧
sign = +1 if bulge > 0 else -1    # bulge>0=CCW, <0=CW
Sc = Sm + sign × d × perp_S
Zc = Zm + sign × d × perp_Z
```

> **bulge 符号保留**：`bulge>0` = 逆时针弧（弧心在弦左侧），`bulge<0` = 顺时针弧（弧心在弦右侧）。
> `|bulge|` 只用于计算 θ 和 R_v 大小；`sign(bulge)` 必须保留用于 `_compute_arc_center` 判断弧心在弦的哪一侧，
> 进而决定竖曲线是凹形（谷底弧，典型倒虹吸）还是凸形（驼峰弧）。这个信息不能从半径大小恢复。

**弧端切线坡角** `_arc_tangent_slope(S, Z, Sc, Zc)` → `β (rad)`（第402–410行）：

```python
# 圆上点 (S,Z) 处的切线坡角
# 微积分推导：圆方程 (S-Sc)² + (Z-Zc)² = R²
# 隐函数求导：2(S-Sc) + 2(Z-Zc)·dZ/dS = 0
# 故 dZ/dS = -(S-Sc)/(Z-Zc) = tan(β)
# 必须经 atan 转换为弧度角 β：
denom = Z - Zc
slope = 0.0 if |denom| < 1e-9 else atan(-(S - Sc) / denom)
```

> **不能用原始比值 `-(S-Sc)/(Z-Zc)`**：该值是 `tan(β)`（无量纲）而非 `β`（弧度）。若直接赋给 slope 字段，后续 `cos(β)`/`sin(β)` 会把 tan 值当弧度代入，导致三角函数值完全错误。
>
> **不能用 `atan2(-(S-Sc), Z-Zc)`**：当弧在弧心下方（谷底弧，典型倒虹吸）时 `Z-Zc < 0`（Z 点在弧心下方），`atan2` 的第二参数（x 分量）为负，会对结果加 ±π 导致完全错误。

### 2.3 变坡点节点表构建（`_build_longitudinal_nodes`，第412–550行）

分为**三步**：

#### 第1步：段属性计算（第428–457行）

遍历相邻顶点对 `(p1, p2)`，判断是直线段还是圆弧段：

```python
for i in range(n - 1):
    p1, p2 = vertices[i], vertices[i+1]
    bulge = bulges[i]
    chord = √((p2[0]-p1[0])² + (p2[1]-p1[1])²)

    if |bulge| > 1e-8 and chord > 1e-6:
        # 圆弧段
        angle_rad = 4 × atan(|bulge|)
        radius = chord / (2 × sin(angle_rad/2))
        Sc, Zc = _compute_arc_center(p1, p2, bulge)
        slope_start = _arc_tangent_slope(p1[0], p1[1], Sc, Zc)
        slope_end   = _arc_tangent_slope(p2[0], p2[1], Sc, Zc)
        → 存储 {type:'arc', p1, p2, radius, arc_angle_deg, Sc, Zc, slope_start, slope_end}
    else:
        # 直线段
        slope_angle = atan2(Δy, Δx)
        → 存储 {type:'line', p1, p2, slope_angle}
```

#### 第2步：提取变坡点（第459–539行）

**通用规则**：只要曲率发生突变（1/R 从 0 变为非 0，或从 R₁ 变为 R₂），或切线出现不连续，就生成节点。

```python
# 起点节点（NONE 类型）
first_slope = seg[0].slope_angle if seg[0].type=='line' else seg[0].slope_start
nodes.append(LongitudinalNode(chainage=x0+offset, elevation=y0,
    turn_type=NONE, slope_after=first_slope))

# 遍历段序列
while i < len(segments_info):
    seg = segments_info[i]
    
    if seg.type == 'line':
        if next_seg.type == 'line':
            # 线→线：坡角差 > 0.5° → FOLD 折点
            angle_diff = |degrees(slope2 - slope1)|
            if angle_diff > 0.5:
                nodes.append(LongitudinalNode(
                    chainage=seg.p2.x + offset,
                    elevation=seg.p2.y,
                    turn_type=FOLD,
                    turn_angle=angle_diff,
                    slope_before=slope1,
                    slope_after=slope2))
        # 线→弧：由弧段处理
        i += 1
    
    elif seg.type == 'arc':
        # 确定进入弧段前的坡角
        if i > 0:
            slope_before = prev_seg.slope_angle if prev.type=='line' else prev.slope_end
        else:
            slope_before = seg.slope_start    # ← 首段边界退化：用弧自身起始坡角
        # 确定离开弧段后的坡角
        if i+1 < len(segments_info):
            slope_after = next_seg.slope_angle if next.type=='line' else next.slope_start
        else:
            slope_after = seg.slope_end        # ← 末段边界退化：用弧自身终止坡角
        turn_angle = |degrees(slope_after - slope_before)|
        
        # 弧起点节点（ARC 类型，存储弧心坐标供 Z 插值）
        nodes.append(LongitudinalNode(
            chainage=seg.p1.x + offset,
            elevation=seg.p1.y,
            turn_type=ARC,
            vertical_curve_radius=seg.radius,
            turn_angle=turn_angle if turn_angle > 0.1 else seg.arc_angle_deg,
            #          ↑ 退化保护：当前后坡角差极小时，退化为DXF圆弧的圆心角
            slope_before=slope_before,
            slope_after=slope_after,
            arc_center_s=seg.Sc + offset,     ← 供 _interpolate_long() 精确Z插值
            arc_center_z=seg.Zc))
        
        # 弧终点节点（NONE 参考点，供区间端点插值用）
        nodes.append(LongitudinalNode(
            chainage=seg.p2.x + offset,
            elevation=seg.p2.y,
            turn_type=NONE,
            slope_before=seg.slope_end,
            slope_after=seg.slope_end))
        i += 1

# 终点节点（NONE 类型，避免重复）
if |nodes[-1].chainage - last_chainage| > 0.01:
    nodes.append(LongitudinalNode(chainage=last_chainage, elevation=yn,
        turn_type=NONE, slope_before=last_slope))
```

**变坡点生成规则汇总**：

| 情形 | 生成节点类型 | slope_before | slope_after |
|---|---|---|---|
| 直线→直线，坡角差>0.5° | FOLD（在前段末端） | 前段坡角 | 后段坡角 |
| 直线→圆弧 | ARC（在弧起点） | 前段坡角 | 下一段（线或弧）的起始坡角 |
| 圆弧→直线 | NONE（弧终点，参考点） | 弧终切线坡角 | 弧终切线坡角 |
| 圆弧→圆弧（S形曲线） | ARC（第二弧起点） | 第一弧终切线坡角 | 第二弧之后的段起始坡角 |
| 首节点 | NONE | 0 | 第一段切线坡角 |
| 末节点 | NONE | 最后段切线坡角 | 0 |

#### 第3步：排序去重（第541–550行）

```python
nodes.sort(key=lambda nd: nd.chainage)
merged = [nodes[0]]
for nd in nodes[1:]:
    if |nd.chainage - merged[-1].chainage| < 0.01:  # 10mm 去重
        # 桩号重复时，保留转弯信息更丰富的节点
        if nd.turn_type != NONE and merged[-1].turn_type == NONE:
            merged[-1] = nd
    else:
        merged.append(nd)
```

---

## 3. 三种合并模式

**入口函数**：`SpatialMerger.merge_and_compute(plan_points, long_nodes, pipe_diameter, verbose)` → `SpatialMergeResult`

```python
has_plan = bool(plan_points) and len(plan_points) >= 2
has_long = bool(long_nodes)  and len(long_nodes)  >= 2

# 模式 A：has_plan AND has_long → 完整三维合并（主路径）
#   调用 _merge_full_3d()
# 模式 B：has_plan only → β=0, Z=0, θ_3D=水平转角
#   调用 _merge_plan_only()
# 模式 C：has_long only → α=0, Y=0, X=桩号, θ_3D=竖向转角
#   调用 _merge_long_only()
# 无数据：直接返回空结果
```

### 3.1 模式 B：仅平面数据（`_merge_plan_only`，第231–273行）

```python
plan_geom = _build_plan_geometry(plan_points)  # 预计算圆弧几何
for i, pp in enumerate(plan_points):
    g = plan_geom[i]
    # ARC 型使用精确弧中点 QZ 坐标
    if pp.turn_type == ARC and g['qz'] is not None:
        x, y = g['qz']
    else:
        x, y = pp.x, pp.y
    
    node = SpatialNode(chainage=pp.chainage, x=x, y=y, z=0.0,
                       slope_before=0.0, slope_after=0.0)
    # 标记转弯
    if pp.turn_angle > 0.1 and pp.turn_type != NONE:
        node.has_plan_turn = True; ...

# 填充方位角（坐标差推算 + ARC 精确切线覆盖）
_fill_azimuths_from_plan(spatial_nodes, plan_points)
for nd in spatial_nodes:
    if nd.has_plan_turn and nd.plan_turn_type == ARC:
        g = plan_geom_dict[round(nd.chainage, 3)]
        nd.azimuth_before = degrees(atan2(g['d_in'][1], g['d_in'][0]))
        nd.azimuth_after  = degrees(atan2(g['d_out'][1], g['d_out'][0]))
```

### 3.2 模式 C：仅纵断面数据（`_merge_long_only`，第275–302行）

```python
# 假设平面走向为正东方向（α=0），X=桩号，Y=0
for ln in long_nodes:
    node = SpatialNode(chainage=ln.chainage,
                       x=ln.chainage, y=0.0, z=ln.elevation,
                       azimuth_before=0.0, azimuth_after=0.0,
                       slope_before=ln.slope_before, slope_after=ln.slope_after)
    if ln.turn_angle > 0.1 and ln.turn_type != NONE:
        node.has_long_turn = True; ...
```

---

## 4. 完整三维合并（模式 A）—— 逐步算法

### 步骤 1：桩号并集（`_merge_full_3d` 第148–167行）

```python
# 构建平面字典（桩号→PlanFeaturePoint），精度1mm
plan_dict = { round(pp.chainage, 3): pp  for pp in plan_points }

# 预计算所有圆弧型IP的精确几何（BC/EC/弧心/QZ/切线方向）
plan_geom = _build_plan_geometry(plan_points)
plan_geom_dict = { round(plan_points[i].chainage, 3): plan_geom[i]
                   for i in range(len(plan_points)) }

# 构建纵断面字典（桩号→LongitudinalNode）
# v2.0: 不做桩号吸附/平移，直接按原始桩号
long_dict = { round(ln.chainage, 3): ln  for ln in long_nodes }

# 桩号并集，排序
all_stations = sorted(set(list(plan_dict.keys()) + list(long_dict.keys())))
```

> **v2.0 变更**：v1.x 的"吸附"步骤会把纵断面弯道桩号强行改为平面 IP 桩号，
> 这在数学上是把一个事件平移到另一个桩号，会导致：
> (1) 三维节点序列几何形状改变；(2) θ_3D、R_3D 被人为制造或消除；(3) 局部损失分配位置失真。
>
> **严格做法**：不改任何 key（桩号）。合并只做"桩号并集 + 同桩号近似去重（1mm）"。

### 步骤 2：空间坐标赋值（第173–221行）

对每个桩号 s，分别从平面和纵断面获取坐标：

#### 2a. X, Y 平面坐标

```python
for s in all_stations:
    pp = plan_dict.get(s)    # 精确命中平面IP？
    
    if pp:
        g = plan_geom_dict.get(s, {})
        if pp.turn_type == ARC and g.get('qz') is not None:
            x, y = g['qz']       # ← 精确弧中点坐标（QZ），避免 IP 坐标的外距偏差
        else:
            x, y = pp.x, pp.y    # ← 折管 IP / 首尾 IP 直接用坐标
        azimuth = pp.azimuth      # ← 临时初始值，步骤4会覆盖
    else:
        x, y, azimuth = _interpolate_plan(plan_points, s, plan_geom)
```

**平面插值函数** `_interpolate_plan(plan_points, s, plan_geom)` → `(X, Y, azimuth_deg)`（第377–449行）：

> **返回值说明**：第三个返回值的角度体系取决于代码路径——精确弧段/切线段插值路径返回**数学方位角**（`atan2(ΔY,ΔX)`），
> 而边界退化和 IP-IP 线性退化路径返回 `pp.azimuth`（**测量方位角**）。这不影响最终结果，因为步骤4（`_fill_adjacent_angles`）
> 会用坐标差重新计算所有节点的方位角，全部覆盖为数学方位角。此处返回值仅作为步骤2的临时初始值。

```python
# 边界处理
if s <= plan_points[0].chainage: return plan_points[0]的坐标
if s >= plan_points[-1].chainage: return plan_points[-1]的坐标

if plan_geom is None:
    # 退化模式：IP-IP 线性插值（向后兼容）
    for i in range(n-1):
        if p1.chainage <= s <= p2.chainage:
            t = (s - p1.chainage) / (p2.chainage - p1.chainage)
            return lerp(p1, p2, t)

# 精确模式（有 plan_geom）：

# 1. 弧段内精确插值
for i in range(n):
    g = plan_geom[i]
    if g['bc_chainage'] is None: continue
    if g['bc_chainage'] <= s <= g['ec_chainage']:
        # 在圆弧段内：沿圆弧方程精确计算
        delta = (s - g['bc_chainage']) / pp.turn_radius   # 弧度偏转角
        pt = _arc_point(g['center'], R, g['bc'], delta, g['left_turn'])
        # 切线方向 = 径向方向 ± 90°
        theta_r = atan2(pt[1]-g['center'][1], pt[0]-g['center'][0])
        az = theta_r + π/2 if left_turn else theta_r - π/2
        return pt[0], pt[1], degrees(az)

# 2. 切线段精确插值（EC_i → BC_{i+1}）
for i in range(n-1):
    # 切线段起点 = 前一个弧的EC（或首IP坐标）
    ts_pt = g1['ec'] if g1['ec'] is not None else (p1.x, p1.y)
    ts_ch = g1['ec_chainage'] if g1['ec_chainage'] is not None else p1.chainage
    # 切线段终点 = 下一个弧的BC（或下一IP坐标）
    te_pt = g2['bc'] if g2['bc'] is not None else (p2.x, p2.y)
    te_ch = g2['bc_chainage'] if g2['bc_chainage'] is not None else p2.chainage
    if ts_ch <= s <= te_ch:
        az = atan2(te_pt[1]-ts_pt[1], te_pt[0]-ts_pt[0])
        t = (s - ts_ch) / (te_ch - ts_ch)
        return lerp(ts_pt, te_pt, t), degrees(az)
```

#### 2b. Z 高程坐标

```python
    ln = long_dict.get(s)    # 精确命中纵断面节点？
    
    if ln:
        z = ln.elevation
        slope = ln.slope_before if ln.slope_before != 0 else ln.slope_after
    else:
        z, slope = _interpolate_long(long_nodes, s)
```

**纵断面插值函数** `_interpolate_long(long_nodes, s)` → `(Z, slope_angle)`（第451–502行）：

```python
# 边界处理
if s <= long_nodes[0].chainage: return (node[0].elevation, node[0].slope_after)
if s >= long_nodes[-1].chainage: return (node[-1].elevation, node[-1].slope_before)

for i in range(len(long_nodes)-1):
    n1, n2 = long_nodes[i], long_nodes[i+1]
    if n1.chainage <= s <= n2.chainage:
        ds = n2.chainage - n1.chainage
        if ds < 1e-6: return n1.elevation, n1.slope_after
        
        # ===== 竖曲线圆弧精确插值（v2.1 漏洞A修复）=====
        if (n1.turn_type == ARC and 
            n1.arc_center_s is not None and 
            n1.arc_center_z is not None and 
            n1.vertical_curve_radius > 0):
            
            Sc = n1.arc_center_s      # 弧心桩号坐标
            Zc = n1.arc_center_z      # 弧心高程坐标
            Rv = n1.vertical_curve_radius
            r2 = Rv² - (s - Sc)²
            
            if r2 >= 0:
                # 符号取决于起点在弧心的上方还是下方
                sign = +1.0 if n1.elevation > Zc else -1.0
                z = Zc + sign × √(r2)
                
                # 坡角：tan(β) = -(s-Sc)/(z-Zc)，必须经 atan 转换
                denom = z - Zc
                slope = 0.0 if |denom| < 1e-9 else atan(-(s-Sc)/denom)
                return z, slope
            # r2 < 0 说明 s 超出弧段范围，退化为线性
        
        # ===== 直线段：线性插值 =====
        t = (s - n1.chainage) / ds
        z = n1.elevation + t × (n2.elevation - n1.elevation)
        slope = atan2(n2.elevation - n1.elevation, ds)
        return z, slope
```

### 步骤 3：转弯标记（第206–221行）

```python
# 平面转弯标记
if pp and pp.turn_angle > 0.1 and pp.turn_type != NONE:
    node.has_plan_turn = True
    node.plan_turn_radius = pp.turn_radius
    node.plan_turn_angle = pp.turn_angle
    node.plan_turn_type = pp.turn_type

# 纵断面转弯标记（精确坡角覆盖插值初始值）
if ln and ln.turn_angle > 0.1 and ln.turn_type != NONE:
    node.has_long_turn = True
    node.long_turn_radius = ln.vertical_curve_radius
    node.long_turn_angle = ln.turn_angle
    node.long_turn_type = ln.turn_type
    node.slope_before = ln.slope_before    # ← 用纵断面精确坡角覆盖
    node.slope_after = ln.slope_after
```

### 步骤 4：方位角与坡角填充（`_fill_adjacent_angles`，第558–638行）

此步骤用坐标差和**桩号差**覆盖所有节点的方位角和坡角（覆盖步骤2的临时初始值），然后对转弯节点执行两道**精确保护覆盖**，确保不会用割线近似替代解析精确值。

#### 4a. 坐标差推算（通用，第577–613行）

```python
n = len(spatial_nodes)
for i in range(n):
    nd = spatial_nodes[i]
    
    # === 后方位角和坡角（当前→下一个节点）===
    if i < n-1:
        nx = spatial_nodes[i+1]
        dx = nx.x - nd.x;  dy = nx.y - nd.y;  dz = nx.z - nd.z
        ds = nx.chainage - nd.chainage    # 桩号差（平面弧长参数增量）
        dh = √(dx² + dy²)                # XY 弦长（仅用于方位角判断 dh>1e-6）
        
        if dh > 1e-6:
            nd.azimuth_after = degrees(atan2(dy, dx))    # 数学方位角（度）
        if |ds| > 1e-6:
            nd.slope_after = atan2(dz, ds)               # 坡角（弧度）← 用桩号差！
    
    # === 前方位角和坡角（上一个→当前节点）===
    if i > 0:
        px = spatial_nodes[i-1]
        dx = nd.x - px.x;  dy = nd.y - px.y;  dz = nd.z - px.z
        ds = nd.chainage - px.chainage    # 桩号差
        dh = √(dx² + dy²)
        
        if dh > 1e-6:
            nd.azimuth_before = degrees(atan2(dy, dx))
        if |ds| > 1e-6:
            nd.slope_before = atan2(dz, ds)

# 首尾节点补齐
spatial_nodes[0].azimuth_before = spatial_nodes[0].azimuth_after
spatial_nodes[0].slope_before   = spatial_nodes[0].slope_after
spatial_nodes[-1].azimuth_after  = spatial_nodes[-1].azimuth_before
spatial_nodes[-1].slope_after    = spatial_nodes[-1].slope_before
```

> **v2.0 关键变更（坡角 β）**：
> - v1.x 用 `dH = √(ΔX²+ΔY²)`（XY 弦长）计算 `β = arctan(ΔZ/dH)`。
>   在圆弧段上，XY 弦长 < 弧长（桩号差 Δs），导致 `ΔZ/dH` 偏大，β 系统性偏陡。
> - v2.0 改用 `Δs = s[i+1] - s[i]`（桩号差 = 平面弧长参数增量），
>   `β = atan2(ΔZ, Δs)`，与纵断面 Z(s) 的定义严格一致，也与后续曲率推导中"s 为弧长参数"的假设一致。
> - before 和 after 分别用各自方向的 Δs 计算（不共用同一个 dH）。

#### 4b. 纵断面转弯精确坡角覆盖（第615–627行）

```python
for nd in spatial_nodes:
    if nd.has_long_turn:
        # 在全部 long_nodes 中找桩号差 ≤ SNAP_TOLERANCE(2.0m) 的最近匹配
        best_ln = None;  best_dist = ∞
        for ln in long_nodes:
            dist = |ln.chainage - nd.chainage|
            if dist <= SNAP_TOLERANCE and dist < best_dist:
                best_dist = dist;  best_ln = ln
        if best_ln is not None:
            nd.slope_before = best_ln.slope_before    # ← 精确坡角（弧心公式），优于坐标差近似
            nd.slope_after  = best_ln.slope_after
```

#### 4c. 圆弧型平面转弯精确方位角覆盖（第629–638行）

```python
if plan_geom_dict:
    for nd in spatial_nodes:
        if nd.has_plan_turn and nd.plan_turn_type == ARC:
            g = plan_geom_dict.get(round(nd.chainage, 3))
            if g and g.get('d_in') is not None:
                # d_in = IP前一段的单位方向向量（精确切线方向）
                # d_out = IP后一段的单位方向向量（精确切线方向）
                nd.azimuth_before = degrees(atan2(g['d_in'][1],  g['d_in'][0]))
                nd.azimuth_after  = degrees(atan2(g['d_out'][1], g['d_out'][0]))
```

> **坐标系约束**：工程坐标 X=东、Y=北，`atan2(dy,dx)` 得**数学方位角**（正东=0°，逆时针）。
> `_fill_adjacent_angles` 输出的 azimuth_before/after 均为**数学方位角（度）**，
> 与 T 向量公式 `(cosβ·cosα, cosβ·sinα, sinβ)` 中 α 的定义自洽。

### 步骤 1b：复合弯道事件检测（`_detect_composite_events`，第504–556行）

此步骤在步骤4之后执行（代码第227行），独立于坐标赋值和角度填充，仅标记近邻弯道事件用于 R_3D 合成和局损查表。

```python
EVENT_WINDOW = SNAP_TOLERANCE    # 2.0m（类常量，可配置）

for nd in spatial_nodes:
    # === 情况1：有平面转弯但无纵断面转弯 ===
    if nd.has_plan_turn and not nd.has_long_turn:
        best_ln = None;  best_dist = ∞
        for ln in long_nodes:
            if ln.turn_angle <= 0.1 or ln.turn_type == NONE: continue
            dist = |ln.chainage - nd.chainage|
            if dist <= EVENT_WINDOW and dist < best_dist:
                best_dist = dist;  best_ln = ln
        if best_ln is not None:
            nd.has_long_turn = True    # ← 标记复合事件
            nd.long_turn_radius = best_ln.vertical_curve_radius
            nd.long_turn_angle  = best_ln.turn_angle
            nd.long_turn_type   = best_ln.turn_type

    # === 情况2：有纵断面转弯但无平面转弯 ===
    if nd.has_long_turn and not nd.has_plan_turn:
        best_pp = None;  best_dist = ∞
        for pp in plan_points:
            if pp.turn_angle <= 0.1 or pp.turn_type == NONE: continue
            dist = |pp.chainage - nd.chainage|
            if dist <= EVENT_WINDOW and dist < best_dist:
                best_dist = dist;  best_pp = pp    # ← 选最近的（非第一个）
        if best_pp is not None:
            nd.has_plan_turn = True    # ← 标记复合事件
            nd.plan_turn_radius = best_pp.turn_radius
            nd.plan_turn_angle  = best_pp.turn_angle
            nd.plan_turn_type   = best_pp.turn_type
```

> 复合事件保留原始桩号用于几何插值与长度积分，合成事件信息仅用于 R_3D 合成和局损查表。

---

## 5. 平面圆弧精确几何预计算

### 5.1 `_build_plan_geometry`（第308–361行）

为每个圆弧型IP点（ARC，非首尾）预计算精确几何参数：

```python
for i in range(1, n-1):        # 跳过首尾IP
    pp = plan_points[i]
    if pp.turn_type != ARC or pp.turn_angle < 0.1 or pp.turn_radius <= 0:
        continue
    
    pp_prev = plan_points[i-1]
    pp_next = plan_points[i+1]
    
    # 入/出切线单位向量
    d_in  = normalize(pp - pp_prev)      # (dx_in/len_in,  dy_in/len_in)
    d_out = normalize(pp_next - pp)      # (dx_out/len_out, dy_out/len_out)
    
    R = pp.turn_radius
    α_rad = radians(pp.turn_angle)
    T = R × tan(α_rad / 2)              # 切线长
    L_arc = R × α_rad                   # 弧长
    
    # 始曲点 BC 和终曲点 EC
    bc = (pp.x - T × d_in[0],  pp.y - T × d_in[1])
    ec = (pp.x + T × d_out[0], pp.y + T × d_out[1])
    
    # 转向判断：d_in × d_out 的 Z 分量 > 0 → 左转（逆时针）
    left_turn = (d_in[0] × d_out[1] - d_in[1] × d_out[0]) > 0
    
    # 弧心：从 BC 沿入切线法向量偏移 R
    if left_turn:
        center = (bc[0] - R × d_in[1], bc[1] + R × d_in[0])    # 左侧法向
    else:
        center = (bc[0] + R × d_in[1], bc[1] - R × d_in[0])    # 右侧法向
    
    # 桩号范围（pp.chainage 是 QZ 弧中点桩号）
    bc_chainage = pp.chainage - L_arc / 2.0
    ec_chainage = pp.chainage + L_arc / 2.0
    
    # QZ 弧中点精确坐标
    qz = _arc_point(center, R, bc, α_rad/2.0, left_turn)
    
    → 存储 {bc, ec, center, qz, bc_chainage, ec_chainage, d_in, d_out, left_turn}
```

### 5.2 `_arc_point`（第363–375行）

从始曲点 BC 沿圆弧行进 delta 弧度，返回弧上坐标：

```python
def _arc_point(center, R, bc, delta, left_turn):
    theta_bc = atan2(bc[1] - center[1], bc[0] - center[0])    # BC 相对弧心的极角
    theta = theta_bc + delta if left_turn else theta_bc - delta  # 逆时针+/顺时针-
    return (center[0] + R × cos(theta),
            center[1] + R × sin(theta))
```

---

## 6. 空间长度计算（第91–113行）

```python
total_L = 0.0
for i in range(len(spatial_nodes) - 1):
    n1 = spatial_nodes[i]
    n2 = spatial_nodes[i+1]
    ds = n2.chainage - n1.chainage    # 桩号差（平面弧长参数增量）
    dz = n2.z - n1.z                  # 高程差
    L_seg = √(ds² + dz²)             # 空间弧长微分的离散近似
    total_L += L_seg

result.total_spatial_length = total_L
```

**数学依据**：空间弧长微分 `dℓ = √(1 + (dZ/ds)²) ds`，离散化为 `Δℓ ≈ √(Δs² + ΔZ²)`。

> **v2.0 变更**：
> - v1.x 用 `√(ΔX²+ΔY²+ΔZ²)`（3D 弦长）。在圆弧段上，ΔX²+ΔY² 是平面弦长平方（< 弧长平方），导致空间长度系统性偏短。
> - v2.0 改用 `√(Δs²+ΔZ²)`，其中 Δs 是桩号差（= 平面弧长参数增量），精确表示水平路径长度。
> - 更高精度选项：对纵断面 DXF 圆弧段（有 bulge），可直接用 `arc_len = R_v × θ` 替代离散近似。

---

## 7. 空间转角计算（`_compute_spatial_angles`，第677–779行）

### 7.1 三维单位切向量

对每个有转弯的节点（`nd.has_turn == True`），构造前后三维单位切向量：

```python
α_before = radians(nd.azimuth_before)     # 数学方位角，度→弧度
α_after  = radians(nd.azimuth_after)
β_before = nd.slope_before                # 已是弧度
β_after  = nd.slope_after

T_before = (cos(β_before) × cos(α_before),
            cos(β_before) × sin(α_before),
            sin(β_before))

T_after  = (cos(β_after) × cos(α_after),
            cos(β_after) × sin(α_after),
            sin(β_after))
```

**退化验证**：

| 退化条件 | β 值 | 期望 θ_3D | 验证 |
|---|---|---|---|
| 纯水平弯道 | β₁ = β₂ = 0 | cos(θ_3D) = cos(Δα) → θ_3D = \|Δα\| | T = (cosα, sinα, 0)，点积 = cos(Δα) ✓ |
| 纯竖向折坡 | Δα = 0 | cos(θ_3D) = cos(β₂-β₁) → θ_3D = \|β₂-β₁\| | 点积 = cos(β₁)cos(β₂)+sin(β₁)sin(β₂) = cos(Δβ) ✓ |

### 7.2 点积计算空间转角

```python
dot = T_before[0]×T_after[0] + T_before[1]×T_after[1] + T_before[2]×T_after[2]
dot = clamp(dot, -1.0, 1.0)    # 防止浮点误差超出 arccos 定义域
θ_3D_rad = arccos(dot)
θ_3D_deg = degrees(θ_3D_rad)
nd.spatial_turn_angle = θ_3D_deg
```

> **角度自洽性注**：`_fill_adjacent_angles` 输出的 `azimuth_before/after` 是数学方位角（`atan2(ΔY,ΔX)`），代入切向量公式后 T 的 X 和 Y 分量物理意义为正东和正北方向，与工程坐标系自洽。若上游只有测量方位角（正北=0°，顺时针），直接代入切向量公式的 X/Y 分量会互换，但点积具有旋转不变性使最终 θ_3D 结果绝对正确。

### 7.3 有效曲率半径确定（第723–761行）

根据转弯来源（仅平面、仅纵断面、两者重叠）确定查表用的有效半径 R_eff：

```python
if nd.has_plan_turn and nd.has_long_turn:
    # ===== 重叠弯道：微分几何精确曲率合成 =====
    R_h = nd.plan_turn_radius
    R_v = nd.long_turn_radius
    
    if R_h > 0 and R_v > 0:
        # 等效坡角（取绝对值平均）
        β_avg = (|β_before| + |β_after|) / 2.0
        cos_β = cos(β_avg)
        cos4_β = cos_β⁴
        
        # 极限校核短路
        if R_v > 1e6:
            R_eff = R_h / cos_β²     # R_v→∞：退化为斜坡上的圆弧
        elif R_h > 1e6:
            R_eff = R_v              # R_h→∞：退化为纯竖向圆弧
        else:
            R_eff = R_h × R_v / √(R_h² + R_v² × cos4_β)
    elif R_h > 0:
        R_eff = R_h
    elif R_v > 0:
        R_eff = R_v
    else:
        R_eff = 0.0                  # 双折管重叠
    
    # 转弯类型：任一为圆弧则整体为圆弧
    eff_type = ARC if (plan_turn_type==ARC or long_turn_type==ARC) else FOLD

elif nd.has_plan_turn:
    R_eff = nd.plan_turn_radius
    eff_type = nd.plan_turn_type

elif nd.has_long_turn:
    R_eff = nd.long_turn_radius
    eff_type = nd.long_turn_type

nd.effective_radius = R_eff
nd.effective_turn_type = eff_type
```

---

## 8. R_3D 曲率合成公式详细推导

### 8.1 数学推导

三维曲线以空间弧长 σ 为参数，单位切向量：

```
T(σ) = (cos β · cos α,  cos β · sin α,  sin β)
```

曲率向量：

```
dT/dσ = (-sin β · cos α · dβ/dσ - cos β · sin α · dα/dσ,
         -sin β · sin α · dβ/dσ + cos β · cos α · dα/dσ,
          cos β · dβ/dσ)
```

曲率的模的平方：

```
κ² = |dT/dσ|² = (dβ/dσ)² + cos²β · (dα/dσ)²
```

**变量定义**：
- `s`：水平轴线弧长参数（桩号）
- `σ`：空间弧长参数
- `R_h`：平面圆曲线半径（按水平弧长 s 定义，`dα/ds = 1/R_h`）
- `R_v`：纵断面 (s,Z) 平面内的圆弧半径（由 DXF 弦长反算，`dβ/dσ_v = 1/R_v`，其中 σ_v 为 (s,Z) 平面弧长）

**弧长参数切换**：
- 空间弧长微分：`dσ = √(ds² + dZ²) = ds / cos β`（因 `dZ/ds = tan β`）
- 水平弧长与空间弧长关系：`ds = dσ · cos β`
- 方位角变化率转换：`dα/dσ = (dα/ds) · (ds/dσ) = (1/R_h) · cos β = cos β / R_h`
- 坡角变化率：在 (s,Z) 平面内，竖曲线弧长 ≈ 空间弧长（当平面无弯时精确成立），故 `dβ/dσ ≈ 1/R_v`

代入曲率公式：

```
κ² = (1/R_v)² + cos²β · (cos β / R_h)²
   = 1/R_v² + cos⁴β / R_h²

R_3D = 1/κ = R_h · R_v / √(R_h² + R_v² · cos⁴β)
```

### 8.2 极限校核

| 极限条件 | 含义 | R_3D 退化结果 | 物理意义 | 验证 |
|---|---|---|---|---|
| R_v → ∞ | 仅平面圆弧，纵坡为常值 | R_h / cos²β | 斜坡上的圆弧（圆柱螺线）曲率半径 | ✓ |
| R_h → ∞ | 仅竖曲线，平面直线 | R_v | 纯竖向圆弧 | ✓ |
| β = 0 | 水平面内弯道 | R_h · R_v / √(R_h² + R_v²) | 正交双曲率合成 | ✓ |
| R_h = R_v, β = 0 | 等半径正交 | R / √2 | 对称合成 | ✓ |

### 8.3 β_avg 等效坡角近似

```python
β_avg = (|β_before| + |β_after|) / 2
```

- 取**绝对值**平均是关键：对于 U 形管底部等 β 变号的情况（如 β_before = -15°，β_after = +15°），直接平均 `(β_before + β_after)/2 = 0°`（错误——管道在此处坡度 15° 而非 0°），而绝对值平均 `(15°+15°)/2 = 15°`（正确代表弯道平均坡度）。
- cos 为偶函数，cos(-β) = cos(β)，因此 cos⁴(β_avg) 在 β 变号时的近似误差微小。
- 对典型倒虹吸管道（β < 30°），cos⁴β 影响很小（cos⁴(30°) = 0.5625），近似误差远小于工程精度要求。

---

## 9. 仅平面模式的方位角填充（`_fill_azimuths_from_plan`，第640–671行）

仅平面模式（模式B）下的方位角填充逻辑：

```python
# 第1步：从匹配的 PlanFeaturePoint 初始化方位角
for i, nd in enumerate(spatial_nodes):
    for pp in plan_points:
        if |pp.chainage - nd.chainage| < 0.1:
            nd.azimuth_before = pp.azimuth    # 测量方位角（临时）
            nd.azimuth_after  = pp.azimuth
            break

# 第2步：用坐标差推算方位角（覆盖初始值）
for i in range(n):
    if i < n-1:
        dx = nx.x - nd.x;  dy = nx.y - nd.y
        if √(dx²+dy²) > 1e-6:
            nd.azimuth_after = degrees(atan2(dy, dx))    # 数学方位角
    if i > 0:
        dx = nd.x - px.x;  dy = nd.y - px.y
        if √(dx²+dy²) > 1e-6:
            nd.azimuth_before = degrees(atan2(dy, dx))

# 第3步：首尾补齐
spatial_nodes[0].azimuth_before = spatial_nodes[0].azimuth_after
spatial_nodes[-1].azimuth_after = spatial_nodes[-1].azimuth_before
```

之后在 `_merge_plan_only` 中，对 ARC 型转弯节点再用 `plan_geom_dict` 的 `d_in`/`d_out` 精确覆盖。

---

## 10. 整体数据流梳理

```
推求水面线表格 (ChannelNode[])
    ↓ siphon_extractor._extract_plan_feature_points()
    ↓   对每行提取: station_MC, x, y, azimuth, turn_radius, turn_angle, ip_number
SiphonGroup.plan_feature_points (List[dict])
    ↓ panel.set_params() → PlanFeaturePoint.from_dict()
PlanFeaturePoint[]  ← azimuth_meas_deg 为测量角（正北=0，atan2(ΔX,ΔY) 输出）
    |                  azimuth_math_rad 为数学角（正东=0，由测量角转换，计算属性）
    |
    |                         DXF 多段线 (LWPOLYLINE)
    |                             ↓ dxf_parser.parse_longitudinal_profile(file, offset)
    |                             ↓   读取顶点(x,y) + 凸度(bulge)
    |                             ↓   _build_longitudinal_nodes()：
    |                             ↓     第1步: 段属性计算（直线/圆弧，弧心坐标，切线坡角）
    |                             ↓     第2步: 提取变坡点（首点/折点/弧起点/弧终点/末点）
    |                             ↓     第3步: 排序去重
    |                         LongitudinalNode[]（含 slope_before/after, arc_center_s/z）
    ↓                             ↓
    +── SpatialMerger.merge_and_compute() ──────────────────────────────────┐
           ↓                                                                │
       步骤1：桩号并集                                                       │
           plan_dict + long_dict → all_stations（sorted）                   │
           预计算 plan_geom = _build_plan_geometry()                         │
           ↓                                                                │
       步骤2：空间坐标赋值                                                   │
           X,Y ← plan_dict命中用QZ/IP坐标，否则 _interpolate_plan()          │
           Z   ← long_dict命中用elevation，否则 _interpolate_long()          │
              └ 竖曲线段: Z = Zc ± √(Rv²-(s-Sc)²)                          │
              └ 直线段:   Z = lerp(Z1, Z2, t)                              │
           ↓                                                                │
       步骤3：转弯标记                                                       │
           平面转弯 → has_plan_turn + R_h + α_plan                          │
           纵断面转弯 → has_long_turn + R_v + 精确slope覆盖                  │
           ↓                                                                │
       步骤4：_fill_adjacent_angles()                                       │
           4a. 坐标差推算: azimuth=atan2(ΔY,ΔX), slope=atan2(ΔZ,Δs)        │
           4b. long_turn精确覆盖: ln.slope_before/after                     │
           4c. ARC精确覆盖: d_in/d_out切线方向                               │
           ↓                                                                │
       步骤1b：_detect_composite_events()                                   │
           EVENT_WINDOW=2.0m 内配对近邻弯道                                  │
           ↓                                                                │
       空间长度：Σ√(Δs²+ΔZ²)                                                │
           ↓                                                                │
       _compute_spatial_angles()：                                          │
           T_before/T_after → dot → θ_3D                                   │
           R_3D = R_h·R_v / √(R_h²+R_v²·cos⁴β_avg)                        │
           ↓                                                                │
       SpatialMergeResult ←─────────────────────────────────────────────────┘
           ↓
    HydraulicCore.execute_calculation()
        ↓ L_friction = total_spatial_length    ← 沿程损失 hf = (v²·L)/(C²·R)
        ↓ 对每个转弯节点按 D、θ_3D、R_3D 查表求 ξ
    ΔZ2 = hf + Σξ·v²/(2g)
```

---

## 11. 常量与配置参数

| 常量/参数 | 值 | 位置 | 说明 |
|---|---|---|---|
| `SNAP_TOLERANCE` | 2.0 m | `SpatialMerger` 类常量 | 复合弯道事件检测窗口；也用于精确坡角覆盖的匹配容差 |
| 桩号精度 | `round(chainage, 3)` | 多处 | 1mm 精度，浮点运算误差远小于此量级 |
| 转弯角度阈值 | 0.1° | 多处 | `turn_angle > 0.1` 才标记为转弯 |
| 折线检测阈值 | 0.5° | `_build_longitudinal_nodes` | 直线→直线坡角差 > 0.5° 生成 FOLD 节点 |
| 去重阈值 | 0.01 m (10mm) | `_build_longitudinal_nodes` | 排序后相邻节点桩号差 < 10mm 视为重复 |
| 弧心距离零阈值 | 1e-9 | `_compute_arc_center` 等 | 弦长/分母为零的保护 |
| 极限半径阈值 | 1e6 m | `_compute_spatial_angles` | R_h 或 R_v > 1e6 时启用极限校核短路 |

---

## 12. 精度与约束说明

| 项目 | 说明 |
|---|---|
| **角度体系** | `azimuth_meas_deg`（测量方位角，度，正北=0°，顺时针）仅用于 UI 显示和上游传递；`azimuth_math_rad`（数学方位角，弧度，正东=0°，逆时针）用于 T 向量公式和所有几何计算。字段名强制区分，不靠注释 |
| **桩号定义** | `chainage` 是平面轴线弧长参数。直线段上 Δs = 弦长；圆弧段上 Δs = R_h·Δφ（弧长），**不等于** XY 弦长 |
| **桩号精度** | `round(chainage, 3)`，即 1mm；浮点运算误差远小于此量级 |
| **ARC 型桩号** | ARC 型 PlanFeaturePoint 的 `chainage` 必须对应弧中点 QZ 的桩号，保证 `chainage ↔ (X,Y)` 指向轴线上同一几何位置 |
| **XY 插值** | 圆弧段内沿圆弧方程精确插值；切线段沿 EC→BC 方向线性插值；均在真实轴线上 |
| **圆弧转弯方位角** | 直接取 `d_in`/`d_out`（由 IP 坐标差解析得到的切线单位向量），解析精确 |
| **坡角 β 计算** | 用 `Δs = s[i+1]-s[i]`（桩号差 = 平面弧长参数增量）计算 `β = atan2(ΔZ, Δs)`（两参数），不用 XY 弦长 dH。before/after 分别用各自方向的 Δs |
| **合并策略** | 纯桩号并集 + 1mm 去重，不做桩号吸附/平移。复合弯道事件在独立步骤中按 EVENT_WINDOW 配对，仅影响 R_3D 合成和局损查表 |
| **空间长度** | `Σ√(Δs²+ΔZ²)`，Δs 为桩号差（精确水平弧长），非 3D 弦长 `√(ΔX²+ΔY²+ΔZ²)` |
| **R_3D 推导** | 前提：s 为弧长参数，α 为数学角，β 为坡角。κ² = 1/R_v² + cos⁴β/R_h²；R_3D = R_h·R_v / √(R_h²+R_v²·cos⁴β)。极限校核：R_v→∞ 时 R_3D=R_h/cos²β，R_h→∞ 时 R_3D=R_v |
| **β_avg** | `(|β_before| + |β_after|) / 2`（等效坡角近似）。取绝对值平均对 U 形管底部等 β 变号情形优于直接平均（后者趋近0，错误）。cos 为偶函数，β < 30° 时 cos⁴β 影响极小，近似误差微小 |
| **DXF 绘制约束** | X:Y 必须 1:1 真实坐标（桩号单位 m，高程单位 m），否则 R_v 将偏差 |

---

## 13. 分段解析几何方法（进阶，可选升级路径）

> 若追求"数值误差只剩浮点舍入"的极致精度，可将 plan/profile 都抽象为"分段解析几何"：

```
平面轴线 → 分段：直线段 (start_s, end_s, direction)、圆弧段 (start_s, end_s, R_h, center, ...)
纵断面   → 分段：直线段 (start_s, end_s, slope)、圆弧段 (start_s, end_s, R_v, ...)

对每个合并桩号 s，直接解析求解：
    X(s), Y(s)   ← 平面分段解析方程
    Z(s)         ← 纵断面分段解析方程
    α(s)         ← 平面切线方向（解析精确）
    β(s)         ← 纵断面坡角（解析精确）

此时 _fill_adjacent_angles() 可完全消除 —— 全部是解析量，数值误差只有浮点舍入。
```

> 当前算法版本（v2.0，代码文件版本标识）不推翻既有架构，但通过桩号差替代弦长、角度体系硬隔离等修正，
> 已消除了主要的系统性几何误差。上述分段解析方法作为未来可选升级路径保留。

---

## 14. 变更日志

| 版本 | 日期 | 变更内容 |
|---|---|---|
| v1.0 | 2026-02-15 | 初始版本 |
| v2.0 | 2026-02-22 | 严格几何修订：移除桩号吸附，角度体系硬隔离，β 用桩号差计算，空间长度用 √(Δs²+ΔZ²)，R_3D β_avg 取绝对值平均 |
| v2.1 | 2026-02-22 | 竖曲线 Z 插值漏洞修复（圆弧公式 + atan 坡角），变坡点生成规则补全（弧端坡角用弧心公式，ARC 存储弧心坐标） |
| v3.0 | 2026-02-27 | 基于代码全面同步重写：补全所有函数签名与行号引用；新增数据结构完整字段表（SpatialNode/SpatialMergeResult）；新增平面圆弧几何预计算章节（_build_plan_geometry/_arc_point）；新增仅平面模式方位角填充章节；算法伪代码全面细化至逐行级别；新增常量/配置参数章节；新增变更日志；补全上游 siphon_extractor 数据提取流程说明 |
