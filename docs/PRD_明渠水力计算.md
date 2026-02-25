# 明渠水力计算模块 — 产品需求文档 (PRD)

> **版本**: v1.1  
> **创建日期**: 2026-02-22  
> **最后更新**: 2026-02-25  
> **状态**: 已实现（完成度 100%，含 U形）

---

## 一、模块概述

明渠水力计算模块是「渠系建筑物水力计算系统」的核心子模块之一，提供 **梯形、矩形、圆形、U形** 四种明渠断面类型的水力设计计算功能。

所有断面类型在架构上处于并列地位，具有统一的调用逻辑和统一的设计接口 `design_channel()`。

### 1.1 设计依据

- **GB 50288-2018《灌溉与排水工程设计标准》**
  - §6.4.8：渠道岸顶超高规定
  - 附录E：梯形渠道实用经济断面计算

### 1.2 核心公式

- **曼宁公式**：`Q = (1/n) × A × R^(2/3) × i^(1/2)`
- **岸顶超高（4级、5级渠道）**：`Fb = (1/4) × hb + 0.2`

---

## 二、文件结构

```
渠系建筑物断面计算/
  └── 明渠设计.py              # 计算引擎（1513行）

渠系断面设计/
  └── open_channel/
      ├── __init__.py           # 模块声明
      ├── panel.py              # UI面板（1341行）
      └── dxf_export.py         # DXF导出（388行）
```

### 2.1 依赖关系

| 文件 | 职责 | 依赖 |
|------|------|------|
| `明渠设计.py` | 纯计算引擎，无UI依赖 | `math`, `dataclasses`, `typing`, `enum` |
| `panel.py` | PySide6 UI面板 | `明渠设计.py`, `styles.py`, `export_utils.py`, `formula_renderer.py`, `dxf_export.py` |
| `dxf_export.py` | DXF断面图导出 | `math`, `ezdxf`（运行时导入） |

### 2.2 共享模块依赖

- `渠系断面设计/styles.py` — 全局样式常量（颜色、字体、布局）
- `渠系断面设计/export_utils.py` — Word导出工具（OMML公式转换、styled表格）
- `渠系断面设计/formula_renderer.py` — KaTeX/SVG公式渲染器
- `渠系断面设计/frozen_table.py` — 冻结列表格控件（批量面板使用）
- `渠系断面设计/structure_type_selector.py` — 结构类型分类选择器（批量面板使用）

---

## 三、数据模型

### 3.1 枚举类型

```python
class SectionType(Enum):
    TRAPEZOIDAL = "trapezoidal"   # 梯形明渠
    RECTANGULAR = "rectangular"   # 矩形明渠
    CIRCULAR    = "circular"      # 圆形明渠
    U_SECTION   = "u_section"     # U形明渠（圆弧底+斜直线壁）
```

### 3.2 输入数据类 `InputData`

| 字段 | 类型 | 说明 |
|------|------|------|
| `Q_design` | `float` | 设计流量 (m³/s) |
| `n_roughness` | `float` | 糙率 |
| `slope_inv` | `float` | 坡度倒数 (1/i) |
| `v_min_allowable` | `float` | 最小允许流速 (m/s) |
| `v_max_allowable` | `float` | 最大允许流速 (m/s) |
| `increase_percent_manual` | `Optional[float]` | 指定加大比例 (%) |
| `D_manual` | `Optional[float]` | 指定直径 (m，仅圆形) |

### 3.3 水力计算结果 `HydraulicResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `y` | `float` | 水深 (m) |
| `A` | `float` | 过水面积 (m²) |
| `P` | `float` | 湿周 (m) |
| `R` | `float` | 水力半径 (m) |
| `V` | `float` | 流速 (m/s) |
| `FB` | `float` | 安全超高/干舷 (m) |
| `PA` | `float` | 净空面积百分比 (0-1) |
| `Q_check` | `float` | 校验流量 (m³/s) |
| `theta` | `float` | 圆心角 (rad，仅圆形) |
| `success` | `bool` | 计算是否成功 |

