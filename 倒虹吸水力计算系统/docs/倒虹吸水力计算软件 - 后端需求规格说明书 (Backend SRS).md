# 倒虹吸水力计算软件 - 后端需求规格说明书 (Backend SRS)

**版本**: v2.0  
**最后更新**: 2026-02-25  
**状态**: 已实现

---

## 1. 系统架构概述

后端系统包含以下五个核心服务模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| **数据模型层** | `siphon_models.py` | 定义全局参数、结构段、空间节点等核心数据结构 |
| **DXF 解析引擎** | `dxf_parser.py` | 读取CAD文件，转化为结构段数据和纵断面变坡点节点表 |
| **系数查询服务** | `siphon_coefficients.py` | 内置《附录L》中的查表、插值及公式计算逻辑 |
| **水力计算核心** | `siphon_hydraulics.py` | 执行设计截面计算、水头损失求解（三段式） |
| **三维空间合并引擎** | `spatial_merger.py` | 按桩号合并平面(X,Y)和纵断面(S,Z)数据，计算空间长度和空间转角 θ_3D |

---

## 2. 数据模型层 (siphon_models.py)

### 2.1 枚举类型

#### SegmentDirection — 结构段方向

| 枚举值 | UI显示 | 说明 |
|--------|--------|------|
| COMMON | 通用 | 通用构件（进/出水口、拦污栅、闸门槽等），仅贡献ξ |
| PLAN | 平面 | 平面段（水平转弯，从推求水面线表格自动提取） |
| LONGITUDINAL | 纵断面 | 纵断面段（竖向剖面，从DXF导入或手动输入） |

#### TurnType — 转弯类型

| 枚举值 | 说明 |
|--------|------|
| NONE | 无转弯 |
| ARC | 圆弧型（有转弯半径，平面圆曲线/纵断面竖曲线/fillet） |
| FOLD | 折线型（无转弯半径） |

#### SegmentType — 结构段类型

| 枚举值 | UI显示 | 所属分类 |
|--------|--------|----------|
| INLET | 进水口 | 通用构件 |
| STRAIGHT | 直管 | 管身段 |
| BEND | 弯管 | 管身段 |
| FOLD | 折管 | 管身段 |
| TRASH_RACK | 拦污栅 | 通用构件 |
| GATE_SLOT | 闸门槽 | 通用构件 |
| BYPASS_PIPE | 旁通管 | 通用构件（冲沙/放空/进人孔等） |
| PIPE_TRANSITION | 管道渐变段 | 通用构件（收缩ξ=0.05/扩散ξ=0.10） |
| OTHER | 其他 | 通用构件（可自定义名称） |
| OUTLET | 出水口 | 通用构件 |

辅助函数 `is_common_type(segment_type)` 和集合 `COMMON_SEGMENT_TYPES` 用于统一判断通用构件。

#### V2Strategy — 进口渐变段末端流速 v₂ 计算策略

| 枚举值 | UI显示 | 说明 |
|--------|--------|------|
| AUTO_PIPE | 自动（= 管道流速） | v₂ = Q/(πD²/4)，推荐 |
| V1_PLUS_02 | v₁ + 0.2 | 经验增量法 |
| SECTION_CALC | 由断面参数计算 | v₂ = Q/[(B+m×h)×h] |
| MANUAL | 手动输入 | 用户直接填写 |

#### GradientType — 渐变段类型

| 枚举值 | 进口ξ₁ | 出口ξ₂ |
|--------|---------|---------|
| NONE | 0.00 | 0.00 |
| REVERSE_BEND（反弯扭曲面） | 0.10 | 0.20 |
| QUARTER_ARC（1/4圆弧） | 0.15 | 0.25 |
| SQUARE_HEAD（方头型） | 0.30 | 0.75 |
| LINEAR_TWIST（直线扭曲面） | 0.20(均值) | 0.40(均值) |

直线扭曲面支持按角度线性插值：进口θ₁=15°~37°→ξ₁=0.05~0.30，出口θ₂=10°~17°→ξ₂=0.30~0.50。

#### InletOutletShape — 进水口形状（表L.1.4-2）

| 枚举值 | 说明 | ξ 范围 |
|--------|------|--------|
| FULLY_ROUNDED | 进口完全修圆 | 0.05~0.10 |
| SLIGHTLY_ROUNDED | 进口稍微修圆 | 0.20~0.25 |
| NOT_ROUNDED | 进口没有修圆 | 0.50 |

