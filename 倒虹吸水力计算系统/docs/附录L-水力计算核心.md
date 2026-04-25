# 5. 水力计算核心 (Hydraulic Core)

**版本**: v2.0  
**最后更新**: 2026-02-25  
**代码**: `siphon_hydraulics.py`（`倒虹吸水力计算系统/`）

根据附录L（倒虹吸管设计计算）的规范内容，对水力计算核心模块进行了重构。新的逻辑严格遵循规范中的公式体系，特别是将总水头损失明确划分为**进口段落差 ($\Delta Z_1$)**、**管身段损失 ($\Delta Z_2$)** 和 **出口段恢复/落差 ($\Delta Z_3$)** 三部分。

支持三种轴线计算模式：
- **A. 平面+纵断面（独立叠加）**：同时有平面IP点和纵断面节点时，平面转弯与纵断面竖向转弯分别计算局部损失后相加
- **B. 仅平面（独立计算）**：仅有平面段或平面总长度时，按平面转弯和通用构件计算
- **C. 仅纵断面（独立计算）**：仅有纵断面节点时，按纵断面竖向转弯和通用构件计算

说明：
- 当前水损计算不再调用 `SpatialMerger.merge_and_compute()` 生成三维空间弯道。
- `SpatialMerger`、`SpatialMergeResult` 等旧模型保留给历史结果、几何诊断和兼容代码，不再作为倒虹吸水损主路径。

---

## 步骤 1：几何设计与流速计算 (Geometry & Velocity)

### 输入
- 设计流量 $Q$ ($\text{m}^3/\text{s}$)
- 拟定流速 $v_{guess}$ ($\text{m}/\text{s}$)
- 进口渠道流速 $v_1$ ($\text{m}/\text{s}$)
- 出口渠道流速 $v_3$ ($\text{m}/\text{s}$)
- 管道根数 $N$（并联管道数量，1~10，默认1）
- $v_2$ 策略（AUTO_PIPE / V1_PLUS_02 / SECTION_CALC / MANUAL）

### 计算
- **并联管道分摊**：$Q_{single} = Q / N$
- **管道断面积**：$\omega = Q_{single} / v_{guess}$
- **理论直径**：$D_{theory} = \sqrt{4\omega / \pi}$
- **直径取整**：
  - 管径≤1m，按照0.05m取整
  - 管径≤1.6m，按照0.1m取整
  - 管径≤5m，按照0.2m取整
  - 用户可自定义实际直径，但不得小于理论直径
- **实际流速**：$v = Q_{single} / A = 4Q_{single} / (\pi D^2)$
- **水力半径**：$R_h = D / 4$ （对于圆管）
- **$v_2$ 确定**：
  - AUTO_PIPE → $v_2 = v$（管道流速，推荐）
  - V1_PLUS_02 → $v_2 = v_1 + 0.2$
  - SECTION_CALC → $v_2 = Q / [(B + m \cdot h) \cdot h]$
  - MANUAL → 用户直接输入
  - 安全兜底：若 $v_2 \le v_1$ 且 $v_1 > 0$，自动回退到管道流速
- **出口渐变段始端流速**：$v_{out} = v$（管道实际流速）

---

## 步骤 2：阻力参数初始化 (Resistance Setup)

### 沿程阻力系数
- 输入：糙率 $n$
- 计算**谢才系数 (Chezy C)** (依据 L.1.4)：

$$C = \frac{1}{n} R_h^{1/6}$$

### 局部损失系数更新
遍历所有管段结构 (StructureSegment)：

- **弯管 (Bend)** (依据 L.1.4-2, 表 L.1.4-3, L.1.4-4)：
  - 根据 $R/D_0$ 查表或插值获取 $\xi_{90^\circ}$
  - 根据弯管角度 $\theta$ 查表或插值获取修正系数 $\gamma$
  - 计算弯管系数：$\xi_w = \gamma \cdot \xi_{90^\circ}$

- **进口/出口渐变段系数**：
  - 获取进口渐变段系数 $\xi_1$ (依据 表 L.1.2)，仅用于 $\Delta Z_1$
  - 获取出口渐变段系数 $\xi_2$ (依据 表 L.1.4-5 或 L.1.3)，仅用于 $\Delta Z_3$
  - 结构段表里的进水口/出水口是构件局部损失，归入 `Σξ_通用` 并参与 $\Delta Z_2$，不替代 $\xi_1 / \xi_2$

- **折管 (Fold)**：
  - 公式：$\zeta = 0.9457 \sin^2(\theta/2) + 2.047 \sin^4(\theta/2)$

- **拦污栅 (TrashRack)** (依据 L.1.4-2, L.1.4-3)：
  - 无支墩：$\xi = \beta_1 (s_1/b_1)^{4/3} \sin\alpha$
  - 有支墩：$\xi = [\beta_1 (s_1/b_1)^{4/3} + \beta_2 (s_2/b_2)^{4/3}] \sin\alpha$

- **管道渐变段**：收缩 $\xi_{jb}=0.05$，扩散 $\xi_{jb}=0.10$

- **其他部件** (闸门槽、旁通管等)：获取相应的 $\xi_s, \xi_m$ 等

详细计算过程会把局部系数拆成三类来源：平面转弯、纵断面转弯、通用构件。每一类先逐项列出最终采用的 $\xi$，再展开 `Σξ_平面`、`Σξ_纵断面`、`Σξ_通用` 和 `Σξ_local` 的加法式；没有公式参数来源的构件只说明“来自结构段表采用值”，不补写不存在的查表过程。

### 计算模式与长度/弯道来源