### 3.4 设计计算结果 `DesignResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `D_calculated` | `float` | 计算直径 (m，仅圆形) |
| `D_design` | `float` | 设计直径 (m，仅圆形) |
| `section_total_area` | `float` | 断面总面积 (m²，仅圆形) |
| `b_calculated` | `float` | 计算底宽 (m，梯形/矩形) |
| `b_design` | `float` | 设计底宽 (m，梯形/矩形) |
| `design` | `HydraulicResult` | 设计工况水力结果 |
| `Q_increased` | `float` | 加大流量 (m³/s) |
| `increased` | `HydraulicResult` | 加大工况水力结果 |
| `Q_min` | `float` | 最小流量 (m³/s) |
| `minimum` | `HydraulicResult` | 最小工况水力结果 |
| `increase_percent` | `float` | 加大百分比 |
| `increase_percent_source` | `str` | 加大来源 ("指定"/"自动") |
| `success` | `bool` | 计算总体成功 |
| `error_message` | `str` | 错误信息 |
| `check_passed` | `bool` | 验证通过 |
| `check_errors` | `List[str]` | 验证错误列表 |

---

## 四、计算引擎

### 4.1 常量定义

#### 4.1.1 通用常量

| 常量 | 值 | 说明 |
|------|------|------|
| `ZERO_TOLERANCE` | `1e-9` | 零值容差 |

#### 4.1.2 梯形与矩形常量

| 常量 | 值 | 说明 |
|------|------|------|
| `MAX_BETA` | `8.0` | 最大宽深比 |
| `FLOW_TOLERANCE` | `0.01` | 流量计算容差 |
| `B_TOLERANCE` | `0.005` | 底宽计算容差 |
| `MAX_H_ITER` | `300` | 水深迭代次数 |
| `MAX_B_ITER` | `100` | 底宽迭代次数 |
| `ALPHA_VALUES` | `[1.00, 1.01, ..., 1.05]` | 附录E α值范围 |

#### 4.1.3 圆形常量

| 常量 | 值 | 说明 |
|------|------|------|
| `MIN_FREEBOARD` | `0.4` | 最小安全超高 (m) |
| `MIN_FREE_AREA_PERCENT` | `15.0` | 最小净空面积百分比 (%) |
| `MIN_FLOW_FACTOR` | `0.4` | 最小流量系数 |
| `ITERATION_DIAMETER_STEP` | `0.001` | 直径迭代步长 (m) |
| `FINAL_DIAMETER_ROUNDING_STEP` | `0.1` | 最终直径取整步长 (m) |
| `MAX_ITERATIONS_Y` | `100` | y/D求解最大迭代次数 |
| `TOLERANCE_Y` | `0.0001` | y/D求解收敛精度 |
| `MAX_ITERATIONS_D_CALC` | `25000` | D计算最大迭代次数 |
| `MAX_ALLOWED_D` | `20.0` | 最大允许直径 (m) |

### 4.2 梯形/矩形明渠计算

矩形是梯形的特例（边坡系数 `m=0`）。

#### 4.2.1 基础水力函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `calculate_area` | `(b, h, m) → float` | 过水面积 `A = (b + m·h)·h` |
| `calculate_wetted_perimeter` | `(b, h, m) → float` | 湿周 `χ = b + 2·h·√(1+m²)` |
| `calculate_hydraulic_radius` | `(b, h, m) → float` | 水力半径 `R = A/χ` |
| `calculate_flow_rate` | `(b, h, i, n, m) → float` | 曼宁公式计算流量 |
| `calculate_velocity` | `(Q, A) → float` | 流速 `V = Q/A` |

#### 4.2.2 反算函数

| 函数 | 说明 | 算法 |
|------|------|------|
| `calculate_depth_for_flow` | 根据流量反算水深 | 迭代调整法（指数因子0.375） |
| `calculate_dimensions_for_flow_and_beta` | 根据流量+宽深比算尺寸 | 直接解析（h^(8/3)方程） |
| `calculate_depth_for_flow_and_bottom_width` | 根据流量+底宽算水深 | 二分法（500次迭代） |

