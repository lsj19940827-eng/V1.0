# PRD：折叠面板回归修复复刻指南（基础设置消失 + 渐变段空白）

## 1. 文档目标

沉淀本次「折叠后内容消失、折叠区与下方 Tab 之间空白过大」问题的成功修复经验，形成可重复执行的标准流程，避免同类 UI 布局回归反复出现。

- 适用范围：`PySide6 + Qt Layout + 自定义折叠组件` 场景
- 适用页面：当前优先 `推求水面线` 面板，后续可复制到其他面板
- 生效日期：2026-03-07

---

## 2. 问题定义（As-Is）

### 2.1 用户可见问题

1. `基础设置` 折叠后再展开，出现「看起来没有内容」的问题（实际是高度异常压缩）。
2. `渐变段设置` 折叠后，和下方 Tab 卡片之间仍留有明显大空白。

### 2.2 复现路径（关键路径）

1. 打开推求水面线页面；
2. 先把两个折叠组都折叠；
3. 只展开 `基础设置`（或先折叠 `渐变段设置` 后再展开 `基础设置`）；
4. 观察到内容高度异常、空白异常。

### 2.3 业务影响

- 用户误判为配置项丢失或界面失效；
- 触发反复返工，影响迭代效率与版本信任度。

---

## 3. 根因分析（To-Be Insight）

## 3.1 技术根因

不是业务数据问题，而是 Qt 布局缓存链路问题：

- 自定义折叠组件仅做了 `content.setVisible()` + `updateGeometry()`；
- `FlowLayout / 父级布局 / splitter` 的高度缓存未被完整失效与激活；
- `splitter` 在错误时机读取到不稳定 `sizeHint`，导致高度分配错误。

### 3.2 关键结论

必须从组件底层处理「布局缓存失效链路」，并在页面层增加「测量前刷新」防御，双保险才能稳定。

---

## 4. 产品目标与验收标准

## 4.1 目标

1. 折叠/展开任意顺序下，内容始终可见；
2. 折叠区与下方 Tab 之间无异常空白；
3. 保存/重开项目后，折叠行为仍稳定；
4. 修复方式可在其他面板复用。

### 4.2 验收标准（DoD）

- 连续切换 20 次无异常（高度正常、无空白累积）；
- 回归测试覆盖 4 个场景并通过；
- 不修改第三方库源码；
- 仅修改自研组件与页面适配层。

---

## 5. 实施方案（最终采用）

## 5.1 底层组件修复（主修）

文件：`app_渠系计算前端/styles.py`

在 `CollapsibleGroupBox` 中引入统一状态切换与布局刷新链：

1. 新增 `_apply_collapsed_state()` 统一 `toggle()` 与 `set_collapsed()`；
2. 新增 `_refresh_layout_chain()`，按顺序强制刷新：
   - `content.layout().invalidate()/activate()`
   - `content.adjustSize()/updateGeometry()`
   - `self.layout().invalidate()/activate()`
   - 逐层父组件 `layout.invalidate()/activate()/updateGeometry()`
   - `self.updateGeometry()`
3. 在状态切换后再发 `toggled` 信号，确保外层读取的是最新几何状态。

## 5.2 页面层防御修复（辅修）

文件：`app_渠系计算前端/water_profile/panel.py`

1. 新增 `_refresh_top_layout_for_measurement()`：
   - 在 `splitter` 测量前，强制刷新顶部折叠区相关布局缓存。
2. 调整 `_adjust_splitter_for_settings()` 的高度计算策略：
   - 优先使用 `totalHeightForWidth`；
   - 若无效再回退 `totalSizeHint`；
   - 避免仅依赖不稳定 `hasHeightForWidth()` 判定。
3. 关键注意：不要在测量阶段调用 `top_w.adjustSize()`，避免将测量宽度错误压窄，导致 `heightForWidth` 假性增大。

---

## 6. 测试与防回归策略

新增测试文件：`tests/test_water_profile_collapsible_layout_regression_unit.py`

覆盖场景：

1. **基础恢复**：全折叠 → 仅展开基础设置，断言内容可见且高度恢复；
2. **空白校验**：展开渐变段后，断言顶部实际高度与两组控件高度之差接近 0；
3. **压力切换**：基础/渐变连续交替切换 20 次，无内容消失与空白累积；
4. **持久化路径**：保存-重开后再切换，行为稳定。

建议执行命令：

```bash
py -3 -m pytest -q tests/test_water_profile_collapsible_layout_regression_unit.py tests/test_water_profile_recalc_downstream_unit.py
```

---

## 7. 复刻 SOP（以后按这个做）

当再次遇到「折叠 UI 异常」时，严格按以下顺序：

1. **先量化再改代码**  
   记录 `splitter sizes / top height / group height / gap`，避免凭感觉调间距。

2. **先修底层组件，再修页面逻辑**  
   优先检查是否存在统一折叠组件；先做布局缓存链修复，再做页面局部补丁。

3. **测量前刷新布局链**  
   在任何 `sizeHint/heightForWidth` 计算前，显式 `invalidate/activate/updateGeometry`。

4. **避免“视觉修补”式魔法数字**  
   禁止通过硬编码 margin/padding 人工抵消空白，必须修复高度计算源头。

5. **测试覆盖“最容易回归的路径”**  
   必须包括：全折叠→单展开、重复切换、保存重开后切换。

---

## 8. 风险与约束

### 8.1 风险

- 过度调用布局刷新可能引入轻微性能开销。

### 8.2 控制

- 刷新仅在折叠状态变更与 splitter 重算时触发；
- 不在普通输入编辑路径触发重排链。

---

## 9. 后续建议（Backlog）

1. 抽象通用 `CollapsibleLayoutDebugMixin`，将 gap 观测能力标准化；
2. 在开发模式加入可选布局诊断日志开关；
3. 将该回归测试纳入 UI 关键路径必跑清单。

---

## 10. 一页复盘结论

本次成功关键不在“调间距”，而在“修正布局缓存链 + 稳定测量时机”。  
可复制经验：**先底层统一修复，再页面防御，再用回归测试锁住。**

