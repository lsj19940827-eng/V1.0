# 有压管道参与批量计算和水面线推求 - PRD V1.0

> **版本**: V1.0  
> **创建日期**: 2026-03-03  
> **状态**: 需求确认完成，待实现

## 一、需求概述

将"有压管道"作为新的结构类型添加到系统中，与倒虹吸类似：
- 在批量计算中作为**占位行**（不直接计算，在独立窗口中完成水头损失计算）
- 支持多行模式：进口行 + 多个IP点行 + 出口行
- 水头损失结果回写到水面线推求，参与全线水位递推

## 二、用户确认的关键需求

| 需求项 | 用户选择 |
|--------|----------|
| 计算模式 | 占位行模式（类似倒虹吸） |
| Excel行组织 | 多行模式（进口/IP点/出口各占一行） |
| 共享参数位置 | 进出口行都填写（Q、D、管材等） |
| 管材指定 | Excel中新增专属列 |
| 管长计算 | 自动计算（通过IP点X/Y坐标） |
| 局部损失计算 | 详细ζ值法（参考倒虹吸弯管系数） |
| 沿程损失公式 | GB 50288公式：hf = f × Q^m / d^b |
| 渐变段处理 | 考虑渐变段损失（可选型式） |
| 纵断面DXF | 第一版就支持导入 |
| 代码架构 | 独立实现，不复用倒虹吸框架 |

## 三、Excel列结构扩展

现有21列（col 0-20），新增3列，共**24列**：

| 新列索引 | 列名 | 说明 | 适用行 |
|---------|------|------|-------|
| col 21 | 管材 | HDPE管/球墨铸铁管/钢管等 | 进口行、出口行 |
| col 22 | 局部损失比例 | 简化模式用，默认0.15 | 进口行 |
| col 23 | 进出口标识 | "进"/"IP"/"出" | 有压管道所有行 |

### 三种行的填写规则

| 列 | 进口行 | IP点行 | 出口行 |
|----|--------|--------|--------|
| 结构形式(3) | 有压管道 | 有压管道 | 有压管道 |
| 名称(2) | 管道名称 | 同名 | 同名 |
| X/Y(4/5) | 进口坐标 | IP点坐标 | 出口坐标 |
| Q(6) | 设计流量 | 留空 | 设计流量 |
| 直径D(13) | 管径 | 留空 | 管径 |
| 转弯半径(20) | 留空 | 该IP点转弯半径 | 留空 |
| 管材(21) | 管材类型 | 留空 | 管材类型（可继承） |
| 局部损失比例(22) | 0.15 | 留空 | 留空 |
| 进出口标识(23) | 进 | IP | 出 |

## 四、新建文件清单

### 4.1 数据提取器：`推求水面线/utils/pressure_pipe_extractor.py`

**PressurePipeGroup 数据类**：
```python
@dataclass
class PressurePipeGroup:
    name: str                           # 管道名称
    rows: List[ChannelNode]             # 所有行（进+IP+出）
    inlet_row_index: int                # 进口行索引
    outlet_row_index: int               # 出口行索引
    ip_row_indices: List[int]           # IP点行索引列表
    design_flow: float                  # 设计流量 Q（m³/s）
    diameter: float                     # 管径 D（m）
    material_key: str                   # 管材 key
    local_loss_ratio: float = 0.15     # 局部损失比例（简化模式）
    ip_points: List[Dict]               # IP点信息（坐标、转弯半径、转角）
    plan_segments: List[Dict]           # 平面段列表（直管+弯管）
    plan_total_length: float            # 总管长（m）
    upstream_velocity: float            # 上游渠道流速 v₁
    downstream_velocity: float          # 下游渠道流速 v₃
    upstream_section_params: Dict       # 上游断面参数
    downstream_section_params: Dict     # 下游断面参数
```

**PressurePipeDataExtractor 类**：
- `extract_pipes(nodes, settings)` — 主入口
- `_calc_plan_segments(group)` — 计算平面段（直管+弯管）
- `_calc_turn_angles(group)` — 计算各IP点转角
- `_extract_adjacent_node_data(group, nodes)` — 提取上下游渠道信息

