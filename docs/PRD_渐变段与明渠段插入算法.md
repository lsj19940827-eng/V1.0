# PRD：渐变段（过渡段）完整需求规格说明书

> **版本**：v3.0 | **最后更新**：2026-03-06
>
> 整合推求水面线模块、倒虹吸水力计算系统、有压管道批量计算中所有与渐变段相关的需求，统一为一份完整文档。

---

## 一、概述

### 1.1 什么是渐变段

渐变段是连接不同断面形式或尺寸的水工建筑物之间的过渡段。当水流从一种断面过渡到另一种断面时，需要渐变段来平滑过渡，减少水头损失。

### 1.2 涉及的三个子系统

| 子系统 | 渐变段角色 | 说明 |
|--------|-----------|------|
| **推求水面线** | 渐变段行自动识别、插入、长度计算、水头损失计算 | 本文主要内容，§二~§十一 |
| **倒虹吸水力计算** | 进出口渐变段水面落差 ΔZ₁/ΔZ₃ | 独立计算，结果回写水面线；§十二 |
| **有压管道计算** | 进出口渐变段损失 | 独立计算，结果回写水面线；§十三 |

### 1.3 规范依据

| 规范 | 条文 | 用途 |
|------|------|------|
| GB 50288-2018 | §10.2.4 条1 | 倒虹吸/有压管道渐变段长度（进口5倍h，出口6倍h） |
| GB 50288-2018 | §10.3.6 | 倒虹吸出口渠底高程计算公式 |
| GB 50288-2018 | 附录K 表K.1.2 | 渡槽/隧洞/暗涵/明渠渐变段局部损失系数 |
| GB 50288-2018 | 附录L 表L.1.2 | 倒虹吸/有压管道渐变段局部损失系数 |
| GB 50288-2018 | 附录L 表L.1.4-3/4 | 弯管局部损失系数（有压管道复用） |

---

## 二、渐变段识别规则

### 2.1 需要插入渐变段的情况

`_needs_transition()` 按以下优先级依次判断：

| 规则 | 触发条件 | 说明 |
|------|---------|------|
| 1 | 倒虹吸相邻 | 倒虹吸水损已含进出口损失，**不插入** |
| 1b | 闸类结构 | 分水闸/分水口/泄水闸/节制闸为点状结构，**不触发渐变段** |
| 2 | 隧洞/渡槽 ↔ 明渠 | 总是插入，不检查底宽 |
| 3 | 隧洞/渡槽 ↔ 隧洞/渡槽（不同子类型） | 如圆形 → 圆拱直墙型，总是插入 |
| 4 | 倒虹吸 ↔ 明渠 | 总是插入（占位行，实际损失不计） |
| 5 | 明渠不同子类型 | 梯形 → 矩形 等，总是插入 |
| 6 | 同类型明渠但不同流量段 | 流量段变化视为不同断面 |
| 7 | **矩形暗涵 ↔ 明渠** | 特例见下表 |
| 8 | 断面特征尺寸不同 | 底宽/直径/换算半径不同时插入 |

#### 有效结构类型（参与渐变段判断）

```python
valid_type_values = {
    "隧洞-圆形", "隧洞-圆拱直墙型", "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型",
    "渡槽-U形", "渡槽-矩形",
    "明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形",
    "矩形暗涵", "倒虹吸",
}
```

不在此集合中的结构类型直接返回 `False`（不需要渐变段）。

#### 规则 7 细化（矩形暗涵 ↔ 明渠）

| 明渠子类型 | 与矩形暗涵底宽关系 | 是否插入渐变段 |
|-----------|-----------------|--------------|
| 矩形明渠 | 底宽相同 | **不插入** |
| 矩形明渠 | 底宽不同 | 插入 |
| 梯形/圆形/U形明渠 | 任意 | **总是插入** |

### 2.2 不触发渐变段的结构

| 结构类型 | 处理方式 |
|---------|----------|
| 分水闸/分水口/泄水闸/节制闸 | 点状结构，不触发渐变段。算法"穿透"闸节点，基于闸两侧的真实结构判断是否需要渐变段 |

#### 闸穿透规则

当相邻节点是闸时，`identify_and_insert_transitions()` 使用三种判断路径：

| 情况 | 方法 | 说明 |
|------|------|------|
| 当前节点是闸 → 下一节点是进口 | `_check_gap_gate_to_entry()` | 仅统计进口侧渐变段，结果加入延迟队列 `deferred_nodes` |
| 当前节点是出口 → 下一节点是闸 | `_check_gap_exit_to_gate()` | 仅统计出口侧渐变段，直接插入 |
| 普通（非闸）对 | `_should_insert_open_channel()` | 标准3行插入（出口渐变段→明渠→进口渐变段） |

**闸与特殊建筑物之间的渐变段插入规则**：

| 场景 | 是否插入渐变段 | skip_loss标记 | 说明 |
|------|--------------|--------------|------|
| 隧洞/渡槽/矩形暗涵/有压管道/倒虹吸 出口 → 闸 | **是** | `True` | 所有特殊建筑物出口后接闸时都需要出口渐变段 |
| 闸 → 隧洞/渡槽/矩形暗涵/有压管道/倒虹吸 进口 | **是** | `True` | 闸后接特殊建筑物进口时都需要进口渐变段 |
| 明渠 → 闸 | **否** | - | 明渠与闸之间不插入渐变段 |
| 闸 → 明渠 | **否** | - | 明渠与闸之间不插入渐变段 |

**skip_loss=True 的含义**：闸前后的渐变段标记为 `transition_skip_loss=True`，跳过水头损失计算。水头损失统一由闸的过闸损失（`head_loss_gate`，默认0.1m）处理，避免重复计算。

**延迟队列机制**：闸→进口方向的插入节点（明渠段+进口渐变段）暂存于 `deferred_nodes`，在下一个非闸节点之前统一冲洗插入，确保闸群结束后节点顺序正确。

**示例**：`隧洞-出 → 闸1 → 闸2 → 渡槽-进`

穿透后等效为 `(隧洞-出, 渡槽-进)` 对，判断结果：需要出口渐变段 + 明渠段 + 进口渐变段。闸将明渠段一分为二：