#### 4.2.3 附录E 梯形渠道实用经济断面

**计算流程：**

1. **第一阶段** — 计算水力最佳断面 `(h0, b0, β0, K)`
   - 几何形状因子：`K = 2√(1+m²) - m`
   - 最佳水深：`h0 = [nQ·2^(2/3) / (K·√i)]^(3/8)`
   - 最佳底宽：`b0 = 2(√(1+m²) - m) × h0`
   - 最佳宽深比：`β0 = 2(√(1+m²) - m)`

2. **第二阶段** — 对 α=1.00~1.05 生成所有方案
   - 水深比：`η = α^2.5 - √(α^5 - α)`（公式 E.0.2-2，取较小根）
   - 实际水深：`h = h0 × η`
   - 宽深比：`β = [α/η² × K] - m`（公式 E.0.2-3）
   - 底宽：`b = β × h`

3. **第三阶段** — 选择满足流速约束的最优方案
   - 优先选 α 最小（面积增加最少）的满足 `v_min < V < v_max` 的方案

**函数清单：**

| 函数 | 说明 |
|------|------|
| `calculate_optimal_hydraulic_section(Q, n, i, m)` | 计算水力最佳断面 |
| `calculate_eta_from_alpha(alpha)` | α → η 转换 |
| `calculate_beta_from_alpha_eta(alpha, eta, K, m)` | 计算宽深比β |
| `calculate_all_appendix_e_schemes(Q, n, i, m)` | 生成全部α方案列表 |
| `calculate_economic_section_appendix_e(Q, n, i, m, v_min, v_max)` | 选择最优方案 |

#### 4.2.4 加大流量比例（规范表）

| 设计流量 Q (m³/s) | 加大比例 |
|-------------------|---------|
| Q < 1 | 30% |
| 1 ≤ Q < 5 | 25% |
| 5 ≤ Q < 20 | 20% |
| 20 ≤ Q < 50 | 15% |
| 50 ≤ Q < 100 | 10% |
| Q ≥ 100 | 5% |

#### 4.2.5 主计算函数 `quick_calculate_trapezoidal`

**参数**：`Q, m, n, slope_inv, v_min, v_max, manual_beta, manual_b, manual_increase_percent`

**设计方法优先级**：
1. **指定底宽优先** — 若指定 `manual_b`，二分法反算水深，验证流速+宽深比
2. **指定宽深比次之** — 若指定 `manual_beta`，解析法计算尺寸，验证流速
3. **附录E算法兜底** — 自动计算水力最佳/实用经济断面

**计算流程**：
1. 输入参数验证（Q>0, n>0, slope_inv>0, v_min<v_max）
2. 按优先级确定底宽 b 和水深 h
3. 所有中间量四舍五入到 3 位小数（确保计算链路一致性）
4. 计算设计工况：A, χ, R, V, Q_calc, β
5. 计算加大流量工况：Q增, h增, A增, V增
6. 计算岸顶超高：`Fb = 0.25 × h增 + 0.2`
7. 计算渠道高度：`H = h增 + Fb`

**返回字典 key**：
- 设计工况：`b_design`, `h_design`, `V_design`, `A_design`, `X_design`, `R_design`, `Beta_design`, `Q_calc`
- 加大工况：`increase_percent`, `Q_increased`, `h_increased`, `V_increased`, `A_increased`, `X_increased`, `R_increased`
- 渠道尺寸：`Fb`, `h_prime`
- 状态：`success`, `error_message`, `design_method`
- 附录E：`appendix_e_schemes`（方案列表，每项含 alpha/eta/h/b/beta/A/V/area_increase/scheme_type）
- 标记：`used_manual_beta`, `used_manual_b`

#### 4.2.6 矩形明渠 `quick_calculate_rectangular`

直接调用 `quick_calculate_trapezoidal` 并令 `m=0`。

### 4.3 圆形明渠计算

