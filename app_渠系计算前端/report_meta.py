# -*- coding: utf-8 -*-
"""
工程计算书元数据管理
- ReportMeta: 项目级元数据数据类
- ProjectSettingsDialog: 全局项目设置对话框（Level 1）
- ExportConfirmDialog: 导出确认框（Level 2，每次导出时弹出）
- 持久化: QSettings("SichuanShuifa", "HydroCalc")
"""

from dataclasses import dataclass, field
from typing import List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QGroupBox, QTabWidget,
    QWidget, QDialogButtonBox, QFrame, QSizePolicy,
    QAbstractItemView, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont

from app_渠系计算前端.styles import P, T1, T2, BD, CARD, DIALOG_STYLE


# ============================================================
# 常量
# ============================================================

DESIGN_UNIT = "四川水发勘测设计研究有限公司"
APP_NAME_VER = "渠系建筑物水力计算系统 V1.0"

REFERENCES_BASE = {
    "open_channel": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
    ],
    "aqueduct": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
    ],
    "tunnel": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
        "《水工隧洞设计规范》(SL 279-2016)",
    ],
    "culvert": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
    ],
    "siphon": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
    ],
    "water_profile": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
    ],
    "pressure_pipe": [
        "《灌溉与排水工程设计标准》(GB 50288-2018)",
        "《管道输水灌溉工程技术规范》(GB/T 20203-2017)",
    ],
}

CALC_PURPOSE_TEMPLATE = {
    "open_channel": (
        "为确定{project}{name}{section_type}明渠的水力断面设计参数，进行明渠水力计算，"
        "验算断面过水能力及流速是否满足《灌溉与排水工程设计标准》(GB 50288-2018)规范要求。"
    ),
    "aqueduct": (
        "为确定{project}{name}渡槽的水力设计参数，对{section_type}渡槽断面进行水力计算，"
        "验算槽身过水能力及设计流速是否满足《灌溉与排水工程设计标准》(GB 50288-2018)规范要求。"
    ),
    "tunnel": (
        "为确定{project}{name}隧洞的水力设计参数，对{section_type}隧洞断面进行水力计算，"
        "验算断面过水能力及流速是否满足《水工隧洞设计规范》(SL 279-2016)规范要求。"
    ),
    "culvert": (
        "为确定{project}{name}矩形暗涵的水力设计参数，进行暗涵断面水力计算，"
        "验算过水能力及净空高度是否满足《灌溉与排水工程设计标准》(GB 50288-2018)规范要求。"
    ),
    "siphon": (
        "为确定{project}{name}倒虹吸的水力设计参数，进行管道水力计算，"
        "验算管道过水能力及水头损失是否满足《灌溉与排水工程设计标准》(GB 50288-2018)规范要求。"
    ),
    "water_profile": (
        "为推求{project}{name}沿线水面线，确定各控制节点水位及水面比降，"
        "为工程水力设计提供依据。"
    ),
    "pressure_pipe": (
        "为确定{project}{name}有压输水管道的管径及水力参数，进行有压管道水力计算，"
        "验算管道流速及水头损失是否满足《灌溉与排水工程设计标准》(GB 50288-2018)第6.7.2条及"
        "《管道输水灌溉工程技术规范》(GB/T 20203-2017)第5.1.4~5.1.6条规范要求。"
    ),
}


def build_calc_purpose(module_key: str, project: str = "", name: str = "",
                       section_type: str = "") -> str:
    """根据模块和上下文参数生成计算目的模板文字"""
    tpl = CALC_PURPOSE_TEMPLATE.get(module_key, "")
    proj_str = project.strip() + "" if project.strip() else ""
    name_str = name.strip() + "" if name.strip() else ""
    st_str = section_type.strip() if section_type.strip() else ""
    return tpl.format(project=proj_str, name=name_str, section_type=st_str)


# ============================================================
# 数据类
# ============================================================