#### TrashRackBarShape — 拦污栅栅条形状（表L.1.4-1）

| 枚举值 | β 系数 |
|--------|--------|
| RECTANGULAR（矩形） | 2.42 |
| ROUNDED_HEAD（单侧圆头） | 1.83 |
| CIRCULAR（圆形） | 1.79 |
| OVAL（双侧圆头） | 1.67 |
| TRAPEZOID（倒梯形单侧圆头） | 1.04 |
| PEAR_SHAPE（梨形/流线型） | 0.92 |
| SHARP_TAIL（两端尖锐型） | 0.76 |

### 2.2 全局参数对象 (GlobalParameters)

| 属性名 | 数据类型 | 默认值 | 说明 |
|--------|----------|--------|------|
| Q | float | 0.0 | 设计流量 (m³/s) |
| v_guess | float | 0.0 | 拟定流速 (m/s) |
| roughness_n | float | 0.014 | 糙率 |
| inlet_type | GradientType | NONE | 进口渐变段型式 |
| outlet_type | GradientType | NONE | 出口渐变段型式 |
| v_channel_in | float | 0.0 | 进口渐变段始端流速 v₁ (m/s) |
| v_pipe_in | float | 0.0 | 进口渐变段末端流速 v₂ (m/s) |
| v_channel_out | float | 0.0 | 出口渐变段始端流速 v (m/s) |
| v_pipe_out | float | 0.0 | 出口渐变段末端流速 v₃ (m/s) |
| xi_inlet | float | 0.0 | 进口局部阻力系数 |
| xi_outlet | float | 0.0 | 出口局部阻力系数 |
| v2_strategy | V2Strategy | AUTO_PIPE | v₂ 计算策略 |
| num_pipes | int | 1 | 管道根数（并联管道数量，1~10） |

### 2.3 结构段对象 (StructureSegment)

| 属性名 | 数据类型 | 说明 |
|--------|----------|------|
| segment_type | SegmentType | 段类型 |
| length | float | 长度 (m) |
| radius | float | 弯管半径 R (m)，仅弯管有效 |
| angle | float | 弯管圆心角或折管折角 (度) |
| xi_user | Optional[float] | 用户手动输入的局部阻力系数 |
| xi_calc | Optional[float] | 程序计算的局部阻力系数 |
| coordinates | List[Tuple] | 几何坐标点集合 |
| locked | bool | 是否锁定（DXF导入行） |
| trash_rack_params | Optional[TrashRackParams] | 拦污栅参数 |
| inlet_shape | Optional[InletOutletShape] | 进水口形状 |
| outlet_shape | Optional[InletOutletShape] | 出水口形状 |
| custom_label | str | 自定义名称（"其他"类型用） |
| direction | SegmentDirection | 方向（默认LONGITUDINAL） |
| start_elevation | Optional[float] | 起点高程 (m) |
| end_elevation | Optional[float] | 终点高程 (m) |
| source_ip_index | Optional[int] | 关联的IP点索引（仅平面段） |

**方法**：
- `get_xi()` → float：获取局部阻力系数（用户值优先于计算值）
- `spatial_length` 属性：计算空间长度（直管段 √(L²+ΔH²)，弯管段 R×θ_rad）
- `elevation_change` 属性：高程差 ΔH (m)

### 2.4 计算结果对象 (CalculationResult)

| 属性名 | 说明 |
|--------|------|
| diameter / diameter_theory | 设计管径 / 理论直径 (m) |
| velocity | 管内实际流速 (m/s) |
| velocity_channel_in | 进口渠道流速 v₁ (m/s) |
| velocity_pipe_in | 进口渐变段末端流速 v₂ (m/s) |
| velocity_outlet_start | 出口渐变段始端流速 v (m/s) |
| velocity_channel_out | 出口渠道流速 v₃ (m/s) |
| area | 断面积 (m²) |
| hydraulic_radius | 水力半径 (m) |
| chezy_c | 谢才系数 |
| loss_inlet | 进口渐变段水面落差 ΔZ₁ (m) |
| loss_pipe | 管身段总水头损失 ΔZ₂ (m) |
| loss_friction | 沿程水头损失 hf (m) |
| loss_local | 管身局部水头损失 hj (m) |
| loss_outlet | 出口渐变段水面落差 ΔZ₃ (m) |
| total_head_loss | 总水面落差 ΔZ = ΔZ₁ + ΔZ₂ - ΔZ₃ (m) |
| total_length | 管道总长度 (m) |
| xi_sum_middle / xi_inlet / xi_outlet | 各部分阻力系数 |
| data_mode / data_note | 计算模式/数据来源说明 |
| num_pipes | 管道根数 |
| **加大流量工况** | |
| increase_percent | 加大比例 (%) |
| Q_increased / velocity_increased | 加大流量/流速 |
| loss_inlet_inc / loss_pipe_inc / loss_outlet_inc | 加大工况三段损失 |
| total_head_loss_inc | 加大工况总落差 ΔZ加大 (m) |
| calculation_steps | 详细计算过程（List[str]） |

