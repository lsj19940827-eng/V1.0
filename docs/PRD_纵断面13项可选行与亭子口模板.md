# PRD：纵断面「13项可选行 + 亭子口模板」

## 1. 文档信息
- 版本：v1.6
- 更新时间：2026-03-12
- 适用模块：生成纵断面表格类导出入口（TXT / DXF / 合并 DXF）
- 涉及文件：
  - `app_渠系计算前端/water_profile/cad_tools.py`
  - `app_渠系计算前端/water_profile/panel.py`
  - `tools/validate_profile_export_with_xlsm.py`
  - `tests/test_text_export_settings_dialog_ui_unit.py`
  - `tests/test_water_profile_profile_rows_unit.py`
  - `tests/test_water_profile_longitudinal_dedup_unit.py`

## 2. 背景与目标
- 纵断面文字导出原本是固定输出，难以适配不同项目模板。
- 用户对“拖拽到底怎么拖才对”反馈较差，尤其是跨列拖拽的学习成本高、容错差。
- 目标是同时解决两类问题：
  - 行内容可配置、可排序、可随项目持久化。
  - 交互足够清晰，第一次使用也能理解正确操作路径。

本次 v1.6 的核心产品决策如下：
- 主交互从“双列穿梭 + 跨列拖拽”升级为“单列表勾选启用 + 已启用项拖拽排序”。
- 拖拽只负责排序，不再承担“启用/移除”的主要学习成本。
- 增加非拖拽补充方式：上移、下移、置顶、置底、右键菜单、快捷键。
- 临时停用重复语义项：
  - `BE(IP文字)`
  - `BK(桩号文字)`
- 注意：底层 13 项定义仍保留，当前仅在“标准配置入口”不暴露 `BE/BK`。

## 3. 功能范围

### 3.1 13项底层行定义

| 序号 | 内部 ID | 显示标签 | hint | 表头文字 | 行高 | 锚点 | 当前状态 |
|------|--------|---------|------|---------|------|------|---------|
| 1 | `building_name` | 建筑物名称 | 按建筑物段居中标注 | 建筑物名称 | 10 | center | 可见 |
| 2 | `slope` | 坡降 | 按建筑物段显示坡降 | 坡降 | 10 | center | 可见 |
| 3 | `ip_name` | IP点名称 | IP节点名称，特殊建筑进/出口点带建筑信息 | IP点名称 | 40 | bottom2 | 可见 |
| 4 | `station` | 里程桩号(千米+米) | 显示格式：0+234.567 | 里程桩号 / （千米+米） | 30 | bottom2 | 可见 |
| 5 | `top_elev` | 渠顶高程(m) | 节点渠顶高程 | 渠顶高程(m) | 15 | bottom1 | 可见 |
| 6 | `water_elev` | 设计水位(m) | 节点设计水位 | 设计水位(m) | 15 | bottom1 | 可见 |
| 7 | `bottom_elev` | 渠底高程(m) | 节点渠底高程 | 渠底高程(m) | 15 | bottom1 | 可见 |
| 8 | `bd_ip_before` | IP弯前(BD) | IP文字弯前点（BC） | IP弯前 | 40 | bottom2 | 可见 |
| 9 | `be_ip_text` | IP文字(BE) | IP文字中心点（MC） | IP文字 | 30 | bottom2 | v1.6 隐藏 |
| 10 | `bf_ip_after` | IP弯后(BF) | IP文字弯后点（EC） | IP弯后 | 40 | bottom2 | 可见 |
| 11 | `bj_station_before` | 桩号文字弯前(BJ) | 桩号文字弯前点（BC） | 桩号文字弯前 | 30 | bottom2 | 可见 |
| 12 | `bk_station` | 桩号文字(BK) | 桩号文字中心点（MC） | 桩号文字 | 25 | bottom2 | v1.6 隐藏 |
| 13 | `bl_station_after` | 桩号文字弯后(BL) | 桩号文字弯后点（EC） | 桩号文字弯后 | 30 | bottom2 | 可见 |