@dataclass
class ReportMeta:
    project_name: str = ""
    design_stage: str = "施工图"
    product_level: str = "三级"
    record_number: str = ""
    specialty: str = "水工"
    calculator: str = ""
    checker: str = ""
    reviewer: str = ""
    approver: str = ""
    volume_current: str = ""
    volume_total: str = ""
    basic_info: str = ""
    mandatory_clause: str = "无"
    extra_references: List[str] = field(default_factory=list)


# ============================================================
# QSettings 持久化助手
# ============================================================

_QSETTINGS_ORG = "SichuanShuifa"
_QSETTINGS_APP = "HydroCalc"


def _qs() -> QSettings:
    return QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)


def load_meta() -> ReportMeta:
    s = _qs()
    extra = s.value("report/extra_references", [], type=list)
    return ReportMeta(
        project_name=s.value("report/project_name", "", str),
        design_stage=s.value("report/design_stage", "施工图", str),
        product_level=s.value("report/product_level", "三级", str),
        record_number=s.value("report/record_number", "", str),
        specialty=s.value("report/specialty", "水工", str),
        calculator=s.value("report/calculator", "", str),
        checker=s.value("report/checker", "", str),
        reviewer=s.value("report/reviewer", "", str),
        approver=s.value("report/approver", "", str),
        volume_current=s.value("report/volume_current", "", str),
        volume_total=s.value("report/volume_total", "", str),
        basic_info=s.value("report/basic_info", "", str),
        mandatory_clause=s.value("report/mandatory_clause", "无", str),
        extra_references=list(extra) if extra else [],
    )


def save_meta(meta: ReportMeta):
    s = _qs()
    s.setValue("report/project_name", meta.project_name)
    s.setValue("report/design_stage", meta.design_stage)
    s.setValue("report/product_level", meta.product_level)
    s.setValue("report/record_number", meta.record_number)
    s.setValue("report/specialty", meta.specialty)
    s.setValue("report/calculator", meta.calculator)
    s.setValue("report/checker", meta.checker)
    s.setValue("report/reviewer", meta.reviewer)
    s.setValue("report/approver", meta.approver)
    s.setValue("report/volume_current", meta.volume_current)
    s.setValue("report/volume_total", meta.volume_total)
    s.setValue("report/basic_info", meta.basic_info)
    s.setValue("report/mandatory_clause", meta.mandatory_clause)
    s.setValue("report/extra_references", meta.extra_references)
    s.sync()


def load_calc_purpose(module_key: str) -> str:
    s = _qs()
    return s.value(f"report/calc_purpose_{module_key}", "", str)


def save_calc_purpose(module_key: str, text: str):
    s = _qs()
    s.setValue(f"report/calc_purpose_{module_key}", text)
    s.sync()


# ============================================================
# 通用 UI 辅助
# ============================================================

def _labeled(label: str, widget) -> QHBoxLayout:
    lay = QHBoxLayout()
    lbl = QLabel(label)
    lbl.setFixedWidth(90)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    lay.addWidget(lbl)
    lay.addWidget(widget, 1)
    return lay


def _hr() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{BD};")
    return f


# ============================================================
# Level 1 — 全局项目设置对话框
# ============================================================