### 2.5 拦污栅参数对象 (TrashRackParams)

| 属性名 | 说明 | 默认值 |
|--------|------|--------|
| alpha | 栅面倾角 (度) | 90.0 |
| has_support | 是否有独立支墩 | False |
| bar_shape | 栅条形状 | RECTANGULAR |
| beta1 | 栅条形状系数 | 2.42 |
| s1 / b1 | 栅条厚度/间距 (mm) | 10.0 / 50.0 |
| support_shape | 支墩形状 | RECTANGULAR |
| beta2 | 支墩形状系数 | 2.42 |
| s2 / b2 | 支墩厚度/净距 (mm) | 10.0 / 50.0 |
| manual_mode | 手动输入模式 | False |
| manual_xi | 手动ξ值 | 0.0 |

支持 `to_dict()` / `from_dict()` 序列化。

### 2.6 三维空间合并数据模型

#### LongitudinalNode（纵断面变坡点）

| 属性名 | 说明 |
|--------|------|
| chainage | 桩号 (m) |
| elevation | 高程 (m) |
| vertical_curve_radius | 竖曲线半径 R_v (m) |
| turn_type | 转弯类型 (TurnType) |
| turn_angle | 竖向转角 (度) |
| slope_before / slope_after | 前后坡角 β (弧度) |
| arc_center_s / arc_center_z | 竖曲线弧心桩号/高程（仅ARC型） |

#### PlanFeaturePoint（平面IP特征点）

| 属性名 | 说明 |
|--------|------|
| chainage | MC桩号 (m) |
| x / y | 工程坐标（X=东, Y=北） |
| azimuth_meas_deg | 测量方位角 (度)，正北=0°顺时针 |
| turn_radius | 水平转弯半径 R_h (m) |
| turn_angle | 水平转角 α (度) |
| turn_type | 转弯类型 |
| ip_index | IP编号 |

角度体系硬隔离：`azimuth_meas_deg`（测量角，UI显示）与 `azimuth_math_rad`（数学角，计算用，正东=0°逆时针）。

#### SpatialNode（三维空间节点）

由 SpatialMerger 按桩号合并 PlanFeaturePoint 和 LongitudinalNode 生成。

| 属性名 | 说明 |
|--------|------|
| chainage / x / y / z | 桩号及三维坐标 |
| azimuth_before / azimuth_after | 前后方位角 (度) |
| slope_before / slope_after | 前后坡角 (弧度) |
| has_plan_turn / has_long_turn | 是否有平面/纵断面转弯 |
| plan_turn_radius / long_turn_radius | 平面/纵断面转弯半径 |
| plan_turn_angle / long_turn_angle | 平面/纵断面转角 |
| spatial_turn_angle | θ_3D (度) |
| effective_radius | 用于查表的有效半径 (m) |
| effective_turn_type | 用于查表的转弯类型 |

#### SpatialMergeResult（空间合并结果）

| 属性名 | 说明 |
|--------|------|
| nodes | List[SpatialNode] |
| total_spatial_length | 空间总长度 (m) |
| segment_lengths | 各段空间长度列表 |
| xi_spatial_bends | 空间弯道损失系数总和（预留） |
| computation_steps | 计算步骤日志 |
| has_plan_data / has_longitudinal_data | 数据存在标志 |

---

## 3. DXF 解析引擎 (dxf_parser.py)

### 3.1 平面管线解析 `parse_dxf()`

**输入**：DXF 文件路径

**校验**：
- 是否安装 ezdxf 库
- 文件是否可读
- 是否存在 LWPOLYLINE 或 POLYLINE 实体