说明：
- `center` = 文本位于该行中线。
- `bottom1` = 文本位于该行底部 + 1.0。
- `bottom2` = 文本位于该行底部 + 2.0。
- `station` 的表头是双行表头：
  - `里程桩号`
  - `（千米+米）`

### 3.2 当前用户可见的 11 项
- `building_name`
- `slope`
- `ip_name`
- `station`
- `top_elev`
- `water_elev`
- `bottom_elev`
- `bd_ip_before`
- `bf_ip_after`
- `bj_station_before`
- `bl_station_after`

### 3.3 暂时隐藏的 2 项
- `be_ip_text`
  - 原因：与 `ip_name` 在当前使用场景中语义重复。
- `bk_station`
  - 原因：与 `station` 在当前使用场景中语义重复。

策略说明：
- 这 2 项的底层生成逻辑保留，不删除代码。
- 标准配置归一化结果不再包含这 2 项。
- 默认配置入口不展示这 2 项。
- 如未来业务确认需要恢复，只需重新纳入可见顺序与默认配置。

## 4. 弹窗交互：`TextExportSettingsDialog`

### 4.1 整体布局
- 保持 Win11 Fluent 风格。
- 左侧：基础参数 + 高级参数。
- 右侧：行配置卡片 + 当前配置预览。
- 底部按钮：`恢复默认` / `取消` / `确定`。

### 4.2 基础参数卡片

| 参数 | key | 默认值 | 说明 |
|------|-----|--------|------|
| 字高 | `text_height` | 3.5 | AutoCAD `-TEXT` 字高 |
| 旋转角度 | `rotation` | 90 | 文本旋转角 |
| 高程小数位数 | `elev_decimals` | 3 | 必须为非负整数 |
| X方向比例(1:N) | `scale_x` | 1 | 里程方向缩放，例 `1:1000` 输入 `1000` |
| Y方向比例(1:N) | `scale_y` | 1 | 高程方向缩放，例 `1:1000` 输入 `1000` |

### 4.3 高级参数卡片（旧版 Y 坐标兼容）

| 参数 | key | normalize fallback | 恢复默认值 |
|------|-----|--------------------|-----------|
| 渠底文字Y | `y_bottom` | 1 | 1 |
| 渠顶文字Y | `y_top` | 31 | 31 |
| 水面文字Y | `y_water` | 16 | 16 |
| 建筑物名称Y | `y_name` | 115 | 115 |
| 坡降Y | `y_slope` | 105 | 105 |
| IP点名称Y | `y_ip` | 77 | 77 |
| 里程桩号Y | `y_station` | 47 | 47 |
| 最小竖线高度 | `y_line_height` | 120 | 120 |

补充说明：
- `panel.py` 中历史初始化值对 `y_name` / `y_slope` 可能存在旧差异，但进入标准流程后，以 `normalize` 和弹窗恢复默认值为准。
- 历史差异的具体值为：
  - `panel.py` 旧初始化：`y_name = 112`、`y_slope = 102`
  - `cad_tools.py` 归一化 fallback / 弹窗恢复默认：`y_name = 115`、`y_slope = 105`
- 产品口径要求统一为：
  - 旧项目如果已经持久化了显式值，则按项目值走。
  - 未显式提供时，标准化结果一律回落到 `115 / 105`。
  - 验收与测试应以标准化后的结果为准，而不是以 `panel.py` 的历史裸初始值为准。
- 高级参数默认折叠。
- 折叠图标通过 `_resolve_fluent_icon()` 做兼容解析。

### 4.4 行配置卡片

#### 4.4.1 v1.6 主交互
- 单列表展示全部可见项。
- 勾选表示启用。
- 已启用项显示在列表上方，未启用项在下方。
- 已启用项显示顺序号，顺序即导出顺序。
- 只有已启用项支持拖拽排序。

#### 4.4.2 快捷操作
- `全启用`
- `全停用`
- `恢复推荐`
- `应用亭子口模板`

