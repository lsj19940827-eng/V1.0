# 隧洞水力计算模块 — 产品需求文档 (PRD)

> **版本**: v1.4
> **创建日期**: 2026-02-22  
> **最后更新**: 2026-04-23
> **状态**: 已实现  

---

## 1. 概述

### 1.1 模块定位

隧洞水力计算模块是「渠系建筑物水力计算系统」的核心子模块之一，负责隧洞断面的水力设计计算。模块集成在主应用侧边导航中，通过 `TunnelPanel` 提供完整的交互界面。

### 1.2 功能摘要

- 支持 **5种断面类型**：圆形、平底圆形、圆拱直墙型、马蹄形标准Ⅰ型、马蹄形标准Ⅱ型
- 基于 **曼宁公式** 进行水力计算
- 对圆形 / 圆拱直墙型 / 马蹄形自动搜索满足约束条件的 **最优断面尺寸**
- 对平底圆形固定采用 **直径 D + 平底宽 B** 两输入，程序自动推导 **总高 H_total**
- 计算 **设计流量** 与 **加大流量** 两种工况
- 支持 **详细计算过程** 输出（含公式推导）
- 导出 **DXF断面图**、**Word计算书**
- 内置 **断面图matplotlib预览**（设计/加大双工况对比）
- 批量/共享/导入链路统一使用 `隧洞-平底圆形`，表3只允许导入复算，不开放手动新选
- `暗涵-圆拱直墙型` 不属于本模块；当前只复用圆拱直墙几何 helper，净空、表1/表3、断面汇总和导出口径都回到暗涵设计链路处理。

### 1.3 当前实现同步（2026-04-17）

- 加大流量输入已统一为 `按比例` / `按Q加大` 两种模式，保留原“考虑加大流量比例系数”开关，默认仍按比例模式。
- `按比例` 可留空，留空时继续按规范表自动取值；`按Q加大` 输入的是加大后的总流量，必须大于设计流量 `Q`。
- 多工况保存新增 `inc_mode / inc_q_text`；旧工程若只有 `inc_pct`，重开后仍按原比例方式回显。
- 切换模式时只保留一项正式输入，另一项只做灰色换算提示；关闭开关时只隐藏，不清空上次输入。
- 首次进入面板时也必须立即按当前模式收口显示；默认只显示“按比例”输入，不得把“按Q加大”一栏一起显示出来。
- 结果页、TXT、Word、DXF 会统一写出输入方式、用户输入值和系统换算值。
- 加大流量链路的内部计算已统一为高精度直传：比例、倍率和 `Q加大` 不会在进入后续水深 / 流速 / 净空计算前提前 round。
- 加大比例统一显示为 3 位小数，公式代入中的比例小数 / 倍率统一显示为 5 位。

### 1.4 当前实现同步（2026-04-23）

- 点击【清空】只清除计算结果、断面图、结果导航和导出缓存；左侧输入参数、加大流量模式与多工况列表保持用户当前输入，不再恢复程序默认值。

---

## 2. 文件结构

```
calc_渠系计算算法内核/
  隧洞设计.py              # 计算内核（1154行）

app_渠系计算前端/
  dxf_common.py            # 断面 DXF 共享图层 / 偏移 / 网格布局工具
  dxf_multi_export.py      # 多工况 DXF 导出弹窗与合并导出工具
  tunnel/
    __init__.py            # 模块声明
    panel.py               # UI面板 TunnelPanel（1069行）
    geometry.py            # 断面共享几何辅助（预览 / DXF 共用）
    dxf_export.py          # DXF断面图导出（209行）

tests/
  test_tunnel_kernel.py    # 全面测试脚本（1013行，15个测试组）
  test_tunnel_flat_bottom_circular_kernel_unit.py
  test_tunnel_flat_bottom_circular_shared_hydraulic_unit.py
  test_tunnel_flat_bottom_circular_dxf_unit.py
  test_tunnel_flat_bottom_circular_panel_batch_unit.py
```

---

## 3. 断面类型详细规格

### 3.1 圆形断面

| 参数 | 值 | 说明 |
|------|-----|------|
| 最小直径 | 2.0 m | `MIN_DIAMETER_CIRC` |
| 搜索范围 | 2.0 ~ 20.0 m | 步长 0.01 m |
| 几何高度 | D（直径） | |
| 总面积 | A = π × D² / 4 | |

**过水面积公式**（弓形面积）:
```
θ = 2 × arccos((R - h) / R)
A = R² × (θ - sinθ) / 2
```

**湿周公式**:
```
χ = R × θ
```

### 3.2 平底圆形断面