```
隧洞-出 → 出口渐变段 → 明渠1 → 闸1 → 闸2 → 明渠2 → 进口渐变段 → 渡槽-进
```

- OC1长度 = 首个闸站号 - 出口渐变段末端站号
- OC2长度 = 进口渐变段起始站号 - 末个闸站号
- 任一段长度 ≤ 0 则不插入该段

#### 闸过闸水头损失去重

连续同名且同坐标（XY差 < 1e-6）的闸节点，仅首行保留 `head_loss_gate`（默认0.1m），后续行清零，避免重复扣减。

### 2.3 断面特征尺寸换算

`_get_characteristic_width()` 按优先级 D > R > B 提取：

| 断面参数 | 特征宽度 | 参数键名（兼容多种） |
|---------|---------|-------------------|
| 直径 D | D | `D`, `直径` |
| 半径 R（U形/圆弧/马蹄形） | 2R | `R_circle`, `半径`, `内半径`, `r` |
| 底宽 B | B | `B`, `底宽`, `b` |

`_has_same_section_size()` 使用容差 `1e-6` 比较两节点的特征宽度。

### 2.4 合并渐变段

当里程差 ≤ 渐变段长度之和（无法插入明渠段）时，使用 `_create_merged_transition_node()` 创建**单行合并渐变段**：

- `transition_length = distance`（使用实际里程差作为长度）
- 倒虹吸侧合并时标记 `transition_skip_loss = True`
- 底坡从最近上游明渠继承

### 2.5 渐变段长度压缩规则

1. **单个渐变段超限**：当计算出的渐变段长度超过可用里程时，压缩到可用里程。
   - 实现：`result['transition_length_1'] = min(calculated_length, result['distance'])`
   - 示例：隧洞出口距离闸10m，计算出15m渐变段，则取10m

2. **出口+进口都需要时**：当出口渐变段+进口渐变段总长度超过可用里程时，合并为单个渐变段。
   - 条件：`total_transition_length > distance and distance > 0`
   - 处理：`transition_length_1 = distance`, `transition_length_2 = 0`, `need_transition_2 = False`, `use_merged_transition = True`
   - ζ系数：使用出口渐变段的ζ系数

3. **明渠段判断**：基于压缩后的渐变段长度判断是否插入明渠段。
   - 公式：`available_length = distance - transition_length_1 - transition_length_2`
   - 条件：`need_open_channel = (available_length > 0)`

4. **水头损失计算**：
   - 局部损失：按正常公式计算（与长度无关）
   - 沿程损失：按压缩后的实际长度计算（`h_f = i_avg × L_compressed`）
   - 实现：`calculate_transition_loss()` 优先使用 `transition_node.transition_length` 已设置的值

---

## 三、渐变段长度计算

### 3.1 基础公式

$$L = k \times |B_1 - B_2|$$

- 进口：$k = 2.5$（`TRANSITION_LENGTH_COEFFICIENTS["进口"]`）
- 出口：$k = 3.5$（`TRANSITION_LENGTH_COEFFICIENTS["出口"]`）

其中 $B_1$、$B_2$ 为水面宽度，由 `get_water_surface_width()` 计算。

### 3.2 水面宽度计算（`get_water_surface_width`）

| 断面类型 | 计算方法 |
|---------|---------|
| 梯形/矩形 | $B = b + 2mh$ |
| 圆形（有直径D） | $h \leq r$：$B = 2\sqrt{r^2-(r-h)^2}$；$h > r$：$B = 2\sqrt{r^2-(h-r)^2}$ |
| 马蹄形隧洞 | `_horseshoe_std_surface_width()`（精确几何公式，Ⅰ/Ⅱ型） |
| 渡槽-U形 | $h \leq R$：圆形公式；$h > R$：$B = 2R$ |
| 明渠-U形 | $h \leq h_0$：圆弧段公式；$h > h_0$：$B = b_{arc} + 2m(h-h_0)$ |
| 隧洞-圆拱直墙型 | `_arch_tunnel_surface_width()`（直墙+圆拱分段） |
| 渡槽-矩形（带倒角） | `_rect_chamfer_surface_width()`（倒角区收窄） |
| 仅有半径R的断面 | $B = 2R$ |

### 3.3 各结构最小长度约束

| 结构类型 | 进口约束 | 出口约束 | 代码常量 |
|---------|---------|---------|---------|
| 渡槽 | $L \geq 6h_{设计}$ | $L \geq 8h_{设计}$ | `TRANSITION_LENGTH_CONSTRAINTS["渡槽"]` |
| 隧洞 | $L \geq \max(5h,\ 3D)$ | $L \geq \max(5h,\ 3D)$ | `TRANSITION_LENGTH_CONSTRAINTS["隧洞"]` |
| 倒虹吸/有压管道 | $L = 5h_{上游}$ | $L = 6h_{下游}$ | `TRANSITION_LENGTH_CONSTRAINTS["倒虹吸"]` |
| 矩形暗涵 | 仅基础公式 | 仅基础公式 | `TRANSITION_LENGTH_CONSTRAINTS["矩形暗涵"]` |

> **注**：
> 1. 已移除原有 10 m 硬编码下限（所有结构类型统一取消）。
> 2. **有压流建筑物（倒虹吸/有压管道）**渐变段长度直接按水深倍数确定，不使用 §3.1 基础公式 $L=k\times|B_1-B_2|$（依据 GB 50288-2018 §10.2.4 条1）。其他结构类型仍先算基础公式再与约束取 max。

### 3.4 渠道水深取值规则

`calculate_transition_length()` 中渠道水深的取值逻辑：

1. **出口渐变段**：使用 `next_node`（下游明渠）的 `water_depth`
2. **进口渐变段**：使用 `prev_node`（上游明渠）的 `water_depth`
3. **回退**：若相邻节点水深无效，调用 `get_channel_design_depth()` 在同一流量段内搜索明渠节点水深（取最大值）

### 3.5 快速估算渐变段长度（`_estimate_transition_length`）

用于判断是否需要插入明渠段时的快速估算，无需精确计算水面宽度。

**估算方法**：

1. **获取特征宽度**：调用 `_get_characteristic_width(node)`，若无效则默认 3.0m
2. **确定假设明渠宽度**：
   - 优先：查找同流量段的参考明渠，使用其 `bottom_width`
   - 兜底：若找不到参考明渠，使用 `B_channel = B × 1.2`