#### 4.4.3 非拖拽补充方式
- 按钮：
  - `上移`
  - `下移`
  - `置顶`
  - `置底`
- 右键菜单：
  - `启用/停用`
  - `上移/下移`
  - `置顶/置底`
- 双击：
  - 双击当前项执行启用/停用切换

#### 4.4.4 提示与反馈
- 顶部必须有显式说明文案：
  - 勾选即启用
  - 拖拽用于排序
  - 右键可快速调整
- 已启用项显示“拖动排序”提示。
- 列表内显示顺序号。
- 拖拽时列表高亮，并保留插入指示线。
- 启用/停用时使用 `InfoBar` 提示结果。
- 需要明确告知用户：
  - `BE(IP文字)` 与 `BK(桩号文字)` 当前版本不提供

#### 4.4.5 推荐标记
- 推荐项保持蓝色高亮与 `★推荐` 标记：
  - `building_name`
  - `slope`
  - `top_elev`
  - `water_elev`
  - `bottom_elev`

#### 4.4.6 历史交互兼容说明
- v1.6 之前的主交互是“双列表 + 添加/移除 + 右侧拖拽排序”。
- 历史实现仍以 `_LegacyTextExportSettingsDialogDualList` 保留在代码中，主要用于：
  - 兼容历史阅读与问题定位
  - 对照旧 PRD / 旧截图 / 旧用户培训材料
- 当前正式产品口径以 `_SingleListTextExportSettingsDialog` 为准。
- 历史配置数据结构仍兼容：
  - 原有 `profile_row_items` 仍可被标准化
  - 标准化后只保留当前可见 11 项，并按新单列表规则展示
- 以后新增交互规则、验收标准、用户说明文案，都只针对单列表方案编写。

### 4.5 当前配置预览卡片
- 可折叠。
- 显示当前已启用项摘要。
- 最多展示前 6 项，其余使用“...（共 N 行）”表示。
- 显示 `-text X,Y 字高 旋转角度 文本` 示例。
- 折叠状态通过 `QSettings` 持久化。

### 4.6 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Escape` | 取消 |
| `Enter` | 确定 |
| `Ctrl+Up` | 上移选中启用项 |
| `Ctrl+Down` | 下移选中启用项 |
| `Ctrl+Home` | 置顶 |
| `Ctrl+End` | 置底 |
| `Delete` | 停用选中项 |

### 4.7 校验规则
- 所有数值参数不能为空，且必须为数值。
- `elev_decimals` 必须为非负整数。
- `scale_x`、`scale_y`、`y_line_height` 必须大于 0。
- 至少启用 1 项行内容，否则阻止确认。
- 若错误字段在高级参数区且当前折叠，需要自动展开后聚焦。

### 4.8 UI 持久化
- 使用 `QSettings` 保存：
  - 对话框宽度
  - 对话框高度
  - 预览卡片展开状态
- `closeEvent` 自动写回。
- 最小尺寸：`960 x 500`

## 5. 默认行为与模板规则

### 5.1 默认启用项
- 默认启用仍为亭子口模板 7 项：
  - `building_name`
  - `slope`
  - `ip_name`
  - `station`
  - `top_elev`
  - `water_elev`
  - `bottom_elev`

### 5.2 默认可见顺序
- `building_name`
- `slope`
- `ip_name`
- `station`
- `top_elev`
- `water_elev`
- `bottom_elev`
- `bd_ip_before`
- `bf_ip_after`
- `bj_station_before`
- `bl_station_after`

### 5.3 亭子口模板
- 模板 ID 顺序为：
  - `building_name`
  - `slope`
  - `ip_name`
  - `station`
  - `top_elev`
  - `water_elev`
  - `bottom_elev`
- 应用模板后：
  - 上述 7 项启用
  - 其余可见项保留但不启用
  - 列表顺序同步调整为模板优先

## 6. 排版与绘图规则

