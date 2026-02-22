# 空间轴线合并算法 — 产品需求规格文档

> **版本**: 2.1（v2.0 严格几何修订 + v2.1 竖曲线Z插值/变坡点规则补全）  **日期**: 2026-02-22  
> **代码**: `spatial_merger.py`, `dxf_parser.py`（`倒虹吸水力计算系统/`）  
> **跨模块**: `推求水面线/utils/siphon_extractor.py`（PlanFeaturePoint）, `推求水面线/core/geometry_calc.py`（方位角）

---

## 0. 背景

倒虹吸管道是一条三维曲线，由两组独立数据描述：

| 数据 | 坐标系 | 内容 |
|---|---|---|
| **平面图**（来自推求水面线） | X-Y 水平面 | IP 点 (X,Y)、水平转角 α、平面半径 R_h |
| **纵断面**（来自 DXF） | 桩号 S - 高程 Z | 变坡点高程、坡角 β、竖曲线半径 R_v |

**核心前提**：桩号 s（chainage）是**平面轴线弧长参数**，即沿水平面轴线的累计弧长。直线段上 Δs = 弦长 = √(ΔX²+ΔY²)；圆弧段上 Δs = R_h·Δφ（弧长），**不等于** XY 弦长。

**算法目标**：按桩号合并后输出三维节点序列，计算每个转弯节点的 θ_3D、R_3D，以及全线空间总长 L_spatial。

---

## 1. 数据结构说明

### 1.1 PlanFeaturePoint（平面 IP 点）

来源：`siphon_extractor._extract_plan_feature_points()` 从 `ChannelNode` 提取。

| 字段 | 单位 | 备注 |
|---|---|---|
| `chainage` | m | MC 桩号（平面轴线弧长参数） |
| `x`, `y` | m | 工程坐标（X=东，Y=北） |
| `azimuth_meas_deg` | **度** | `geometry_calc.calculate_azimuth()` → `atan2(ΔX, ΔY)` → **测量方位角**（正北=0°，顺时针），0~360°。**仅用于 UI 显示和上游数据传递** |
| `azimuth_math_rad` | **弧度** | **数学方位角**（正东=0°，逆时针）。由测量方位角唯一转换：`α_math = π/2 - radians(azimuth_meas_deg)`，归一化到 (-π, π]。**T 向量公式必须使用此字段** |
| `turn_angle` | 度 | 水平转角（首尾 IP 为 0） |
| `turn_radius` | m | 平面圆曲线半径 R_h（`n×D` 更新） |
| `turn_type` | — | ARC / FOLD / NONE |
| `ip_index` | — | IP 编号（整数，供 UI 显示用，计算不使用）|

> **角度体系硬隔离约束**：
> - 上游 `siphon_extractor` 和 `geometry_calc` 输出的方位角是**测量方位角**（`atan2(ΔX,ΔY)`，正北=0°，顺时针）。
> - 三维切向量公式 `T = (cosβ·cosα, cosβ·sinα, sinβ)` 要求 α 为**数学方位角**（`atan2(ΔY,ΔX)`，正东=0°，逆时针）。
> - 字段名 `azimuth_meas_deg` 与 `azimuth_math_rad` 在数据结构层面强制区分，不靠注释记忆。
> - 转换公式：`α_math_rad = π/2 - radians(α_meas_deg)`，归一化到 (-π, π] 或 [0, 2π)。

> **ARC 型桩号定义约束**：
> - 当 `turn_type == ARC` 时，`pp.chainage` 必须等于该弧中点 QZ 的桩号（而非交点 PI 的桩号）。
> - `pp.x`, `pp.y` 对于 ARC 型仍存储 IP（交点）坐标（用于计算 BC/EC/弧心几何），但在合并时使用 QZ 坐标。
> - 这保证了 `chainage ↔ (X,Y)` 在轴线上的一致性：节点的桩号 s 与其空间坐标 (X(s), Y(s)) 指向同一个几何位置。

### 1.2 LongitudinalNode（纵断面变坡点）

来源：`dxf_parser._build_longitudinal_nodes()` 解析 DXF LWPOLYLINE。

| 字段 | 单位 | 备注 |
|---|---|---|
| `chainage` | m | DXF 顶点 X + chainage_offset |
| `elevation` | m | DXF 顶点 Y |
| `slope_before` | **弧度** | `atan2(Δ高程, Δ桩号)` |
| `slope_after` | **弧度** | 同上 |
| `turn_angle` | **度** | 前后坡角差绝对值 |
| `vertical_curve_radius` | m | R_v（圆弧段反算） |
| `arc_center_s` | m | 竖曲线弧心桩号坐标 Sc（仅 ARC 型节点有效，供 Z 插值精确公式使用） |
| `arc_center_z` | m | 竖曲线弧心高程坐标 Zc（仅 ARC 型节点有效） |