3. **基础公式**：`L_basic = coefficient × |B_channel - B|`
   - 进口系数：2.5
   - 出口系数：3.5

**约束条件**（与 §3.3 一致）：

| 结构类型 | 进口 | 出口 |
|---------|------|------|
| 渡槽 | `max(L_basic, 6h)` | `max(L_basic, 8h)` |
| 隧洞 | `max(L_basic, max(5h, 3D))` | `max(L_basic, max(5h, 3D))` |
| 倒虹吸/有压管道 | `5h` | `6h` |
| 矩形暗涵 | `L_basic` | `L_basic` |

**水深取值**：优先使用 `node.water_depth`，若无效则默认 2.0m

**注意**：此估算仅用于判断是否插入明渠段，实际渐变段长度由 `calculate_transition_length()` 精确计算。

### 3.6 渐变段长度计算详情

每次计算后，详细参数保存到 `transition_node.transition_length_calc_details` 字典中，供双击展示使用：

```python
{
    "transition_type", "struct_name", "B1", "B2", "coefficient",
    "L_basic", "channel_depth", "L_result", "constraint_applied",
    "prev_name", "next_name",
    # 约束类型特有字段：
    "depth_multiplier", "L_depth",                    # 渡槽/倒虹吸
    "tunnel_multiplier", "tunnel_size", "L_tunnel",   # 隧洞
    "constraint_desc",                                 # 所有类型
}
```

---

## 四、渐变段水头损失计算（推求水面线模块）

### 4.1 总损失公式

$$h_{渐} = h_{j1} + h_f$$

### 4.2 局部水头损失

$$h_{j1} = \xi_1 \frac{|v_2^2 - v_1^2|}{2g}$$

### 4.3 局部损失系数 $\xi_1$

#### 渡槽/隧洞/暗涵/明渠渐变段（GB 50288 表 K.1.2）

`TRANSITION_ZETA_COEFFICIENTS` 定义：

| 渐变段形式 | 进口 $\xi_1$ | 出口 $\xi_1$ |
|-----------|-------------|-------------|
| 曲线形反弯扭曲面 | 0.10 | 0.20 |
| 圆弧直墙 | 0.20 | 0.50 |
| 八字形 | 0.30 | 0.50 |
| 直角形 | 0.40 | 0.75 |

**直线形扭曲面**：根据θ角度线性插值（`TRANSITION_TWISTED_ZETA_RANGE`）：

| 参数 | 进口 | 出口 |
|------|------|------|
| θ范围 | 15°~37° | 15°~37° |
| ζ范围 | 0.0~0.10 | 0.10~0.17 |
| 插值公式 | $\zeta = 0 + \frac{\theta-15}{37-15} \times 0.1$ | $\zeta = 0.1 + \frac{\theta-15}{37-15} \times 0.07$ |
| θ ≤ 15° | 取最小值 | 取最小值 |
| θ ≥ 37° | 取最大值 | 取最大值 |

#### 倒虹吸渐变段（GB 50288 表 L.1.2）

`SIPHON_TRANSITION_ZETA_COEFFICIENTS` 定义：

| 渐变段型式 | 进口 $\xi_1$ | 出口 $\xi_1$ | 备注 |
|-----------|-------------|-------------|------|
| 反弯扭曲面 | 0.10 | 0.20 | |
| 直线扭曲面 | 0.20 | 0.40 | 取均值（范围0.05~0.30 / 0.30~0.50） |
| 1/4圆弧 | 0.15 | 0.25 | |
| 方头型 | 0.30 | 0.75 | |

型式选项列表：`SIPHON_TRANSITION_FORM_OPTIONS = ["反弯扭曲面", "直线扭曲面", "1/4圆弧", "方头型"]`

倒虹吸型式→渡槽/隧洞型式映射（`SIPHON_TO_TRANSITION_FORM_MAP`）：
- `"反弯扭曲面"` → `"曲线形反弯扭曲面"`
- `"直线扭曲面"` → `"直线形扭曲面"`
- `"1/4圆弧"` 和 `"方头型"` 在表K.1.2中无直接对应

#### ζ系数获取优先级（`get_transition_zeta`）

1. 用户手动设置 `transition_node.transition_zeta > 0` → 直接使用
2. 从表K.1.2查表 → 固定值或直线形扭曲面插值
3. 默认值：进口 0.1，出口 0.2

### 4.4 沿程水头损失（平均值法）

$$h_f = i_{avg} \times L$$

其中平均水力坡降 $i_{avg}$ 由曼宁公式反算：

$$i_{avg} = \left(\frac{v_{avg} \cdot n}{R_{avg}^{2/3}}\right)^2$$

- $R_{avg} = (R_1 + R_2) / 2$（若任一为0则取非零值）
- $v_{avg} = (v_1 + v_2) / 2$（若任一为0则取非零值）
- $n$ = 渐变段节点的糙率（优先），否则用全局糙率

### 4.5 计算详情记录

每次计算后，详细参数保存到 `transition_node.transition_calc_details`：

```python
{
    "transition_type", "transition_form", "zeta",
    "v1", "v2", "B1", "B2", "length",
    "R_avg", "v_avg", "h_j1", "h_f", "total",
}
```

### 4.6 倒虹吸/有压管道占位渐变段

倒虹吸侧或有压管道侧的渐变段标记 `transition_skip_loss = True`：
- 只计算渐变段长度（调用 `calculate_transition_length`）
- **不计算水头损失**（水损已含在倒虹吸/有压管道水力计算中）
- 判断方法：`is_pressurized_flow_structure(node)` 判断节点是否为有压流结构（倒虹吸或有压管道）

---

## 五、明渠段自动插入

### 5.1 触发条件

$$\Delta S_{MC} > L_{出口渐变段} + L_{进口渐变段}$$

当两个特殊建筑物（隧洞/渡槽/倒虹吸/矩形暗涵）之间的里程差大于两侧渐变段长度之和时，自动检测到明渠段缺口，插入 3 行：

```
出口渐变段 → 明渠段 → 进口渐变段
```

当里程差 ≤ 渐变段长度之和时，不插入明渠段，改为插入1行合并渐变段。