### 6.1 行高与文字锚点
- 行高与锚点完全由 `_PROFILE_ROW_DEFS` 控制。
- `_build_profile_row_layout()` 负责根据当前启用项计算：
  - `enabled_ids`
  - `row_layout`
  - `total_height`
  - `line_height`
  - `boundaries`

### 6.2 高度计算
- `total_height = 所有已启用行高之和`
- `line_height = max(total_height, y_line_height)`
- 行从上到下依次排布。
- `boundaries = 各行 top/bottom + {0, total_height, line_height}`

补充说明：
- `0` 是表格底边。
- `total_height` 是“已启用内容真实占高”的上边界。
- `line_height` 是最终竖线与外框的统一上边界。
- 当 `line_height > total_height` 时，顶部会保留一段空白补高带：
  - 范围为 `y ∈ [total_height, line_height]`
  - 这段区域没有内容行，但会保留外框与全高竖线
  - 该设计用于兼容旧项目坐标、避免启用行较少时整体显得过矮
- `boundaries` 排序后既用于左侧表头分隔线，也用于主体区域全宽水平线，二者必须共用同一组 y 值，避免表头与主体错层。

### 6.3 表头区域
- 表头区宽度固定为 40。
- 范围：`x = -40` 到 `x = 0`
- 表头文字中心：`x = -20`
- 单行表头：居中对齐。
- 双行表头：上下行间距为 `text_height * 2.5`

补充说明：
- 左侧表头区的水平线全部使用 `boundaries` 逐条绘制：
  - 从 `x = -40` 画到 `x = sx(0)`
- 表头竖线固定两条：
  - 左边界：`x = -40`
  - 右边界：`x = 0`
  - 纵向范围均为 `y = 0` 到 `y = line_height`
- 主体区域再使用同一组 `boundaries` 从 `x = sx(0)` 画到 `x = sx(last_mc)`，这样表头列和正文区域在所有分隔线位置上完全对齐。
- 双行表头的垂直布局规则为：
  - `line_spacing = text_height * 2.5`
  - `block_h = line_spacing + text_height`
  - 再在当前行高范围内做居中分配，而不是简单贴边摆放
- `station` 的双行表头必须保持：
  - 第一行：`里程桩号`
  - 第二行：`（千米+米）`
  - 不能折叠成单行，否则与既有图纸习惯不一致。

### 6.4 节点竖线高度
- 特殊建筑进/出口节点：竖线取 `line_height`
- 其他节点：取 `short_line_height`

`short_line_height` 规则：
1. 若启用 `slope` 行：`short_line_height = slope.bottom`
2. 若未启用 `slope`，但启用 `building_name`：`short_line_height = building_name.bottom`
3. 两者都未启用：`short_line_height = line_height`

此规则同时作用于：
- DXF 导出：`_draw_profile_on_msp()`
- TXT 导出：`_export_longitudinal_txt_to_path()`

补充说明：
- `short_line_height` 是“普通节点短竖线”的统一高度切断位置，不是某个单独行的文字 y。
- 闸、倒虹吸、隧洞、有压管道、渡槽、暗涵等特殊建筑的进/出口节点，必须保留全高竖线，不能被 `short_line_height` 截断，否则建筑边界不清楚。
- 这条规则同时影响：
  - 表格观感
  - 建筑物名称居中定位时的边界识别
  - 坡降行的中点求解

### 6.5 BC / MC / EC 竖线分段规则
- 当某个 IP 节点满足以下任一条件时：
  - `station_BC != station_MC`
  - `station_EC != station_MC`
- 且当前启用了任一 BC/EC 辅助行时，不能再把该节点简单画成一条完整竖线。
- 系统需改用 `_compute_node_vline_segments()` 按行分段：
  - 属于 BC 语义的行，竖线画在 `station_BC`
  - 属于 EC 语义的行，竖线画在 `station_EC`
  - 其余行继续画在 `station_MC`
- 这样做的目的不是“看起来更复杂”，而是避免：
  - 弯前/弯后文字列与中间列共用一根竖线时产生错位
  - `BD/BF/BJ/BL` 开启后，线框与文字语义不一致
