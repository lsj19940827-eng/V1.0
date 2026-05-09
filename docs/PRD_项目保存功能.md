# 项目保存功能实现方案

> **文档版本**: PRD V1.1
> **创建日期**: 2026-03-03
> **最后更新**: 2026-05-09

---

## 需求概述

为渠系水力计算系统添加以项目为单位的保存/加载功能。当前保存范围包括批量计算、推求水面线、明渠、渡槽、隧洞、暗涵、倒虹吸和有压管道等主要工作面板的数据。

## 确认的需求规格

| 项目 | 规格 |
|------|------|
| 文件格式 | JSON，扩展名 `.qxproj` |
| 触发方式 | 手动保存 + 自动定时(1分钟) + 程序关闭时保存 |
| 默认文件名 | `渠道名称+级别+时间戳.qxproj`（如：南峰寺支渠_20260303_143052.qxproj） |
| 自动保存路径 | `{程序目录}/data/南峰寺支渠_autosave.qxproj` |
| 启动行为 | 空白启动 |
| 数据冲突 | 加载新项目时提示是否保存当前数据 |
| 窗口标题 | `渠系建筑物水力计算系统 - 项目名.qxproj *`（*表示未保存） |
| 快捷键 | Ctrl+S 保存，Ctrl+O 打开，Ctrl+N 新建 |
| 数据兼容 | 向后兼容（缺失字段用默认值填充） |
| 保存提示 | 手动保存：浮动通知+状态栏；自动保存：仅状态栏 |

## UI 布局

侧边栏单个「项目管理」按钮，点击弹出菜单：
```
📁 项目管理
├── 🆕 新建项目          (Ctrl+N)
├── 📂 打开项目...       (Ctrl+O)
├── 💾 保存项目          (Ctrl+S)
├── 💾 另存为...
├── ─────────────────
├── ⚙  项目设置          → 复用现有对话框
├── ─────────────────
└── 🕐 最近项目 ▶        → 最多5个
```

---

## 项目文件 JSON 结构

```json
{
  "format": "qxproj",
  "version": "1.0",
  "app_version": "1.0.6.x",
  "created_at": "2026-03-03 14:30:52",
  "saved_at": "2026-03-03 14:31:05",
  
  "project_meta": {
    "channel_name": "南峰寺支渠",
    "channel_level": "支渠",
    "description": ""
  },
  
  "modules": {
    "batch": {
      "version": "1.0",
      "channel_name": "南峰寺",
      "channel_level": "支渠",
      "input_rows": [["1", "第一段", "明渠-梯形", ...], ...]
    },
      "water_profile": {
        "version": "1.0",
        "ui_settings": {
          "channel_name": "南峰寺",
          "channel_level": "支渠",
          "start_water_level": "100.0",
          "design_flows_text": "5.5,4.2",
          "max_flows_text": "6.0,4.8",
          "start_station_text": "0+000.000",
        "roughness": "0.014",
        "turn_radius": "300.0",
        "trans_inlet_form": "曲线形反弯扭曲面",
        "trans_inlet_zeta": "0.10",
        "trans_outlet_form": "曲线形反弯扭曲面",
        "trans_outlet_zeta": "0.20",
        "oc_trans_form": "曲线形反弯扭曲面",
        "oc_trans_zeta": "0.10",
        "siphon_inlet_form": "反弯扭曲面",
        "siphon_inlet_zeta": "0.10",
        "siphon_outlet_form": "反弯扭曲面",
        "siphon_outlet_zeta": "0.20"
      },
      "project_settings": { "...ProjectSettings.to_dict()输出..." },
      "nodes": [{ "...ChannelNode序列化..." }, ...],
      "calculated_nodes": [{ "...ChannelNode序列化..." }, ...],
      "extra_caches": {
        "node_structure_heights": {},
        "node_chamfer_params": {},
        "node_u_params": {}
      }
    }
  }
}
```

> 流量段保存口径：界面虽然改为“共享当前流量段的只读查看组”，且主界面不再显示 `x段` 一类段数提示，但项目文件继续保留 `ui_settings.design_flows_text / max_flows_text` 作为兼容文本缓存，并保留 `project_settings.design_flows / max_flows` 作为结构化真值；不再新增 `current_flow_index` 一类字段，项目重开后主界面统一回到第一流量段展示。

### 新增可选字段

以下字段均为向后兼容字段，不提升强制版本，也不要求迁移脚本；旧项目缺少这些字段时按原有默认逻辑恢复。