#### 4.3.1 无量纲系数

给定 `y/D` 比值，计算：
- `k_A = (θ - sinθ) / 8`（面积系数）
- `k_P = θ / 2`（湿周系数）
- `k_R = k_A / k_P`（水力半径系数）
- `θ = 2·arccos(1 - 2·y/D)`（圆心角）

#### 4.3.2 核心计算函数

| 函数 | 说明 |
|------|------|
| `get_circular_coefficients_for_y_over_D(y_over_D)` | 计算无量纲系数 |
| `calculate_water_depth_y_circular(D, K_target)` | 根据D和流量模数K求解水深y（二分法） |
| `calculate_circular_hydraulics(D, Q, n, slope, K_req)` | 计算指定D和Q的完整水力特性 |
| `solve_D_and_y_from_A_and_R(A_target, R_target)` | 根据A和R反算D和y |

#### 4.3.3 直径搜索算法

**二分法** `_find_diameter_binary_search`（主算法）：
- **下界约束**（随D增大而满足）：success + FB ≥ 0.4m + PA ≥ 15% + V ≤ v_max
- **上界约束**（流速下限）：V ≥ v_min
- 二分查找满足下界约束的最小D，再验证上界约束
- 精度：0.001m

**线性搜索** `_find_diameter_linear_search`（保留用于验证）：
- 从0.1m步进0.001m，逐一检查三工况全部约束

#### 4.3.4 设计直径取整 `get_design_diameter_rounded`

| 计算直径范围 | 取整步长 |
|-------------|---------|
| D ≤ 0.5m | 0.05m |
| 0.5 < D ≤ 1.5m | 0.1m |
| D > 1.5m | 0.2m |

#### 4.3.5 三工况校验

| 工况 | 流量 | 校验项 |
|------|------|--------|
| 设计工况 | Q_design | V范围 + FB ≥ 0.4m + PA ≥ 15% |
| 加大工况 | Q × (1+加大%) | V范围 + FB ≥ 0.4m + PA ≥ 15% |
| 最小工况 | Q × 0.4 | V ≥ v_min |

#### 4.3.6 主计算函数

| 函数 | 说明 |
|------|------|
| `process_circular_single_row(input_data)` | 单行圆形明渠计算（返回 DesignResult） |
| `process_circular_batch(data_list)` | 批量计算 |
| `circular_result_to_dict(result)` | DesignResult → 字典 |
| `quick_calculate_circular(Q, n, slope_inv, ...)` | 快速单行计算（返回字典） |
| `calculate_circular_hydraulic_params(D, y)` | 根据D和y计算水力参数 |
| `calculate_circular_flow_capacity(D, n, slope_inv, y)` | 根据D/n/i/y计算流量 |

### 4.4 U形明渠计算

#### 4.4.1 几何模型

圆弧底 + 斜直线壁，三参数：R（圆弧半径）、α（直线段外倾角°）、θ（圆弧段圆心角°）

**临界水深** h₀ = R·(1 − cos(θ/2))

#### 4.4.2 分段面积/湿周公式

| 情形 | 条件 | 面积 A | 湿周 χ |
|------|------|--------|--------|
| 纯弧区 | h ≤ h₀ | `arccos((R-h)/R)·R² − (R-h)·√(2Rh−h²)` | `2R·arccos((R-h)/R)` |
| 直线段 | h > h₀ | `A_arc + (b + m·h_s)·h_s` | `θ·R + 2·h_s·√(1+m²)` |

其中 m=tan(α)，b=2R·sin(θ/2)，h_s=h−h₀，A_arc=R²·(θ/2−sin(θ/2)·cos(θ/2))

#### 4.4.3 水面宽精确公式（转弯半径/弯道损失用）

| 情形 | 水面宽 B |
|------|----------|
| h ≤ h₀ | `2·√[R²−(R−h)²]` |
| h > h₀ | `2R·sin(θ/2) + 2·m·(h−h₀)` |

#### 4.4.4 主计算函数 `quick_calculate_u_section`

