# -*- coding: utf-8 -*-
"""
PySide6版 公式渲染对话框 + 表头公式提示

完整复刻原版Tkinter formula_dialog.py 和 latex_tooltip.py 功能：
  1. FormulaDialog   — 双击水头损失/高程单元格时弹出的详细计算过程对话框
  2. COLUMN_FORMULAS — 列ID → 公式说明映射（鼠标悬停表头时显示tooltip）
  3. show_xxx_dialog — 各类水头损失/高程的快捷弹窗函数
"""

import re
import html as html_mod
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QFrame, QSizePolicy,
)
try:
    from qfluentwidgets import PushButton
except ImportError:
    from PySide6.QtWidgets import QPushButton as PushButton
from PySide6.QtCore import Qt, QTimer, QByteArray, QRectF, QSize, QPoint
from PySide6.QtGui import QFont, QPainter, QPainterPath, QLinearGradient, QColor, QPixmap, QPen

try:
    from PySide6.QtSvg import QSvgRenderer
    HAS_SVG = True
except ImportError:
    HAS_SVG = False

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

try:
    from 渠系断面设计.formula_renderer import render_latex_svg
    HAS_SVG_RENDERER = True
except ImportError:
    HAS_SVG_RENDERER = False


# ================================================================
# 列ID → 公式说明映射（与原版 latex_tooltip.py COLUMN_FORMULAS 完全一致）
# ================================================================
COLUMN_FORMULAS: Dict[str, Dict[str, str]] = {
    "转角": {
        "title": "转角计算",
        "description": "使用余弦定理计算三点形成的偏角",
        "formula": r"α = 180° - arccos((a² + c² - b²) / 2ac)",
        "latex": r"\alpha = 180^{\circ} - \arccos\left(\frac{a^2 + c^2 - b^2}{2ac}\right)",
        "note": "其中: a=当前点到下一点距离, b=前一点到下一点距离, c=前一点到当前点距离",
    },
    "切线长": {
        "title": "切线长计算",
        "description": "根据转角和转弯半径计算切线长度",
        "formula": r"T = R × tan(α/2)",
        "latex": r"T = R \times \tan\left(\frac{\alpha}{2}\right)",
        "note": "其中: R=转弯半径, α=转角(弧度)",
    },
    "弧长": {
        "title": "弧长计算",
        "description": "根据转角和转弯半径计算弧长",
        "formula": r"L = R × α",
        "latex": r"L = R \times \alpha",
        "note": "其中: R=转弯半径, α=转角(弧度)",
    },
    "弯道长度": {
        "title": "弯道长度",
        "description": "弯道长度等于弧长",
        "formula": r"L_curve = S_EC - S_BC = L_arc",
        "latex": r"L_{curve} = S_{EC} - S_{BC} = L_{arc}",
        "note": "即EC桩号与BC桩号之差",
    },
    "IP直线间距": {
        "title": "IP直线间距",
        "description": "相邻两个IP点之间的直线距离",
        "formula": r"D = √((Xi - Xi-1)² + (Yi - Yi-1)²)",
        "latex": r"D = \sqrt{(X_i - X_{i-1})^2 + (Y_i - Y_{i-1})^2}",
        "note": "使用两点间距离公式计算",
    },
    "IP点桩号": {
        "title": "IP点桩号",
        "description": "IP点的累计桩号",
        "formula": r"S_IP(i) = S₀ + Σ Dⱼ",
        "latex": r"S_{IP}^{(i)} = S_0 + \sum D_j",
        "note": "其中: S₀=起始桩号, Dⱼ=第j段的IP直线间距",
    },
    "弯前BC": {
        "title": "弯前BC桩号",
        "description": "弯道起点(曲线起点)的桩号",
        "formula": r"S_BC = S_MC - L/2",
        "latex": r"S_{BC} = S_{MC} - \frac{L}{2}",
        "note": "其中: S_MC=里程MC, L=弧长",
    },
    "里程MC": {
        "title": "里程MC桩号",
        "description": "弯道中点的桩号，使用递推公式计算",
        "formula": r"S_MC(i) = S_MC(i-1) + Di - Ti-1 - Ti + Li-1/2 + Li/2",
        "latex": r"S_{MC}^{(i)} = S_{MC}^{(i-1)} + D_i - T_{i-1} - T_i + \frac{L_{i-1}}{2} + \frac{L_i}{2}",
        "note": "其中: D=IP间距, T=切线长, L=弧长",
    },
    "弯末EC": {
        "title": "弯末EC桩号",
        "description": "弯道终点(曲线终点)的桩号",
        "formula": r"S_EC = S_BC + L",
        "latex": r"S_{EC} = S_{BC} + L",
        "note": "其中: S_BC=弯前BC桩号, L=弧长",
    },
    "转弯半径": {
        "title": "转弯半径",
        "description": "弯道的圆曲线半径",
        "formula": r"R",
        "latex": r"R",
        "note": "用户输入值，影响切线长和弧长的计算",
    },
    "复核弯前长度": {
        "title": "复核弯前长度",
        "description": "检查当前弯道的起弯点(BC)是否超过了上一个IP点",
        "formula": r"L_pre = Li - Ti",
        "latex": r"L_{pre} = L_i - T_i",
        "note": "若为负数说明起弯点跑到了上一IP点前面，设计不合理",
    },
    "复核弯后长度": {
        "title": "复核弯后长度",
        "description": "检查当前弯道的出弯点(EC)是否超过了下一个IP点",
        "formula": r"L_post = Li+1 - Ti",
        "latex": r"L_{post} = L_{i+1} - T_i",
        "note": "若为负数说明出弯点跑到了下一IP点后面，设计不合理",
    },
    "复核总长度": {
        "title": "复核总长度（夹直线长度）",
        "description": "检查两个弯道之间是否有足够的直线缓冲段",
        "formula": r"L_total = Li - Ti-1 - Ti",
        "latex": r"L_{total} = L_i - T_{i-1} - T_i",
        "note": "若为负数说明两弯道曲线重叠，无法施工",
    },
    "弯道水头损失": {
        "title": "弯道水头损失计算",
        "description": "弯道处水流产生二次流（螺旋流），导致动能损耗增加",
        "formula": r"hw = n²·L·v² / R^(4/3) × (3/4)√(B/Rc)",
        "latex": r"h_w = \frac{n^2 \cdot L \cdot v^2}{R^{4/3}} \times \frac{3}{4}\sqrt{\frac{B}{R_c}}",
        "note": "n=糙率, L=弯道长度, v=流速, R=水力半径, B=水面宽度, Rc=转弯半径\n双击单元格可查看详细计算过程",
    },
    "渐变段水头损失": {
        "title": "渐变段水头损失计算",
        "description": "渐变段水头损失包括局部损失和沿程损失（平均值法）",
        "formula": r"h_tr = ξ₁·|v₂²-v₁²|/(2g) + i·L",
        "latex": r"h_{tr} = \zeta_1 \cdot \frac{|v_2^2 - v_1^2|}{2g} + i \cdot L",
        "note": "ξ₁=局部损失系数(表K.1.2), v₁=起始流速, v₂=末端流速\n双击单元格可查看详细计算过程",
    },
    "沿程水头损失": {
        "title": "沿程水头损失计算",
        "description": "使用底坡和有效长度计算沿程水头损失",
        "formula": r"hf = i × L_eff",
        "latex": r"h_f = i \times L_{eff}",
        "note": "有效长度 = (里程MC差) - 渐变段长度 - 上行弧长/2 - 本行弧长/2\n双击单元格可查看详细计算过程",
    },
    "预留水头损失": {
        "title": "预留水头损失",
        "description": "用于补充工程中程序未覆盖的损失，工程师可按经验自行输入",
        "formula": r"h_res",
        "latex": r"h_{res}",
        "note": "该值不参与公式计算，直接计入总水头损失",
    },
    "过闸水头损失": {
        "title": "过闸水头损失",
        "description": "分水闸/分水口/节制闸/泄水闸等闸类结构通过闸孔产生的水头损失",
        "formula": r"h_gate",
        "latex": r"h_{gate}",
        "note": "该值可手动输入；闸类结构若为空则自动填充默认值",
    },
    "倒虹吸/有压管道水头损失": {
        "title": "倒虹吸/有压管道水头损失",
        "description": "由倒虹吸或有压管道模块回写的总水头损失",
        "formula": r"h_sip",
        "latex": r"h_{sip}",
        "note": "由倒虹吸/有压管道水力计算模块计算后回写",
    },
    "总水头损失": {
        "title": "总水头损失",
        "description": "该节点的总水头损失（包含弯道、渐变段、沿程及其他损失）",
        "formula": r"hΣ = hw + h_tr + hf + h_res + h_gate + h_sip",
        "latex": r"h_{\Sigma} = h_w + h_{tr} + h_f + h_{res} + h_{gate} + h_{sip}",
        "note": "双击单元格可查看详细计算过程",
    },
    "累计总水头损失": {
        "title": "累计总水头损失",
        "description": "从第一行开始逐行累加的水头损失",
        "formula": r"h_cum,i = Σ hk",
        "latex": r"h_{cum,i} = \sum h_k",
        "note": "普通行取总水头损失，渐变段行取渐变段水头损失\n双击单元格可查看详细计算过程",
    },
    "水位": {
        "title": "水位计算",
        "description": "根据上一节点水位与各项损失推求当前水位",
        "formula": r"Zi = Zi-1 - hf - hj - hw - h_tr",
        "latex": r"Z_i = Z_{i-1} - \Delta h_i",
        "note": "首节点水位取起始水位；分水闸按过闸损失扣减\n双击单元格可查看详细计算过程",
    },
    "渠底高程": {
        "title": "渠底高程计算",
        "description": "由水位与水深计算渠底高程",
        "formula": r"Zb = Z - h",
        "latex": r"Z_b = Z - h",
        "note": "Z=水位, h=水深\n双击单元格可查看详细计算过程",
    },
    "渠顶高程": {
        "title": "渠顶高程计算",
        "description": "由渠底高程与结构高度计算渠顶高程",
        "formula": r"Zt = Zb + H",
        "latex": r"Z_t = Z_b + H",
        "note": "Zb=渠底高程, H=结构高度\n双击单元格可查看详细计算过程",
    },
    "水深h设计": {
        "title": "水深",
        "description": "利用曼宁公式试算法求解正常水深",
        "formula": r"Q = A·R^(2/3)·i^(1/2) / n",
        "latex": r"Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}",
        "note": "Q=流量, A=过水断面面积, R=水力半径, i=底坡, n=糙率",
    },
    "过水断面面积A": {
        "title": "过水断面面积",
        "description": "根据断面类型计算",
        "formula": r"梯形: A = (B + m·h)·h  |  圆形: A = f(D,h)",
        "latex": r"A = (B + m \cdot h) \cdot h",
        "note": "B=底宽, m=边坡系数, h=水深, D=直径",
    },
    "湿周X": {
        "title": "湿周",
        "description": "水流与渠道壁面接触的长度",
        "formula": r"梯形: χ = B + 2h√(1+m²)  |  圆形: χ = f(D,h)",
        "latex": r"\chi = B + 2h\sqrt{1+m^2}",
        "note": "B=底宽, m=边坡系数, h=水深",
    },
    "水力半径R": {
        "title": "水力半径",
        "description": "过水断面面积与湿周之比",
        "formula": r"R = A / χ",
        "latex": r"R = \frac{A}{\chi}",
        "note": "A=过水断面面积, χ=湿周",
    },
    "流速v设计": {
        "title": "流速",
        "description": "由连续性方程计算",
        "formula": r"v = Q / A",
        "latex": r"v = \frac{Q}{A}",
        "note": "Q=流量, A=过水断面面积",
    },
    "渐变段长度L": {
        "title": "渐变段长度",
        "description": "根据水面宽度差和渐变段角度计算",
        "formula": r"L = |B₁ - B₂| × 系数",
        "latex": r"L = k \times |B_1 - B_2|",
        "note": "已按规范约束取大值",
    },
}

