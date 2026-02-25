# PRD — 拦污栅详细参数配置模块

**版本**: v1.3  
**最后更新**: 2026-02-24  
**规范依据**: GB 50288-2018 附录L，公式 L.1.4-2 / L.1.4-3，表 L.1.4-1，图 L.1.4-1  
**状态**: v1.3 — 全部核心需求已实现，P0/P1 已修复，主表格集成已完成

---

## 一、模块概述

拦污栅是倒虹吸进口前的通用构件，其水头损失系数 ξs 依据栅条/支墩几何尺寸和栅面倾角，按附录L公式计算。本模块提供可视化参数配置环境：用户在对话框中对照规范示意图和系数表选择栅条形状，程序自动计算 ξs 并回填至结构段表格。

---

## 二、文件结构

```
渠系断面设计/siphon/
└── dialogs.py           # TrashRackConfigDialog（配置对话框）

倒虹吸水力计算系统/
├── siphon_models.py     # TrashRackBarShape(Enum), TrashRackParams(dataclass)
├── siphon_coefficients.py  # CoefficientService — 计算引擎
└── resources/
    ├── 图L.1.4-1.png    # 栅条形状示意图（已使用）
    └── 表L.1.4-1.png    # 形状系数表图片（存在但未使用）
```

> **集成入口**：`渠系断面设计/siphon/panel.py` — 结构段表格双击/编辑分发逻辑（第2178行）

---

## 三、数据模型

### 3.1 TrashRackBarShape（枚举）

| 枚举值 | UI 显示名称 | β 系数 |
|--------|------------|--------|
| `RECTANGULAR` | 矩形 | 2.42 |
| `ROUNDED_HEAD` | 单侧圆头 | 1.83 |
| `CIRCULAR` | 圆形 | 1.79 |
| `OVAL` | 双侧圆头 | 1.67 |
| `TRAPEZOID` | 倒梯形单侧圆头 | 1.04 |
| `PEAR_SHAPE` | 梨形/流线型 | 0.92 |
| `SHARP_TAIL` | 两端尖锐型 | 0.76 |

**文件**: `siphon_models.py:88-96` / `siphon_coefficients.py:67-76`

### 3.2 TrashRackParams（数据类）

```python
@dataclass
class TrashRackParams:
    alpha: float = 90.0                  # 栅面倾角 (度)，0~180
    has_support: bool = False            # 是否有独立支墩
    bar_shape: TrashRackBarShape = RECTANGULAR
    beta1: float = 2.42                  # 栅条形状系数（自动查表）
    s1: float = 10.0                     # 栅条厚度 (mm)
    b1: float = 50.0                     # 栅条间距 (mm)
    support_shape: TrashRackBarShape = RECTANGULAR
    beta2: float = 2.42                  # 支墩形状系数（自动查表）
    s2: float = 10.0                     # 支墩厚度 (mm)（与栅条默认值一致）
    b2: float = 50.0                     # 支墩净距 (mm)（与栅条默认值一致）
    manual_mode: bool = False            # 强制手动输入模式
    manual_xi: float = 0.0              # 手动输入的最终系数
```

`trash_rack_params` 字段挂载在 `StructureSegment` 上（`siphon_models.py:127`），仅当 `segment_type == TRASH_RACK` 时有效。

---

## 四、计算引擎

**文件**: `siphon_coefficients.py:199-298`  
**方法**: `CoefficientService.calculate_trash_rack_xi(params, verbose=False)`

### 公式 L.1.4-2（无独立支墩）

$$\xi_s = \beta_1 \cdot \left(\frac{s_1}{b_1}\right)^{4/3} \cdot \sin\alpha$$

### 公式 L.1.4-3（有独立支墩）

$$\xi_s = \left[\beta_1 \cdot \left(\frac{s_1}{b_1}\right)^{4/3} + \beta_2 \cdot \left(\frac{s_2}{b_2}\right)^{4/3}\right] \cdot \sin\alpha$$

### 参数校验

| 条件 | 处理方式 |
|------|---------|
| `alpha < 0` 或 `alpha > 180` | 返回 0.0，verbose 模式报错 |
| `b1 <= 0` | 返回 0.0，报错 |
| `has_support` 且 `b2 <= 0` | 返回 0.0，报错 |
| `manual_mode = True` | 直接返回 `manual_xi`，跳过公式 |

### 验收样例

输入：`alpha=90°, bar_shape=矩形(β=2.42), s1=10mm, b1=50mm, has_support=False`  
计算：`ξs = 2.42 × (10/50)^(4/3) × sin(90°) = 0.2830`  
预期：**0.283** ✅

---

## 五、配置对话框（TrashRackConfigDialog）

**文件**: `渠系断面设计/siphon/dialogs.py:448-754`  
**继承**: `QDialog`  
**窗口尺寸**: 900×750（最小 820×660）

### 5.1 总体布局

左右双栏（`QHBoxLayout`，各占 stretch=1）：

- **左侧**：参数录入区（`QVBoxLayout`，从上到下：基础参数 → 栅条参数 → 支墩参数 → 计算结果）
- **右侧**：规范参考区（栅条形状示意图 + 形状系数表）