- 如果 `BC/EC` 与 `MC` 没有差异，仍退化成一根普通竖线，避免不必要的分段复杂度。

### 6.6 首列偏移与 DXF / TXT 差异
- 对以下逐节点文字行，首个文本都要做首列偏移：
  - `bottom_elev`
  - `top_elev`
  - `water_elev`
  - `station`
  - 全部 IP 相关行
- 首列偏移公式固定为：
  - `first_col_x_offset = text_height + 1.3`
- 设计意图：
  - 避开起始竖线与首列文字重叠
  - 让最左端第一条文字不贴边
  - 保持与既有图纸出图习惯一致

输出差异说明：

| 场景 | 首个文字 | 非首个文字 |
|------|---------|-----------|
| DXF (`_draw_profile_on_msp`) | `sx(x) + first_col_x_offset` | `sx(x) - 1` |
| TXT (`_export_longitudinal_txt_to_path`) | `sx(x) + first_col_x_offset` | `sx(x)` |

补充说明：
- 这不是笔误，而是当前实现刻意保留的历史差异。
- `DXF` 路径会对后续列额外左收 `1` 个单位，使视觉上更接近既有 CAD 直接出图效果。
- `TXT` 路径保持原始缩放坐标，不额外做 `-1` 修正，以兼容历史命令流。
- `building_name` 与 `slope` 使用分段中点居中放置，不适用本节的首列偏移规则。

## 7. 数据与文本规则

### 7.1 `building_name`
- 按建筑物分段逻辑输出。
- 自动插入明渠段节点不参与 `building_segments`。
- 特殊建筑内部节点不参与建筑物名称分段，仅进/出口参与。
- 闸类建筑按首节点标注，其余建筑按段中心标注。

补充说明：
- `_get_building_display_name()` 的实现意图非常关键：
  - 不是“凡是特殊建筑节点都标名称”
  - 而是“只允许进/出口节点参与段落划定”
- 原因：
  - 隧洞、倒虹吸、有压管道、渡槽、暗涵等特殊建筑内部往往存在多个 IP 节点
  - 如果这些内部节点也参与 `building_segments`，会把同一个建筑物切碎成多个短段
  - 进而导致 `building_name` 重复、`slope` 重复，甚至两者在视觉上互相挤压
- 明渠、矩形暗涵等直接以结构类型作为显示名。
- 若节点自带 `name`，则采用“名称 + 建筑类别”的合成名，例如：
  - `某某隧洞`
  - `某某渡槽`
- `_merge_segments_across_gates()` 还需要额外处理一种历史规则：
  - 如果两个同名段之间只隔着闸类点状建筑物，则视为同一段落连续，不应被闸拆断。

### 7.2 `slope`
- 复用 `building_segments`。
- 闸类建筑跳过。
- 倒虹吸段、有压管道段输出 `-`。
- 其余建筑取段内第一个有效 `slope_i`，格式化为 `1/N`。

补充说明：
- `slope` 不自行重新分段，而是严格复用 `building_name` 的段结果，避免名称行与坡降行边界不一致。
- 闸类建筑属于点状设施，只用于界定，不参与坡降文本输出。
- 段中点并非一律取 `(start + end) / 2`，而是通过 `_resolve_segment_mid_mc()` 结合全高边界竖线做求解：
  - 单点段优先取所在单元格的几何中心
  - 普通长段优先取段落边界中点
  - 这样能减少文字压在线上或跨越特殊建筑全高竖线的情况
- 取坡降值时，段内按顺序查找第一个有效 `slope_i`：
  - 若格式化结果为无效值 `/`，继续向后查
  - 全段都没有有效值时，不输出坡降文本

### 7.3 `top_elev` / `water_elev` / `bottom_elev` / `station`
- 使用 `_build_profile_text_nodes()` 输出。
- 过滤：
  - 渐变段
  - 自动插入明渠段
- 同桩号归并：
  - 取最优代表节点
  - 各高程字段要求非零唯一
- 同桩号冲突：
  - 若出现多个非零且不同值，抛 `ValueError` 中断导出