| 参数 | 值 | 说明 |
|------|-----|------|
| 最小直径 | 2.0 m | 复用 `MIN_DIAMETER_CIRC` |
| 用户输入 | `D + B` | `D` 为洞径，`B` 为平底宽 |
| 校验范围 | `D >= 2.0`，`0 < B ≤ D` | 允许 `B = D`，此时退化为半圆 |
| 手工模式 | 仅指定尺寸 | 不提供自动寻优，不提供“削底高度”第三参数 |
| 表3策略 | 仅导入复算 | 不进入表3手动结构选择器 |

**几何定义**:
- 以直径 `D` 的完整圆为母形；
- 用一条水平、居中的弦切去下部圆弓，仅保留上部断面；
- 底边就是这条弦，宽度为 `B`。

记 `R = D / 2`，`y_c = sqrt(R² - (B/2)²)`，则:
```
h_cut = R - y_c
H_total = R + y_c
θ_cut = 2 × arcsin(B / D)
A_total = πR² - R² × (θ_cut - sinθ_cut) / 2
```

**过水面积公式**（复用完整圆弓形面积差）:
```
A(h) = A_circle(h_cut + h) - A_circle(h_cut)
0 ≤ h ≤ H_total
```

**湿周公式**:
```
χ(h) = B + 2R × (arcsin((h - y_c)/R) + arcsin(y_c/R))
```

**水面宽公式**:
```
T(h) = 2 × sqrt(R² - (h - y_c)²)
0 < h < H_total
```

### 3.3 圆拱直墙型断面

> 范围边界：本节仅描述 `隧洞-圆拱直墙型`。`暗涵-圆拱直墙型` 可复用本节几何公式，但不得复用隧洞的最小高度、最小宽度、高宽比、围岩或 `xx管` 隧洞摘要规则。

| 参数 | 值 | 说明 |
|------|-----|------|
| 最小高度 | 2.0 m | `MIN_HEIGHT_HS` |
| 最小宽度 | 1.8 m | `MIN_WIDTH_HS` |
| 高宽比范围 | 1.0 ~ 1.5 | `HB_RATIO_MIN` / `HB_RATIO_MAX` |
| 拱顶圆心角 | 90° ~ 180° | 默认 180°（半圆拱） |
| 搜索范围(B) | 1.8 ~ 20.0 m | 粗搜索步长 0.1m，精细搜索步长 0.01m |

**几何结构**:
- 底部矩形：宽 B，高 H_straight
- 顶部圆拱：拱半径 R_arch = (B/2) / sin(θ/2)，拱高 H_arch = R_arch × (1 - cos(θ/2))
- 总高 H_total = H_straight + H_arch

**过水面积计算**（分段）:
- h ≤ H_straight: A = B × h
- h > H_straight: A = 直墙矩形面积 + 拱部过水面积

**搜索优化**:
1. 粗搜索：B步长0.1m，HB比步长0.05 → 减少90%搜索次数
2. 最优解附近精细搜索：±0.3m范围内，B步长0.01m，HB比步长0.01
3. 以最小总面积 `A_total` 为优化目标

### 3.4 马蹄形标准Ⅰ型

| 参数 | 值 | 常量名 |
|------|-----|--------|
| t | 3.0 | `HORSESHOE_T1` |
| θ | 0.294515 rad (16.874°) | `HORSESHOE_THETA1` |
| c | 0.201996 | `HORSESHOE_C1` |
| 底拱半径 | R = t × r = 3r | |
| 最小半径 | 1.0 m | `MIN_RADIUS_HORSESHOE_STD` |
| 搜索范围 | 1.0 ~ 10.0 m | 步长 0.01 m |

适用于地质条件 **较好** 的隧洞。

### 3.5 马蹄形标准Ⅱ型

| 参数 | 值 | 常量名 |
|------|-----|--------|
| t | 2.0 | `HORSESHOE_T2` |
| θ | 0.424031 rad (24.295°) | `HORSESHOE_THETA2` |
| c | 0.436624 | `HORSESHOE_C2` |
| 底拱半径 | R = t × r = 2r | |
| 最小半径 | 1.0 m | `MIN_RADIUS_HORSESHOE_STD` |
| 搜索范围 | 1.0 ~ 10.0 m | 步长 0.01 m |

适用于地质条件 **一般** 的隧洞。

### 3.6 马蹄形断面几何计算（Ⅰ/Ⅱ型通用）

断面分为 **三段**，底拱段高度 e = R_arch × (1 - cosθ):

**① 底拱段** (0 ≤ h ≤ e):
```
β = arccos(1 - h / R_arch)
A = (t×r)² × (β - 0.5×sin(2β))
B = 2×t×r×sin(β)
χ = 2×R_arch×β
```

**② 侧拱段** (e < h ≤ r):
```
α = arcsin((1 - h/r) / t)
A = R_arch² × (c - α - 0.5×sin(2α) + ((2t-2)/t)×sin(α))
B = 2×r×(t×cos(α) - t + 1)
χ = 2×t×r×(2θ - α)
```