---

## 2. DXF 纵断面解析

### 2.1 弧段参数反算（`dxf_parser`）

AutoCAD 凸度 `bulge = tan(θ/4)`，θ = 圆心角：

```
θ (rad) = 4 × atan(|bulge|)     ← |bulge| 仅用于圆心角大小
chord   = √(Δx² + Δy²)         ← Δx=桩号差, Δy=高程差
R_v     = chord / (2×sin(θ/2))
arc_len = R_v × θ
```

> **bulge 符号保留**：`bulge>0` = 逆时针弧（弧心在弦左侧），`bulge<0` = 顺时针弧（弧心在弦右侧）。
> `|bulge|` 只用于计算 θ 和 R_v 大小；`sign(bulge)` 必须保留用于 `_compute_arc_center` 判断弧心在弦的哪一侧，
> 进而决定竖曲线是冈形还是凸形。这个信息不能从半径大小恢复。

### 2.2 变坡点生成规则

**通用规则**：只要曲率发生突变（1/R 从 0 变为非 0，或从 R₁ 变为 R₂），或切线出现不连续，就生成节点。

| 情形 | 生成节点类型 | slope_before | slope_after |
|---|---|---|---|
| 直线→直线，坡角差>0.5° | FOLD（在前段末端） | 前段坡角 | 后段坡角 |
| 直线→圆弧 | ARC（在弧起点） | 前段坡角 | 弧心公式计算的弧终切线坡角 |
| 圆弧→直线 | NONE（弧终点） | 弧终切线坡角 | 弧终切线坡角 |
| 圆弧→圆弧（S形曲线） | ARC（第二弧起点） | 第一弧终切线坡角 | 第二弧弧心公式计算的弧终切线坡角 |
| 首节点 | NONE | 第一段切线坡角 | 第一段切线坡角 |
| 末节点 | NONE | 最后段切线坡角 | 最后段切线坡角 |

> v2.1 变更：弧端切线坡角由弧心公式直接计算：
> `slope = math.atan(-(S点-Sc) / (Z点-Zc))`
>
> **不能用原始比値 `-(S-Sc)/(Z-Zc)`**：该值是 `tan β`（无量纲）而非 `β`（弧度）。若直接赋给 slope 字段，后续 `cos(β)`/`sin(β)` 会把 tan 値当弧度代入。
> **不能用 `atan2(-(S-Sc), Z-Zc)`**：当弧在弧心下方（谷底弧，典型倒虹吸）时 `Z-Zc<0`，
> `atan2` 的 x 分量为负，会对结果加±π 导致完全错误。
> ARC 节点存储弧心坐标 (arc_center_s, arc_center_z)。

---

## 3. 三种合并模式

```
has_plan = len(plan_points) >= 2
has_long = len(long_nodes)  >= 2

A. has_plan AND has_long  → 完整三维合并（主路径）
B. has_plan only          → β=0，Z=0，θ_3D = α（水平转角）
C. has_long only          → α=0，Y=0，X=桩号，θ_3D = 竖向转角
```

---

## 4. 完整三维合并（模式 A）—— 逐步算法

### 步骤 1：桩号并集（不修改任何原始桩号）

```
plan_dict  = { round(pp.chainage, 3): pp  for pp in plan_points }
long_dict  = { round(ln.chainage, 3): ln  for ln in long_nodes  }
all_stations = sorted( set(plan_dict.keys()) ∪ set(long_dict.keys()) )
桩号精度：round(chainage, 3)（1mm）
```

> **v2.0 变更**：v1.x 的"吸附"步骤会把纵断面弯道桩号强行改为平面 IP 桩号，
> 这在数学上是把一个事件平移到另一个桩号，会导致：
> (1) 三维节点序列几何形状改变；(2) θ_3D、R_3D 被人为制造或消除；(3) 局部损失分配位置失真。
>
> **严格做法**：不改任何 key（桩号）。合并只做"桩号并集 + 同桩号近似去重（1mm）"。

### 步骤 1b：复合弯道事件检测（独立步骤，仅用于局损计算）