### 5.2 参考明渠确定算法（`_find_reference_channel_same_section`）

**核心原则**：在**同一流量段**内搜索，按优先级选出最佳类型，从最近节点取参数。

#### 步骤

1. 取空隙所在节点的 `flow_section`
2. 扫描所有节点，收集同流量段内的明渠节点（兼容旧版 `"矩形"` 类型）
3. 按优先级分组选出最高优先级类型：

   | 优先级 | 类型 |
   |--------|------|
   | 1（最高） | `明渠-矩形` / `矩形`（旧版） |
   | 2 | `明渠-梯形` |
   | 3 | `明渠-圆形` |
   | 4（最低） | `明渠-U形` |

4. 从最高优先级组中，取**距离空隙最近**的节点作为参数来源
5. 若同流量段内无任何明渠节点 → 返回 `(None, None)`，触发经济断面回退

#### 返回参数字典

```python
{
    'name', 'structure_type',  # 类型名（旧版"矩形"→"明渠-矩形"）
    'bottom_width',            # B 或 D（圆形时用D代替B）
    'water_depth', 'side_slope', 'roughness',
    'slope_inv',               # 1/i
    'flow', 'flow_section', 'structure_height',
    'arc_radius',              # R_circle（明渠-U形用）
    'theta_deg',               # 圆心角（明渠-U形用）
}
```

#### 旧版兼容

`"矩形"` 类型（`StructureType.RECTANGULAR`）等价于 `"明渠-矩形"`，在查找和显示时统一规范化为 `"明渠-矩形"`。`_is_any_channel_type()` 同时匹配 `"矩形"` 旧值。

### 5.3 同流量段无明渠时的回退策略

当同流量段内找不到任何明渠节点时，执行以下回退流程：

1. **跨流量段**获取参考参数（`_find_global_nearest_channel`）：全局搜索距离空隙最近的明渠节点，提取其 `slope_i`（底坡，默认1/3000）、`roughness`（糙率，默认0.014）、`side_slope`（边坡，默认1.0）
2. 取当前流量段的设计流量 `Q`
3. 使用 **实用经济断面公式**（`_compute_economic_section`）自动计算4种明渠类型的断面参数：

| 类型 | 设计方法 | 预填内容 |
|------|---------|---------|
| 明渠-矩形 | 实用经济断面 $B = 2h$，二分法求 $h$ | B、h、m=0、n、底坡 |
| 明渠-梯形 | 实用经济断面 $B = 2h(\sqrt{1+m^2}-m)$，二分法求 $h$ | B、h、m（来自参考节点）、n、底坡 |
| 明渠-圆形 | 调用 `明渠设计.quick_calculate_circular`（留空自动搜索最优 D），失败回退到满流公式 | D（作为 B 填入）、h=设计水深、n、底坡 |
| 明渠-U形 | 不自动计算；只预填 n 和底坡 | n、底坡（R 和 h 由用户手动输入） |

4. 对话框预填最高优先级类型（**明渠-矩形**）的计算结果
5. 用户切换结构形式下拉框时，矩形/梯形/圆形自动更新参数；U形仅预填 n 和底坡，其余手动输入

### 5.4 批量插入对话框行为

| 场景 | 行为 |
|------|------|
| 同流量段有明渠 | 自动预填参数，行全部有值 |
| 同流量段无明渠 | 经济断面公式计算，预填明渠-矩形；切换类型自动更新参数 |
| 一键全流程（auto_confirm） | 同上自动预填；若仍有空行则用 `_fill_with_fallback_if_empty()`（向前最近明渠）兜底 |

### 5.5 明渠段节点创建（`_create_open_channel_node`）

| 属性 | 来源 |
|------|------|
| `structure_type` | 从 `OpenChannelParams.structure_type` 转换为枚举 |
| `section_params` | 圆形→`{"D": ..., "m": 0}`；U形→`{"R_circle": ..., "m": ..., "theta_deg": ...}`；其他→`{"B": ..., "m": ...}` |
| `water_depth` | `OpenChannelParams.water_depth` |
| `roughness` | `OpenChannelParams.roughness` |
| `slope_i` | `1/slope_inv` |
| `flow` | params优先，否则继承 `prev_node.flow` |
| `x`, `y` | `(prev_node + next_node) / 2`（坐标插值） |
| `is_auto_inserted_channel` | `True`（不分配IP编号） |
| `structure_height` | 从 params 继承 |
| 水力参数 | 立即计算 A/X/R/v（圆形调用 `_fill_circular_section_params`，U形调用 `fill_section_params`，梯形/矩形内联计算） |

### 5.6 自动插入明渠行的几何列显示规则

自动插入明渠行（`is_auto_inserted_channel=True`）不是真实IP转折点，几何列在表格中全部留空，数据模型值不变（下游水力计算依赖 `station_MC`）。

| 列（索引） | 显示 | 说明 |
|-----------|------|------|
| 结构形式(2) | `"明渠-梯形(连接段)"` | 加`(连接段)`后缀标识 |
| IP编号(4)、X(5)、Y(6) | 留空 | 无真实坐标 |
| 转角(8)、切线长(9)、弧长(10)、弯道长度(11) | 留空 | 非IP转折点，值为0无意义 |
| IP直线间距(12)、IP点桩号(13)、弯前BC(14)、里程MC(15)、弯末EC(16) | 留空 | 非IP节点 |
| 复核弯前长度(17)、复核弯后长度(18)、复核总长度(19) | 留空 | 不参与弯道重叠检查 |
| 水力列(20-43) | 正常显示 | 水力计算有意义（沿程损失、水深、流速等） |

**视觉区分**：
- 文字颜色：绿色（`#2E7D32`）
- 悬浮提示："自动插入的明渠连接段，用于计算两个建筑物之间的沿程及弯道水头损失。几何列留空因为该行不是真实IP转折点。"

### 5.7 复核长度列（check_pre_curve / check_post_curve / check_total_length）显示规则

复核长度用于检查弯道切线是否重叠，仅对有真实XY坐标的原生IP节点有意义。