**③ 顶拱段** (r < h ≤ 2r):
```
φ/2 = arccos(h/r - 1), φ = 2×(φ/2)
A = r² × (t²×c + 0.5×(π - φ + sin(φ)))
B = 2×r×sin(φ/2)
χ = 4×t×r×θ + r×(π - φ)
```

**分段连续性要求**: A 在 h=e 和 h=r 处必须连续（误差 < 0.01 m²）。

---

## 4. 水力计算核心

### 4.1 曼宁公式

```
Q = (1/n) × A × R^(2/3) × i^(1/2)
R = A / χ       （水力半径）
V = Q / A       （流速）
```

其中:
- Q: 流量 (m³/s)
- n: 糙率
- A: 过水面积 (m²)
- χ: 湿周 (m)
- R: 水力半径 (m)
- i: 水力坡降
- V: 流速 (m/s)

### 4.2 水深求解

采用 **二分法** 反算水深:
- 容差: `SOLVER_TOLERANCE = 0.0001`（相对误差）
- 最大迭代: `MAX_ITERATIONS = 100`
- 搜索范围: `[0.00001, H_total]`
- 先检查上下界是否满足，再进行二分迭代
- 最终校核容差放宽至 1.5 倍

### 4.3 断面尺寸搜索

搜索算法按以下约束逐步筛选:
1. 设计水深 h_design < 断面高度
2. 设计流速 v_min ≤ V_design ≤ v_max
3. 设计净空高度 ≥ 0.4 m
4. 设计净空面积比 ≥ 15%
5. 加大水深 h_increased < 断面高度
6. 加大流速 V_increased ≤ v_max
7. 加大净空高度 ≥ 0.4 m
8. 加大净空面积比 ≥ 15%

找到满足所有约束的 **最小尺寸** 即停止（圆形/马蹄形），或 **最小总面积** 方案（圆拱直墙型）。

### 4.4 净空约束

| 约束项 | 值 | 常量名 |
|--------|-----|--------|
| 最小净空面积比 | 15% | `MIN_FREEBOARD_PCT_TUNNEL` |
| 最小净空高度 | 0.4 m | `MIN_FREEBOARD_HGT_TUNNEL` |

净空计算:
- **净空面积比**: (A_total - A_water) / A_total × 100%
- **净空高度**: H_total - h（圆形为 D-h，马蹄形为 2r-h）

### 4.5 加大流量比例

根据设计流量 Q 查表自动确定（也可指定）:

| 设计流量 Q (m³/s) | 加大比例 |
|-------------------|---------|
| Q < 1 | 30% |
| 1 ≤ Q < 5 | 25% |
| 5 ≤ Q < 20 | 20% |
| 20 ≤ Q < 50 | 15% |
| 50 ≤ Q < 100 | 10% |
| Q ≥ 100 | 5% |

函数: `get_flow_increase_percent(design_Q)`

---

## 5. 输入参数

### 5.1 通用参数（所有断面类型）

| 参数 | 字段 | 默认值 | 必填 | 说明 |
|------|------|--------|------|------|
| 设计流量 Q | `Q_edit` | 10.0 | ✅ | m³/s，必须>0 |
| 糙率 n | `n_edit` | 0.014 | ✅ | 必须>0 |
| 水力坡降 1/ | `slope_edit` | 2000 | ✅ | 倒数输入，必须>0 |
| 不淤流速 | `vmin_edit` | 0.1 | ✅ | m/s |
| 不冲流速 | `vmax_edit` | 100.0 | ✅ | m/s，必须>不淤流速 |
| 流量加大比例 | `inc_edit` | 留空 | ❌ | %，留空自动查表 |

### 5.2 圆形断面专用参数

| 参数 | 字段 | 默认值 | 必填 | 说明 |
|------|------|--------|------|------|
| 指定直径 D | `D_edit` | 留空 | ❌ | m，留空自动搜索 |

### 5.3 平底圆形断面专用参数

| 参数 | 字段 | 默认值 | 必填 | 说明 |
|------|------|--------|------|------|
| 平底圆形直径 D | `flat_bottom_D_edit` | 留空 | ✅ | m，必须 `>= 2.0` |
| 平底宽 B | `flat_bottom_B_edit` | 留空 | ✅ | m，必须 `> 0` 且 `<= D` |

### 5.4 圆拱直墙型专用参数

| 参数 | 字段 | 默认值 | 必填 | 说明 |
|------|------|--------|------|------|
| 拱顶圆心角 | `theta_edit` | 180 | ❌ | 度，90~180 |
| 指定底宽 B | `B_hs_edit` | 留空 | ❌ | m，留空自动搜索 |

### 5.5 马蹄形专用参数

| 参数 | 字段 | 默认值 | 必填 | 说明 |
|------|------|--------|------|------|
| 指定半径 r | `r_edit` | 留空 | ❌ | m，留空自动搜索 |

---

## 6. 输出结果