# 兼容旧表头名称（历史项目/旧版界面）
COLUMN_FORMULAS["倒虹吸水头损失"] = COLUMN_FORMULAS["倒虹吸/有压管道水头损失"]

# 需要双击弹窗的列名集合（与Tkinter版_on_cell_double_click对齐）
DOUBLE_CLICK_COLUMNS = {
    "渐变段长度L",
    "弯道水头损失", "沿程水头损失", "渐变段水头损失", "总水头损失", "累计总水头损失",
    "水位", "渠底高程", "渠顶高程",
}


# ================================================================
# 对话框 CSS 样式
# ================================================================
_DIALOG_CSS = """
* { box-sizing: border-box; }
body {
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: 14px; color: #242424; line-height: 1.6;
    margin: 0; padding: 16px 20px; background: #F5F5F5;
}
svg { vertical-align: middle; }
.sec-title {
    font-weight: 700; font-size: 15px; color: #242424;
    margin: 14px 0 8px 0; padding-bottom: 6px;
    border-bottom: 1px solid #F0F0F0;
}
.formula-card {
    background: #fff; border: 1px solid #F0F0F0;
    border-radius: 8px; margin: 6px 0;
    padding: 14px 18px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
}
.content-text {
    margin: 4px 0; padding: 8px 14px;
    background: #F8F9FE; border-radius: 6px;
    font-size: 13px; color: #424242;
}
.values-card {
    background: #f8f9fa; border: 1px solid #E8E8E8;
    border-radius: 8px; margin: 6px 0;
    padding: 10px 14px;
}
.val-line {
    margin: 4px 0; padding: 6px 12px;
    background: #fff; border-radius: 6px;
}
.val-sep {
    border: none; border-top: 1px solid #ccc; margin: 8px 12px;
}
.sep {
    border: none; border-top: 1px solid #E8E8E8; margin: 14px 0;
}
"""