### 4.2 数据管理器：`推求水面线/managers/pressure_pipe_manager.py`

**PressurePipeManager 类**（参照SiphonManager）：
- 配置文件：`项目文件名.ppipe.json`
- `set_config(name, config)` — 保存配置
- `get_config(name)` — 获取配置
- `set_result(name, total_head_loss, ...)` — 保存计算结果
- `get_result(name)` — 获取水头损失结果

### 4.3 水力计算核心：`推求水面线/core/pressure_pipe_calc.py`

**PressurePipeHydraulicCalc 类**：

```python
# 沿程损失（GB 50288-2018 §6.7.2）
def calc_friction_loss(Q_m3s, D_m, L_m, material_key):
    Q_m3h = Q_m3s * 3600      # m³/s → m³/h
    d_mm = D_m * 1000          # m → mm
    f, m, b = PIPE_MATERIALS[material_key]
    hf = f * L_m * (Q_m3h ** m) / (d_mm ** b)
    return hf  # 单位：m

# 弯头局部损失（参考倒虹吸表L.1.4-3/L.1.4-4）
def calc_bend_local_loss(D_m, turn_radius_m, turn_angle_deg, V_m_s):
    R_D = turn_radius_m / D_m
    xi_90 = lookup_xi90_table(R_D)      # 表L.1.4-3
    gamma = lookup_gamma_table(turn_angle_deg)  # 表L.1.4-4
    xi_bend = xi_90 * gamma
    hj = xi_bend * V_m_s**2 / (2 * 9.81)
    return xi_bend, hj

# 渐变段损失（可选型式，参考表L.1.2）
def calc_transition_loss(V_pipe, V_channel, zeta, is_inlet):
    if is_inlet:
        hj = zeta * (V_pipe**2 - V_channel**2) / (2 * 9.81)
    else:
        hj = zeta * (V_channel**2 - V_pipe**2) / (2 * 9.81)
    return max(0, hj)

# 管内流速
def calc_pipe_velocity(Q_m3s, D_m):
    return Q_m3s / (math.pi * D_m**2 / 4)
```

### 4.4 计算面板：`渠系断面设计/pressure_pipe/pp_calc_panel.py`

单管道计算面板（QWidget），功能区域：
1. 基本参数区：名称、Q、D、管材选择
2. 进出口渐变段参数：型式选择（反弯扭曲面/直线扭曲面/圆弧/方头型）、ζ值
3. 轴线段表格：类型/长度/转弯半径/转角/ζ
4. 计算结果区：沿程损失、弯头局部损失、渐变段损失、**总水头损失**
5. 详细过程文本区

### 4.5 多标签对话框：`渠系断面设计/pressure_pipe/multi_pressure_pipe_dialog.py`

参照`multi_siphon_dialog.py`：
- 每个有压管道一个标签页
- 支持"全部计算"和"导入水头损失"
- 汇总结果表格

## 五、修改现有文件

### 5.1 `推求水面线/models/enums.py`
- `StructureType` 新增：`PRESSURE_PIPE = "有压管道"`
- `get_special_structures()` 加入 `PRESSURE_PIPE`

### 5.2 `推求水面线/models/data_models.py`
- `ChannelNode` 新增字段：`is_pressure_pipe: bool = False`
- `section_params` 透传：`pipe_material`、`local_loss_ratio`、`in_out_raw`

### 5.3 `渠系断面设计/batch/panel.py`
- `SECTION_TYPES` 新增 `"有压管道"`
- `INPUT_HEADERS` 追加3列：`"管材"`、`"局部损失比例"`、`"进出口标识"`
- `_batch_calculate()` 新增有压管道占位行处理分支
- `_one_click_full_flow()` 新增有压管道检测和计算调用

### 5.4 `渠系断面设计/water_profile/panel.py`
- 工具栏新增"有压管道计算"按钮
- `_import_from_batch()` 处理有压管道数据导入
- 新增 `_open_pressure_pipe_calculator()` 方法
- `_start_calc()` 新增有压管道未计算警告

### 5.5 `推求水面线/core/hydraulic_calc.py`
- 新增 `pressure_pipe_losses: Dict[str, float]`
- 新增 `import_pressure_pipe_losses()` 方法
- `_calc_head_loss()` 新增有压管道分支