| 节点类型 | 计算逻辑 | 表格显示 |
|---------|---------|----------|
| 原生IP节点（有XY） | 正常计算 | 显示数值 |
| 渐变段（`is_transition`） | 置0 | 留空（整行不显示几何） |
| 自动插入明渠（`is_auto_inserted_channel`） | 置0 | 留空 |
| 倒虹吸（`is_inverted_siphon`） | 置0（不需要检查弯道重叠） | 留空 |
| 进/出口节点 | 正常计算 | 显示数值 |
| 闸类节点 | 正常计算 | 显示数值 |

**`geometry_calc.py` 第四步查找逻辑**：计算原生行的 `prev_tangent` / `next_straight` 时，同时跳过 `is_transition` 和 `is_auto_inserted_channel` 行，与第二步 `find_prev_real` / `find_next_real` 保持一致。

---

## 六、渐变段节点创建

### 6.1 三种创建方式

| 方法 | 场景 | 特点 |
|------|------|------|
| `_create_transition_node()` | 出口渐变段（标准3行插入） | 继承 prev_node 的坐标、流量、糙率 |
| `_create_inlet_transition_node()` | 进口渐变段（标准3行插入） | 继承 next_node 的坐标、流量、糙率 |
| `_create_merged_transition_node()` | 合并渐变段（里程差不足时） | `transition_length = distance`（实际里程差） |

### 6.2 公共属性

| 属性 | 值 |
|------|-----|
| `is_transition` | `True` |
| `name` | `"-"` |
| `structure_type` | `StructureType.TRANSITION`（值为`"渐变段"`） |
| `transition_type` | `"进口"` 或 `"出口"` |
| `transition_form` | 从 `ProjectSettings` 读取（默认`"曲线形反弯扭曲面"`） |
| `transition_zeta` | 从 `ProjectSettings` 读取用户指定值（若>0） |
| `transition_skip_loss` | 倒虹吸/有压管道侧为 `True` |

### 6.3 渐变段形式与ζ系数选取逻辑

创建渐变段节点时，根据相邻建筑物类型选择不同的配置来源：

| 相邻建筑物 | 配置来源 | 型式选项 |
|-----------|---------|---------|
| 隧洞/渡槽/矩形暗涵 | `settings.transition_inlet/outlet_form/zeta` | 表K.1.2（5种） |
| 倒虹吸/有压管道 | `settings.siphon_transition_inlet/outlet_form/zeta` | 表L.1.2（4种） |
| 明渠↔明渠 | `settings.open_channel_transition_form/zeta` | 表K.1.2（5种） |

---

## 七、特殊建筑物进出口标识

以下结构类型需要标识进口/出口 IP 点（`_is_special_structure_sv()` 判断）：

- 隧洞（各型）
- 渡槽（各型）
- 倒虹吸
- **矩形暗涵**

关键词匹配：`("隧洞", "渡槽", "倒虹吸", "暗涵")` 中任一出现在 `structure_type.value` 中即为特殊建筑物。

**IP 列显示规则**（`get_ip_str()`）：
- 隧洞/渡槽/倒虹吸：`IP{n} {建筑物名称}{类型缩写}{进/出}`，如 `IP42 油房坨隧进`
  - 类型缩写：隧洞→"隧"，渡槽→"渡"，倒虹吸→"倒"
- **矩形暗涵**：仅显示 `IP{n}`，**不加进/出后缀**

---

## 八、项目设置中的渐变段配置

`ProjectSettings` 数据模型中与渐变段相关的字段：

### 8.1 渡槽/隧洞渐变段（表K.1.2）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `transition_inlet_form` | `"曲线形反弯扭曲面"` | 进口渐变段形式 |
| `transition_inlet_zeta` | `0.10` | 进口ζ系数 |
| `transition_outlet_form` | `"曲线形反弯扭曲面"` | 出口渐变段形式 |
| `transition_outlet_zeta` | `0.20` | 出口ζ系数 |

### 8.2 明渠渐变段

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `open_channel_transition_form` | `"曲线形反弯扭曲面"` | 明渠间渐变段形式 |
| `open_channel_transition_zeta` | `0.10` | 明渠间ζ系数 |

### 8.3 倒虹吸渐变段（表L.1.2）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `siphon_transition_inlet_form` | `"反弯扭曲面"` | 进口型式 |
| `siphon_transition_outlet_form` | `"反弯扭曲面"` | 出口型式 |
| `siphon_transition_inlet_zeta` | `0.10` | 进口ζ系数 |
| `siphon_transition_outlet_zeta` | `0.20` | 出口ζ系数 |

---

## 九、ChannelNode 渐变段相关字段

`data_models.ChannelNode` 中与渐变段相关的完整字段列表：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `is_transition` | `bool` | `False` | 是否为渐变段专用行 |
| `transition_skip_loss` | `bool` | `False` | 占位渐变段，不计算水头损失（倒虹吸/有压管道渐变段已含在其水损中） |
| `transition_type` | `str` | `""` | `"进口"` 或 `"出口"` |
| `transition_form` | `str` | `""` | 渐变段形式（如`"曲线形反弯扭曲面"`） |
| `transition_zeta` | `float` | `0.0` | 局部损失系数ζ |
| `transition_theta` | `float` | `0.0` | 直线形扭曲面的θ角度 |
| `transition_length` | `float` | `0.0` | 渐变段长度L（m） |
| `transition_water_width_1` | `float` | `0.0` | 起始水面宽度B₁（m） |
| `transition_water_width_2` | `float` | `0.0` | 末端水面宽度B₂（m） |
| `transition_velocity_1` | `float` | `0.0` | 起始流速v₁（m/s） |
| `transition_velocity_2` | `float` | `0.0` | 末端流速v₂（m/s） |
| `transition_avg_R` | `float` | `0.0` | 平均水力半径R_avg（m） |
| `transition_avg_v` | `float` | `0.0` | 平均流速v_avg（m/s） |
| `transition_head_loss_local` | `float` | `0.0` | 局部水头损失h_j1（m） |
| `transition_head_loss_friction` | `float` | `0.0` | 沿程水头损失h_f（m） |
| `head_loss_transition` | `float` | `0.0` | 渐变段总水头损失（h_j1 + h_f） |
| `transition_calc_details` | `dict` | `{}` | 水损计算详情（LaTeX显示） |
| `transition_length_calc_details` | `dict` | `{}` | 长度计算详情（双击展示） |