### 6.1 计算结果字段（result dict）

**通用字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 计算是否成功 |
| `error_message` | str | 失败时的错误信息 |
| `section_type` | str | 断面类型名称 |
| `design_method` | str | 设计方案描述字符串 |
| `A_total` | float | 断面总面积 (m²) |
| `h_design` | float | 设计水深 (m) |
| `V_design` | float | 设计流速 (m/s) |
| `A_design` | float | 设计过水面积 (m²) |
| `P_design` | float | 设计湿周 (m) |
| `R_hyd_design` | float | 设计水力半径 (m) |
| `Q_calc` | float | 计算流量校核 (m³/s) |
| `freeboard_pct_design` | float | 设计净空面积比 (%) |
| `freeboard_hgt_design` | float | 设计净空高度 (m) |
| `increase_percent` | float | 加大比例 (%) |
| `Q_increased` | float | 加大流量 (m³/s) |
| `h_increased` | float | 加大水深 (m) |
| `V_increased` | float | 加大流速 (m/s) |
| `A_increased` | float | 加大过水面积 (m²) |
| `P_increased` | float | 加大湿周 (m) |
| `R_hyd_increased` | float | 加大水力半径 (m) |
| `freeboard_pct_inc` | float | 加大净空面积比 (%) |
| `freeboard_hgt_inc` | float | 加大净空高度 (m) |

**圆形断面专用**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `D` | float | 直径 (m) |

**平底圆形断面专用**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `D` | float | 洞径 (m) |
| `B` | float | 平底宽 (m) |
| `H_total` | float | 程序推导总高 (m) |

**圆拱直墙型专用**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `B` | float | 底宽 (m) |
| `H_total` | float | 总高 (m) |
| `H_straight` | float | 直墙高度 (m) |
| `theta_deg` | float | 圆心角 (度) |
| `HB_ratio` | float | 高宽比 H/B |

**马蹄形专用**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `r` | float | 马蹄形半径 (m) |
| `D_equiv` | float | 等效直径 2r (m) |

### 6.2 结果一致性约束

以下一致性必须满足（测试覆盖）:
- `R_hyd_design = A_design / P_design`
- `V_design × A_design ≈ Q`（相对误差 < 2%）
- `h_design < h_increased`（加大流量水深更大）
- `V_increased ≥ V_design`（加大流量流速更大）
- `Q_increased = Q × (1 + increase_percent / 100)`
- `freeboard_hgt_design = H_total - h_design`
- `design_method` 非空字符串

---

## 7. UI面板规格

### 7.1 布局

- **左侧**: 输入参数面板（可滚动，宽度 280~420px）
- **右侧**: 输出区域（QTabWidget，两个Tab）
  - Tab1「计算结果」: QWebEngineView 显示格式化计算过程
  - Tab2「断面图」: matplotlib Figure + NavigationToolbar

### 7.2 输入区域

- 断面类型下拉框（ComboBox）切换时动态显示/隐藏对应参数组:
  - 圆形 → `circ_grp`（指定直径 D）
  - 平底圆形 → `flat_bottom_grp`（直径 D + 平底宽 B）
  - 圆拱直墙型 → `hs_grp`（圆心角 θ + 指定底宽 B）
  - 马蹄形标准Ⅰ型/Ⅱ型 → `shoe_grp`（指定半径 r）
- 通用参数始终可见
- 「考虑加大流量比例系数」CheckBox（`inc_cb`，默认勾选）：勾选时显示流量加大比例输入框和动态提示标签，不勾选时隐藏并以 `manual_increase_percent=0` 传入计算内核
- 「输出详细计算过程」复选框（默认勾选）

### 7.3 操作按钮

| 按钮 | 功能 |
|------|------|
| **计算** | PrimaryPushButton，执行水力计算 |
| **清空** | PushButton，清除计算结果并重置为初始帮助页，保留用户输入与多工况 |
| **导出DXF** | PushButton；单工况直接选择比例尺并导出，多工况弹出共享 DXF 范围对话框 |
| **导出Word** | PushButton，生成Word计算书 |

### 7.4 初始帮助页

通过 `HelpPageBuilder` 构建，包含:
- 支持断面类型列表（5种，含各自特点说明）
- 曼宁公式
- 净空约束条件
- 加大流量比例规范表

### 7.5 计算结果显示

**简要模式**（detail_cb 未勾选）:
- 输入参数 → 断面尺寸 → 设计流量工况 → 加大流量工况（仅勾选时） → 验证结果

**加大流量条件化显示**：当 `use_increase=False`（不勾选“考虑加大流量比例系数”）时，简要/详细模式均跳过加大流量工况段落，验证结果仅使用设计流量工况数据（净空验证仅检查设计工况）。