class ProjectSettingsDialog(QDialog):
    """全局项目设置对话框（Level 1）
    包含工程名称、设计阶段、产品级别、人员、基本资料、强标条款、项目特有参考文献。
    数据持久化到 QSettings。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("项目设置 — 计算书信息")
        self.setMinimumSize(640, 560)
        self.setStyleSheet(DIALOG_STYLE)
        self._meta = load_meta()
        self._init_ui()
        self._load_to_ui()

    # ----------------------------------------------------------
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # ---- Tab1: 基本信息 ----
        t1 = QWidget()
        t1lay = QVBoxLayout(t1)
        t1lay.setSpacing(8)

        grp1 = QGroupBox("工程信息")
        g1lay = QVBoxLayout(grp1)
        g1lay.setSpacing(6)
        self.ed_project = QLineEdit(); self.ed_project.setPlaceholderText("如：南峰寺水库灌区改扩建工程")
        self.cb_stage = QComboBox(); self.cb_stage.addItems(["规划", "项目建议书", "可行性研究", "初步设计", "招标设计", "施工详图设计"])
        self.cb_level = QComboBox(); self.cb_level.addItems(["一级", "二级", "三级"])
        self.ed_record = QLineEdit(); self.ed_record.setPlaceholderText("可留空")
        self.ed_vol_cur = QLineEdit(); self.ed_vol_cur.setFixedWidth(60); self.ed_vol_cur.setPlaceholderText("1")
        self.ed_vol_tot = QLineEdit(); self.ed_vol_tot.setFixedWidth(60); self.ed_vol_tot.setPlaceholderText("1")
        vol_lay = QHBoxLayout()
        vol_lay.addWidget(QLabel("第")); vol_lay.addWidget(self.ed_vol_cur)
        vol_lay.addWidget(QLabel("册 / 共")); vol_lay.addWidget(self.ed_vol_tot)
        vol_lay.addWidget(QLabel("册")); vol_lay.addStretch()
        g1lay.addLayout(_labeled("工程名称:", self.ed_project))
        g1lay.addLayout(_labeled("设计阶段:", self.cb_stage))
        g1lay.addLayout(_labeled("产品级别:", self.cb_level))
        g1lay.addLayout(_labeled("记录编号:", self.ed_record))
        g1lay.addLayout(vol_lay)
        t1lay.addWidget(grp1)

        grp2 = QGroupBox("人员信息")
        g2lay = QVBoxLayout(grp2)
        g2lay.setSpacing(6)
        self.ed_specialty = QLineEdit(); self.ed_specialty.setPlaceholderText("水工")
        self.ed_calc = QLineEdit(); self.ed_calc.setPlaceholderText("计算人姓名")
        self.ed_check = QLineEdit(); self.ed_check.setPlaceholderText("校核人姓名（可留空）")
        self.ed_review = QLineEdit(); self.ed_review.setPlaceholderText("审查人姓名（可留空）")
        self.ed_approve = QLineEdit(); self.ed_approve.setPlaceholderText("审定人姓名（可留空）")
        g2lay.addLayout(_labeled("专业名称:", self.ed_specialty))
        g2lay.addLayout(_labeled("计    算:", self.ed_calc))
        g2lay.addLayout(_labeled("校    核:", self.ed_check))
        g2lay.addLayout(_labeled("审    查:", self.ed_review))
        g2lay.addLayout(_labeled("审    定:", self.ed_approve))
        t1lay.addWidget(grp2)
        t1lay.addStretch()
        tabs.addTab(t1, "基本信息")

        # ---- Tab2: 基本资料 ----
        t2 = QWidget()
        t2lay = QVBoxLayout(t2)
        lbl2 = QLabel('工程基本资料（将出现在计算书第5页"3、基本资料"节）：')
        lbl2.setWordWrap(True)
        self.ed_basic_info = QTextEdit()
        self.ed_basic_info.setPlaceholderText(
            "请描述工程概况，如：本工程位于XX省XX县，设计灌溉面积XXX亩，渠道等级X级，"
            "设计流量X.XX m³/s，采用梯形断面……"
        )
        t2lay.addWidget(lbl2)
        t2lay.addWidget(self.ed_basic_info, 1)
        tabs.addTab(t2, "基本资料")

        # ---- Tab3: 项目参考文献 ----
        t3 = QWidget()
        t3lay = QVBoxLayout(t3)
        lbl3 = QLabel("项目特有参考文献（将追加在规范标准之后，按编号顺序排列）：")
        lbl3.setWordWrap(True)
        t3lay.addWidget(lbl3)
        self.ref_list = QListWidget()
        self.ref_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.ref_list.setToolTip("可拖拽调整顺序")
        t3lay.addWidget(self.ref_list, 1)
        ref_btns = QHBoxLayout()
        self.ed_ref_input = QLineEdit()
        self.ed_ref_input.setPlaceholderText("如：《南峰寺水库初步设计报告》")
        btn_add_ref = QPushButton("添加"); btn_add_ref.clicked.connect(self._add_ref)
        btn_del_ref = QPushButton("删除"); btn_del_ref.clicked.connect(self._del_ref)
        ref_btns.addWidget(self.ed_ref_input, 1)
        ref_btns.addWidget(btn_add_ref)
        ref_btns.addWidget(btn_del_ref)
        t3lay.addLayout(ref_btns)
        tabs.addTab(t3, "项目参考文献")

        # ---- Tab4: 强标条款 ----
        t4 = QWidget()
        t4lay = QVBoxLayout(t4)
        lbl4 = QLabel('强制性标准条文执行情况（出现在第3页强标检查表，默认为"无"）：')
        lbl4.setWordWrap(True)
        self.ed_mandatory = QTextEdit()
        self.ed_mandatory.setPlaceholderText("无")
        t4lay.addWidget(lbl4)
        t4lay.addWidget(self.ed_mandatory, 1)
        tabs.addTab(t4, "强标条款")

        # ---- 底部按钮 ----
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ----------------------------------------------------------
    def _load_to_ui(self):
        m = self._meta
        self.ed_project.setText(m.project_name)
        idx = self.cb_stage.findText(m.design_stage)
        if idx >= 0: self.cb_stage.setCurrentIndex(idx)
        idx = self.cb_level.findText(m.product_level)
        if idx >= 0: self.cb_level.setCurrentIndex(idx)
        self.ed_record.setText(m.record_number)
        self.ed_vol_cur.setText(m.volume_current)
        self.ed_vol_tot.setText(m.volume_total)
        self.ed_specialty.setText(m.specialty)
        self.ed_calc.setText(m.calculator)
        self.ed_check.setText(m.checker)
        self.ed_review.setText(m.reviewer)
        self.ed_approve.setText(m.approver)
        self.ed_basic_info.setPlainText(m.basic_info)
        self.ed_mandatory.setPlainText(m.mandatory_clause or "无")
        for ref in m.extra_references:
            self.ref_list.addItem(QListWidgetItem(ref))

    def _add_ref(self):
        txt = self.ed_ref_input.text().strip()
        if txt:
            self.ref_list.addItem(QListWidgetItem(txt))
            self.ed_ref_input.clear()

    def _del_ref(self):
        for item in self.ref_list.selectedItems():
            self.ref_list.takeItem(self.ref_list.row(item))

    def _save_and_accept(self):
        m = self._meta
        m.project_name = self.ed_project.text().strip()
        m.design_stage = self.cb_stage.currentText()
        m.product_level = self.cb_level.currentText()
        m.record_number = self.ed_record.text().strip()
        m.volume_current = self.ed_vol_cur.text().strip()
        m.volume_total = self.ed_vol_tot.text().strip()
        m.specialty = self.ed_specialty.text().strip() or "水工"
        m.calculator = self.ed_calc.text().strip()
        m.checker = self.ed_check.text().strip()
        m.reviewer = self.ed_review.text().strip()
        m.approver = self.ed_approve.text().strip()
        m.basic_info = self.ed_basic_info.toPlainText().strip()
        m.mandatory_clause = self.ed_mandatory.toPlainText().strip() or "无"
        m.extra_references = [
            self.ref_list.item(i).text()
            for i in range(self.ref_list.count())
        ]
        save_meta(m)
        self.accept()

    def get_meta(self) -> ReportMeta:
        return self._meta


# ============================================================
# Level 2 — 导出确认框
# ============================================================

class ExportConfirmDialog(QDialog):
    """导出确认框（Level 2）
    每次点击"导出Word"时弹出，预填计算目的（可编辑），显示本次计算依据列表。
    """

    def __init__(self, module_key: str, calc_title: str,
                 auto_purpose: str,
                 parent=None,
                 n_cases: int = 1,
                 current_case_label: str = ""):
        """
        Args:
            module_key: 模块标识，如 'open_channel'
            calc_title: 如 '明渠水力计算书'
            auto_purpose: 自动生成的计算目的文字
            n_cases: 工况数量（>1 时显示导出范围选项）
            current_case_label: 当前工况标签文字（用于显示）
        """
        super().__init__(parent)
        self.module_key = module_key
        self._n_cases = n_cases
        self._current_case_label = current_case_label
        self.setWindowTitle(f"导出计算书 — {calc_title}")
        self.setMinimumSize(560, 420)
        self.setStyleSheet(DIALOG_STYLE)
        self._meta = load_meta()
        saved_purpose = load_calc_purpose(module_key)
        self._init_purpose = saved_purpose if saved_purpose else auto_purpose
        self._auto_purpose = auto_purpose
        self._init_ui(calc_title)

    def _init_ui(self, calc_title: str):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # 标题提示
        tip = QLabel(f'即将导出 <b>{calc_title}</b>，请确认计算目的后点击"确认导出"。')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{P}; font-size:13px; padding:4px 0;")
        root.addWidget(tip)

        root.addWidget(_hr())

        # ---------- 导出范围（仅多工况时显示） ----------
        self._export_scope_group = None
        self._rb_current = None
        self._rb_all = None
        if self._n_cases > 1:
            scope_grp = QGroupBox("导出范围")
            scope_lay = QVBoxLayout(scope_grp)
            self._rb_current = QRadioButton(
                f"仅导出当前工况（{self._current_case_label}）"
            )
            self._rb_all = QRadioButton(
                f"导出全部工况（{self._n_cases}个工况，合并文档）"
            )
            self._rb_all.setChecked(True)
            btn_group = QButtonGroup(self)
            btn_group.addButton(self._rb_current)
            btn_group.addButton(self._rb_all)
            scope_lay.addWidget(self._rb_current)
            scope_lay.addWidget(self._rb_all)
            root.addWidget(scope_grp)
            root.addWidget(_hr())
            self._export_scope_group = scope_grp

        # 计算目的
        grp1 = QGroupBox("计算目的（可直接使用或修改）")
        g1lay = QVBoxLayout(grp1)
        self.ed_purpose = QTextEdit()
        self.ed_purpose.setPlainText(self._init_purpose)
        self.ed_purpose.setMinimumHeight(100)
        btn_reset = QPushButton("重置为自动生成")
        btn_reset.setFixedWidth(130)
        btn_reset.clicked.connect(lambda: self.ed_purpose.setPlainText(self._auto_purpose))
        g1lay.addWidget(self.ed_purpose)
        g1lay.addWidget(btn_reset, 0, Qt.AlignRight)
        root.addWidget(grp1)

        # 计算依据（只读预览）
        grp2 = QGroupBox("计算依据（规范 + 项目参考文献）")
        g2lay = QVBoxLayout(grp2)
        refs = REFERENCES_BASE.get(self.module_key, []) + self._meta.extra_references
        ref_lbl = QLabel("\n".join(f"{i+1}、{r}" for i, r in enumerate(refs)))
        ref_lbl.setWordWrap(True)
        ref_lbl.setStyleSheet(f"color:{T1}; font-size:12px; padding:4px;")
        edit_hint = QLabel('（如需修改规范或添加项目文件，请在侧边栏"项目设置"中调整）')
        edit_hint.setStyleSheet(f"color:{T2}; font-size:11px;")
        g2lay.addWidget(ref_lbl)
        g2lay.addWidget(edit_hint)
        root.addWidget(grp2)

        root.addStretch()
        root.addWidget(_hr())

        # 底部按钮
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("取消"); self.btn_cancel.setFixedWidth(80)
        self.btn_ok = QPushButton("确认导出"); self.btn_ok.setFixedWidth(100)
        self.btn_ok.setStyleSheet(f"background:{P}; color:white; border-radius:4px; padding:6px;")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_accept)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        root.addLayout(btns)

    def _on_accept(self):
        save_calc_purpose(self.module_key, self.ed_purpose.toPlainText().strip())
        self.accept()

    def get_calc_purpose(self) -> str:
        return self.ed_purpose.toPlainText().strip()

    def get_meta(self) -> ReportMeta:
        return self._meta

    def get_references(self) -> List[str]:
        return REFERENCES_BASE.get(self.module_key, []) + self._meta.extra_references

    def get_export_scope(self) -> str:
        """返回导出范围: 'current' 或 'all'。单工况时始终返回 'all'。"""
        if self._rb_current is not None and self._rb_current.isChecked():
            return 'current'
        return 'all'
