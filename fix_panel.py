# -*- coding: utf-8 -*-
import sys

# 读取文件
with open(r"渠系断面设计\water_profile\panel.py", 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改 _open_pressure_pipe_calculator 方法，在检查完成后添加配置对话框
old_calc_start = '''        print("[DEBUG] 开始导入模块和提取有压管道分组")
        try:'''

new_calc_start = '''        # 弹出配置对话框
        from 渠系断面设计.water_profile.water_profile_dialogs import PressurePipeConfigDialog
        config_dlg = PressurePipeConfigDialog(
            parent=self,
            default_sensitivity_enabled=self._is_pressure_pipe_sensitivity_enabled()
        )
        if config_dlg.exec() != QDialog.Accepted:
            print("[DEBUG] 用户取消了配置对话框")
            return

        # 获取用户配置
        sensitivity_enabled = config_dlg.get_sensitivity_enabled()
        self._set_pressure_pipe_sensitivity_enabled(sensitivity_enabled)
        print(f"[DEBUG] 用户配置: sensitivity_enabled={sensitivity_enabled}")

        print("[DEBUG] 开始导入模块和提取有压管道分组")
        try:'''

content = content.replace(old_calc_start, new_calc_start)

# 2. 移除工具栏中的勾选框
old_toolbar = '''        for w in [btn_transition, btn_siphon, self.btn_pressure_pipe_calc, btn_calc]:
            tb.addWidget(w)

        self.chk_pressure_pipe_sensitivity = QCheckBox("球墨铸铁管 f 上下限对比")
        self.chk_pressure_pipe_sensitivity.setChecked(self._pressure_pipe_sensitivity_enabled)
        self.chk_pressure_pipe_sensitivity.setToolTip(
            "球墨铸铁管按规范给 f 上下限（非单一值）：主值 f=223200；下限对比 f=189900（仅对比，不影响回写）"
        )
        self.chk_pressure_pipe_sensitivity.toggled.connect(self._set_pressure_pipe_sensitivity_enabled)
        tb.addWidget(self.chk_pressure_pipe_sensitivity)

        # 数据清理组'''

new_toolbar = '''        for w in [btn_transition, btn_siphon, self.btn_pressure_pipe_calc, btn_calc]:
            tb.addWidget(w)

        # 数据清理组'''

content = content.replace(old_toolbar, new_toolbar)

# 3. 修改结果对话框，添加重新计算功能
old_result_dialog = '''        opt_row = QHBoxLayout()
        cb_show_sensitivity = QCheckBox("显示球墨铸铁管上下限对比列")
        cb_show_sensitivity.setChecked(show_sensitivity)
        cb_show_sensitivity.setEnabled(has_sensitivity_data)
        if not has_di_material:
            cb_show_sensitivity.setEnabled(False)
            cb_show_sensitivity.setToolTip("本批次无球墨铸铁管")
        elif not has_sensitivity_data:
            cb_show_sensitivity.setToolTip("本批次未生成上下限对比结果，请开启工具栏"球墨铸铁管 f 上下限对比"后重新计算")
        opt_row.addWidget(cb_show_sensitivity)
        opt_row.addStretch()
        lay.addLayout(opt_row)'''

new_result_dialog = '''        opt_row = QHBoxLayout()

        # 球墨铸铁管上下限对比勾选框（用于重新计算）
        try:
            from qfluentwidgets import CheckBox
            cb_sensitivity_calc = CheckBox("球墨铸铁管 f 上下限对比")
        except ImportError:
            cb_sensitivity_calc = QCheckBox("球墨铸铁管 f 上下限对比")

        cb_sensitivity_calc.setChecked(batch_sensitivity_enabled)
        cb_sensitivity_calc.setToolTip("勾选后重新计算将包含球墨铸铁管上下限对比分析\n主值 f=223200，下限 f=189900")

        def _on_sensitivity_calc_changed(checked: bool):
            """当用户修改勾选框时，询问是否重新计算"""
            if checked == batch_sensitivity_enabled:
                return

            from 渠系断面设计.styles import fluent_question
            reply = fluent_question(
                "重新计算确认",
                f"您{'开启' if checked else '关闭'}了球墨铸铁管上下限对比。\n\n"
                "是否立即重新执行有压管道计算？\n"
                "(重新计算将更新所有有压管道的结果)",
                dlg
            )
            if reply:
                # 保存新的配置
                self._set_pressure_pipe_sensitivity_enabled(checked)
                # 关闭当前对话框
                dlg.accept()
                # 重新执行计算
                self._open_pressure_pipe_calculator()
            else:
                # 用户取消，恢复原状态
                cb_sensitivity_calc.blockSignals(True)
                cb_sensitivity_calc.setChecked(batch_sensitivity_enabled)
                cb_sensitivity_calc.blockSignals(False)

        cb_sensitivity_calc.toggled.connect(_on_sensitivity_calc_changed)
        opt_row.addWidget(cb_sensitivity_calc)

        opt_row.addSpacing(20)

        # 显示/隐藏对比列的勾选框
        cb_show_sensitivity = QCheckBox("显示球墨铸铁管上下限对比列")
        cb_show_sensitivity.setChecked(show_sensitivity)
        cb_show_sensitivity.setEnabled(has_sensitivity_data)
        if not has_di_material:
            cb_show_sensitivity.setEnabled(False)
            cb_show_sensitivity.setToolTip("本批次无球墨铸铁管")
        elif not has_sensitivity_data:
            cb_show_sensitivity.setToolTip("本批次未生成上下限对比结果")
        opt_row.addWidget(cb_show_sensitivity)
        opt_row.addStretch()
        lay.addLayout(opt_row)'''

content = content.replace(old_result_dialog, new_result_dialog)

# 写回文件
with open(r"渠系断面设计\water_profile\panel.py", 'w', encoding='utf-8') as f:
    f.write(content)

print("修改完成")