### 7.4 IP 相关行
- 统一基于 `_build_ip_related_row_records()` 生成：
  - `ip_name`
  - `bd_ip_before`
  - `be_ip_text`
  - `bf_ip_after`
  - `bj_station_before`
  - `bk_station`
  - `bl_station_after`

#### 节点过滤规则
- 渐变段节点排除。
- 自动插入明渠段排除。
- 特殊建筑节点允许进入 IP 相关逻辑。
- 普通节点如与特殊建筑进/出口桩号重合，需要避让，避免重复标注。

#### 命名规则
- 普通 IP：
  - `IP{序号}`
- 特殊建筑进/出口节点：
  - `IP{序号} {合并名称}{进/出}`
- 特殊建筑内部节点：
  - 仅 `IP{序号}`

#### 文字列含义
- `BD`
  - 使用 `station_BC`
  - 普通有转角时可带“弯前”语义
- `BE`
  - 使用 `station_MC`
  - 中心文字
- `BF`
  - 使用 `station_EC`
  - 普通有转角时可带“弯后”语义
- `BJ`
  - `format_station(station_BC)`
- `BK`
  - `format_station(station_MC)`
- `BL`
  - `format_station(station_EC)`

#### v1.6 可见性策略
- `BD/BF/BJ/BL` 继续保留在用户可选列表中。
- `BE/BK` 底层逻辑保留，但不再出现在标准配置列表中。

#### 重复桩号避让
- 同一 `row_id` 内若当前 x 与上一条 x 相同，执行 `x += 6.0`

## 8. 转角校验策略
- 只对特殊建筑进/出口点检查转角。
- 阈值：`_SPECIAL_ANGLE_TOL_DEG = 0.01`
- 分类：
  - `0 < angle < tol`：接近 0，提示复核
  - `angle >= tol`：超过阈值，重点复核
- 提示方式：
  - `fluent_info`
  - 不阻断导出
- 当前主要在 DXF 导出入口启用

## 9. 技术落地摘要

### 9.1 核心数据结构
- `_PROFILE_ROW_DEFS`
- `_PROFILE_ROW_DEF_MAP`
- `_PROFILE_ROW_DEFAULT_ORDER`
- `_PROFILE_ROW_VISIBLE_ORDER`
- `_PROFILE_ROW_VISIBLE_ID_SET`
- `_PROFILE_ROW_HIDDEN_IDS`
- `_TINGZIKOU_TEMPLATE_ROW_IDS`
- `_PROFILE_RECOMMENDED_ROW_IDS`
- `_PROFILE_EXTENDED_ROW_IDS`
- `_SPECIAL_ANGLE_TOL_DEG`

### 9.2 关键函数
- `_default_profile_row_items()`
- `_normalize_profile_row_items()`
- `_normalize_text_export_settings()`
- `_get_enabled_profile_row_ids()`
- `_build_profile_row_layout()`
- `_build_ip_related_row_records()`
- `_build_profile_text_nodes()`
- `_build_special_angle_warning()`
- `_draw_profile_on_msp()`
- `_export_longitudinal_txt_to_path()`

### 9.3 关键类
- `_ProfileRowListWidget`
  - 单列表拖拽排序控件
- `_SingleListTextExportSettingsDialog`
  - v1.6 当前正式入口
- `_LegacyTextExportSettingsDialogDualList`
  - 旧双列表实现，保留作为历史参考

### 9.4 三个导出入口
- `export_longitudinal_profile_txt()`
- `export_longitudinal_profile_dxf()`
- `export_combined_dxf()`

三者都通过 `TextExportSettingsDialog` 获取：
- 参数设置
- 行配置
- 排序结果

入口差异说明：