其他关联字段：
- `is_auto_inserted_channel: bool` — 是否为自动插入的明渠段（不分配IP编号）
- `stat_length: float` — 统计用长度（结构类型汇总用）

`OpenChannelParams` 数据模型：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `"-"` | 名称 |
| `structure_type` | `str` | `"明渠-梯形"` | 如`"明渠-梯形"` |
| `bottom_width` | `float` | `0.0` | 底宽或直径 |
| `water_depth` | `float` | `0.0` | 水深 |
| `side_slope` | `float` | `0.0` | 边坡系数m |
| `roughness` | `float` | `0.014` | 糙率n |
| `slope_inv` | `float` | `3000.0` | 底坡倒数1/i |
| `flow` | `float` | `0.0` | 流量Q |
| `flow_section` | `str` | `""` | 流量段 |
| `structure_height` | `float` | `0.0` | 结构高度 |
| `arc_radius` | `float` | `0.0` | 圆弧半径（明渠-U形用） |
| `theta_deg` | `float` | `0.0` | 圆弧圆心角（明渠-U形用） |

---

## 十、累计水头损失

### 10.1 渐变段损失的累计方式

`_calculate_cumulative_head_loss()` 从第一行逐行累加：

- **渐变段行**：累加 `head_loss_transition`
- **普通行**：累加 `head_loss_total`
- 每行的 `head_loss_cumulative` = 截至该行的累计值

### 10.2 水位递推（`recalculate_water_levels_with_transition_losses`）

渐变段水头损失计算完成后，重新递推水位：

1. 找到第一个非渐变段节点，设其水位为 `start_water_level`
2. 从该节点起顺推，对每个常规节点：
   - 累加从上一常规节点到当前节点之间所有渐变段行的 `head_loss_transition`
   - 水位递推：$Z_{curr} = Z_{prev} - (h_f + h_j + h_w + h_{reserve} + h_{gate} + h_{siphon} + h_{transition})$
3. 分水闸/分水口只扣过闸损失

### 10.3 内联模式（`calculate_transition_losses_inline`）

不插入专用渐变段行的备选模式：
- 逐对扫描 `(curr_node, next_node)`，跳过闸节点
- 调用 `_needs_transition()` 判断是否需要渐变段
- 渐变段损失累加到 `curr_node.head_loss_total`
- 详情保存到 `curr_node.transition_calc_details`

---

## 十一、UI 交互

### 11.1 渐变段设置区（可折叠，3行网格）

| 行 | 建筑物类型 | 内容 |
|----|-----------|------|
| 第1行 | 渡槽/隧洞 | 进口形式+ζ₁（表K.1.2）、出口形式+ζ₂ |
| 第2行 | 明渠 | 渐变段形式+ζ（明渠不同子类型间的过渡） |
| 第3行 | 倒虹吸 | 进口形式+ζ₁（表L.1.2）、出口形式+ζ₂、"参考系数表"按钮 |

点击"参考系数表"弹出 `TransitionReferenceDialog`，展示 K.1.2（渡槽/隧洞）和 L.1.2（倒虹吸）的系数图表（含示意图缩略图，支持点击放大）。

### 11.2 插入渐变段按钮交互流程

```
用户点击【插入渐变段】
    ├─ 前置校验（节点数、流量、设置）
    ├─ 若已有渐变段 → 确认是否清除并重新插入
    ├─ pre_scan_open_channels() → 扫描所有空隙(gaps)
    ├─ 若 gaps ≥ 2 → 弹出 BatchChannelConfirmDialog
    │     ├─ 表格编辑模式：统一配置所有明渠段参数
    │     └─ 逐一弹窗模式：每个空隙逐一确认
    └─ prepare_transitions(nodes, open_channel_callback)
           └─ 对每个 gap 调用 open_channel_callback
                  ├─ 表格编辑 → 用预设参数
                  ├─ 自动推荐 → 用上游参数
                  └─ 逐一弹窗 → OpenChannelDialog
    ↓
更新表格、统计渐变段/明渠段数量、InfoBar 提示下一步操作
```

### 11.3 双击详情弹窗

| 双击列 | 弹出内容 |
|--------|---------|
| 渐变段长度L | 基本公式+各约束条件+最终取值 |
| 渐变段水头损失 | 局部损失（ζ/v₁/v₂）+ 沿程损失（R_avg/v_avg/n/L）+ 总损失 |

### 11.4 节点数据表列定义（渐变段相关列）

| 列索引 | 列名 | 宽度 | 可编辑 |
|--------|------|------|--------|
| 32 | 渐变段长度L | 90 | 只读 |
| 33 | 渐变段水头损失 | 110 | 只读 |

---

## 十二、倒虹吸水力计算中的渐变段

倒虹吸水力计算系统独立计算进出口渐变段水面落差，结果回写水面线推求模块。

### 12.1 三段式水头损失公式

$$\Delta Z = \Delta Z_1 + \Delta Z_2 - \Delta Z_3$$

| 段 | 公式 | 说明 |
|----|------|------|
| 进口渐变段 $\Delta Z_1$ | $(1 + \xi_1) \frac{v_2^2 - v_1^2}{2g}$ | $v_1$=进口渐变段始端流速，$v_2$=末端流速 |
| 管身段 $\Delta Z_2$ | $h_f + h_j$（沿程+局部） | 不含进出口渐变段 |
| 出口渐变段 $\Delta Z_3$ | $(1 - \xi_2) \frac{v^2 - v_3^2}{2g}$ | $v$=出口渐变段始端流速，$v_3$=末端流速（动能回收） |

### 12.2 渐变段型式枚举（GradientType）

| 枚举值 | 进口ξ₁ | 出口ξ₂ |
|--------|---------|---------|
| NONE | 0.00 | 0.00 |
| REVERSE_BEND（反弯扭曲面） | 0.10 | 0.20 |
| LINEAR_TWIST（直线扭曲面） | 0.20(均值) | 0.40(均值) |
| QUARTER_ARC（1/4圆弧） | 0.15 | 0.25 |
| SQUARE_HEAD（方头型） | 0.30 | 0.75 |