**详细模式**（detail_cb 勾选，默认）:
- 输入参数（一）
- 断面尺寸（二）: 含面积公式展开
- 设计流量工况计算（三）: 20个步骤
  1. 设计水深
  2-3. 圆心角/过水面积/湿周（按断面类型分支展开公式）
  4. 水力半径 R = A/χ
  5. 设计流速（曼宁公式展开）
  6. 流量校核
  7. 净空面积计算
  8. 净空高度计算
- 加大流量工况计算（四）（仅勾选时）: 步骤 9-17
  9. 加大流量计算
  10. 加大水深
  11-12. 加大过水面积/湿周
  13. 加大水力半径
  14. 加大流速
  15. 加大流量校核
  16. 加大净空面积
  17. 加大净空高度
- 设计验证（五）: 步骤 18-20
  18. 流速验证（v_min ≤ V ≤ v_max）
  19. 净空面积验证（≥ 15%）（勾选时用加大工况，不勾选时用设计工况）
  20. 净空高度验证（≥ 0.4m）（同上）

输出通过 `plain_text_to_formula_html()` 转换后加载到 `QWebEngineView`。

### 7.6 断面图预览

matplotlib 绘制，1行2列子图:
- **左图**: 设计流量工况
- **右图**: 加大流量工况

每幅图包含:
- 断面轮廓（黑色实线）
- 水面线（蓝色填充）
- 尺寸标注（箭头+文字）
- 标题（断面类型 + Q + V）
- 网格线 + 等比例

三种断面类型各有独立绘制方法:
- `_draw_circular()`: 圆形轮廓 + 弓形水面
- `_draw_flat_bottom_circle()`: 平底圆形轮廓 + 水平底边 + 圆弧顶 + 分段水面填充
- `_draw_horseshoe()`: 底板 + 直墙 + 拱部 + 分区水面填充
- `_draw_horseshoe_std()`: 精确轮廓曲线（100点采样）+ 水面填充

---

## 8. DXF 导出规格

### 8.1 文件格式

- DXF版本: R2010
- 单位: mm (`$INSUNITS=4`, `$MEASUREMENT=1`)
- 线型比例: `$LTSCALE = sf × 0.5`

### 8.2 图层定义

| 图层名 | 颜色 | 线宽 | 用途 |
|--------|------|------|------|
| `轮廓线` | 7 (白) | 50 | 断面轮廓 |
| `设计水位` | 5 (蓝) | 25 | 设计水位线 |
| `加大水位` | 4 (青) | 25 | 加大水位线（虚线 DASHED） |
| `尺寸标注` | 2 (黄) | 18 | 尺寸标注 |
| `参数文字` | 3 (绿) | 18 | 参数文字块 |

### 8.3 缩放机制

- 缩放因子: `sf = 1000.0 / scale_denom`
- 支持比例尺: 1:20, 1:50, 1:100（默认）, 1:200, 1:500
- 单工况导出前弹出比例尺选择
- 多工况导出前弹出共享 DXF 对话框，固定包含导出范围（当前工况 / 勾选多个工况 / 全部工况）、比例尺和工况勾选列表

### 8.4 各断面绘制内容

### 当前实现同步说明（2026-03-22）

- 圆拱直墙型 DXF 已改为与界面断面图共用同一套几何公式，不再单独手写另一套圆心坐标。
- 平底圆形 DXF 已改为与界面断面图、表3复算共用同一套共享几何 helper；轮廓固定画成 `1 条水平底边 LWPOLYLINE + 1 条原生 ARC`。
- 圆拱直墙型轮廓已改为：`1 条 LWPOLYLINE`（底板+直墙） + `1 条 ARC`（拱顶），导出后拱脚与直墙顶严格重合，不再出现断面不闭合。
- 马蹄形标准Ⅰ型 / Ⅱ型轮廓已改为 `4 条 ARC` 精确拼接，不再使用采样折线逼近。
- 圆拱直墙型水位线宽度已按真实拱部几何计算；进入拱部后不会再按固定底宽 B 直接画满。
- 多工况导出时，“当前工况”固定以左侧输入区当前激活标签 `_current_case_idx` 为准，不再从 `current_result` / `input_params` 推断，也不再落到最后一个工况。
- 多工况 DXF 对话框固定支持 `当前工况`、`勾选多个工况`、`全部工况` 三种范围；切到“勾选多个工况”时默认仅勾选当前工况。
- 当最终有效工况数大于 1 时，导出结果为 1 个合并 DXF，采用自动网格排版：`ncols = ceil(sqrt(n))`、`nrows = ceil(n / ncols)`，按从左到右、从上到下摆放。
- 合并 DXF 中每个工况块都使用独立图层前缀，例如 `工况1_轮廓线`、`工况1_设计水位`，便于在 CAD 中按工况开关显示。
- 无效工况定义为：无计算结果、计算失败、或当前面板 `_results_dirty=True`；批量导出时会自动跳过，并在完成后汇总提示“已导出 M 个工况，跳过 X 个无效工况”。