**参数**：`Q, R, alpha_deg, theta_deg, n, slope_inv, v_min, v_max, manual_increase_percent=None`

**返回字典 key**：
- 几何参数：`R, alpha_deg, theta_deg, m, h0, b_arc`
- 设计工况：`h_design, A_design, X_design, R_design, V_design, Q_calc`
- 加大工况：`increase_percent, Q_increased, h_increased, V_increased, A_increased, X_increased, R_increased`
- 渠道尺寸：`Fb, h_prime`
- 状态：`success, error_message`

### 4.5 统一接口

```python
def design_channel(section_type: SectionType, **kwargs) -> Dict[str, Any]:
```

根据 `section_type` 分发到对应的 `quick_calculate_*` 函数。支持通用参数名映射（如 `Q`/`Q_design`, `n`/`n_roughness`）。

### 4.6 向后兼容

```python
def quick_calculate(Q, m, n, slope_inv, v_min, v_max, ...) -> Dict[str, Any]:
```

保留原函数名 `quick_calculate`，内部调用 `quick_calculate_trapezoidal`。

---

## 五、UI 面板 (`OpenChannelPanel`)

### 5.1 布局结构

```
QHBoxLayout
├── 左侧：QScrollArea（输入面板，宽280~420px）
│   └── QGroupBox "输入参数"
│       ├── 断面类型下拉框 (ComboBox: 梯形/矩形/圆形/U形)
│       ├── 基础参数区
│       │   ├── 设计流量 Q (m³/s)
│       │   ├── 边坡系数 m（梯形可见）
│       │   ├── 圆弧半径 R（U形可见，默认0.8m）
│       │   ├── 外倾角 α°（U形可见，默认14°）
│       │   ├── 圆心角 θ°（U形可见，默认152°）
│       │   ├── 糙率 n
│       │   └── 水力坡降 1/
│       ├── 流速参数区
│       │   ├── 不淤流速 (m/s) — 默认0.1
│       │   └── 不冲流速 (m/s) — 默认100.0
│       ├── 流量加大区
│       │   └── 流量加大比例 (%) — 留空自动计算
│       ├── 可选参数区
│       │   ├── 指定宽深比 β（梯形/矩形可见）
│       │   ├── 指定底宽 B (m)（梯形/矩形可见）
│       │   └── 指定直径 D (m)（圆形可见）
│       ├── 输出详细计算过程（CheckBox，默认选中）
│       ├── [计算] [清空] 按钮
│       └── [导出DXF] [导出Word] 按钮
│
└── 右侧：QTabWidget
    ├── Tab "计算结果" — QWebEngineView（KaTeX公式渲染）
    └── Tab "断面图" — matplotlib Figure + NavigationToolbar
```

### 5.2 断面类型切换逻辑

| 断面类型 | 显示控件 | 隐藏控件 | m值 |
|---------|---------|---------|-----|
| 梯形 | m, β, B | D | 用户输入（默认1.0） |
| 矩形 | β, B | m, D | 强制设为0.0 |
| 圆形 | D | m, β, B | — |

### 5.3 计算结果显示

#### 5.3.1 显示模式

- **简要模式**（`detail_cb` 未选中）：输入参数 → 设计结果 → 加大工况 → 验证结果
- **详细模式**（`detail_cb` 选中）：增加逐步计算公式推导过程

#### 5.3.2 梯形/矩形结果内容

**简要模式**：
- 输入参数汇总
- 设计结果：b, h, β, A, R, V, 设计方法
- 附录E方案对比表（仅自动计算时显示，HTML styled table）
- 加大工况：加大比例, Q增, h增, V增, Fb, H
- 验证结果：流速验证 + 超高复核

