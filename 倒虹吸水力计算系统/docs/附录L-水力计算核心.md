# 5. 水力计算核心 (Hydraulic Core)

根据附录L（倒虹吸管设计计算）的规范内容，对水力计算核心模块进行了重构。新的逻辑严格遵循规范中的公式体系，特别是将总水头损失明确划分为**进口段落差 ($\Delta Z_1$)**、**管身段损失 ($\Delta Z_2$)** 和 **出口段恢复/落差 ($\Delta Z_3$)** 三部分。

---

## 步骤 1：几何设计与流速计算 (Geometry & Velocity)

### 输入
- 设计流量 $Q$ ($\text{m}^3/\text{s}$)
- 拟定流速 $v_{guess}$ ($\text{m}/\text{s}$)
- 进口渠道流速 $v_1$ ($\text{m}/\text{s}$)
- 出口渠道流速 $v_3$ ($\text{m}/\text{s}$)

### 计算
- **管道断面积**：$\omega = Q / v_{guess}$
- **理论直径**：$D_{theory} = \sqrt{4\omega / \pi}$
- **直径取整**：
  - 管径≤1m，按照0.05m取整
  - 管径≤1.6m，按照0.1m取整
  - 管径≤5m，按照0.2m取整
  - 用户可自定义实际直径，但不得小于理论直径
- **实际流速**：$v = 4Q / (\pi D^2)$
- **水力半径**：$R_h = D / 4$ （对于圆管）

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

- **其他部件** (如拦污栅、闸门槽等)：获取相应的 $\xi_s, \xi_m$ 等

---

## 步骤 3：水头损失求解 (Head Loss Calculation)

依据规范 L.1.6，倒虹吸管的总水面落差 $\Delta Z$ 由三部分组成：

$$\Delta Z = \Delta Z_1 + \Delta Z_2 + \Delta Z_3$$

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

*注：$v$ 为出口渐变段始端流速，$v_3$ 为出口渐变段末端流速。根据规范公式，该项通常为正值，需计入总落差中。*

### 4. 总水面落差 ($\Delta Z$)

依据公式 L.1.6：

$$\Delta Z = \Delta Z_1 + \Delta Z_2 + \Delta Z_3$$

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

### 生成结果对象 (Result Object)

- `Diameter` ($D$)
- `Velocity` ($v$, $v_1$, $v_3$)
- `HeadLoss_Inlet` ($\Delta Z_1$)
- `HeadLoss_Pipe` ($\Delta Z_2$)
  - `Friction` ($h_f$)
  - `Local` ($h_j$)
- `HeadLoss_Outlet` ($\Delta Z_3$)
- `Total_Drop_Required` ($\Delta Z$)
- `Is_Verified` (Bool)