**解析逻辑**：
1. **顶点提取**：读取多段线顶点列表 (x, y) 及对应凸度 (bulge)
2. **首节点**：创建 INLET 段（默认"进口稍微修圆"，ξ取范围中值0.225）
3. **遍历线段**：
   - bulge ≠ 0 → 弯管识别：angle = 4×atan(|bulge|)，R = chord/(2×sin(θ/2))，弧长 = R×θ
   - bulge = 0 → 直管段暂存，检测折角（>1°为折管）
4. **折管处理**：合并折点前后两段为 FOLD 段，支持连续折点
5. **尾节点**：创建 OUTLET 段

**输出**：(List[StructureSegment], 上游渠底高程建议值, 消息字符串)

### 3.2 纵断面解析 `parse_longitudinal_profile()`

**输入**：DXF 文件路径、桩号偏移量 chainage_offset

**坐标约定（1:1 实际坐标）**：
- X 坐标 = 桩号（局部值，加 chainage_offset 对齐到 MC 桩号）
- Y 坐标 = 高程 (m)
- bulge ≠ 0 的段 = 竖曲线（fillet圆弧），R_v 由 bulge 推算
- bulge = 0 的段 = 等坡直线段

**解析步骤（v2.1）**：
1. **段属性计算**：每段判断直线或圆弧，圆弧段用弧心公式精确计算弧端切线坡角
2. **提取变坡点**：
   - 线→线坡角差 > 0.5° → FOLD 节点
   - 弧段 → ARC 节点（存储弧心坐标 arc_center_s/arc_center_z 供精确Z插值）+ 弧终点 NONE 参考节点
3. **排序去重**：保留转弯信息更丰富的节点

**弧心坐标计算**：`_compute_arc_center(p1, p2, bulge)` — 符号由 bulge 正负决定弧心在弦的左/右侧

**弧上切线坡角**：`_arc_tangent_slope(S, Z, Sc, Zc)` — β = atan(-(S-Sc)/(Z-Zc))

**输出**：(List[LongitudinalNode], 消息字符串)

### 3.3 校验 `validate_dxf()`

快速校验 DXF 文件是否包含有效多段线，不执行完整解析。

---

## 4. 系数查询服务 (siphon_coefficients.py)

### 4.1 渐变段系数 `get_gradient_coeff()`

| 渐变段型式 | 进口 ξ₁ | 出口 ξ₂ | 备注 |
|-----------|---------|---------|------|
| 无 | 0.00 | 0.00 | — |
| 反弯扭曲面 | 0.10 | 0.20 | θ₁,θ₂≤12.5° |
| 1/4圆弧 | 0.15 | 0.25 | θ₁,θ₂≤12.5° |
| 方头型 | 0.30 | 0.75 | 阻力最大 |
| 直线扭曲面 | 0.20(均值) | 0.40(均值) | 范围见下 |

### 4.2 直线扭曲面角度插值 `calculate_linear_twist_coeff()`

进口：θ₁=15°~37° → ξ₁=0.05~0.30  
出口：θ₂=10°~17° → ξ₂=0.30~0.50  
超出范围按端点值返回（不外推）。

### 4.3 弯管系数 `calculate_bend_coeff(R, D, angle)`

1. 计算 R/D₀
2. 查表 L.1.4-3（线性插值）→ ξ₉₀
3. 查表 L.1.4-4（线性插值）→ γ
4. ξ = ξ₉₀ × γ

**表 L.1.4-3 直角弯道损失系数表**

| R/D₀ | 0.5 | 1.0 | 1.5 | 2.0 | 3.0 | 4.0 | 5.0 | 6.0 | 7.0 | 8.0 | 9.0 | 10.0 | 11.0 |
|------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|------|------|
| ξ₉₀ | 1.20 | 0.80 | 0.60 | 0.48 | 0.36 | 0.30 | 0.29 | 0.28 | 0.27 | 0.26 | 0.25 | 0.24 | 0.23 |

**表 L.1.4-4 任意角修正系数 γ 值表**

| θ(°) | 5 | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 100 | 120 | 140 |
|------|---|----|----|----|----|----|----|----|----|-----|-----|-----|-----|
| γ | 0.125 | 0.23 | 0.40 | 0.55 | 0.65 | 0.75 | 0.83 | 0.88 | 0.95 | 1.00 | 1.05 | 1.13 | 1.20 |

### 4.4 折管系数 `calculate_fold_coeff(angle)`