### 5.2 左侧：参数录入区

#### 分组一：基础参数

| 控件 | 说明 | 状态 |
|------|------|------|
| 栅面倾角 (度) | `LineEdit`，默认 90，范围 0~180 | ✅ 已实现 |
| 计算模式 | `QButtonGroup` + 两个 `QRadioButton` | ✅ 已实现 |
| ○ 无独立支墩 (公式L.1.4-2) | 默认选中 | ✅ |
| ○ 有独立支墩 (公式L.1.4-3) | 选中后激活分组三 | ✅ |

#### 分组二：栅条参数

| 控件 | 说明 | 状态 |
|------|------|------|
| 栅条形状 | `ComboBox`，选项格式 `"矩形 (β=2.42)"` | ✅ 已实现 |
| 选择形状→右侧表格高亮 | `_on_bar_changed()` → `_sync_table_highlight()` | ✅ 已实现 |
| 栅条厚度 s₁ (mm) | `LineEdit` | ✅ 已实现 |
| 栅条间距 b₁ (mm) | `LineEdit` | ✅ 已实现 |
| s₁/b₁ 动态显示 | 实时计算阻塞比 | ✅ 已实现 |

#### 分组三：支墩参数（仅有独立支墩时激活）

| 控件 | 说明 | 状态 |
|------|------|------|
| 支墩形状 | `ComboBox`，格式同栅条形状 | ✅ 已实现 |
| 支墩厚度 s₂ (mm) | `LineEdit` | ✅ 已实现 |
| 支墩净距 b₂ (mm) | `LineEdit` | ✅ 已实现 |
| s₂/b₂ 动态显示 | 实时计算阻塞比 | ✅ 已实现 |

> 无独立支墩时整个分组三 `setEnabled(False)`（控件灰色显示，仍可见）。

#### 分组四：计算结果

| 控件 | 说明 | 状态 |
|------|------|------|
| ☑ 强制手动输入 | `CheckBox` | ✅ 已实现 |
| 手动 ξs 输入框 | 仅勾选时可编辑；切换时自动预填公式计算值 | ✅ 已实现 |
| ξs = 0.XXXX 结果显示 | 20px 粗体主色调，实时更新 | ✅ 已实现 |
| 公式渲染卡片 | `QWebEngineView` + KaTeX SVG 实时展开公式；手动模式下隐藏 | ✅ 已实现 |
| 几何输入框勾选后禁用 | 勾选手动后 `g2`(栅条) 和 `g3`(支墩) 全部 `setEnabled(False)` | ✅ 已实现 |
| [确定] / [取消] 按钮 | 确定→写回 `TrashRackParams.result` | ✅ 已实现 |

### 5.3 右侧：规范参考区

#### 上部：栅条形状示意图 (图L.1.4-1)

| 功能 | 说明 | 状态 |
|------|------|------|
| 图片加载 | `QPixmap(图L.1.4-1.png)`，`KeepAspectRatio` | ✅ 已实现 |
| 固定高度 240px | 防止图片撑满右侧 | ✅ 已实现 |
| 自适应缩放 | `resizeEvent` 时重新按实际 label 尺寸缩放 | ✅ 已实现 |
| 双击放大查看 | 弹出独立 `QDialog`，图片缩放至屏幕 80% | ✅ 已实现 |

#### 下部：形状系数表 (表L.1.4-1)

| 功能 | 说明 | 状态 |
|------|------|------|
| 两列：形状名称 / 系数β | `QTableWidget`，7行 | ✅ 已实现 |
| 只读 | `NoEditTriggers` | ✅ 已实现 |
| 列宽 Stretch 充满 | 两列均 `SectionResizeMode.Stretch` | ✅ 已实现 |
| 无水平滚动条 | `ScrollBarAlwaysOff` | ✅ 已实现 |
| 点击行→同步左侧栅条形状 ComboBox | `_on_table_clicked()` | ✅ 已实现 |
| 第三列：形状缩略图（可选） | 原始需求列2，嵌入小图 | ❌ **未实现** |

---

## 六、主表格集成入口

### 6.1 当前状态（panel.py:2191）✅ 已实现

```python
elif seg.segment_type == SegmentType.TRASH_RACK:
    dlg = TrashRackConfigDialog(self, seg.trash_rack_params)
    if dlg.exec() == QDialog.Accepted and dlg.result:
        real_idx = self.segments.index(seg)
        self.segments[real_idx].trash_rack_params = dlg.result
        self.segments[real_idx].xi_calc = CoefficientService.calculate_trash_rack_xi(dlg.result)
        self.segments[real_idx].xi_user = None
```

### 6.2 功能清单

