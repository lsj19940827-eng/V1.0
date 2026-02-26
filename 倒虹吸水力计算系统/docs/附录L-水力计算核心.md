# 5. 水力计算核心 (Hydraulic Core)

**版本**: v2.0  
**最后更新**: 2026-02-25  
**代码**: `siphon_hydraulics.py`（`倒虹吸水力计算系统/`）

根据附录L（倒虹吸管设计计算）的规范内容，对水力计算核心模块进行了重构。新的逻辑严格遵循规范中的公式体系，特别是将总水头损失明确划分为**进口段落差 ($\Delta Z_1$)**、**管身段损失 ($\Delta Z_2$)** 和 **出口段恢复/落差 ($\Delta Z_3$)** 三部分。

支持三种计算模式：
- **A. 三维空间合并模式**：同时有平面IP点和纵断面节点时，使用 SpatialMerger 计算空间长度和空间转角 θ_3D
- **B. 传统模式**：仅有平面段或平面总长度
- **C. 单数据源模式**：仅有纵断面或无空间数据

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

- **进出口**：
  - 获取进口局部损失系数 $\xi_1$ (依据 表 L.1.2)
  - 获取出口局部损失系数 $\xi_2$ (依据 表 L.1.4-5 或 L.1.3)

- **折管 (Fold)**：
  - 公式：$\zeta = 0.9457 \sin^2(\theta/2) + 2.047 \sin^4(\theta/2)$

- **拦污栅 (TrashRack)** (依据 L.1.4-2, L.1.4-3)：
  - 无支墩：$\xi = \beta_1 (s_1/b_1)^{4/3} \sin\alpha$
  - 有支墩：$\xi = [\beta_1 (s_1/b_1)^{4/3} + \beta_2 (s_2/b_2)^{4/3}] \sin\alpha$

- **管道渐变段**：收缩 $\xi_{jb}=0.05$，扩散 $\xi_{jb}=0.10$

- **其他部件** (闸门槽、旁通管等)：获取相应的 $\xi_s, \xi_m$ 等

### 计算模式与长度/弯道来源

- **模式A（三维空间合并）**：调用 `SpatialMerger.merge_and_compute()`，使用空间长度 $L_{spatial} = \sqrt{\Delta s^2 + \Delta Z^2}$ 和空间转角 $\theta_{3D}$ 查表。详见 `空间轴线合并算法-PRD.md`
- **模式B（传统）**：使用平面总长度和平面弯管查表
- **模式C（单数据源）**：使用纵断面段长度之和

---

## 步骤 3：水头损失求解 (Head Loss Calculation)

依据规范 L.1.6，倒虹吸管的总水面落差 $\Delta Z$ 由三部分组成：

$$\Delta Z = \Delta Z_1 + \Delta Z_2 - \Delta Z_3$$

### 1. 进口渐变段水面落差 ($\Delta Z_1$)

依据公式 L.1.2-2，包含流速水头增加及进口局部损失：

$$\Delta Z_1 = (1 + \xi_1) \frac{v_2^2 - v_1^2}{2g}$$

*注：$v_1$ 为进口渐变段始端流速，$v_2$ 为进口渐变段末端流速。*

### 2. 管身段总水头损失 ($\Delta Z_2$)

依据公式 L.1.4-7，包含沿程摩擦损失和管内局部损失总和。

**沿程损失项**：

$$h_f = \sum \frac{2g L_i}{C_i^2 R_i} \left( \frac{\omega}{\omega_i} \right)^2 \frac{v^2}{2g}$$

*注：若管径均一，简化为 $\frac{L_{total}}{C^2 R_h} v^2$*

**局部损失项**：

$$h_j = \sum \xi_i \left( \frac{\omega}{\omega_i} \right)^2 \frac{v^2}{2g}$$

*注：$\xi_i$ 包括弯管、人孔、拦污栅等除进出口外的所有系数*

**总和**：

$$\Delta Z_2 = h_f + h_j$$

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