```
EVENT_WINDOW = SNAP_TOLERANCE  # 2.0m（可配置）

对每个 spatial_node（nd）：
    若 nd 有平面转弯（has_plan_turn）但无纵断面转弯：
        在全部 long_nodes 中找桩号差 ≤ EVENT_WINDOW 的最近纵断面转弯 ln
        若找到：
            nd.has_long_turn = True（标记复合事件）
            nd.long_turn_radius = ln.vertical_curve_radius
            nd.long_turn_angle  = ln.turn_angle
            nd.long_turn_type   = ln.turn_type

    若 nd 有纵断面转弯（has_long_turn）但无平面转弯：
        在全部 plan_points 中找桩号差 ≤ EVENT_WINDOW 的最近平面转弯 pp
        选择规则：选距离最近的 pp（不是"第一个满足 dist≤tol 就 break"）
        若找到：
            nd.has_plan_turn = True（标记复合事件）
            nd.plan_turn_radius = pp.turn_radius
            nd.plan_turn_angle  = pp.turn_angle
            nd.plan_turn_type   = pp.turn_type
```

> 复合事件保留原始桩号用于几何插值与长度积分，合成事件信息仅用于 R_3D 合成和局损查表。

### 步骤 2：空间坐标赋值

对每个桩号 s：

**X, Y（平面插值）**：
```
预先调用 _build_plan_geometry() 提供 BC/EC/弧心/QZ 坐标

若 plan_dict 有 s（即为 IP 节点）：
    若 pp.turn_type == ARC 且 qz 已计算：X,Y = qz（弧中点，精确在轴线上）
    否则：X,Y = pp.x, pp.y（折管 IP 本身在轴线上，直接用）
否则（需插值）：
    1. 若 bc_chainage ≤ s ≤ ec_chainage（在某圆弧段内）：
           delta = (s - bc_chainage) / R_h
           (X,Y) = _arc_point(center, R, bc, delta, left_turn)   ← 弧上精确坐标
    2. 若 ec_chainage[i] ≤ s ≤ bc_chainage[i+1]（在切线段）：
           t = (s - ec_ch[i]) / (bc_ch[i+1] - ec_ch[i])
           (X,Y) = EC[i] + t × (BC[i+1] - EC[i])              ← 精确切线插值
```

**Z（纵断面插值）**：
```
若 long_dict 有 s：
    Z = ln.elevation
    slope = ln.slope_before（若 slope_before≠0），否则取 ln.slope_after
    （注：转弯节点此处初始化为 ln 坡角；步骤3 & 步骤4 将用精确坡角覆盖）
否则：
    若区间起点 n1 为 ARC 型且已存储弧心（arc_center_s, arc_center_z）：
        竖曲线圆弧公式：Z = Zc ± √(Rv² - (s-Sc)²)  ← v2.1 漏洞A修复
        副号取决于 n1.elevation 在弧心上方还是下方
        坡角：slope = math.atan(-(s-Sc)/(Z-Zc))  ← v2.1.1 漏洞A修复
        （原始比値 -(s-Sc)/(Z-Zc) 是 tanβ，不是 β，必须经 atan 转换）
    直线段：Z = Z₁ + t×(Z₂-Z₁)（线性插值）， slope = atan2(ΔZ, Δs)
```

### 步骤 3：转弯标记

```
if pp 且 pp.turn_angle > 0.1° 且 pp.turn_type ≠ NONE：
    has_plan_turn = True
    plan_turn_radius = pp.turn_radius, plan_turn_angle = pp.turn_angle

if ln 且 ln.turn_angle > 0.1° 且 ln.turn_type ≠ NONE：
    has_long_turn = True
    long_turn_radius = ln.vertical_curve_radius
    slope_before/after ← 用 ln 的值覆盖插值结果（精确坡角）
```

### 步骤 4：方位角与坡角填充（`_fill_adjacent_angles`）

用坐标差和**桩号差**覆盖所有方位角和坡角（会覆盖步骤2的临时初始值）；对转弯节点有两道精确保护覆盖，不会用割线近似：