**详细模式（19步计算过程）**：
1. 设计底宽 B
2. 设计水深 h
3. 宽深比 β = B/h
4. 过水面积 A = (B + m×h)×h（含展开式）
5. 湿周 χ = B + 2h√(1+m²)（含展开式）
6. 水力半径 R = A/χ
7. 曼宁公式流速 V（含展开式）
8. 流量校核 Q计算 = V×A
9. 加大流量 Q增 = Q×(1+加大比例)
10. 加大水深 h增（反算）
11. 加大过水面积 A增
12. 加大湿周 χ增
13. 加大水力半径 R增
14. 加大流速 V增（曼宁公式展开）
15. 流量校核 Q校核 = V增×A增
16. 岸顶超高 Fb = (1/4)×h增 + 0.2
17. 渠道高度 H = h增 + Fb
18. 流速验证
19. 超高复核

#### 5.3.3 圆形结果内容

**简要模式**：
- 输入参数 → 断面尺寸(D) → 设计工况 → 加大工况 → 验证结果

**详细模式（26步计算过程）**：
1. 计算直径 / 设计直径
2–3. 管道总断面积
4. 设计水深（反算）
5. 圆心角 θ = 2·arccos((R-h)/R)
6. 过水面积 A = (D²/8)(θ-sinθ)
7. 湿周 χ = (D/2)·θ
8. 水力半径 R = A/χ
9. 曼宁公式流速
10. 流量校核
11. 净空高度 Fb = D - h
12. 净空面积 PA
13–22. 加大工况（同上结构）
23. 流速验证（v_min ≤ V ≤ v_max）
24. 净空高度验证（Fb ≥ 0.4m）
25. 净空面积验证（PA ≥ 15%）
26. 最小流速验证（V_min ≥ v_min）

#### 5.3.4 附录E方案对比表

当使用附录E算法计算时，在结果中嵌入HTML styled table：

| 列 | 内容 |
|----|------|
| α值 | 1.00 ~ 1.05 |
| 方案类型 | 水力最佳/实用经济 |
| 底宽B(m) | 计算值 |
| 水深h(m) | 计算值 |
| 宽深比β | 计算值 |
| 流速V(m/s) | 计算值 |
| 面积增加 | +0% ~ +5% |
| 状态 | ★选中 / 流速不符 / 空 |

### 5.4 断面图绘制（matplotlib）

#### 5.4.1 梯形/矩形

- 双子图：设计流量 + 加大流量
- 轮廓线（黑色实线）
- 水面填充（浅蓝半透明）
- 底宽标注 B（灰色双箭头）
- 渠高标注 H（紫色双箭头）
- 水深标注 h（蓝色双箭头）
- 地面线（棕色粗线）
- 等比例坐标轴

#### 5.4.2 圆形

- 单子图
- 轮廓圆（黑色实线）
- 水面弧面填充（浅蓝半透明）
- 直径标注 D（灰色双箭头）
- 水深标注 y（蓝色双箭头）
- 地面基准线（棕色粗线 + 虚线延伸）

---

## 六、DXF 导出

### 6.1 出图规格

| 项目 | 说明 |
|------|------|
| DXF版本 | R2010 |
| 单位 | mm（图纸单位） |
| 度量 | 公制 |
| 比例尺 | 用户选择（1:20 / 1:50 / 1:100 / 1:200 / 1:500） |

### 6.2 图层定义

| 图层名 | ACI颜色 | 线宽 | 内容 |
|--------|---------|------|------|
| `OUTLINE` | 7 (白/黑) | 50 | 断面轮廓线 |
| `WATER_DESIGN` | 5 (蓝) | 25 | 设计水面线 |
| `WATER_INCREASED` | 4 (青) | 25 | 加大水面线（虚线） |
| `DIMENSION` | 2 (黄) | 18 | 尺寸标注 |
| `TEXT_PARAMS` | 3 (绿) | 18 | 参数文字块 |

### 6.3 图形内容

#### 6.3.1 梯形/矩形

1. **轮廓线** — 底边 + 两侧边坡 + 顶边（闭合多边形）
2. **设计水面线** — 水平线 + 水位标注文字 `▽ 设计水位 h=...m`
3. **加大水面线** — 虚线 + 水位标注文字 `▽ 加大水位 h=...m`
4. **尺寸标注**：
   - 水平：底宽 `B=...m`（底部）
   - 垂直：设计水深 `h=...m`（左侧）
   - 垂直：渠道高度 `H=...m`（右侧）
   - 坡比文字 `1:m`（斜面上）
