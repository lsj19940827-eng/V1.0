## 有压管道 V9 内核植入主程序（完整版）实施方案

### 摘要
将 `有压管道/V9.py` 拆分为“可复用计算内核 + 主程序UI面板 + 批量算表/绘图后台任务”，并接入主程序左侧导航。  
你已确认的关键决策将全部落实：  
- 独立导航页  
- 沿用 V9 五种管材与离散管径序列  
- 推荐规则“经济优先 + 妥协兜底 + 就近流速兜底”  
- 单次计算包含无压部分（新增 `i`、`n` 输入）  
- 水损同时输出 `m/km` 与按 `L` 折算总损失  
- 保留 V9 批量绘图（CSV + PNG/PDF + 合并PDF）  
- 批量参数默认值可编辑，后台线程执行，输出目录每次选择

### 目标文件
- 新增内核：[有压管道设计.py](C:/Users/大渔/Desktop/V1.0/渠系建筑物断面计算/有压管道设计.py)
- 新增面板包：[__init__.py](C:/Users/大渔/Desktop/V1.0/渠系断面设计/pressure_pipe/__init__.py)
- 新增面板：[panel.py](C:/Users/大渔/Desktop/V1.0/渠系断面设计/pressure_pipe/panel.py)
- 主程序导航接入：[app.py](C:/Users/大渔/Desktop/V1.0/渠系断面设计/app.py)
- 打包脚本更新：[build.py](C:/Users/大渔/Desktop/V1.0/tools/build.py)
- 依赖更新：[requirements.txt](C:/Users/大渔/Desktop/V1.0/tools/requirements.txt)
- 新增测试：[test_pressure_pipe_kernel.py](C:/Users/大渔/Desktop/V1.0/tests/test_pressure_pipe_kernel.py)
- 新增批量输出测试：[test_pressure_pipe_batch.py](C:/Users/大渔/Desktop/V1.0/tests/test_pressure_pipe_batch.py)

### 公共接口与类型变更（新增）
在 `有压管道设计.py` 提供稳定接口（供面板和测试调用）：

1. 常量与配置
- `PIPE_MATERIALS`（V9 五种管材 `f/m/b`）
- `DEFAULT_DIAMETER_SERIES`（V9 口径序列）
- `DEFAULT_Q_RANGE / DEFAULT_SLOPE_RANGE`（批量默认扫描参数）
- `ECONOMIC_RULE` 与 `COMPROMISE_RULE`（阈值）

2. 数据结构
- `PressurePipeInput`：`Q, material_key, slope_i, n_unpr, length_m, manual_increase_percent(optional)`
- `DiameterCandidate`：`D, V_press, hf_friction_km, hf_local_km, hf_total_km, h_loss_total_m, unpressurized_fields..., flags`
- `RecommendationResult`：`recommended, top_candidates, category, reason, calc_steps`
- `BatchScanConfig`：`q_values, slope_values, diameter_values, materials, output_dir`
- `BatchScanResult`：`csv_path, generated_pngs, generated_pdfs, merged_pdf, logs`

3. 计算函数
- `get_flow_increase_percent(Q) -> float`
- `evaluate_single_diameter(input, D) -> DiameterCandidate`
- `recommend_diameter(input) -> RecommendationResult`
- `run_batch_scan(config, progress_cb=None, cancel_flag=None) -> BatchScanResult`
- `build_detailed_process_text(input, recommendation) -> str`

### 详细实现步骤

1. 内核重构（从 V9 抽离）
- 将 V9 中“有压计算、无压计算、加大流量、材料系数、筛选规则”重构为纯函数。
- 去掉脚本级全局执行与硬编码路径，全部改为参数驱动。
- 保留 V9 数学口径：
  - `V_press = Q / A_full`
  - `Q_inc = Q * (1 + p/100)`
  - `hf_friction_km = f * (1000 * (Q_inc_m3h^m)) / (d_mm^b)`
  - `hf_local_km = 0.15 * hf_friction_km`
  - `hf_total_km = hf_friction_km + hf_local_km`
  - `h_total_m = hf_total_km * (L/1000)`

2. 推荐算法落地
- 第一步：筛选“经济区”（`0.9<=V<=1.5` 且 `hf_total<=5`），取最小 `D`。
- 第二步：若无，筛选“妥协区”（`0.6<=V<0.9` 且 `hf_total<=5`），取最小 `D`。
- 第三步：若仍无，按“`|V-0.9|` 最小 + `hf_total` 最小”兜底，并显式标记“未满足约束”。
- 生成前 5 候选，供单次结果展示与可追溯说明。

3. 单次计算 UI（新导航页）
- 新增“有压管道设计”面板，输入项：
  - 设计流量 `Q`
  - 管材下拉（V9 五种）
  - 无压参数 `i(1/x)`、`n`
  - 管长 `L`（默认 `1000m`）
  - 详细过程开关（默认开）
- 输出区：
  - 推荐结果卡片（推荐管径、流速、沿程/局部/总水损 `m/km`、总损失 `m`）
  - 前 5 候选表
  - 完整计算过程（公式代入 + 筛选判定 + 推荐理由），走现有公式渲染器

4. 批量计算与绘图（本页按钮入口）
- 在有压管道页增加“批量计算”按钮，进入批量任务区或子面板。
- 批量参数采用“默认值可编辑”：
  - `Q` 默认 `0.1~2.0 step 0.1`
  - `i` 默认 `1/500...1/4000`
  - `D` 默认 V9 序列
- 执行方式：
  - `QThread` 后台运行
  - 进度条 + 日志输出 + 取消按钮
- 输出：
  - CSV（明细）
  - 图1/图2（与 V9 一致口径）
  - 子图 PNG
  - 按规则合并 PDF（`pypdf`）

5. 主程序接线
- 在 `app.py` 中：
  - 导入 `PressurePipePanel`
  - 导航 `modules` 增加“有压管道设计”
  - `QStackedWidget` 增加新面板
  - `_switch_to` 的名称列表同步扩容
- 保持其他模块行为不变。

6. 依赖与打包
- `tools/requirements.txt` 增加：
  - `seaborn`
  - `pypdf`
- `tools/build.py` 更新：
  - `hidden_imports` 增加 `seaborn`、`pypdf`、`有压管道设计`
  - 如需，补充 seaborn 资源收集参数（避免运行时缺样式资源）

### 测试与验收场景

1. 内核单元测试
- 加大流量比例边界点测试：`Q=0.99/1.0/4.99/5.0/...`
- 单管径计算一致性：`V_press`、`hf_total_km`、`h_total_m` 与公式复算一致
- 推荐规则顺序正确：经济优先、妥协次之、兜底最后
- 兜底判定正确且有“未满足约束”标记
- 非法输入防御：`Q<=0`、`D<=0`、`L<=0`、未知管材

2. 批量输出测试
- 小样本配置下生成 CSV/PNG/PDF/合并PDF
- 取消任务可中断且不崩溃
- 输出目录选择为空或无权限时给出明确错误

3. UI 集成冒烟
- 新导航页可打开
- 单次计算可出结果与详细过程
- 批量按钮可启动后台任务并显示进度

### 显式假设与默认值
- 单次计算默认展示完整过程，不做“仅摘要”模式。
- 管材仅使用 V9 五种，不提供自定义 `f/m/b`。
- 批量参数预填 V9 默认值，但允许用户编辑。
- 批量输出目录每次由用户选择，不使用硬编码盘符路径。
- 本次以“功能对齐 V9 + 主程序可用”为目标，不扩展到跨模块联动取长度。
- 本次不使用 `skill-creator/skill-installer`，因为任务不属于技能创建或安装范畴。