def _e(s):
    """HTML 转义"""
    return html_mod.escape(str(s))


# ================================================================
# FormulaDialog — PySide6 版公式渲染对话框（SVG 矢量渲染）
# ================================================================
class FormulaDialog(QDialog):
    """使用 SVG 矢量渲染 LaTeX 公式，展示详细计算过程。

    复用 formula_renderer.render_latex_svg 将公式渲染为内联 SVG，
    在 QWebEngineView 中显示，任何缩放下都完美清晰。
    """

    def __init__(self, parent, title: str, sections: List[Dict[str, Any]],
                 width: int = 700, height: int = 600):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, height)
        self.setMinimumSize(500, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        layout = QVBoxLayout(self)

        if HAS_WEBENGINE and HAS_SVG_RENDERER:
            self._web = QWebEngineView()
            layout.addWidget(self._web, 1)
            self._web.setHtml(self._build_html(sections))
        else:
            # Fallback: 纯文本（无 WebEngine 或无 SVG 渲染器时）
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            cl = QVBoxLayout(content)
            cl.setAlignment(Qt.AlignTop)
            for sec in sections:
                if "title" in sec:
                    lbl = QLabel(sec["title"])
                    lbl.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
                    cl.addWidget(lbl)
                for key in ("formula", "content", "values"):
                    if key in sec:
                        lbl = QLabel(sec[key].replace("$", "").replace("\\", ""))
                        lbl.setWordWrap(True)
                        lbl.setFont(QFont("Microsoft YaHei", 10))
                        cl.addWidget(lbl)
            cl.addStretch()
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.exec()

    # ---- HTML 构建 ----

    def _build_html(self, sections):
        """将 sections 数据构建为含 SVG 公式的完整 HTML 页面。"""
        body_parts = []
        for i, sec in enumerate(sections):
            if i > 0:
                body_parts.append('<hr class="sep">')
            if "title" in sec:
                body_parts.append(
                    f'<div class="sec-title">{_e(sec["title"])}</div>')
            if "formula" in sec:
                body_parts.append(self._render_formula_block(sec["formula"]))
            if "content" in sec:
                body_parts.append(self._render_content_block(sec["content"]))
            if "values" in sec:
                body_parts.append(self._render_values_block(sec["values"]))
        body = '\n'.join(body_parts)
        return (f'<html><head><meta charset="utf-8">'
                f'<style>{_DIALOG_CSS}</style></head>'
                f'<body>{body}</body></html>')

    # ---- 渲染辅助 ----

    @staticmethod
    def _latex_to_svg(latex_str, fontsize=16):
        """去除 $...$ 并渲染为 SVG。"""
        clean = latex_str.strip()
        if clean.startswith('$') and clean.endswith('$'):
            clean = clean[1:-1].strip()
        return render_latex_svg(clean, fontsize=fontsize)

    @staticmethod
    def _inline_replace(text, fontsize=14):
        """将文本中的 $...$ 替换为 SVG 内联公式。"""
        parts = re.split(r'(\$[^$]+\$)', text)
        html_parts = []
        for part in parts:
            if part.startswith('$') and part.endswith('$'):
                latex = part[1:-1]
                svg = render_latex_svg(latex, fontsize=fontsize)
                html_parts.append(svg if svg else _e(part))
            else:
                html_parts.append(_e(part))
        return ''.join(html_parts)

    def _render_formula_block(self, formula_text):
        """渲染独立公式块（大字号，白色卡片）。"""
        svg = self._latex_to_svg(formula_text, fontsize=16)
        if svg:
            return f'<div class="formula-card">{svg}</div>'
        clean = formula_text.replace('$', '')
        return f'<div class="formula-card"><code>{_e(clean)}</code></div>'

    def _render_content_block(self, content_text):
        """渲染描述文本（可含内联 $...$）。"""
        if '$' in content_text:
            rendered = self._inline_replace(content_text, fontsize=14)
        else:
            rendered = _e(content_text)
        return f'<div class="content-text">{rendered}</div>'

    def _render_values_block(self, values_text):
        """渲染多行计算过程（每行含中文标签 + 内联 $...$）。"""
        lines = values_text.split('\n')
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) >= 3 and all(
                    c in '─━═—–\u2015-' for c in stripped):
                html_lines.append('<hr class="val-sep">')
                continue
            if '$' in stripped:
                rendered = self._inline_replace(stripped, fontsize=14)
            else:
                rendered = _e(stripped)
            html_lines.append(f'<div class="val-line">{rendered}</div>')
        return '<div class="values-card">' + ''.join(html_lines) + '</div>'


# ================================================================
# 快捷弹窗函数（与原版 formula_dialog.py 完全对齐）
# ================================================================