| 所属面板 | 字段 | 用途 |
|---|---|---|
| `batch_panel` | `batch_results` | 保存批量计算成功结果，供重开后继续查看和同步到水面线 |
| `batch_panel` | `result_rows` | 保存批量结果表的文本快照 |
| `batch_panel` | `detail_text_cache` | 保存详细计算过程文本 |
| `batch_panel` | `has_batch_errors` | 保存批量失败锁定状态 |
| `pressure_pipe_panel` | `all_results` | 保存有压管道单项页全部工况结果 |
| `pressure_pipe_panel` | `current_result` | 保存当前结果对象 |
| `pressure_pipe_panel` | `export_plain_text` | 保存 Word 导出所需纯文本 |
| `open_channel_panel` | `result_state` | 保存多工况结果是否过期 |
| `aqueduct_panel` | `result_state` | 保存多工况结果是否过期 |
| `tunnel_panel` | `result_state` | 保存多工况结果是否过期 |
| `culvert_panel` | `result_state` | 保存多工况结果是否过期 |
| `pressure_pipe_panel` | `result_state` | 保存有压管道单项页多工况结果是否过期 |

结果恢复策略：有效结果重开后可继续查看和使用；已过期结果重开后保留显示，但继续提示“请重新计算”。批量计算如果存在失败条目，导出和下游共享保持锁定；如果全部成功，重开项目后会重新同步共享数据。

### 结果恢复补充（2026-05-08）

- 明渠、渡槽、暗涵、隧洞四类设计面板在打开 `.qxproj` 后都会沿用已保存的 `all_results` 恢复“工况对比”表，不重新计算。
- 项目文件只新增向后兼容可选字段；JSON 读回后由元组变成列表的旧工况结果，恢复时仍按原结果识别。
- 如果某个设计面板的对比表刷新失败，只清理该面板当前显示，不影响其他面板已经恢复的数据。

### 断面图与结果恢复补充（2026-05-09）

- 明渠、渡槽、暗涵、隧洞恢复项目时，结果文字恢复、断面图恢复、工况对比恢复分开处理；断面图绘制失败只清空断面图，不清空已加载结果。
- 断面图清空时同步恢复默认单图高度，避免多工况大画布留下空白滚动区。
- 停留在断面图页缩放窗口时，按可视区域重新布局；窄窗口继续单列显示，不开启横向滚动。
- 打开项目并恢复到“断面图”页后，四类设计面板会延迟按最终可视宽度刷新一次；即使页签索引没有变化，也不需要用户拖动分隔栏来触发重排。
- 该恢复刷新只负责项目打开后的时机稳定；隧洞多工况断面图右侧空白由隧洞专用 520px 行高解决，项目保存结构不变。
- 明渠、渡槽、暗涵在多工况过滤失败项后只剩一个成功工况时，也保留双击放大入口；隧洞保持统一循环逻辑。
- 有压管道单项页保存项目时会把 `NaN`、`Infinity` 和 `-Infinity` 递归转换为空值，保证严格 JSON 工具可读取。
- 批量计算恢复失败结果现场时不写入“已计算快照”，用户可不修改输入直接重新计算。

---

## 关键文件修改清单

### 1. 新建文件：`app_渠系计算前端/project_manager.py`

**ProjectManager 类**：项目保存/加载的核心管理器

```python
class ProjectManager(QObject):
    # 信号
    project_changed = Signal(str)    # 项目路径改变
    dirty_changed = Signal(bool)     # 脏状态改变
    status_message = Signal(str)     # 状态栏消息
    
    # 属性
    current_path: str | None         # 当前项目文件路径
    is_dirty: bool                   # 有未保存的修改
    recent_projects: List[str]       # 最近项目列表（最多5个）
    _auto_save_timer: QTimer         # 1分钟自动保存定时器
    
    # 核心方法
    def new_project(self)            # 新建项目
    def open_project(self, path=None)# 打开项目
    def save_project(self)           # 保存项目
    def save_as_project(self)        # 另存为
    def auto_save(self)              # 自动保存
    def mark_dirty(self)             # 标记为已修改
```

### 2. 修改：`app_渠系计算前端/app.py`

- 创建 `ProjectManager` 实例并注入
- 替换侧边栏"项目设置"按钮为"项目管理"按钮 + QMenu弹出菜单
- 添加 QShortcut 快捷键（Ctrl+S/O/N）
- 新增 `_update_window_title()` 方法
- 修改 `closeEvent()` 添加保存提示逻辑
- 连接 `project_changed` 和 `dirty_changed` 信号到窗口标题更新

### 3. 修改：`app_渠系计算前端/batch/panel.py`

新增两个方法：
- `to_project_dict()` - 序列化输入表格、批量结果、结果表快照和详细过程文本
- `from_project_dict(d)` - 反序列化恢复输入表格和可用计算现场
- 连接 `input_table.cellChanged` 到 `mark_dirty()`

### 4. 修改：`app_渠系计算前端/water_profile/panel.py`