**圆形** (`_draw_circ`):
- 圆形轮廓（`add_circle`）
- 中心线（虚线）
- 设计/加大水位线 + 水位文字标注
- 直径标注、水深标注、净空标注、半径标注
- 参数文字块（输入参数 + 断面 + 设计/加大工况）

**平底圆形** (`_draw_flat_bottom_circ`):
- 水平底边（`LWPOLYLINE`）
- 上部原生圆弧（`ARC`）
- 设计/加大水位线 + 水位文字标注
- `D / B / H_total / h / 净空` 标注
- 参数文字块（统一显示 `D + B + H_total`）

**圆拱直墙型** (`_draw_arch`):
- 底板 + 左右直墙开放多段线（`LWPOLYLINE`）
- 拱部原生圆弧（`ARC`）
- 水位线 + 标注
- B/h/H/θ 标注
- 参数文字块

**马蹄形** (`_draw_shoe`):
- 底拱 1 段圆弧 + 左右侧拱 2 段圆弧 + 顶拱 1 段圆弧
- 水位线 + 标注
- 2r/h/H/r 标注
- 参数文字块（含标准Ⅰ型/Ⅱ型名称）

### 8.5 公共绘图工具

复用自 `app_渠系计算前端.dxf_common` 与 `app_渠系计算前端.dxf_multi_export`:
- `ensure_section_dxf_layers()` / `setup_section_dxf_document()`: 创建共享图层、字体与标注样式
- `TrackedSectionMsp`: 为单工况绘图提供偏移包装与包络尺寸统计
- `_add_dim_h()` / `_add_dim_v()` / `_add_text_block()`: 通用尺寸标注与参数文字块
- `compute_auto_grid()` / `export_combined_case_dxf()`: 多工况合并 DXF 自动网格布局与保存

---

## 9. Word 导出规格

### 9.1 依赖

- `python-docx`
- `latex2mathml`
- `lxml`

如未安装，按钮点击时 InfoBar 提示安装命令。

### 9.2 报告结构

使用 `create_styled_doc()` 创建高端咨询报告风格文档:
- **封面**: 标题「隧洞水力计算书」+ 副标题（断面类型 + 设计方案）
- **一、基础公式**: 曼宁公式 + 水力半径公式（LaTeX渲染）
- **二、计算过程**: 从 `_export_plain_text` 渲染，跳过标题行
- **三、断面图**: 从 matplotlib Figure 导出 PNG 后插入（宽度14cm, 150dpi）

---

## 10. 计算内核 API

### 10.1 公开函数

文件: `calc_渠系计算算法内核/隧洞设计.py`

| 函数 | 说明 |
|------|------|
| `get_flow_increase_percent(design_Q)` | 查表返回加大比例 (%) |
| `get_required_freeboard_height(H_total)` | 返回最小净空高度 0.4m |
| `calculate_circular_area(D, h)` | 圆形过水面积 |
| `calculate_circular_perimeter(D, h)` | 圆形湿周 |
| `calculate_circular_outputs(D, h, n, slope)` | 圆形全部水力要素 |
| `solve_water_depth_circular(D, n, slope, Q_target)` | 圆形水深反算 |
| `quick_calculate_circular(Q, n, slope_inv, ...)` | **圆形一键计算** |
| `calculate_flat_bottom_circular_area(D, B, h)` | 平底圆形过水面积 |
| `calculate_flat_bottom_circular_perimeter(D, B, h)` | 平底圆形湿周 |
| `calculate_flat_bottom_circular_surface_width(D, B, h)` | 平底圆形水面宽 |
| `calculate_flat_bottom_circular_outputs(D, B, h, n, slope)` | 平底圆形全部水力要素 |
| `solve_water_depth_flat_bottom_circular(D, B, n, slope, Q_target)` | 平底圆形水深反算 |
| `quick_calculate_flat_bottom_circular(Q, n, slope_inv, ...)` | **平底圆形一键计算** |
| `calculate_horseshoe_area(B, H_total, theta_rad, h)` | 圆拱直墙过水面积 |
| `calculate_horseshoe_perimeter(B, H_total, theta_rad, h)` | 圆拱直墙湿周 |
| `calculate_horseshoe_total_area(B, H_total, theta_rad)` | 圆拱直墙总面积 |
| `calculate_horseshoe_outputs(B, H_total, theta_rad, h, n, slope)` | 圆拱直墙全部水力要素 |
| `solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q_target)` | 圆拱直墙水深反算 |
| `quick_calculate_horseshoe(Q, n, slope_inv, ...)` | **圆拱直墙一键计算** |
| `calculate_horseshoe_std_elements(section_type, r, h)` | 马蹄形水力要素 (A, B, P) |
| `calculate_horseshoe_std_outputs(section_type, r, h, n, slope)` | 马蹄形全部水力要素 |
| `solve_water_depth_horseshoe_std(section_type, r, n, slope, Q_target)` | 马蹄形水深反算 |
| `quick_calculate_horseshoe_std(Q, n, slope_inv, ...)` | **马蹄形一键计算** |