5. **参数文字块**（右侧）：输入参数 + 断面尺寸 + 设计/加大工况结果

#### 6.3.2 圆形

1. **轮廓圆** + 地面基准虚线
2. **设计水面线** — 弦线 + 标注
3. **加大水面线** — 虚线弦 + 标注
4. **尺寸标注**：
   - 直径 `D=...m`（底部水平）
   - 水深 `y=...m`（左侧垂直）
   - 净空 `Fb=...m`（右侧垂直）
   - 半径线 + `R=...m`（45°方向）
5. **参数文字块**（右侧）

### 6.4 标注细节

- 箭头：实心三角形（SOLID图元）
- 延伸线：超出尺寸线0.5×箭头长度
- 文字高度：按比例自适应（`char × 0.055`）
- 文字块逐行输出，标题行/正文行区分字号

---

## 七、Word 导出

### 7.1 报告结构

```
封面页（标题 + 副标题 + 页眉）
├── 一、基础公式（LaTeX → OMML可编辑公式）
│   ├── 曼宁公式
│   ├── 过水面积公式（分断面类型）
│   ├── 湿周公式
│   ├── 水力半径公式
│   └── 流速公式
├── 二、计算过程（纯文本 → styled Word段落）
├── 三、断面方案对比（附录E表格，仅梯形/矩形）
└── 四、断面图（matplotlib截图嵌入，14cm宽）
```

### 7.2 公式技术

- LaTeX → MathML (latex2mathml) → OMML (MML2OMML.XSL) → Word可编辑公式
- 回退：纯文本公式行识别 + 自动LaTeX转换

### 7.3 依赖

- `python-docx` — Word文档生成
- `latex2mathml` — LaTeX → MathML
- `lxml` — XSLT转换
- Office MML2OMML.XSL — MathML → OMML

---

## 八、与其他模块的集成

### 8.1 批量计算面板

`渠系断面设计/batch/panel.py` 支持明渠所有断面类型的批量输入、计算和结果汇总。

结构类型映射：`明渠-梯形`, `明渠-矩形`, `明渠-圆形`

调用引擎：
- `mingqu_calculate`（梯形/矩形）
- `circular_calculate`（圆形）

### 8.2 土石方模块跨面板读取

`土石方计算/ui/panel.py` 中的 "↑ 从明渠设计模块读取当前参数" 按钮，通过主窗口父链访问 `OpenChannelPanel` 的 `m_edit`, `b_edit`, `current_result`，将设计断面参数复用到土石方计算。

### 8.3 推求水面线模块

通过 `shared_data_manager` 共享断面参数。批量计算面板的结果可推送到推求水面线模块。

---

## 九、设计验证规则

### 9.1 梯形/矩形

| 验证项 | 条件 | 依据 |
|--------|------|------|
| 流速验证 | `v_min < V < v_max` | 不淤/不冲流速约束 |
| 超高复核 | `Fb ≥ (1/4)×h增 + 0.2` | GB 50288-2018 §6.4.8-2 |
| 宽深比 | `0 < β ≤ 8` | 工程经验上限 |

### 9.2 圆形

| 验证项 | 条件 | 依据 |
|--------|------|------|
| 设计流速 | `v_min ≤ V ≤ v_max` | 不淤/不冲流速约束 |
| 加大流速 | `v_min ≤ V增 ≤ v_max` | 加大工况同验证 |
| 净空高度 | `Fb ≥ 0.4m` | 最小安全超高 |
| 净空面积 | `PA ≥ 15%` | 最小净空比例 |
| 最小流速 | `V_min ≥ v_min` | 最小工况不淤 |

---