```
Δs_after  = s[i+1] - s[i]        ← 桩号差（平面弧长参数增量）
Δs_before = s[i] - s[i-1]

# 方位角：从 XY 坐标差推算（数学方位角，存为度，正东=0°，逆时针）
azimuth_after[i]  = degrees(atan2(Y[i+1]-Y[i], X[i+1]-X[i]))   ← 数学角（度）
azimuth_before[i] = degrees(atan2(Y[i]-Y[i-1], X[i]-X[i-1]))

# 坡角：用桩号差 Δs（而非 XY 弦长 dH），确保与 Z(s) 的定义严格一致
slope_after[i]    = atan2(Z[i+1]-Z[i], Δs_after)
slope_before[i]   = atan2(Z[i]-Z[i-1], Δs_before)

首节点：azimuth_before = azimuth_after，slope_before = slope_after
末节点：azimuth_after  = azimuth_before，slope_after  = slope_before

对 has_long_turn 节点：
    在全部 long_nodes 中找桩号差 ≤ SNAP_TOLERANCE 的最近匹配项
    覆盖 slope_before/after（精确坡角，优于坐标差近似）

对 has_plan_turn 且 plan_turn_type == ARC 节点：
    从 plan_geom_dict 取 d_in, d_out（入/出切线单位向量）
    azimuth_before = degrees(atan2(d_in.y,  d_in.x))   ← 解析精确，存为度，与其余节点单位一致
    azimuth_after  = degrees(atan2(d_out.y, d_out.x))
```

> **v2.0 变更（坡角 β）**：
> - v1.x 用 `dH = √(ΔX²+ΔY²)`（XY 弦长）计算 β = arctan(ΔZ/dH)。
>   在圆弧段上，XY 弦长 < 弧长（桩号差 Δs），导致 ΔZ/dH 偏大，β 系统性偏陡。
> - v2.0 改用 `Δs = s[i+1] - s[i]`（桩号差 = 平面弧长参数增量），
>   β = arctan(ΔZ/Δs)，与纵断面 Z(s) 的定义严格一致，也与后续曲率推导中"s 为弧长参数"的假设一致。
> - before 和 after 分别用各自方向的 Δs 计算（不共用同一个 dH）。

> **坐标系约束**：工程坐标 X=东、Y=北，`atan2(dy,dx)` 得**数学方位角**（正东=0°，逆时针）。
> `_fill_adjacent_angles` 输出的 azimuth_before/after 均为**数学方位角（度）**，
> 与 T 向量公式 `(cosβcosα, cosβsinα, sinβ)` 中 α 的定义自洽。

---

## 5. 空间长度计算

```
Δs_i     = s[i+1] - s[i]                         ← 桩号差（平面弧长参数增量）
ΔZ_i     = Z[i+1] - Z[i]
L_seg_i  = √(Δs_i² + ΔZ_i²)                      ← 空间弧长微分的离散近似
L_spatial = Σ L_seg_i
```

> **v2.0 变更**：
> - v1.x 用 `√(ΔX²+ΔY²+ΔZ²)`（3D 弦长）。在圆弧段上，ΔX²+ΔY² 是平面弦长平方（< 弧长平方），
>   导致空间长度系统性偏短。
> - v2.0 改用 `√(Δs²+ΔZ²)`，其中 Δs 是桩号差（= 平面弧长参数增量），精确表示水平路径长度。
>   数学依据：空间弧长微分 `dℓ = √(1 + (dZ/ds)²) ds`，离散化为 `Δℓ ≈ √(Δs² + ΔZ²)`。
> - 更高精度选项：对纵断面 DXF 圆弧段（有 bulge），可直接用 `arc_len = R_v × θ` 替代离散近似。

---

## 6. 空间转角计算

### 6.1 切向量

```
T_before = (cosβ_before × cosα_before,
            cosβ_before × sinα_before,
            sinβ_before)

T_after  = (cosβ_after × cosα_after,
            cosβ_after × sinα_after,
            sinβ_after)
```

其中 α（度→弧度），β（已是弧度，直接用）。

> **角度自洽性注**：`_fill_adjacent_angles` 输出的 `azimuth_before/after` 是数学方位角（`atan2(ΔY,ΔX)`），
> 代入上式后 T 的 X 和 Y 分量物理意义为正东和正北方向，与工程坐标系自洽。
> 若上游只有测量方位角（正北=0°，顺时针），直接代入切向量公式的 X/Y 分量会互换，但点积具屏转不变性使最终 θ_3D 结果绝对正确。
> 若需输出真实三维方向向量供渲染，必须将测量角转换为数学角：α_math = π/2 - α_meas。

| 退化验证 | 条件 | 期望结果 |
|---|---|---|
| 纯水平弯道 | β₁=β₂=0 | cos(θ_3D) = cos(Δα) → θ_3D = |Δα| ✓ |
| 纯竖向折坡 | Δα=0 | cos(θ_3D) = cos(β₂-β₁) → θ_3D = |β₂-β₁| ✓ |