### 10.2 快速计算函数签名

```python
quick_calculate_circular(
    Q: float, n: float, slope_inv: float,
    v_min: float, v_max: float,
    manual_D: float = None,
    manual_increase_percent: float = None
) -> Dict[str, Any]

quick_calculate_flat_bottom_circular(
    Q: float, n: float, slope_inv: float,
    v_min: float, v_max: float,
    manual_D: float,
    manual_B: float,
    manual_increase_percent: float = None
) -> Dict[str, Any]

quick_calculate_horseshoe(
    Q: float, n: float, slope_inv: float,
    v_min: float, v_max: float,
    theta_deg: float = 180.0,
    manual_B: float = None,
    manual_increase_percent: float = None
) -> Dict[str, Any]

quick_calculate_horseshoe_std(
    Q: float, n: float, slope_inv: float,
    v_min: float, v_max: float,
    section_type: int,       # 1=标准Ⅰ型, 2=标准Ⅱ型
    manual_r: float = None,
    manual_increase_percent: float = None
) -> Dict[str, Any]
```

### 10.3 常量

```python
PI = 3.14159265358979
MIN_DIAMETER_CIRC = 2.0           # 圆形最小直径
MIN_HEIGHT_HS = 2.0               # 圆拱直墙最小高度
MIN_WIDTH_HS = 1.8                # 圆拱直墙最小宽度
HB_RATIO_MIN = 1.0               # 高宽比下限
HB_RATIO_MAX = 1.5               # 高宽比上限
MIN_RADIUS_HORSESHOE_STD = 1.0   # 马蹄形最小半径
MIN_FREEBOARD_PCT_TUNNEL = 0.15  # 最小净空面积比 15%
MIN_FREEBOARD_HGT_TUNNEL = 0.4   # 最小净空高度 0.4m
SOLVER_TOLERANCE = 0.0001        # 二分法相对容差
MAX_ITERATIONS = 100             # 最大迭代次数
DIM_INCREMENT = 0.01             # 尺寸搜索步长
```

---

## 11. 错误处理

### 11.1 输入校验

| 条件 | 处理 |
|------|------|
| Q ≤ 0 | 弹出错误提示 + 结果区显示错误 |
| n ≤ 0 | 弹出错误提示 |
| slope_inv ≤ 0 | 弹出错误提示（不触发 ZeroDivisionError） |
| v_min ≥ v_max | 弹出错误提示 |
| 圆拱直墙 θ ∉ [90°, 180°] | 返回 success=False + error_message |
| 马蹄形 section_type ∉ {1, 2} | 返回 success=False + error_message |
| 输入格式错误（非数字） | ValueError 捕获，提示检查必填参数 |

### 11.2 计算失败

当搜索范围内找不到满足约束的尺寸时:
- 指定尺寸: 提示"指定的尺寸无法满足要求" + 建议
- 自动搜索失败: 提示搜索范围 + 建议检查流量/坡降

### 11.3 导出异常

| 异常 | 处理 |
|------|------|
| `ImportError` (ezdxf/docx) | InfoBar 提示安装命令 |
| `PermissionError` | InfoBar 提示关闭同名文件 |
| 其他 Exception | InfoBar 显示错误信息 |

---

## 12. 测试覆盖

### 12.1 测试文件

- `tests/test_tunnel_kernel.py` — 原有圆形 / 圆拱直墙型 / 马蹄形回归
- `tests/test_tunnel_flat_bottom_circular_kernel_unit.py` — 平底圆形内核与边界条件
- `tests/test_tunnel_flat_bottom_circular_shared_hydraulic_unit.py` — 共享结果、表3导入复算与展示兜底
- `tests/test_tunnel_flat_bottom_circular_dxf_unit.py` — 平底圆形 DXF 轮廓连通性、总高一致性与极小水深边界
- `tests/test_tunnel_flat_bottom_circular_panel_batch_unit.py` — 单断面页、批量页、参数回填与 Word/TXT 标题链路
- `tests/test_tunnel_flat_bottom_circular_table3_xxpipe_unit.py` — 表3手工限制与 `xx管` 隧洞摘要链路
- `tests/test_tunnel_flat_bottom_circle_section_summary_unit.py` — 断面汇总独立分组、标题与配置入口

### 12.2 测试组清单