### 5.6 `推求水面线/shared/shared_data_manager.py`
- `_extract_section_result()` 新增有压管道处理分支

## 六、关键算法

### 6.1 转角自动计算
```
对于中间IP点 Pᵢ：
  v_in = Pᵢ - Pᵢ₋₁（进入方向向量）
  v_out = Pᵢ₊₁ - Pᵢ（离开方向向量）
  θᵢ = arccos(v_in · v_out / |v_in| |v_out|)
```

### 6.2 管长计算
```
总管长 = Σ直管段长度 + Σ弯管弧长
直管段长度 = √((Xᵢ - Xᵢ₋₁)² + (Yᵢ - Yᵢ₋₁)²) - 切线长修正
弯管弧长 = R × θ_rad
```

### 6.3 弯管局部损失系数（表L.1.4-3/L.1.4-4）
```
1. 计算 R/D 比值
2. 查表L.1.4-3得 ξ₉₀（直角弯道系数）
3. 查表L.1.4-4得 γ（角度修正系数）
4. ξ_弯 = ξ₉₀ × γ
```

### 6.4 渐变段型式与ζ值（表L.1.2）
| 渐变段型式 | 进口ζ₁ | 出口ζ₃ |
|-----------|--------|--------|
| 反弯扭曲面 | 0.10 | 0.20 |
| 直线扭曲面 | 0.20 | 0.30 |
| 1/4圆弧 | 0.25 | 0.35 |
| 方头型 | 0.30 | 0.75 |

## 七、实现顺序

1. **基础层**
   - 修改 `enums.py`、`data_models.py`（新增枚举和字段）
   
2. **计算内核**
   - 新建 `pressure_pipe_calc.py`（纯函数，可独立测试）
   - 复用倒虹吸的 `CoefficientService` 查表功能
   
3. **数据层**
   - 新建 `pressure_pipe_extractor.py`
   - 新建 `pressure_pipe_manager.py`
   
4. **批量计算**
   - 修改 `batch/panel.py`（新增列、占位行处理）
   - 修改 `shared_data_manager.py`
   
5. **计算窗口**
   - 新建 `pp_calc_panel.py`
   - 新建 `multi_pressure_pipe_dialog.py`
   - 支持DXF导入纵断面
   
6. **水面线集成**
   - 修改 `hydraulic_calc.py`
   - 修改 `water_profile/panel.py`

## 八、验证方案

### 8.1 单元测试
- 测试 `calc_friction_loss()` 与现有有压管道模块结果一致
- 测试 `calc_bend_local_loss()` 与倒虹吸弯管系数一致
- 测试转角计算正确性

### 8.2 集成测试
1. 准备测试Excel：包含一个有压管道（进口+2个IP点+出口）
2. 执行批量计算，验证占位行正确识别
3. 导入到水面线推求，验证多行结构正确
4. 打开有压管道计算窗口，验证参数自动填充
5. 执行计算，验证水头损失结果合理
6. 导入水头损失，验证回写到水面线表格
7. 执行水面线推求，验证水位递推正确

### 8.3 端到端测试
- 执行"一键全流程"，验证有压管道自动计算并参与水面线推求

## 九、关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 批量计算面板 | `渠系断面设计/batch/panel.py` |
| 水面线面板 | `渠系断面设计/water_profile/panel.py` |
| 倒虹吸提取器（参考） | `推求水面线/utils/siphon_extractor.py` |
| 倒虹吸管理器（参考） | `推求水面线/managers/siphon_manager.py` |
| 倒虹吸系数服务（复用） | `倒虹吸水力计算系统/siphon_coefficients.py` |
| 现有有压管道模块（复用管材参数） | `渠系建筑物断面计算/有压管道设计.py` |
| 枚举定义 | `推求水面线/models/enums.py` |
| 数据模型 | `推求水面线/models/data_models.py` |
| 水力计算核心 | `推求水面线/core/hydraulic_calc.py` |
| 共享数据管理 | `推求水面线/shared/shared_data_manager.py` |

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| V1.0 | 2026-03-03 | 初始版本，完成需求确认 |