### 6.2 点积角度

```
dot = T_before · T_after = clamp(dot, -1, 1)
θ_3D = arccos(dot)
```

---

## 7. 有效曲率半径合成（重叠弯道）

当节点同时有平面转弯和纵断面转弯时，合成三维有效半径 R_3D：

### 7.1 数学推导

三维曲线 `T = (cosβ·cosα, cosβ·sinα, sinβ)`（单位切向量，按空间弧长 σ 参数化），曲率：

```
κ² = |dT/dσ|² = (dβ/dσ)² + cos²β·(dα/dσ)²
```

**变量定义**：
- `s`：水平轴线弧长参数（桩号）
- `R_h`：平面圆曲线半径（按水平弧长定义）
- `R_v`：纵断面圆弧半径（(s,Z) 平面内的圆弧半径，由 DXF 弦长 `√(Δs²+ΔZ²)` 反算）
- `β`：坡角（弧度）

**弧长参数切换**：推导用空间弧长 σ（而非水平 s）作为曲率公式的参数。对于平面直线管段（平面无弯），`dσ = √(ds²+dZ²) = ds/cosβ`，此时 (s,Z) 平面弧长 = 空间弧长。

```
dα/dσ = cosβ / R_h    （水平弧长 ds_h = dσ·cosβ，dα/ds_h = 1/R_h ⇒ dα/dσ = cosβ/R_h）
dβ/dσ = 1 / R_v       （R_v 为 (s,Z)平面圆弧半径，空间弧长参数下 dβ/dσ = 1/R_v）
```

代入 κ² = |dT/dσ|² = (dβ/dσ)² + cos²β·(dα/dσ)²：

```
κ² = (1/R_v)² + cos²β·(cosβ/R_h)²
   = 1/R_v² + cos⁴β/R_h²

R_3D = 1/κ = R_h·R_v / √(R_h² + R_v²·cos⁴β)
```

β=0 时退化：`R_3D = R_h·R_v / √(R_h²+R_v²)` ✓

> **注**：公式中 β 是圈定典型位置的**等效坡角**（取 `(β_before+β_after)/2` 的绝对値平均），属工程近似。
> 严格讲 R_3D 是上述弧长参数 σ 处的**局部曲率半径**，如要数学精确应在事件窗口中点直接计算 β(σ)。

### 7.2 极限校核

| 极限条件 | 含义 | 期望结果 | 验证 |
|---|---|---|---|
| R_v → ∞（仅平面圆弧，坡度常值） | 只有水平弯道 | κ = cos²β / R_h，R_3D = R_h / cos²β | "斜坡上的圆（圆柱螺线）"的曲率 ✓ |
| R_h → ∞（仅竖曲线） | 只有纵断面弯道 | R_3D = R_v | 退化为纯竖向圆弧 ✓ |
| β = 0 | 水平面内弯道 | R_3D = R_h·R_v / √(R_h²+R_v²) | v1.x 已验证 ✓ |

> 代码中应对 R_h 或 R_v 极大（> 1e6）的情况做短路处理，直接返回退化结果。

### 7.3 代码实现

```python
β_avg  = (|β_before| + |β_after|) / 2           # 取绝对值平均代表弯道坡角
cos_β  = cos(β_avg)
cos4_β = cos_β ** 4
R_3D   = R_h×R_v / √(R_h² + R_v²×cos4_β)        # 精确曲率合成公式
```

> 取绝对值平均是正确的工程近似：对于 U 形管底部等 β 变号的情况其中
> `(β_before + β_after)/2 ≈ 0`（错误），而 `(|β_before|+|β_after|)/2` 正确代表弯道平均坡度。
> 对倍垒管道（β < 30°），cos⁴β 影响权强，该近似高度精顽。
>
> R_h=0 或 R_v=0 时取非零项；两者均为 0（双折管重叠）时 R_3D=0，类型取 FOLD。

---

## 8. 整体数据流梳理