| # | 测试组 | 测试内容 | 用例数量级 |
|---|--------|----------|-----------|
| 1 | `test_circular_geometry` | 圆形面积/湿周 vs 独立验算 | ~30 |
| 2 | `test_circular_outputs` | 圆形水力要素 (R_hyd, V, Q, 净空) | ~64 |
| 3 | `test_circular_solver` | 圆形水深反算精度 (<1%) | ~24 |
| 4 | `test_circular_design` | 圆形完整设计（18组参数） | ~200+ |
| 5 | `test_horseshoe_geometry` | 圆拱直墙面积/湿周/总面积/单调性 | ~100+ |
| 6 | `test_horseshoe_solver` | 圆拱直墙水深反算 | ~16 |
| 7 | `test_horseshoe_design` | 圆拱直墙完整设计（14组参数） | ~200+ |
| 8 | `test_horseshoe_std_geometry` | 马蹄形Ⅰ/Ⅱ型几何 + 分段连续性 + 单调性 | ~200+ |
| 9 | `test_horseshoe_std_solver` | 马蹄形水深反算 | ~20 |
| 10 | `test_horseshoe_std_design` | 马蹄形完整设计（15组参数） | ~200+ |
| 11 | `test_flow_increase` | 加大流量查表 (19个Q值 + 边界) | ~21 |
| 12 | `test_boundary_conditions` | 异常输入 (Q=0, n=0, slope=0, θ越界, type=3, h>2r等) | ~15 |
| 13 | `test_outputs_field_validation` | 圆拱/马蹄形 outputs 字段独立验证 | ~60+ |
| 14 | `test_manual_params` | manual_increase_percent + manual_B/manual_D/manual_r | ~40+ |
| 15 | `test_consistency_and_misc` | h_d<h_inc 一致性, design_method非空, R_hyd=A/P, V_inc≥V_d | ~20 |

### 12.3 测试方法

- **独立验算函数**: 测试文件内有 `_circ_area`, `_circ_perim`, `_manning`, `_hs_area`, `_hs_perim`, `_hs_total_area`, `_shoe_elems` 等独立实现，与被测模块交叉验证
- **精度要求**: 面积/湿周绝对误差 < 0.001, 流量相对误差 < 2%, 水深反算相对误差 < 1%
- **运行方式**: `python tests/test_tunnel_kernel.py`

---

## 13. 技术栈与依赖

| 组件 | 用途 |
|------|------|
| **PySide6** | UI框架 |
| **qfluentwidgets** | Fluent风格控件 (ComboBox, PushButton, LineEdit, CheckBox, InfoBar) |
| **QWebEngineView** | 计算结果HTML渲染 |
| **matplotlib** | 断面图绘制 + NavigationToolbar |
| **numpy** | 绘图数据生成 |
| **ezdxf** | DXF文件导出（可选依赖） |
| **python-docx** | Word文档导出（可选依赖） |
| **latex2mathml + lxml** | Word公式渲染（可选依赖） |

---

## 14. 集成方式

### 14.1 主应用注册

文件: `app_渠系计算前端/app.py`

```python
from app_渠系计算前端.tunnel.panel import TunnelPanel
self.tunnel_panel = TunnelPanel()
self.stack.addWidget(self.tunnel_panel)
```

导航索引: **第3个**（明渠→渡槽→隧洞→矩形暗涵→...）

### 14.2 内核导入路径

`panel.py` 通过 `sys.path` 注入 `calc_渠系计算算法内核/` 目录后导入:
```python
from 隧洞设计 import (
    quick_calculate_circular,
    quick_calculate_horseshoe,
    quick_calculate_horseshoe_std,
    PI, MIN_FREEBOARD_PCT_TUNNEL, MIN_FREEBOARD_HGT_TUNNEL,
)
```

### 14.3 样式复用

从 `app_渠系计算前端.styles` 导入共享样式常量:
`P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE`

从 `app_渠系计算前端.export_utils` 导入共享导出工具。

从 `app_渠系计算前端.formula_renderer` 导入公式渲染工具:
`plain_text_to_formula_html, load_formula_page, make_plain_html, HelpPageBuilder`

---

## 15. 变更日志

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-02-22 | v1.0 | 初始版本，完整记录已实现功能 |
| 2026-02-25 | v1.1 | 新增“考虑加大流量比例系数”CheckBox控件（`inc_cb`，默认勾选）：不勾选时`manual_increase_percent=0`传入计算内核，简要/详细模式均跳过加大流量工况段落，验证结果仅使用设计流量数据。涉及文件：tunnel/panel.py |
| 2026-04-13 | v1.3 | 完成 `平底圆形` 隧洞断面全链路收口：表1参数弹窗回填与提示文案、单断面多工况与 Word/TXT 标题、DXF 总高一致性、表3手工输入拦截、`xx管` 隧洞摘要、断面汇总独立分组和对应测试全部补齐；表3继续只允许来源带入、不开放手动新选。 |
| 2026-04-14 | v1.4 | 文档口径同步：明确 `暗涵-圆拱直墙型` 不属于隧洞模块，只能复用圆拱直墙几何，不能复用隧洞约束、`xx管` 隧洞摘要或隧洞导出标题。 |