| 导出入口 | 文件类型 | 是否先弹文字配置框 | 是否有额外配置框 | 是否弹特殊转角提示 | 是否支持 `.txt` 回退 | 纵断面绘制实现 |
|---------|---------|------------------|----------------|------------------|--------------------|---------------|
| `export_longitudinal_profile_txt()` | `.txt` | 是 | 否 | 否 | 不适用 | `_export_longitudinal_txt_to_path()` |
| `export_longitudinal_profile_dxf()` | `.dxf` / `.txt` | 是 | 否 | 是 | 是 | `.dxf` 走 `_draw_profile_on_msp()`；`.txt` 走 `_export_longitudinal_txt_to_path()` |
| `export_combined_dxf()` | `.dxf` | 是 | 是，需再弹 `SectionSummaryDialog` | 当前未弹 | 否 | 纵断面部分走 `_draw_profile_on_msp()`，再与断面汇总/IP表合并 |

补充说明：
- `export_longitudinal_profile_txt()` 的定位是“直接输出 AutoCAD 命令流”，流程最短。
- `export_longitudinal_profile_dxf()` 在保存框里允许用户改选 `.txt`：
  - 这是历史兼容入口，不是重复按钮
  - 目的是让用户从同一入口按需选择“真正 DXF”或“命令流 TXT”
- `export_longitudinal_profile_dxf()` 会在保存文件前调用 `_show_special_angle_warning()`：
  - 只提示，不阻断导出
  - 便于用户在正式出图前注意特殊建筑转角异常
- `export_combined_dxf()` 当前不会弹特殊转角提示：
  - 这属于现状说明，不是产品推荐终态
  - 如果后续希望统一体验，应补成与单独 DXF 入口一致
- 合并导出除了文字配置外，还必须补充断面汇总表参数，因此流程比单独纵断面导出更长。

### 9.5 `panel.py`
- 默认 `_text_export_settings` 与当前产品策略一致：
  - `BE/BK` 不再作为默认可见项
  - 代码中以注释形式保留，便于后续恢复

## 10. 验收标准
- 用户不需要理解跨列拖拽即可完成启用与排序。
- 首次进入即可理解主操作方式。
- 已启用项顺序与导出顺序一致，且界面有顺序号反馈。
- 不使用拖拽时，仍可通过按钮、右键、快捷键完成排序调整。
- `BE/BK` 不再出现在当前配置列表中。
- `BD/BF/BJ/BL` 保留可配置能力。
- 历史底层导出逻辑保留，不做硬删除。
- 配置可随项目保存并恢复。
- X/Y 比例缩放继续正确应用到里程与高程。

## 11. 测试覆盖

### 11.1 UI 测试
`tests/test_text_export_settings_dialog_ui_unit.py`
- 单列表初始化
- 历史配置归一化
- `BE/BK` 隐藏
- 勾选启用/停用
- 快捷操作
- 排序行为
- 校验行为
- 列表可视容量

### 11.2 规则测试
`tests/test_water_profile_profile_rows_unit.py`
- 默认归一化结果只保留 11 项可见行
- 亭子口默认启用项正确
- IP 相关记录生成规则正确
- 特殊转角警告正确

### 11.3 导出偏移测试
`tests/test_water_profile_longitudinal_dedup_unit.py`
- 当前可见 IP/桩号辅助行在 DXF/TXT 中按各自既定偏移规则输出
- 首列偏移 `text_height + 1.3` 保持一致，非首列差异保持稳定
- 隐藏 `BE/BK` 后，其余辅助行不受影响

## 12. 变更日志
- v1.0
  - 初始版本，定义 13 项可选行、亭子口模板、基础导出规则。
- v1.1
  - 与第一轮代码实现同步。
- v1.2
  - 补充高级参数兼容规则、同桩号冲突校验、部分命名与偏移细节。
- v1.3
  - 梳理实现与规格的一致性。
- v1.4
  - 修正建筑物分段、坡降、IP 名称等规则描述。
- v1.5
  - 修正表头竖线与自动插入明渠段相关规则。
- v1.6
  - 弹窗交互从双列表改为单列表。
  - 新增顺序号、置顶/置底、右键菜单、拖拽高亮。
  - `BE/BK` 从标准配置入口中隐藏，但保留底层定义。