直线扭曲面支持按角度线性插值：进口θ₁=15°~37°→ξ₁=0.05~0.30，出口θ₂=10°~17°→ξ₂=0.30~0.50。

### 12.3 v₂ 计算策略（V2Strategy）

| 策略 | 说明 |
|------|------|
| AUTO_PIPE | v₂ = 管道流速（推荐） |
| V1_PLUS_02 | v₂ = v₁ + 0.2 |
| SECTION_CALC | v₂ = Q/[(B+m×h)×h] |
| MANUAL | 用户直接输入 |

安全兜底：若 $v_2 \le v_1$ 且 $v_1 > 0$，自动回退到管道流速。

### 12.4 管道渐变段（管径变化段）

倒虹吸管身内部的管道渐变段（`SegmentType.PIPE_TRANSITION`）：
- 收缩段：$\xi_{jb} = 0.05$
- 扩散段：$\xi_{jb} = 0.10$

### 12.5 与水面线推求的衔接

1. 倒虹吸计算完成后，总水头损失 $\Delta Z$ 回写到水面线节点的 `head_loss_siphon`
2. 水面线推求中，倒虹吸侧渐变段标记 `transition_skip_loss=True`，仅占位不重复计算损失
3. 渐变段长度仍由水面线推求模块计算（用于建筑物长度统计和纵断面绘图）

---

## 十三、有压管道计算中的渐变段

有压管道独立计算进出口渐变段水头损失，逻辑与倒虹吸类似。

### 13.1 渐变段损失公式

**进口渐变段**：

$$h_{j1} = \xi_1 \frac{V_{管道}^2 - V_{渠道}^2}{2g}$$

**出口渐变段**：

$$h_{j3} = \xi_3 \frac{V_{渠道}^2 - V_{管道}^2}{2g}$$

取 $\max(0, h_j)$，确保非负。

### 13.2 ζ系数表（表L.1.2，与倒虹吸共用）

| 渐变段型式 | 进口ζ₁ | 出口ζ₃ |
|-----------|--------|--------|
| 反弯扭曲面 | 0.10 | 0.20 |
| 直线扭曲面 | 0.20 | 0.40 |
| 1/4圆弧 | 0.15 | 0.25 |
| 方头型 | 0.30 | 0.75 |

### 13.3 ζ系数获取优先级（`pressure_pipe_calc.get_transition_zeta`）

1. 用户手动指定 `inlet_transition_zeta > 0` → 直接使用
2. 从 `SIPHON_TRANSITION_ZETA_COEFFICIENTS` 查表
3. 默认：进口 0.10，出口 0.20

### 13.4 计算结果字段

`PressurePipeCalcResult` 中的渐变段相关字段：

| 字段 | 说明 |
|------|------|
| `inlet_transition_loss` | 进口渐变段损失（m） |
| `outlet_transition_loss` | 出口渐变段损失（m） |
| `inlet_transition_details` | 进口渐变段计算详情 |
| `outlet_transition_details` | 出口渐变段计算详情 |

### 13.5 计算函数签名

```python
calculate_pressure_pipe(
    ...,
    inlet_transition_form: str = "反弯扭曲面",
    outlet_transition_form: str = "反弯扭曲面",
    inlet_transition_zeta: Optional[float] = None,
    outlet_transition_zeta: Optional[float] = None,
) -> PressurePipeCalcResult
```

支持平面模式和空间模式（`calculate_pressure_pipe_spatial`），两种模式的渐变段计算逻辑相同。

### 13.6 与水面线推求的衔接

与倒虹吸完全一致：
1. 有压管道计算完成后，总水头损失回写到 `head_loss_siphon`（复用倒虹吸损失列）
2. 水面线推求中，有压管道侧渐变段标记 `transition_skip_loss=True`
3. 渐变段长度仍由水面线推求模块按 GB 50288-2018 §10.2.4 计算（进口5h，出口6h）

---

## 十四、相关代码文件索引

### 14.1 推求水面线模块

| 文件 | 关键方法/类 |
|------|------------|
| `推求水面线/core/calculator.py` | `_needs_transition()`, `_is_mingqu_type()`, `_is_tunnel_or_aqueduct()`, `_is_culvert_type()`, `_is_diversion_gate_type()`, `is_pressurized_flow_structure()`, `_has_same_section_size()`, `_get_characteristic_width()`, `_find_next_non_gate_idx()`, `_check_gap_exit_to_gate()`, `_check_gap_gate_to_entry()`, `_should_insert_open_channel()`, `_estimate_transition_length()`, `_find_reference_channel_same_section()`, `_find_global_nearest_channel()`, `_compute_economic_section()`, `_find_nearest_upstream_channel()`, `_create_transition_node()`, `_create_inlet_transition_node()`, `_create_merged_transition_node()`, `_create_open_channel_node()`, `identify_and_insert_transitions()`, `calculate_transition_losses()`, `calculate_transition_losses_inline()`, `pre_scan_open_channels()`, `_calculate_cumulative_head_loss()`, `_update_total_head_loss()`, `prepare_transitions()` |
| `推求水面线/core/hydraulic_calc.py` | `get_water_surface_width()`, `get_transition_zeta()`, `calculate_transition_length()`, `calculate_transition_friction_loss()`, `calculate_transition_loss()`, `calculate_transition_loss_inline()`, `_estimate_transition_loss()`, `get_channel_design_depth()`, `recalculate_water_levels_with_transition_losses()` |
| `推求水面线/models/enums.py` | `StructureType`（含 `TRANSITION="渐变段"`、`get_special_structures()`、`is_diversion_gate()`、`is_diversion_gate_str()`） |
| `推求水面线/models/data_models.py` | `ChannelNode`（渐变段字段）、`OpenChannelParams`（含 `arc_radius`/`theta_deg`/`name`/`structure_height`）、`ProjectSettings`（渐变段配置字段）、`ChannelNode.get_ip_str()` |
| `推求水面线/config/constants.py` | `TRANSITION_LENGTH_COEFFICIENTS`, `TRANSITION_LENGTH_CONSTRAINTS`, `TRANSITION_ZETA_COEFFICIENTS`, `TRANSITION_TWISTED_ZETA_RANGE`, `TRANSITION_FORM_OPTIONS`, `SIPHON_TRANSITION_FORM_OPTIONS`, `SIPHON_TRANSITION_ZETA_COEFFICIENTS`, `SIPHON_TO_TRANSITION_FORM_MAP` |