```
推求水面线表格 (ChannelNode)
    ↓ 推求水面线/utils/siphon_extractor._extract_plan_feature_points()
PlanFeaturePoint[]  ← azimuth_meas_deg 为测量角（正北=0，atan2(ΔX,ΔY) 输出）
    |                  azimuth_math_rad 为数学角（正东=0，由测量角转换）
    ↓ panel.set_params()
    |                         DXF 多段线 (LWPOLYLINE)
    |                             ↓ dxf_parser.parse_longitudinal_profile()
    |                         LongitudinalNode[]  ← slope 为弧度
    |                             ↓ panel._build_longitudinal_nodes()（重建坡角）
    ↓                         LongitudinalNode[]（含 slope_before/after）
    +── SpatialMerger.merge_and_compute() ──────────────────────────┐
           ↓                                                        │
       步骤1：桩号并集（不修改任何原始桩号）                             │
       步骤1b：复合弯道事件检测（EVENT_WINDOW 内配对）                  │
           ↓                                                        │
       步骤2：X/Y 平面插值 + Z 纵断面插值                              │
           ↓                                                        │
       步骤3：转弯标记                                                │
           ↓                                                        │
       步骤4：_fill_adjacent_angles()                                │
              方位角：atan2(ΔY,ΔX) → 数学角（度）                      │
              坡角：atan2(ΔZ,Δs) → 用桩号差而非 XY 弦长                │
              精确覆盖：long_turn→ln坡角，ARC→d_in/d_out 切线          │
           ↓                                                        │
       空间长度：Σ√(Δs²+ΔZ²)                                        │
           ↓                                                        │
       _compute_spatial_angles()：θ_3D, R_3D                        │
           ↓                                                        └─→ SpatialMergeResult
    HydraulicCore.execute_calculation()
        ↓ L_friction = total_spatial_length
        ↓ 对每个转弯节点按 D、θ_3D、R_3D 查表求 ξ
    ΔZ2 = hf + hj
```

---

## 9. 精度与约束说明

| 项目 | 说明 |
|---|---|
| **角度体系** | `azimuth_meas_deg`（测量方位角，度，正北=0°，顺时针）仅用于 UI 显示和上游传递；`azimuth_math_rad`（数学方位角，弧度，正东=0°，逆时针）用于 T 向量公式和所有几何计算。字段名强制区分，不靠注释 |
| **桩号定义** | `chainage` 是平面轴线弧长参数。直线段上 Δs = 弦长；圆弧段上 Δs = R_h·Δφ（弧长），**不等于** XY 弦长 |
| **桩号精度** | `round(chainage, 3)`，即 1mm；浮点运算误差远小于此量级 |
| **ARC 型桩号** | ARC 型 PlanFeaturePoint 的 `chainage` 必须对应弧中点 QZ 的桩号，保证 `chainage ↔ (X,Y)` 指向轴线上同一几何位置 |
| **XY 插值** | 圆弧段内沿圆弧方程精确插值；切线段沿 EC→BC 方向线性插值；均在真实轴线上 |
| **圆弧转弯方位角** | 直接取 `d_in`/`d_out`（由 IP 坐标差解析得到的切线单位向量），解析精确 |
| **坡角 β 计算** | 用 `Δs = s[i+1]-s[i]`（桩号差 = 平面弧长参数增量）计算 β = arctan(ΔZ/Δs)，不用 XY 弦长 dH。before/after 分别用各自方向的 Δs |
| **合并策略** | 纯桩号并集 + 1mm 去重，不做桩号吸附/平移。复合弯道事件在独立步骤中按 EVENT_WINDOW 配对，仅影响 R_3D 合成和局损查表 |
| **空间长度** | `Σ√(Δs²+ΔZ²)`，Δs 为桩号差（精确水平弧长），非 3D 弦长 `√(ΔX²+ΔY²+ΔZ²)` |
| **R_3D 推导** | 前提：s 为弧长参数，α 为数学角，β 为坡角。κ² = 1/R_v² + cos⁴β/R_h²；R_3D = R_h·R_v / √(R_h²+R_v²cos⁴β)。极限校核：R_v→∞ 时 R_3D=R_h/cos²β，R_h→∞ 时 R_3D=R_v |
| **β_avg** | `(|β_before| + |β_after|) / 2`（等效坡角近似）。并非数学精确値（圆弧上各点 β 不同，没有唯一 β），但是实践中最合理的工程近似：取绝对値平均对 U 形管底部等 β 变号情形优于直接平均（后者趋近0，错误）。cos 为偶函数，β < 30° 时 cos⁴β 影响极小，近似误差微小。 |
| **DXF 绘制约束** | X:Y 必须 1:1 真实坐标（桩号单位 m，高程单位 m），否则 R_v 将偏差 |

---

## 10. 分段解析几何方法（进阶，可选升级路径）

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

> 当前版本（v2.0）不推翻既有架构，但通过桩号差替代弦长、角度体系硬隔离等修正，
> 已消除了主要的系统性几何误差。上述分段解析方法作为未来可选升级路径保留。