公式：ζ = 0.9457 × sin²(θ/2) + 2.047 × sin⁴(θ/2)

### 4.5 拦污栅系数 `calculate_trash_rack_xi(params)`

**公式 L.1.4-2（无独立支墩）**：ξ = β₁ × (s₁/b₁)^(4/3) × sin(α)

**公式 L.1.4-3（有独立支墩）**：ξ = [β₁ × (s₁/b₁)^(4/3) + β₂ × (s₂/b₂)^(4/3)] × sin(α)

支持手动输入模式（manual_mode=True 时直接返回 manual_xi）。

### 4.6 管道渐变段系数

| 类型 | ξjb |
|------|-----|
| 收缩（方变圆/圆管收缩） | 0.05 |
| 扩散（圆变方/圆管扩大，扩散角≤10°） | 0.10 |

---

## 5. 水力计算核心 (siphon_hydraulics.py)

### 5.1 三种计算模式

| 模式 | 触发条件 | 长度来源 | 弯道损失来源 |
|------|----------|----------|-------------|
| **A. 三维空间合并** | 有 plan_feature_points 或 longitudinal_nodes (≥2) | 空间长度 √(Δs²+ΔZ²) | 空间弯道 θ_3D 查表 |
| **B. 传统模式** | 仅有 plan_segments 或 plan_total_length | 平面总长度 | 平面弯道查表 |
| **C. 单数据源** | 无空间数据 | 纵断面段长度之和 | — |

### 5.2 接口签名

```python
HydraulicCore.execute_calculation(
    global_params: GlobalParameters,
    segments: List[StructureSegment],
    diameter_override: Optional[float] = None,    # 用户指定管径
    verbose: bool = False,                         # 详细计算过程
    plan_segments: List[StructureSegment] = None,  # 平面段（旧接口）
    plan_total_length: float = 0.0,                # 平面总长度
    plan_feature_points: List[PlanFeaturePoint] = None,   # 平面IP点（新接口）
    longitudinal_nodes: List[LongitudinalNode] = None,    # 纵断面节点（新接口）
    increase_percent: Optional[float] = None,      # 加大流量比例 (%)
) -> CalculationResult
```

### 5.3 步骤1：几何设计与流速计算

1. **并联管道分摊**：Q_single = Q / num_pipes
2. **断面积**：ω = Q_single / v_guess
3. **理论直径**：D_theory = √(4ω/π)
4. **管径取整** `round_diameter()`：
   - D ≤ 1.0m → 按 0.05m 向上取整
   - D ≤ 1.6m → 按 0.1m 向上取整
   - D ≤ 5.0m → 按 0.2m 向上取整
   - 用户可覆盖（diameter_override），但小于理论值时给出警告
5. **实际流速**：v = Q_single / A
6. **水力半径**：R_h = D / 4
7. **v₂ 策略确定**：
   - AUTO_PIPE → v₂ = v（管道流速）
   - V1_PLUS_02 → v₂ = v₁ + 0.2
   - SECTION_CALC / MANUAL → 使用传入值
   - 安全兜底：若 v₂ ≤ v₁ 且 v₁ > 0，自动回退到管道流速
8. **出口渐变段始端流速**：v_out = v（管道实际流速）

### 5.4 步骤2：阻力参数初始化

1. **谢才系数**：C = (1/n) × R_h^(1/6)
2. **计算模式判断**：
   - 模式A → 调用 SpatialMerger.merge_and_compute()，遍历空间节点查表计算弯道ξ
   - 模式B → 遍历 plan_segments 计算平面弯管ξ
3. **通用构件贡献**：遍历 segments 中 direction=COMMON 或 is_common_type 的段，累加ξ和长度
4. **进出口系数**：从 global_params 获取 xi_inlet / xi_outlet

### 5.5 步骤3：水头损失求解（三段式）

**总水面落差公式**：ΔZ = ΔZ₁ + ΔZ₂ - ΔZ₃

| 分段 | 公式 | 规范引用 |
|------|------|----------|
| ΔZ₁ 进口渐变段 | (1 + ξ₁) × (v₂² - v₁²) / (2g) | L.1.2-2 |
| ΔZ₂ 管身段 | hf + hj | L.1.4-7 |
| 　hf 沿程损失 | L × v² / (C² × R_h) | — |
| 　hj 局部损失 | Σξ_middle × v² / (2g) | — |
| ΔZ₃ 出口渐变段 | (1 - ξ₂) × (v² - v₃²) / (2g) | L.1.3-2 |