新增两个方法：
- `to_project_dict()` - 序列化所有设置和节点数据
- `from_project_dict(d)` - 反序列化恢复所有UI控件和数据
- 基础设置区的设计流量 / 加大流量改为共享当前流量段的只读查看组，主界面只负责查看和切换，不再直接编辑
- 保存时继续兼容 `design_flows_text / max_flows_text` 与 `ProjectSettings.design_flows / max_flows`
- 连接关键控件的 `editingFinished` 到 `mark_dirty()`

### 5. 修改：`推求水面线/models/data_models.py`

为 `ChannelNode` 新增：
- `to_project_dict()` - 完整序列化所有50+字段
- `from_project_dict(d)` - 反序列化，含默认值兜底

为 `ProjectSettings` 新增：
- `from_dict(d)` - 从字典恢复对象

---

## 实施步骤

### 步骤 1：扩展数据模型（data_models.py）
- 为 `ChannelNode` 添加 `to_project_dict()` 和 `from_project_dict()` 方法
- 为 `ProjectSettings` 添加 `from_dict()` 静态方法

### 步骤 2：实现 BatchPanel 序列化（batch/panel.py）
- 添加 `to_project_dict()` 方法收集输入表格数据
- 添加 `from_project_dict()` 方法恢复输入表格

### 步骤 3：实现 WaterProfilePanel 序列化（water_profile/panel.py）
- 添加 `to_project_dict()` 方法收集所有设置和节点
- 添加 `from_project_dict()` 方法恢复UI控件和数据
- 继续同时保存流量段文本缓存与结构化列表，不新增当前流量段索引字段

### 步骤 4：创建 ProjectManager（新建 project_manager.py）
- 实现核心的保存/加载/自动保存/最近项目逻辑
- 实现 QTimer 定时自动保存
- 实现 QSettings 持久化最近项目列表

### 步骤 5：改造主窗口 UI（app.py）
- 注入 ProjectManager 实例
- 替换侧边栏按钮为项目管理菜单
- 添加快捷键绑定
- 改造 closeEvent 添加保存提示
- 连接信号实现窗口标题联动

### 步骤 6：连接脏状态信号
- BatchPanel: `input_table.cellChanged` → `mark_dirty()`
- WaterProfilePanel: 关键控件 `editingFinished` → `mark_dirty()`
- 计算完成后 → `mark_dirty()`

---

## 脏状态跟踪策略

不监听每个控件的 `textChanged`（性能代价高），改用事件节点驱动：

| 触发场景 | 处理方式 |
|---------|---------|
| 批量计算输入表格单元格变化 | `input_table.cellChanged` → `mark_dirty()` |
| 水面线基础设置控件编辑完成 | 各 LineEdit 的 `editingFinished` → `mark_dirty()` |
| 水面线节点表格变化 | `node_table.cellChanged` → `mark_dirty()` |
| 完成计算后 | 计算成功回调 → `mark_dirty()` |
| 新建/打开项目后 | 重置 `is_dirty = False` |
| 保存成功后 | 重置 `is_dirty = False` |

**注意**：在 `from_project_dict()` 执行期间设置守卫标志 `_loading_project = True`，禁止脏标记。

---

## 验证测试计划

1. **保存测试**
   - 在批量计算输入数据后，点击保存，验证 .qxproj 文件生成
   - 在水面线计算后，点击保存，验证节点数据完整保存

2. **加载测试**
   - 重启程序，打开保存的项目文件
   - 验证批量计算输入表格数据恢复
   - 验证水面线设置和节点数据恢复
   - 验证设计流量 / 加大流量恢复为当前流量段视图，而不是旧的整串文本框视图
   - 验证计算结果直接显示无需重算

3. **流量段兼容测试**
   - 验证旧项目里的 `design_flows_text / max_flows_text` 仍能正确恢复为多流量段
   - 验证 `ProjectSettings.design_flows / max_flows` 与文本缓存保持一致
   - 验证批量同步后当前流量段回到第一段，并自动重算加大流量

4. **自动保存测试**
   - 修改数据后等待1分钟，验证 autosave 文件生成
   - 验证状态栏显示自动保存消息

5. **关闭保存测试**
   - 修改数据后关闭程序，验证弹出保存提示
   - 选择"保存"后验证文件已保存
   - 选择"取消"后验证程序不关闭

6. **标题栏测试**
   - 验证打开项目后标题显示项目名
   - 验证修改数据后标题出现 * 标记
   - 验证保存后 * 标记消失

7. **快捷键测试**
   - 测试 Ctrl+S 保存
   - 测试 Ctrl+O 打开
   - 测试 Ctrl+N 新建

8. **最近项目测试**
   - 保存多个项目，验证最近项目列表更新
   - 从最近项目列表打开文件
   - 验证不存在的文件显示灰色

9. **兼容性测试**
   - 手动删除 .qxproj 文件中的某些字段，验证加载不报错
   - 验证缺失字段使用默认值填充
