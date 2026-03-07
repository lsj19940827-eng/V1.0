# 项目保存功能实现方案

> **文档版本**: PRD V1.0  
> **创建日期**: 2026-03-03

---

## 需求概述

为渠系水力计算系统添加以项目为单位的保存/加载功能，保存范围包括**水面线推求**和**批量计算**两个模块的数据。

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
- `to_project_dict()` - 序列化输入表格数据
- `from_project_dict(d)` - 反序列化恢复输入表格
- 连接 `input_table.cellChanged` 到 `mark_dirty()`

### 4. 修改：`app_渠系计算前端/water_profile/panel.py`

新增两个方法：
- `to_project_dict()` - 序列化所有设置和节点数据
- `from_project_dict(d)` - 反序列化恢复所有UI控件和数据
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
   - 验证计算结果直接显示无需重算

3. **自动保存测试**
   - 修改数据后等待1分钟，验证 autosave 文件生成
   - 验证状态栏显示自动保存消息

4. **关闭保存测试**
   - 修改数据后关闭程序，验证弹出保存提示
   - 选择"保存"后验证文件已保存
   - 选择"取消"后验证程序不关闭

5. **标题栏测试**
   - 验证打开项目后标题显示项目名
   - 验证修改数据后标题出现 * 标记
   - 验证保存后 * 标记消失

6. **快捷键测试**
   - 测试 Ctrl+S 保存
   - 测试 Ctrl+O 打开
   - 测试 Ctrl+N 新建

7. **最近项目测试**
   - 保存多个项目，验证最近项目列表更新
   - 从最近项目列表打开文件
   - 验证不存在的文件显示灰色

8. **兼容性测试**
   - 手动删除 .qxproj 文件中的某些字段，验证加载不报错
   - 验证缺失字段使用默认值填充
