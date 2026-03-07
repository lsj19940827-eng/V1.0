# 对话框样式更新 - Win11 Fluent Design

## 修改内容

### 1. 新增 Fluent Design 风格的三按钮对话框

在 `app_渠系计算前端/styles.py` 中新增了 `fluent_save_discard_cancel()` 函数，用于替代系统原生的 QMessageBox 三按钮对话框。

**特性：**
- Win11 Fluent Design 风格
- 中文按钮文本（保存/放弃/取消）
- 圆角边框和阴影效果
- 使用 qfluentwidgets 的按钮组件
- 自适应内容宽度

**函数签名：**
```python
def fluent_save_discard_cancel(
    parent, 
    title, 
    content, 
    save_text="保存", 
    discard_text="放弃", 
    cancel_text="取消"
) -> str
```

**返回值：**
- `'save'` - 用户点击保存按钮
- `'discard'` - 用户点击放弃按钮
- `'cancel'` - 用户点击取消按钮或关闭对话框

### 2. 更新项目管理器对话框

在 `app_渠系计算前端/project_manager.py` 中：
- 导入新的 `fluent_save_discard_cancel` 函数
- 替换 `_check_save_before_close()` 方法中的 `QMessageBox.question()` 调用
- 将英文按钮（Save/Discard/Cancel）改为中文（保存/放弃/取消）

**修改前：**
```python
reply = QMessageBox.question(
    None,
    "保存项目",
    "当前项目有未保存的修改，是否保存？",
    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
    QMessageBox.Save
)
```

**修改后：**
```python
result = fluent_save_discard_cancel(
    None,
    "保存项目",
    "当前项目有未保存的修改，是否保存？",
    save_text="保存",
    discard_text="放弃",
    cancel_text="取消"
)
```

## 设计规范

### 视觉样式
- **背景色：** #F3F3F3（浅灰色，符合Win11风格）
- **边框：** 1px solid #E5E5E5，圆角 8px
- **阴影：** 20px 模糊，偏移 (0, 4)，透明度 60
- **标题字体：** 18px，粗体，颜色 #1F1F1F
- **内容字体：** 14px，常规，颜色 #605E5C
- **按钮高度：** 32px
- **按钮最小宽度：** 88px
- **按钮间距：** 10px

### 布局规范
- **对话框最小宽度：** 440px
- **内边距：** 24px (左右上下)
- **标题与内容间距：** 16px
- **内容与按钮间距：** 24px
- **按钮右对齐**

## 测试

可以运行 `test_fluent_dialog.py` 来测试新对话框的外观和功能：

```bash
python test_fluent_dialog.py
```

## 影响范围

- 项目保存提示对话框（关闭/新建/打开项目时）
- 所有需要"保存/放弃/取消"三选项的场景

## 兼容性

- 完全兼容现有代码逻辑
- 不影响其他对话框（如 fluent_question、fluent_info 等）
- 保持与 qfluentwidgets 库的一致性