def show_bend_loss_dialog(parent, node_name: str, details: Dict[str, Any]):
    """弯道水头损失计算详情"""
    n = details.get('n', 0)
    L = details.get('L', 0)
    v = details.get('v', 0)
    R = details.get('R', 0)
    Rc = details.get('Rc', 0)
    B = details.get('B', 0)
    hw = details.get('hw', 0)
    sections = [
        {"title": "1. 弯道水头损失公式",
         "formula": r"$h_w = \frac{n^2 \cdot L \cdot v^2}{R^{4/3}} \times \frac{3}{4} \times \sqrt{\frac{B}{R_c}}$",
         "content": "其中: $n$=糙率, $L$=弯道长度(弧长), $v$=流速, $R$=水力半径, $B$=水面宽度, $R_c$=转弯半径"},
        {"title": "2. 计算参数",
         "values": f"糙率  $n = {n:.6f}$\n弯道长度  $L = {L:.3f}$ m\n流速  $v = {v:.4f}$ m/s\n"
                   f"水力半径  $R = {R:.4f}$ m\n水面宽度  $B = {B:.3f}$ m\n转弯半径  $R_c = {Rc:.3f}$ m"},
        {"title": "3. 代入公式计算",
         "values": f"$h_w = ({n:.6f})^2 \\times {L:.3f} \\times ({v:.4f})^2 / ({R:.4f})^{{4/3}} \\times 0.75 \\times \\sqrt{{{B/Rc if Rc>0 else 0:.6f}}}$\n"
                   f"    $= {hw:.6f}$ m"},
        {"title": "4. 计算结果", "formula": f"$h_w = {hw:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 弯道水头损失计算详情", sections)


def show_friction_loss_dialog(parent, node_name: str, details: Dict[str, Any]):
    """沿程水头损失计算详情"""
    method = details.get('method', 'slope')
    if method == 'slope':
        slope_i = details.get('slope_i', 0)
        L_eff = details.get('L_effective', 0)
        hf = details.get('hf', 0)
        ratio = f"  (即 $1/{1/slope_i:.0f}$)" if slope_i > 0 else ""
        sections = [
            {"title": "1. 沿程水头损失公式（底坡法）",
             "formula": r"$h_f = i \times L_{eff}$",
             "content": "其中: $i$=底坡, $L_{eff}$=有效计算长度"},
            {"title": "2. 有效长度计算",
             "formula": r"$L_{eff} = \Delta S_{MC} - L_{trans} - \frac{L_{arc,1}}{2} - \frac{L_{arc,2}}{2}$",
             "values": f"有效长度  $L_{{eff}} = {L_eff:.3f}$ m\n(扣除了渐变段长度和上下游弧长的一半)"},
            {"title": "3. 计算参数",
             "values": f"底坡  $i = {slope_i:.6f}${ratio}\n有效长度  $L_{{eff}} = {L_eff:.3f}$ m"},
            {"title": "4. 代入公式计算",
             "values": f"$h_f = {slope_i:.6f} \\times {L_eff:.3f}$\n    $= {hf:.6f}$ m"},
            {"title": "5. 计算结果", "formula": f"$h_f = {hf:.4f} \\ m$"},
        ]
    else:
        J1 = details.get('J1', 0); J2 = details.get('J2', 0)
        J_avg = details.get('J_avg', 0); L = details.get('L', 0)
        hf = details.get('hf', 0); n = details.get('n', 0)
        v1 = details.get('v1', 0); v2 = details.get('v2', 0)
        R1 = details.get('R1', 0); R2 = details.get('R2', 0)
        sections = [
            {"title": "1. 沿程水头损失公式（曼宁法）",
             "formula": r"$h_f = J_{avg} \times L$",
             "content": "其中: $J_{avg}$=平均水力坡降, $L$=计算长度"},
            {"title": "2. 水力坡降计算公式",
             "formula": r"$J = \left(\frac{v \cdot n}{R^{2/3}}\right)^2$"},
            {"title": "3. 计算参数",
             "values": f"糙率  $n = {n:.6f}$\n上游流速  $v_1 = {v1:.4f}$ m/s\n下游流速  $v_2 = {v2:.4f}$ m/s\n"
                       f"上游水力半径  $R_1 = {R1:.4f}$ m\n下游水力半径  $R_2 = {R2:.4f}$ m\n计算长度  $L = {L:.3f}$ m"},
            {"title": "4. 代入公式计算",
             "values": f"$J_{{avg}} = {J_avg:.8f}$\n$h_f = {J_avg:.8f} \\times {L:.3f} = {hf:.6f}$ m"},
            {"title": "5. 计算结果", "formula": f"$h_f = {hf:.4f} \\ m$"},
        ]
    FormulaDialog(parent, f"{node_name} - 沿程水头损失计算详情", sections)


def show_transition_loss_dialog(parent, node_name: str, details: Dict[str, Any]):
    """渐变段水头损失计算详情"""
    zeta = details.get('zeta', 0)
    v1 = details.get('v1', 0); v2 = details.get('v2', 0)
    B1 = details.get('B1', 0); B2 = details.get('B2', 0)
    length = details.get('length', 0); R_avg = details.get('R_avg', 0)
    v_avg = details.get('v_avg', 0)
    h_j1 = details.get('h_j1', 0); h_f = details.get('h_f', 0)
    total = details.get('total', 0)
    sections = [
        {"title": "1. 基本信息",
         "values": f"渐变段类型:  {details.get('transition_type', '')}\n渐变段形式:  {details.get('transition_form', '')}\n"
                   f"局部损失系数  $\\zeta_1 = {zeta:.4f}$"},
        {"title": "2. 流速参数",
         "values": f"起始流速  $v_1 = {v1:.4f}$ m/s\n末端流速  $v_2 = {v2:.4f}$ m/s\n平均流速  $v_{{avg}} = {v_avg:.4f}$ m/s"},
        {"title": "3. 断面参数",
         "values": f"起始水面宽度  $B_1 = {B1:.3f}$ m\n末端水面宽度  $B_2 = {B2:.3f}$ m\n平均水力半径  $R_{{avg}} = {R_avg:.4f}$ m"},
        {"title": "4. 渐变段长度计算",
         "values": f"$L$ = 系数 $\\times |B_1 - B_2| = {length:.3f}$ m\n(已按规范约束取大值)"},
        {"title": "5. 局部水头损失计算",
         "formula": r"$h_{j1} = \zeta_1 \times \frac{|v_2^2 - v_1^2|}{2g}$",
         "values": f"$h_{{j1}} = {zeta:.4f} \\times |{v2:.4f}^2 - {v1:.4f}^2| / (2 \\times 9.81)$\n    $= {h_j1:.4f}$ m"},
        {"title": "6. 沿程水头损失计算（平均值法）",
         "formula": r"$h_f = i \times L$",
         "values": f"$h_f = {h_f:.4f}$ m"},
        {"title": "7. 总水头损失",
         "formula": r"$h_{tr} = h_{j1} + h_f$",
         "values": f"$h_{{tr}} = {h_j1:.4f} + {h_f:.4f} = {total:.4f}$ m"},
    ]
    FormulaDialog(parent, f"{node_name} - 渐变段水头损失计算详情", sections)


def show_total_loss_dialog(parent, node_name: str, details: Dict[str, Any]):
    """总水头损失计算详情"""
    hw = details.get('head_loss_bend', 0)
    h_tr = details.get('head_loss_transition', 0)
    hf = details.get('head_loss_friction', 0)
    hj = details.get('head_loss_local', 0)
    h_res = details.get('head_loss_reserve', 0)
    h_gate = details.get('head_loss_gate', 0)
    h_sip = details.get('head_loss_siphon', 0)
    h_total = details.get('head_loss_total', 0)
    sections = [
        {"title": "1. 总水头损失公式",
         "formula": r"$h_{\Sigma} = h_w + h_j + h_{tr} + h_f + h_{res} + h_{gate} + h_{sip}$",
         "content": "其中: $h_w$=弯道损失, $h_j$=局部损失, $h_{tr}$=渐变段损失, $h_f$=沿程损失, $h_{res}$=预留损失, $h_{gate}$=过闸损失, $h_{sip}$=倒虹吸损失"},
        {"title": "2. 各项损失值",
         "values": f"弯道水头损失  $h_w = {hw:.4f}$ m\n局部水头损失  $h_j = {hj:.4f}$ m\n"
                   f"渐变段水头损失  $h_{{tr}} = {h_tr:.4f}$ m\n沿程水头损失  $h_f = {hf:.4f}$ m\n"
                   f"预留水头损失  $h_{{res}} = {h_res:.4f}$ m\n过闸水头损失  $h_{{gate}} = {h_gate:.4f}$ m\n"
                   f"倒虹吸/有压管道水头损失  $h_{{sip}} = {h_sip:.4f}$ m"},
        {"title": "3. 代入公式计算",
         "values": f"$h_{{\\Sigma}} = {hw:.4f} + {hj:.4f} + {h_tr:.4f} + {hf:.4f} + {h_res:.4f} + {h_gate:.4f} + {h_sip:.4f}$\n    $= {h_total:.4f}$ m"},
        {"title": "4. 计算结果", "formula": f"$h_{{\\Sigma}} = {h_total:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 总水头损失计算详情", sections)


def show_water_level_dialog(parent, node_name: str, details: Dict[str, Any]):
    """水位计算详情"""
    is_first = details.get('is_first', False)
    is_gate = details.get('is_gate', False)
    wl = details.get('water_level', 0.0)
    start_level = details.get('start_level', 0.0)
    cumulative = details.get('cumulative', 0.0)

    if is_first:
        sections = [
            {"title": "1. 起点水位", "formula": r"$Z_0 = Z_{start}$", "content": "起始水位由基础设置输入。"},
            {"title": "2. 计算参数", "values": f"起始水位  $Z_{{start}} = {start_level:.4f}$ m"},
            {"title": "3. 计算结果", "formula": f"$Z_0 = {wl:.4f} \\ m$"},
        ]
    elif is_gate:
        prev = details.get('prev_level', 0.0)
        h_gate = details.get('head_loss_gate', 0.0)
        sections = [
            {"title": "1. 过闸水位推求公式", "formula": r"$Z_i = Z_{i-1} - h_{gate}$", "content": "闸类结构（分水闸/分水口/节制闸/泄水闸等）仅考虑过闸水头损失。"},
            {"title": "2. 计算参数", "values": f"上一节点水位  $Z_{{i-1}} = {prev:.4f}$ m\n过闸水头损失  $h_{{gate}} = {h_gate:.4f}$ m"},
            {"title": "3. 代入公式计算", "values": f"$Z_i = {prev:.4f} - {h_gate:.4f} = {wl:.4f}$ m"},
            {"title": "4. 校验", "values": f"起始水位  $Z_{{start}} = {start_level:.4f}$ m\n累计总水头损失 $= {cumulative:.4f}$ m\n"
                                            f"$Z_{{start}}$ - 累计 $= {start_level - cumulative:.4f}$ m"},
            {"title": "5. 计算结果", "formula": f"$Z_i = {wl:.4f} \\ m$"},
        ]
    else:
        prev = details.get('prev_level', 0.0)
        hf = details.get('hf', 0.0); hj = details.get('hj', 0.0)
        hw = details.get('hw', 0.0); h_tr = details.get('h_tr', 0.0)
        h_res = details.get('h_reserve', 0.0)
        h_gate = details.get('h_gate', 0.0)
        h_sip = details.get('h_siphon', 0.0)
        delta = hf + hj + hw + h_tr + h_res + h_gate + h_sip
        sections = [
            {"title": "1. 水位推求公式（逐段递推）", "formula": r"$Z_i = Z_{i-1} - \Delta h_i$",
             "content": "$\\Delta h_i$ 为该行全部水头损失之和。"},
            {"title": "2. 该行各项水头损失",
             "values": f"沿程水头损失  $h_f = {hf:.4f}$ m\n局部水头损失  $h_j = {hj:.4f}$ m\n"
                       f"弯道水头损失  $h_w = {hw:.4f}$ m\n渐变段损失  $h_{{tr}} = {h_tr:.4f}$ m\n"
                       f"预留水头损失  $h_{{res}} = {h_res:.4f}$ m\n过闸水头损失  $h_{{gate}} = {h_gate:.4f}$ m\n"
                       f"倒虹吸/有压管道水头损失  $h_{{sip}} = {h_sip:.4f}$ m\n"
                       f"───────────────────────\n该行水位降落  $\\Delta h_i = {delta:.4f}$ m"},
            {"title": "3. 代入公式计算", "values": f"$Z_i = {prev:.4f} - {delta:.4f} = {prev-delta:.4f}$ m"},
            {"title": "4. 校验", "values": f"起始水位  $Z_{{start}} = {start_level:.4f}$ m\n累计总水头损失 $= {cumulative:.4f}$ m\n"
                                            f"$Z_{{start}}$ - 累计 $= {start_level - cumulative:.4f}$ m"},
            {"title": "5. 计算结果", "formula": f"$Z_i = {wl:.4f} \\ m$"},
        ]
    FormulaDialog(parent, f"{node_name} - 水位计算详情", sections)


def show_bottom_elevation_dialog(parent, node_name: str, details: Dict[str, Any]):
    """渠底高程计算详情"""
    wl = details.get('water_level', 0.0)
    wd = details.get('water_depth', 0.0)
    be = details.get('bottom_elevation', 0.0)
    sections = [
        {"title": "1. 渠底高程计算公式", "formula": r"$Z_b = Z - h$", "content": "其中: $Z$=水位, $h$=水深"},
        {"title": "2. 计算参数", "values": f"水位  $Z = {wl:.4f}$ m\n水深  $h = {wd:.4f}$ m"},
        {"title": "3. 代入公式计算", "values": f"$Z_b = {wl:.4f} - {wd:.4f} = {be:.4f}$ m"},
        {"title": "4. 计算结果", "formula": f"$Z_b = {be:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 渠底高程计算详情", sections)


def show_siphon_outlet_elevation_dialog(parent, node_name: str, details: Dict[str, Any]):
    """倒虹吸出口渠底高程计算详情（公式10.3.6）"""
    H_u = details.get('H_u', 0.0); h_u = details.get('h_u', 0.0)
    h_d = details.get('h_d', 0.0); delta_Z = details.get('delta_Z', 0.0)
    H_d = details.get('H_d', 0.0)
    upstream_wl = details.get('upstream_wl', 0.0)
    downstream_wl = details.get('downstream_wl', 0.0)
    up_name = details.get('upstream_name', '上游渠道')
    dn_name = details.get('downstream_name', '下游渠道')
    sections = [
        {"title": "1. 出口渐变段末端渠底高程公式（规范 10.3.6）",
         "formula": r"$H_d = H_u + h_u - h_d - \Delta Z$",
         "content": "$H_d$=下游底高程, $H_u$=上游底高程, $h_u$=上游水深, $h_d$=下游水深, $\\Delta Z$=水面落差"},
        {"title": "2. 计算参数",
         "values": f"上游（{up_name}）底高程  $H_u = {H_u:.4f}$ m\n上游水深  $h_u = {h_u:.4f}$ m\n下游（{dn_name}）水深  $h_d = {h_d:.4f}$ m"},
        {"title": "3. ΔZ 上下游水面总落差",
         "values": f"上游水位  $Z_u = {upstream_wl:.4f}$ m\n下游水位  $Z_d = {downstream_wl:.4f}$ m\n"
                   f"$\\Delta Z = {upstream_wl:.4f} - {downstream_wl:.4f} = {delta_Z:.4f}$ m"},
        {"title": "4. 代入公式计算",
         "values": f"$H_d = {H_u:.4f} + {h_u:.4f} - {h_d:.4f} - {delta_Z:.4f} = {H_d:.4f}$ m"},
        {"title": "5. 计算结果", "formula": f"$H_d = {H_d:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 渠底高程计算详情（公式10.3.6）", sections)


def show_top_elevation_dialog(parent, node_name: str, details: Dict[str, Any]):
    """渠顶高程计算详情"""
    be = details.get('bottom_elevation', 0.0)
    sh = details.get('structure_height', 0.0)
    te = details.get('top_elevation', 0.0)
    sections = [
        {"title": "1. 渠顶高程计算公式", "formula": r"$Z_t = Z_b + H$", "content": "其中: $Z_b$=渠底高程, $H$=结构高度"},
        {"title": "2. 计算参数", "values": f"渠底高程  $Z_b = {be:.4f}$ m\n结构高度  $H = {sh:.4f}$ m"},
        {"title": "3. 代入公式计算", "values": f"$Z_t = {be:.4f} + {sh:.4f} = {te:.4f}$ m"},
        {"title": "4. 计算结果", "formula": f"$Z_t = {te:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 渠顶高程计算详情", sections)


def show_transition_length_dialog(parent, node_name: str, details: Dict[str, Any]):
    """渐变段长度计算详情"""
    transition_type = details.get('transition_type', '')
    struct_name = details.get('struct_name', '')
    B1 = details.get('B1', 0)
    B2 = details.get('B2', 0)
    coefficient = details.get('coefficient', 2.5)
    L_basic = details.get('L_basic', 0)
    channel_depth = details.get('channel_depth', 0)
    L_result = details.get('L_result', 0)
    constraint_applied = details.get('constraint_applied', '')
    prev_name = details.get('prev_name', '')
    next_name = details.get('next_name', '')

    # 基本公式说明
    if transition_type == "进口":
        formula_str = r"$L = 2.5 \times |B_1 - B_2|$"
        coeff_note = "进口系数 = 2.5"
    else:
        formula_str = r"$L = 3.5 \times |B_1 - B_2|$"
        coeff_note = "出口系数 = 3.5"

    sections = [
        {"title": "1. 渐变段长度基本公式",
         "formula": formula_str,
         "content": f"其中: $B_1$=起始端水面宽度, $B_2$=末端水面宽度\n{coeff_note}"},
        {"title": "2. 基本参数",
         "values": f"渐变段类型:  {transition_type}渐变段\n"
                   f"关联建筑物:  {struct_name}\n"
                   f"起始端（{prev_name}）水面宽度  $B_1 = {B1:.3f}$ m\n"
                   f"末端（{next_name}）水面宽度  $B_2 = {B2:.3f}$ m"},
        {"title": "3. 基本公式计算",
         "values": f"$L_{{basic}} = {coefficient} \\times |{B1:.3f} - {B2:.3f}|$\n"
                   f"    $= {coefficient} \\times {abs(B1 - B2):.3f}$\n"
                   f"    $= {L_basic:.3f}$ m"},
    ]

    # 约束条件说明
    if constraint_applied:
        constraint_desc = details.get('constraint_desc', '')
        depth_multiplier = details.get('depth_multiplier', 0)
        L_depth = details.get('L_depth', 0)

        constraint_vals = f"渠道设计水深  $h = {channel_depth:.3f}$ m\n"

        if "隧洞" in constraint_applied:
            tunnel_multiplier = details.get('tunnel_multiplier', 3)
            tunnel_size = details.get('tunnel_size', 0)
            L_tunnel = details.get('L_tunnel', 0)
            constraint_vals += (
                f"{depth_multiplier}倍水深约束  $L_{{depth}} = {depth_multiplier} \\times {channel_depth:.3f} = {L_depth:.3f}$ m\n"
                f"洞径/洞宽  $D = {tunnel_size:.3f}$ m\n"
                f"{tunnel_multiplier}倍洞径约束  $L_{{tunnel}} = {tunnel_multiplier} \\times {tunnel_size:.3f} = {L_tunnel:.3f}$ m\n"
                f"───────────────────────\n"
                f"取大值:  $L = max({L_basic:.3f},\\; {L_depth:.3f},\\; {L_tunnel:.3f}) = {L_result:.3f}$ m"
            )
        elif "渡槽" in constraint_applied:
            constraint_vals += (
                f"{depth_multiplier}倍水深约束  $L_{{depth}} = {depth_multiplier} \\times {channel_depth:.3f} = {L_depth:.3f}$ m\n"
                f"───────────────────────\n"
                f"取大值:  $L = max({L_basic:.3f},\\; {L_depth:.3f}) = {L_result:.3f}$ m"
            )
        elif "倒虹吸" in constraint_applied:
            constraint_vals += (
                f"{depth_multiplier}倍水深约束  $L_{{depth}} = {depth_multiplier} \\times {channel_depth:.3f} = {L_depth:.3f}$ m\n"
                f"───────────────────────\n"
                f"取大值:  $L = max({L_basic:.3f},\\; {L_depth:.3f}) = {L_result:.3f}$ m"
            )

        sections.append(
            {"title": f"4. 规范约束条件（{constraint_desc}）",
             "values": constraint_vals}
        )
        sections.append(
            {"title": "5. 计算结果（取大值）",
             "formula": f"$L = {L_result:.3f} \\ m$"}
        )
    else:
        sections.append(
            {"title": "4. 计算结果",
             "formula": f"$L = {L_result:.3f} \\ m$",
             "content": "无规范约束条件生效，直接采用基本公式计算值。"}
        )

    FormulaDialog(parent, f"{node_name} - 渐变段长度计算详情", sections)


def show_cumulative_loss_dialog(parent, node_name: str, details: Dict[str, Any]):
    """累计总水头损失计算详情"""
    cumulative = details.get('cumulative', 0.0)
    rows_text = details.get('rows_text', '')
    sections = [
        {"title": "1. 累计总水头损失公式", "formula": r"$h_{cum,i} = \sum_{k=1}^{i} h_k$",
         "content": "普通行取总水头损失，渐变段行取渐变段水头损失。"},
        {"title": "2. 逐行累加明细", "values": rows_text},
        {"title": "3. 计算结果", "formula": f"$h_{{cum,i}} = {cumulative:.4f} \\ m$"},
    ]
    FormulaDialog(parent, f"{node_name} - 累计总水头损失计算详情", sections)


# ================================================================
# FormulaTooltipWidget — Fluent Design 悬浮公式卡片
# ================================================================

class FormulaTooltipWidget(QWidget):
    """Fluent Design 风格的公式悬浮提示卡片。

    鼠标悬停表头列时弹出，显示：
      - 蓝色渐变标题栏（标题 + 说明）
      - LaTeX 公式（matplotlib SVG 矢量渲染）
      - 灰色注释区（含左侧蓝色边线）

    公式使用 render_latex_svg 渲染为 SVG，再通过 QSvgRenderer 转为 QPixmap 显示。
    """

    _SHADOW_MARGIN = 10
    _CARD_RADIUS = 12
    _MIN_CARD_WIDTH = 360
    _MAX_CARD_WIDTH = 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._current_col = None
        self._pending_col = None
        self._pending_pos = None
        self._pixmap_cache: Dict[str, QPixmap] = {}

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(200)
        self._hide_timer.timeout.connect(self._do_hide)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(300)
        self._show_timer.timeout.connect(self._do_show)

        self._setup_ui()

    # ---- UI 构建 ----

    def _setup_ui(self):
        m = self._SHADOW_MARGIN
        root = QVBoxLayout(self)
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(0)

        self._card = QWidget()
        self._card.setMinimumWidth(self._MIN_CARD_WIDTH)
        self._card.setMaximumWidth(self._MAX_CARD_WIDTH)
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        # --- 标题区 ---
        self._header_widget = QWidget()
        h_lay = QVBoxLayout(self._header_widget)
        h_lay.setContentsMargins(18, 14, 18, 14)
        h_lay.setSpacing(4)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            "color:#fff; font-size:15px; font-weight:bold; background:transparent;")
        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(
            "color:rgba(255,255,255,0.85); font-size:12px; background:transparent;")
        h_lay.addWidget(self._title_label)
        h_lay.addWidget(self._desc_label)
        card_lay.addWidget(self._header_widget)

        # --- 公式 + 注释 ---
        body = QWidget()
        b_lay = QVBoxLayout(body)
        b_lay.setContentsMargins(18, 14, 18, 14)
        b_lay.setSpacing(12)

        # 公式区域
        self._formula_frame = QFrame()
        self._formula_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #F8F9FE, stop:1 #F0F4FF);
                border: 1px solid #E3ECF9;
                border-radius: 8px;
            }
        """)
        f_lay = QVBoxLayout(self._formula_frame)
        f_lay.setContentsMargins(14, 14, 14, 14)
        f_lay.setAlignment(Qt.AlignCenter)

        self._formula_label = QLabel()
        self._formula_label.setAlignment(Qt.AlignCenter)
        self._formula_label.setStyleSheet("background:transparent; border:none;")
        f_lay.addWidget(self._formula_label)
        b_lay.addWidget(self._formula_frame)

        # 注释区域
        self._note_label = QLabel()
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet("""
            QLabel {
                font-size: 12px; color: #424242;
                background: #FAFAFA; border-radius: 6px;
                border-left: 3px solid #1976D2;
                padding: 8px 12px;
            }
        """)
        b_lay.addWidget(self._note_label)

        card_lay.addWidget(body)
        root.addWidget(self._card)

    # ---- 自定义绘制（圆角卡片 + 蓝色标题 + 阴影） ----

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        m = self._SHADOW_MARGIN
        r = self._CARD_RADIUS
        card_rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

        # 阴影（从外到内逐层绘制半透明圆角矩形）
        for i in range(m, 0, -1):
            alpha = int(25 * ((1 - i / m) ** 2))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            expand = m - i
            p.drawRoundedRect(
                card_rect.adjusted(-expand, -expand + 2, expand, expand + 2),
                r + expand, r + expand)

        # 剪裁为卡片圆角区域
        clip = QPainterPath()
        clip.addRoundedRect(card_rect, r, r)
        p.setClipPath(clip)

        # 白色背景
        p.fillRect(card_rect, QColor("#FFFFFF"))

        # 蓝色渐变标题栏
        header_h = self._header_widget.height()
        header_rect = QRectF(card_rect.x(), card_rect.y(),
                             card_rect.width(), header_h)
        grad = QLinearGradient(header_rect.topLeft(), header_rect.topRight())
        grad.setColorAt(0, QColor("#1565C0"))
        grad.setColorAt(1, QColor("#1E88E5"))
        p.fillRect(header_rect, grad)

        # 1px 卡片边框
        p.setClipping(False)
        p.setPen(QPen(QColor("#E0E0E0"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card_rect, r, r)

        p.end()

    # ---- 公式 SVG → QPixmap ----

    @staticmethod
    def _fix_svg_pt_units(svg_str: str) -> str:
        """将 SVG 的 width/height 从 pt 转换为 px（×4/3）。

        matplotlib 输出 SVG 使用 pt 单位，但 QSvgRenderer 把 pt 数值
        当 px 解释，导致 defaultSize() 偏小约 25%、公式右侧被截断。
        """
        def _pt_to_px(m):
            attr = m.group(1)          # 'width' or 'height'
            val = float(m.group(2))    # 数值
            px = val * 4.0 / 3.0       # 1pt = 4/3 px @96dpi
            return f'{attr}="{px:.2f}"'
        return re.sub(r'(width|height)="([\d.]+)pt"', _pt_to_px, svg_str, count=2)

    def _render_formula_pixmap(self, latex_str: str):
        """将 LaTeX 渲染为 QPixmap（缓存结果）。

        使用 matplotlib Agg 后端直接渲染 PNG，再加载为 QPixmap。
        完全绕过 SVG → QSvgRenderer 路径中无法修复的 pt/px 单位混淆
        （QSvgRenderer.render() 始终按 SVG width/height 的 pt 数值当 px
        确定渲染区域，导致公式右侧被截断约 25%）。
        """
        if latex_str in self._pixmap_cache:
            return self._pixmap_cache[latex_str]

        try:
            import io as _io
            import matplotlib
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg as _FC
        except ImportError:
            self._pixmap_cache[latex_str] = None
            return None

        try:
            dpr = self.devicePixelRatioF()
            render_scale = max(dpr, 2.0)          # 至少 2× 确保清晰
            render_dpi = int(100 * render_scale)

            # 不使用 _MATH_RC（CJK 字体配置）！
            # Microsoft YaHei 缺少正确的数学符号度量，导致
            # get_window_extent() 返回极小的 bbox（如 14px），
            # bbox_inches='tight' 据此裁剪后公式被严重截断。
            # 悬浮公式均为纯 ASCII 数学，使用默认 CM 字体即可。
            with matplotlib.rc_context({'svg.fonttype': 'path'}):
                fig = Figure(dpi=100)
                _FC(fig)                           # 绑定 Agg canvas
                fig.patch.set_alpha(0.0)

                fig.text(0.5, 0.5, '$' + latex_str + '$',
                         fontsize=16, va='center', ha='center',
                         color='#1a1a1a')

                buf = _io.BytesIO()
                fig.savefig(buf, format='png', transparent=True,
                            bbox_inches='tight', pad_inches=0.05,
                            dpi=render_dpi)

                import matplotlib.pyplot as plt
                plt.close(fig)

            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            pixmap.setDevicePixelRatio(render_scale)

            # 超过最大卡片内容宽度时等比缩放
            max_w = self._MAX_CARD_WIDTH - 80
            logical_w = pixmap.width() / render_scale
            if logical_w > max_w:
                new_w = int(max_w * render_scale)
                pixmap = pixmap.scaledToWidth(new_w, Qt.SmoothTransformation)
                pixmap.setDevicePixelRatio(render_scale)

            self._pixmap_cache[latex_str] = pixmap
            return pixmap
        except Exception:
            self._pixmap_cache[latex_str] = None
            return None

    # ---- 显示 / 隐藏 ----

    def show_for_column(self, col_name: str, global_pos: QPoint):
        """为指定列显示悬浮公式卡片（带 500ms 延迟）。"""
        if col_name == self._current_col and self.isVisible():
            self._hide_timer.stop()
            return

        info = COLUMN_FORMULAS.get(col_name)
        if not info:
            return

        self._hide_timer.stop()

        # 如果目标列未变且定时器已在运行，仅更新坐标
        if col_name == self._pending_col and self._show_timer.isActive():
            self._pending_pos = global_pos
            return

        # 记录待显示信息，启动延迟定时器
        self._pending_col = col_name
        self._pending_pos = global_pos
        self._show_timer.start()
        return

    def _do_show(self):
        """延迟到期后真正显示悬浮卡片。"""
        col_name = self._pending_col
        global_pos = self._pending_pos
        if not col_name or not global_pos:
            return

        info = COLUMN_FORMULAS.get(col_name)
        if not info:
            return

        self._current_col = col_name

        # 更新内容
        self._title_label.setText(info['title'])
        self._desc_label.setText(info['description'])

        latex = info.get('latex', '')
        pixmap = self._render_formula_pixmap(latex) if latex else None
        if pixmap:
            self._formula_label.setPixmap(pixmap)
            self._formula_label.setText('')
            # 显式设置 label 最小宽度，确保 adjustSize 能正确扩展卡片
            dpr = pixmap.devicePixelRatio() or 1.0
            fw = int(pixmap.width() / dpr)
            self._formula_label.setMinimumWidth(fw)
            # 卡片宽度 = 公式宽度 + body 边距(18×2) + frame 边距(14×2) + border(2)
            needed = fw + 66
            needed = max(needed, self._MIN_CARD_WIDTH)
            needed = min(needed, self._MAX_CARD_WIDTH)
            self._card.setMinimumWidth(needed)
        else:
            self._formula_label.setPixmap(QPixmap())
            self._formula_label.setText(info.get('formula', ''))
            self._formula_label.setFont(QFont("Cambria Math", 14))
            self._formula_label.setMinimumWidth(0)
            self._card.setMinimumWidth(self._MIN_CARD_WIDTH)

        note_text = info.get('note', '').replace('\n', '\n')
        self._note_label.setText(note_text)
        self._note_label.setVisible(bool(note_text))

        # 调整尺寸 & 定位
        self.adjustSize()
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() + 4

        screen = self.screen()
        if screen:
            sr = screen.availableGeometry()
            if x + self.width() > sr.right():
                x = sr.right() - self.width()
            if x < sr.left():
                x = sr.left()
            if y + self.height() > sr.bottom():
                y = global_pos.y() - self.height() - 4

        self.move(x, y)
        self.show()

    def schedule_hide(self):
        """延迟隐藏（给用户移入 tooltip 的时间）。"""
        self._show_timer.stop()
        self._pending_col = None
        self._pending_pos = None
        self._hide_timer.start()

    def _do_hide(self):
        self._current_col = None
        self.hide()

    def enterEvent(self, event):
        self._hide_timer.stop()

    def leaveEvent(self, event):
        self.schedule_hide()