## 十、技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.x |
| UI框架 | PySide6 (Qt 6) |
| UI组件 | qfluentwidgets (Fluent Design) |
| 图表 | matplotlib (QtAgg backend) |
| 公式渲染 | matplotlib mathtext → SVG（界面） / KaTeX（备选） |
| 公式导出 | LaTeX → MathML → OMML（Word可编辑公式） |
| DXF | ezdxf |
| Word | python-docx + latex2mathml + lxml |
| 数值 | numpy（断面绘图） |

---

## 十一、API 速查

### 11.1 计算引擎（`明渠设计.py`）

```python
# 梯形明渠
quick_calculate_trapezoidal(Q, m, n, slope_inv, v_min, v_max,
                            manual_beta=None, manual_b=None,
                            manual_increase_percent=None) → Dict

# 矩形明渠（m=0特例）
quick_calculate_rectangular(Q, n, slope_inv, v_min, v_max, ...) → Dict

# 圆形明渠
quick_calculate_circular(Q, n, slope_inv, v_min, v_max,
                         increase_percent=None, manual_D=None) → Dict

# U形明渠
quick_calculate_u_section(Q, R, alpha_deg, theta_deg, n, slope_inv,
                          v_min, v_max,
                          manual_increase_percent=None) → Dict

# 统一接口
design_channel(section_type: SectionType, **kwargs) → Dict

# 向后兼容
quick_calculate(Q, m, n, slope_inv, v_min, v_max, ...) → Dict
```

### 11.2 DXF 导出（`dxf_export.py`）

```python
export_open_channel_dxf(filepath, result, input_params, scale_denom=100)
```

### 11.3 UI 面板（`panel.py`）

```python
class OpenChannelPanel(QWidget):
    # 主要属性
    input_params: dict          # 当前输入参数
    current_result: dict        # 当前计算结果
    m_edit: LineEdit            # 边坡系数输入框（土石方模块跨面板读取）
    b_edit: LineEdit            # 底宽输入框（土石方模块跨面板读取）
```

---

## 附录A：测试用例（内置 `__main__`）

```python
# 梯形明渠
quick_calculate_trapezoidal(Q=5.0, m=1.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)

# 矩形明渠
quick_calculate_rectangular(Q=2.0, n=0.014, slope_inv=2000, v_min=0.4, v_max=2.5)

# 圆形明渠
quick_calculate_circular(Q=5.0, n=0.014, slope_inv=1000, v_min=0.6, v_max=3.0)

# U形明渠
quick_calculate_u_section(Q=2.0, R=0.8, alpha_deg=14, theta_deg=152,
                          n=0.014, slope_inv=3000, v_min=0.1, v_max=100)

# 统一接口测试
design_channel(SectionType.TRAPEZOIDAL, Q=10.0, n=0.016, slope_inv=5000, v_min=0.6, v_max=2.5, m=1.5)
design_channel(SectionType.RECTANGULAR, Q=10.0, n=0.016, slope_inv=5000, v_min=0.6, v_max=2.5)
design_channel(SectionType.CIRCULAR,    Q=10.0, n=0.016, slope_inv=5000, v_min=0.6, v_max=2.5)
design_channel(SectionType.U_SECTION,   Q=2.0,  n=0.014, slope_inv=3000, v_min=0.1, v_max=100,
               arc_radius=0.8, alpha_deg=14, theta_deg=152)
```

---

## 附录B：变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-02-22 | 创建。担梯形/矩形/圆形三种断面类型，完整计算引擎 + UI + DXF导出 + 批量计算集成 |
| v1.1 | 2026-02-25 | 新增U形明渠断面类型。改动点：(1)明渠设计.py新增SectionType.U_SECTION、_u_arc_geometry、calculate_u_depth_for_flow、quick_calculate_u_section；(2)open_channel/panel.py UI/计算/结果显示/DXF/Word全链路；(3)open_channel/dxf_export.py _draw_u_section；(4)batch/panel.py批量计算+示例数据增至46行；(5)structure_type_selector.py明渠分类新增U形；(6)推求水面线全链路支持（enums/data_models/calculator/hydraulic_calc/shared_data_manager/water_profile面板）；(7)新增test21/22/23 U形测试 |