### 5.6 加大流量工况

当 increase_percent > 0 时，在同一次计算中完成加大工况：
- Q_inc = Q × (1 + increase_percent/100)
- v_inc = Q_inc_single / A
- v₂_inc 按相同策略确定
- 重新计算 ΔZ₁加大、ΔZ₂加大、ΔZ₃加大

### 5.7 结果格式化 `format_result()`

输出包含：设计参数汇总、三段式水头损失分解、管道总长、加大工况（如有）、详细计算过程（可选）。

---

## 6. 三维空间合并引擎 (spatial_merger.py)

详见 `空间轴线合并算法-PRD.md`，此处仅列接口。

### 6.1 入口方法

```python
SpatialMerger.merge_and_compute(
    plan_points: List[PlanFeaturePoint],
    long_nodes: List[LongitudinalNode],
    pipe_diameter: float = 0.0,
    verbose: bool = True
) -> SpatialMergeResult
```

### 6.2 三种退化场景

| 场景 | β 取值 | α 取值 | 长度计算 |
|------|--------|--------|----------|
| 仅平面 | 0 | 从坐标差推算 | L_plan |
| 仅纵断面 | 从高程差推算 | 0（常数） | √(Δs²+ΔZ²) |
| 完整三维 | 精确坡角 | 精确方位角 | √(Δs²+ΔZ²) |

### 6.3 核心算法

1. **桩号并集**（不修改任何原始桩号）
2. **复合弯道事件检测**（EVENT_WINDOW = 2.0m）
3. **空间坐标插值**（圆弧段精确几何 / 切线段线性插值）
4. **方位角/坡角填充**（圆弧型用入/出切线精确方向覆盖坐标差推算值）
5. **空间转角计算**：θ_3D = arccos(T_before · T_after)，T = (cosβ·cosα, cosβ·sinα, sinβ)
6. **有效半径合成**（重叠弯道）：R_3D = R_h·R_v / √(R_h² + R_v²·cos⁴β)

---

## 7. 接口定义 (API)

### 7.1 后端向前端暴露的主要接口

```python
# 1. 平面管线解析
DxfParser.parse_dxf(file_path: str) -> (List[StructureSegment], float, str)

# 2. 纵断面解析
DxfParser.parse_longitudinal_profile(file_path: str, chainage_offset: float) -> (List[LongitudinalNode], str)

# 3. DXF校验
DxfParser.validate_dxf(file_path: str) -> (bool, str)

# 4. 渐变段系数查询
CoefficientService.get_gradient_coeff(gradient_type, is_inlet) -> float

# 5. 直线扭曲面角度插值
CoefficientService.calculate_linear_twist_coeff(angle, is_inlet) -> float

# 6. 弯管系数计算
CoefficientService.calculate_bend_coeff(R, D, angle, verbose) -> (float, str) | float

# 7. 折管系数计算
CoefficientService.calculate_fold_coeff(angle, verbose) -> (float, str) | float

# 8. 拦污栅系数计算
CoefficientService.calculate_trash_rack_xi(params, verbose) -> (float, str) | float

# 9. 核心计算
HydraulicCore.execute_calculation(...) -> CalculationResult

# 10. 结果格式化
HydraulicCore.format_result(result, show_steps) -> str

# 11. 管径取整
HydraulicCore.round_diameter(d_theory) -> float

# 12. 三维空间合并
SpatialMerger.merge_and_compute(...) -> SpatialMergeResult
```

### 7.2 面板外部接口（与推求水面线联动）

```python
# SiphonPanel 对外接口
set_params(**kwargs)          # 从外部设置参数（Q, v_guess, n, v₁, v₃, 平面数据等）
get_result() -> CalculationResult
get_total_head_loss() -> float
to_dict() -> dict             # 序列化（项目保存）
from_dict(d: dict)            # 反序列化（项目加载）
```

---

## 8. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-02-15 | 初始版本，基础架构 |
| v2.0 | 2026-02-25 | 全面重写：新增V2Strategy枚举、并联管道、加大流量工况、三维空间合并模式、纵断面DXF解析、折管公式、管道渐变段、直线扭曲面角度插值、进水口形状枚举、拦污栅手动模式；数据模型与代码完全对齐 |