| 需求 | 说明 | 状态 |
|------|------|------|
| 双击拦污栅行 → 弹出 `TrashRackConfigDialog` | panel.py:2191 | ✅ 已实现 |
| 确定后回填 ξs 至表格 | `trash_rack_params` → `xi_calc`，`xi_user = None` | ✅ 已实现 |
| 类型列显示配置状态 | `"拦污栅(已配置)"` / `"拦污栅(未配置)"` | ✅ 已实现 |
| 序列化/反序列化 | `_seg_to_dict` / `_dict_to_seg` 保存/恢复 `trash_rack_params` | ✅ 已实现 |
| 反序列化时自动重算 ξ | `_dict_to_seg` 中若 `xi_calc is None` 且非手动模式，自动调用 `calculate_trash_rack_xi` | ✅ 已实现 |

---

## 七、异常处理

| 场景 | 当前处理 | 状态 |
|------|---------|------|
| b1 = 0 或 s1 = 0 | 结果显示"请输入栅条参数"；确定时弹 InfoBar 报错 | ✅ |
| b2 = 0（有支墩时） | 结果显示"请输入支墩参数"；确定时弹 InfoBar 报错 | ✅ |
| alpha 超范围 | `_collect()` 返回 None | ✅ |
| 手动模式下禁用几何输入框 | `_on_manual()` 中 `g2.setEnabled(False)`, `g3.setEnabled(False)` | ✅ |
| 手动模式下清除表格高亮 | `_sync_table_highlight()` 中 `bar_idx`/`sup_idx` 置 -1 | ✅ |
| 切换为无支墩时重置活跃目标 | `_on_mode()` 中 `_active_target = 'bar'` | ✅ |
| ξs 为负数 | 未校验（`calculate_trash_rack_xi` 不会出负数） | — |

---

## 八、验收标准

| 编号 | 验收项 | 状态 |
|------|--------|------|
| AC-1 | 打开配置窗口，右侧清晰显示规范示意图和系数表 | ✅ |
| AC-2 | 在左侧选择"矩形"，右侧系数表第一行高亮 | ✅ |
| AC-3 | 点击系数表第N行，左侧栅条形状自动切换至第N项 | ✅ |
| AC-4 | 双击示意图，弹出大图窗口 | ✅ |
| AC-5 | 输入 s1=10, b1=50, alpha=90, 矩形，结果显示 0.2830 | ✅ |
| AC-6 | 双击结构段表格拦污栅行，弹出 TrashRackConfigDialog | ✅ 已实现 |
| AC-7 | 确定后，主界面表格 ξ 列更新为计算值 | ✅ 已实现 |
| AC-8 | 拦污栅行类型列显示"已配置"/"未配置"状态 | ✅ 已实现 |

---

## 九、待办事项

### 已完成

- [x] **P0 panel.py 集成**：双击拦污栅行弹出 `TrashRackConfigDialog`，结果写回 `trash_rack_params` + `xi_calc`（v1.3）
- [x] **P1 手动模式禁用输入框**：勾选后 g2/g3 全部 `setEnabled(False)`（v1.2）
- [x] **默认值对齐**：支墩默认 s2/b2 改为与栅条一致（10.0/50.0）（v1.3）

### 待定（可选）

- [ ] **P2 系数表第三列缩略图**：在 `形状系数表` 中增加第三列，嵌入各形状小图或 SVG 截面示意

---

## 十、变更日志

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-02-24 | 首次创建。反向梳理当前实现，记录 `TrashRackConfigDialog` 已实现内容与主表格集成缺口；补充 RadioButton 双选/双向同步/双击放大/自适应缩放等恢复功能的实现说明 |
| v1.1 | 2026-02-24 | 方案A三控件上下文感知联动：①新增 `_active_target` 追踪活跃目标；②表格点击根据活跃目标分发到栅条/支墩ComboBox；③`_sync_table_highlight()` 改为双色背景高亮（蓝=栅条、琥珀=支墩、紫=重叠）；④`_update_tbl_title()` 动态更新表格标题显示当前联动目标；⑤新增 `_on_sup_changed()` 支墩变化处理器；⑥`_on_mode()` 切换无支墩时自动重置为 bar 目标；⑦表格设为 `NoSelection` 模式 + 手型光标；⑧底部添加颜色图例 |
| v1.2 | 2026-02-24 | 四项UX优化：①**D** `g2`/`g3` GroupBox 标题加蓝色/琥珀色圆点（`QGroupBox::title` stylesheet），与表格高亮色视觉映射；②**B** `formula_view`（`QWebEngineView` + KaTeX SVG）实时展开公式卡片，手动模式下隐藏（高度置0）；③**C** Bug修复：`_sync_table_highlight()` 手动模式下将 `bar_idx`/`sup_idx` 置 -1，清除所有高亮；④**A** `_on_manual()` 切换为手动模式时调用新增 `_calc_xi_auto()` 预填公式计算值，并禁用 `g2`/`g3` 全部输入框 |
| v1.3 | 2026-02-24 | ①支墩默认值对齐：`s2` 100→10, `b2` 1000→50（与栅条 s1/b1 一致）；`from_dict` 回退默认值同步更新；②PRD全面同步代码现状：panel.py 集成入口已实现（2191行），手动模式禁用已实现，AC-6/7/8 验收通过；③待办事项更新为已完成状态 |