### 14.2 UI 层

| 文件 | 关键方法/类 |
|------|------------|
| `渠系断面设计/water_profile/panel.py` | `_insert_transitions()`, `open_channel_callback()`, `_show_transition_length_details()`, `_show_transition_calc_details()`, `_open_transition_reference()` |
| `渠系断面设计/water_profile/water_profile_dialogs.py` | `BatchChannelConfirmDialog`, `_fill_all_recommended()`, `_fill_with_fallback_if_empty()` |
| `渠系断面设计/water_profile/formula_dialog.py` | `show_transition_loss_dialog()`, `show_transition_length_dialog()` |
| `渠系断面设计/water_profile/cad_tools.py` | `_is_special_structure_sv()` |

### 14.3 倒虹吸水力计算

| 文件 | 关键方法/类 |
|------|------------|
| `倒虹吸水力计算系统/siphon_models.py` | `GradientType`（渐变段型式枚举）、`V2Strategy`（v₂策略）、`GlobalParameters`（inlet_type/outlet_type/xi_inlet/xi_outlet）、`SegmentType.PIPE_TRANSITION` |
| `倒虹吸水力计算系统/siphon_hydraulics.py` | 三段式水头损失计算（ΔZ₁/ΔZ₂/ΔZ₃） |
| `倒虹吸水力计算系统/siphon_coefficients.py` | `CoefficientService`（表L.1.2/L.1.4-3/L.1.4-4查表） |

### 14.4 有压管道计算

| 文件 | 关键方法/类 |
|------|------------|
| `推求水面线/core/pressure_pipe_calc.py` | `calc_transition_loss()`, `get_transition_zeta()`, `calculate_pressure_pipe()`, `calculate_pressure_pipe_spatial()`, `PressurePipeCalcResult` |
| `推求水面线/utils/pressure_pipe_extractor.py` | `PressurePipeGroup`, `PressurePipeDataExtractor` |
| `推求水面线/managers/pressure_pipe_manager.py` | `PressurePipeManager` |

---

## 十五、计算调用流程概览

```
用户点击【插入渐变段】
  → _insert_transitions()
      → pre_scan_open_channels() → gaps
      → BatchChannelConfirmDialog (若 gaps ≥ 2)
      → prepare_transitions(nodes, open_channel_callback)
          → identify_and_insert_transitions()
              → _check_gap_gate_to_entry / _check_gap_exit_to_gate（闸穿透）
              → _should_insert_open_channel（普通出口→进口）
              → _needs_transition（明渠↔明渠等）
              → _create_transition_node / _create_inlet_transition_node / _create_merged_transition_node
              → _estimate_transition_length
  → 更新表格

用户点击【执行计算】
  → calculate_all()
      → calculate_transition_losses()
          → calculate_transition_length() (精确长度)
          → calculate_transition_loss() (水头损失)
      → _update_total_head_loss()
      → _calculate_cumulative_head_loss()
      → recalculate_water_levels_with_transition_losses()

倒虹吸水力计算
  → siphon_hydraulics.calculate()
      → ΔZ₁ = (1+ξ₁)(v₂²-v₁²)/(2g)
      → ΔZ₃ = (1-ξ₂)(v²-v₃²)/(2g)
      → ΔZ = ΔZ₁ + ΔZ₂ - ΔZ₃
  → 回写 head_loss_siphon

有压管道计算
  → calculate_pressure_pipe()
      → calc_transition_loss(V_pipe, V_channel, zeta, is_inlet)
      → 进出口渐变段损失合入总损失
  → 回写 head_loss_siphon
```

---

## 十六、变更日志

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-02-22 | 初版：渐变段识别规则、长度计算、水头损失、明渠段自动插入、IP标识 |
| v2.0 | 2026-02-26 | 全面对齐最新代码：新增有效结构类型集合；修正ζ系数表（表K.1.2直线形扭曲面为θ插值非固定值，表L.1.2倒虹吸独立系数表）；新增合并渐变段逻辑；新增水面宽度计算方法（8种断面类型）；新增渠道水深取值规则；新增计算详情记录；补充沿程损失曼宁公式平均值法；新增倒虹吸占位渐变段；新增明渠段节点创建详情；新增渐变段节点创建（3种方式）；新增项目设置中渐变段配置字段；新增ChannelNode/OpenChannelParams完整字段列表；新增累计水头损失与内联模式；更新代码文件索引 |
| v2.1 | 2026-02-26 | 新增自动插入明渠行几何列显示规则；新增复核长度列显示规则；geometry_calc.py第四步跳过is_auto_inserted_channel |
| v2.2 | 2026-03-04 | 扩展闸穿透规则：所有特殊建筑物与闸之间都需要插入渐变段（skip_loss=True）；明渠与闸之间不插入渐变段 |
| v2.3 | 2026-03-04 | 新增渐变段长度压缩规则（单个超限压缩、出口+进口合并、明渠段基于压缩后长度判断）；新增快速估算方法 |
| v2.4 | 2026-03-05 | 改进快速估算：优先查找同流量段参考明渠底宽 |
| **v3.0** | **2026-03-06** | **整合为统一PRD**：合并原 `PRD_渐变段与明渠段插入算法.md`、`渐变段计算说明.md`、`PRD_推求水面线.md`（渐变段部分）、`PRD_有压管道批量计算_V1.0.md`（渐变段部分）、`附录L-水力计算核心.md`（渐变段部分）、`倒虹吸后端SRS`（渐变段部分）为一份文档；新增§十二倒虹吸三段式渐变段公式（ΔZ₁/ΔZ₃/GradientType/V2Strategy/管道渐变段）；新增§十三有压管道渐变段计算（损失公式/PressurePipeCalcResult/calc_transition_loss）；新增§十一 UI交互流程（设置区/插入按钮交互/双击弹窗）；新增§十五计算调用流程概览；新增§六.3渐变段形式与ζ系数选取逻辑（按建筑物类型区分配置来源）；§九OpenChannelParams补充`name`/`structure_height`字段及默认值；§十新增水位递推说明；§十四代码索引扩展至4个子系统 |