- **平面+纵断面（独立叠加）**：平面弯管/折管按平面特征点查表，纵断面弯管/折管按纵断面节点查表，二者局部损失系数相加。
- **仅平面（独立计算）**：使用平面总长度和平面弯管/折管查表。
- **仅纵断面（独立计算）**：使用纵断面实长和纵断面弯管/折管查表。
- 沿程损失只计算一次：有纵断面实长时优先使用纵断面实长，没有纵断面时使用平面总长度。

---

## 步骤 3：水头损失求解 (Head Loss Calculation)

依据规范 L.1.6，倒虹吸管的总水面落差 $\Delta Z$ 由三部分组成：

$$\Delta Z = \Delta Z_1 + \Delta Z_2 - \Delta Z_3$$

### 1. 进口渐变段水面落差 ($\Delta Z_1$)

依据公式 L.1.2-2，包含流速水头增加及进口局部损失：

$$\Delta Z_1 = (1 + \xi_1) \frac{v_2^2 - v_1^2}{2g}$$

*注：$v_1$ 为进口渐变段始端流速，$v_2$ 为进口渐变段末端流速。*

### 2. 管身段总水头损失 ($\Delta Z_2$)

依据 L.1.4，包含沿程摩擦损失、管内局部损失和进口渐变段末端至管道进口的速度水头差。

**沿程损失项**：

$$h_f = \sum \frac{2g L_i}{C_i^2 R_i} \left( \frac{\omega}{\omega_i} \right)^2 \frac{v^2}{2g}$$

*注：若管径均一，简化为 $\frac{L_{total}}{C^2 R_h} v^2$*

**局部损失项**：

$$h_j = \sum \xi_i \left( \frac{\omega}{\omega_i} \right)^2 \frac{v^2}{2g}$$

*注：当前实现中的 `Σξ_local` 包括平面转弯、纵断面转弯，以及进水口/出水口构件、拦污栅、闸门槽、旁通管、管内独立渐变段等通用构件；进口/出口渐变段系数 $\xi_1 / \xi_2$ 仍只用于 $\Delta Z_1 / \Delta Z_3$。*

**总和**：

$$\Delta Z_2 = h_f + h_j + \frac{v^2 - v_2^2}{2g}$$

*注：当 $v_2$ 与管道实际流速 $v$ 相等时，速度水头差项为 0。*

### 3. 出口渐变段水面恢复/落差 ($\Delta Z_3$)

依据公式 L.1.3-2：

$$\Delta Z_3 = (1 - \xi_2) \frac{v^2 - v_3^2}{2g}$$

*注：$v$ 为出口渐变段始端流速，$v_3$ 为出口渐变段末端流速。$\Delta Z_3$ 为出口淨回升水头，在总落差中应减去（出口动能回收）。*

### 4. 总水面落差 ($\Delta Z$)

依据公式 L.1.6：

$$\Delta Z = \Delta Z_1 + \Delta Z_2 - \Delta Z_3$$

---

## 步骤 4：校验与结果生成 (Verification)

### 流能比校验 (可选)

计算流量系数 $\mu$ (依据 L.1.5-2)：

$$\mu = \frac{1}{\sqrt{\sum \xi_i + \sum \frac{2g L_i}{C_i^2 R_i} + 1 - \left(\frac{\omega}{\omega_{out}}\right)^2}}$$

*注：此处仅作为理论参数参考，实际校核以 $\Delta Z$ 为准*

### 水位校核

判断进出口水位差是否满足要求：

$$(H_{up} - H_{down}) \ge \Delta Z$$

- $H_{up}$：上游设计水位
- $H_{down}$：下游设计水位
- 计算安全裕度：$Margin = (H_{up} - H_{down}) - \Delta Z$

### 生成结果对象 (CalculationResult)

- `diameter` / `diameter_theory`：设计管径 / 理论直径 (m)
- `velocity`：管内实际流速 (m/s)
- `velocity_channel_in` / `velocity_pipe_in`：$v_1$ / $v_2$ (m/s)
- `velocity_outlet_start` / `velocity_channel_out`：$v_{out}$ / $v_3$ (m/s)
- `area` / `hydraulic_radius` / `chezy_c`：断面积 / 水力半径 / 谢才系数
- `loss_inlet` ($\Delta Z_1$) / `loss_pipe` ($\Delta Z_2$) / `loss_outlet` ($\Delta Z_3$)
- `loss_friction` ($h_f$) / `loss_local` ($h_j$)
- `total_head_loss` ($\Delta Z$)
- `total_length`：管道总长度 (m)
- `xi_sum_middle` / `xi_inlet` / `xi_outlet`：各部分阻力系数
- `num_pipes`：管道根数
- `data_mode` / `data_note`：计算模式说明
- `calculation_steps`：详细计算过程 (List[str])

---

## 步骤 5：加大流量工况 (Increased Flow)

当 `increase_percent > 0` 时，在同一次计算中完成加大工况：

- $Q_{inc} = Q \times (1 + p/100)$，其中 $p$ 为加大比例 (%)
- $v_{inc} = Q_{inc,single} / A$（管径不变，流速增大）
- $v_{2,inc}$ 按相同策略确定
- 重新计算三段水头损失：$\Delta Z_{1,inc}$、$\Delta Z_{2,inc}$、$\Delta Z_{3,inc}$

结果存储在 `CalculationResult` 的加大工况字段中：
- `increase_percent` / `Q_increased` / `velocity_increased`
- `loss_inlet_inc` / `loss_pipe_inc` / `loss_outlet_inc` / `total_head_loss_inc`

---

## 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-02-15 | 初始版本，三段式水头损失公式 |
| v2.0 | 2026-02-25 | 新增：并联管道(num_pipes)、v2策略、折管公式、拦污栅公式、管道渐变段系数、三维空间合并模式、加大流量工况；结果对象与代码对齐 |
