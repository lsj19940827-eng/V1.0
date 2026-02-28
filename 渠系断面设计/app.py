# -*- coding: utf-8 -*-
"""
渠系建筑物水力计算系统 —— 主入口

侧边导航 + 面板切换框架
支持模块：明渠设计、渡槽设计、隧洞设计、矩形暗涵设计、倒虹吸设计、有压管道设计、批量计算、推求水面线
"""

import sys
import os

# 确保项目根目录在搜索路径中
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# ---- 高DPI环境变量（必须在 QApplication 之前设置） ----
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QStackedWidget, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter

from qfluentwidgets import (
    PushButton, InfoBar, InfoBarPosition, setTheme, Theme
)

from version import APP_VERSION
from 渠系断面设计.styles import (
    P, S, W, E, BG, CARD, BD, T1, T2, GLOBAL_STYLE, NAV_STYLE
)
from 渠系断面设计.report_meta import ProjectSettingsDialog
from 渠系断面设计.open_channel.panel import OpenChannelPanel
from 渠系断面设计.aqueduct.panel import AqueductPanel
from 渠系断面设计.tunnel.panel import TunnelPanel
from 渠系断面设计.culvert.panel import CulvertPanel
from 渠系断面设计.batch.panel import BatchPanel
from 渠系断面设计.siphon.panel import SiphonPanel
from 渠系断面设计.water_profile.panel import WaterProfilePanel
from 渠系断面设计.pressure_pipe.panel import PressurePipePanel
_EARTHWORK_AVAILABLE = False


# ============================================================
# 导航按钮
# ============================================================
def _get_dpi_scale() -> float:
    """获取当前主屏幕的 DPI 缩放因子（1.0 = 100%，1.5 = 150%，2.0 = 200%）

    Qt 6 默认开启高DPI缩放，logicalDotsPerInch() 始终返回 96，
    因此使用 devicePixelRatio() 获取实际缩放比。
    """
    app = QApplication.instance()
    if app:
        screen = app.primaryScreen()
        if screen:
            return screen.devicePixelRatio()
    return 1.0


class NavButton(PushButton):
    """侧边导航按钮（选中态高亮）"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self._selected = False
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {P}; color: white;
                    border: none; border-radius: 6px;
                    font-size: 13px; font-weight: bold;
                    text-align: left; padding: 0 16px;
                }}
                QPushButton:hover {{ background: #1565C0; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {T1};
                    border: none; border-radius: 6px;
                    font-size: 13px;
                    text-align: left; padding: 0 16px;
                }}
                QPushButton:hover {{ background: #E8EAF6; }}
            """)


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    """渠系建筑物水力计算系统 —— 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"渠系建筑物水力计算系统 V{APP_VERSION}")

        # ---- 根据屏幕分辨率自适应窗口尺寸 ----
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            sw, sh = avail.width(), avail.height()
            # 最小尺寸：不超过可用屏幕的 85%
            min_w = min(1200, int(sw * 0.85))
            min_h = min(800, int(sh * 0.85))
            # 初始尺寸：不超过可用屏幕的 92%
            init_w = min(1400, int(sw * 0.92))
            init_h = min(900, int(sh * 0.90))
        else:
            min_w, min_h = 1200, 800
            init_w, init_h = 1400, 900
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        # 图标路径
        _res_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
        self._ico_logo_path = os.path.join(_res_dir, "logo.ico")
        self._svg_logo_path = os.path.join(_res_dir, "logo.svg")
        self._app_icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "推求水面线", "resources", "app_icon.ico"
        )

        # 设置窗口图标（ICO多尺寸优先 → SVG → 旧ICO）
        _icon_src = (
            self._ico_logo_path if os.path.exists(self._ico_logo_path)
            else self._svg_logo_path if os.path.exists(self._svg_logo_path)
            else self._app_icon_path
        )
        if os.path.exists(_icon_src):
            self.setWindowIcon(QIcon(_icon_src))

        self._nav_buttons = []
        self._init_ui()

        # 默认选中第一个
        self._switch_to(0)
        self.statusBar().showMessage(f"就绪 | 渠系建筑物水力计算系统 V{APP_VERSION}")

        # ---- 启动时静默检查更新 ----
        self._start_silent_update_check()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QHBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ---- 左侧导航栏 ----
        nav_panel = QFrame()
        nav_panel.setObjectName("navPanel")
        nav_panel.setFixedWidth(180)
        nav_panel.setStyleSheet(NAV_STYLE)
        nav_lay = QVBoxLayout(nav_panel)
        nav_lay.setContentsMargins(10, 10, 10, 10)
        nav_lay.setSpacing(4)

        # 标题区域（Apple Pro 风格）
        brand_card = QFrame()
        brand_card.setObjectName("navBrandCard")
        brand_lay = QVBoxLayout(brand_card)
        brand_lay.setContentsMargins(12, 14, 12, 14)
        brand_lay.setSpacing(4)

        logo_lbl = QLabel()
        logo_lbl.setObjectName("navBrandLogo")
        logo_lbl.setFixedSize(48, 48)
        logo_lbl.setAlignment(Qt.AlignCenter)
        # 优先加载 SVG（矢量无损），回退到 ICO
        _logo_src = self._svg_logo_path if os.path.exists(self._svg_logo_path) else self._app_icon_path
        if os.path.exists(_logo_src):
            logo_pix = QIcon(_logo_src).pixmap(QSize(40, 40))
            logo_lbl.setPixmap(logo_pix)
        brand_lay.addWidget(logo_lbl, 0, Qt.AlignHCenter)

        title_lbl = QLabel("渠系建筑物")
        title_lbl.setObjectName("navTitle")
        brand_lay.addWidget(title_lbl)

        subtitle_lbl = QLabel("水力计算系统")
        subtitle_lbl.setObjectName("navSubtitle")
        brand_lay.addWidget(subtitle_lbl)

        ver_lbl = QLabel(f"V{APP_VERSION}")
        ver_lbl.setObjectName("navVersion")
        brand_lay.addWidget(ver_lbl, 0, Qt.AlignHCenter)

        nav_lay.addWidget(brand_card)
        nav_lay.addSpacing(8)

        # 分割线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{BD};")
        nav_lay.addWidget(sep)
        nav_lay.addSpacing(6)

        # 导航按钮
        modules = [
            ("明渠设计", "梯形/矩形/圆形明渠"),
            ("渡槽设计", "U形/矩形渡槽"),
            ("隧洞设计", "圆形/圆拱直墙/马蹄形"),
            ("矩形暗涵设计", "经济最优断面/指定参数"),
            ("倒虹吸设计", "倒虹吸管水力计算"),
            ("有压管道设计", "有压管道水力计算"),
            ("批量计算", "多流量段批量水力计算"),
            ("推求水面线", "水面线推求与纵剖面"),
        ]
        for idx, (name, desc) in enumerate(modules):
            btn = NavButton(name)
            btn.setToolTip(desc)
            btn.clicked.connect(lambda checked, i=idx: self._switch_to(i))
            nav_lay.addWidget(btn)
            self._nav_buttons.append(btn)

        nav_lay.addStretch()

        # 项目设置按钮
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{BD};")
        nav_lay.addWidget(sep2)
        nav_lay.addSpacing(4)
        btn_proj_settings = PushButton("⚙ 项目设置")
        btn_proj_settings.setToolTip("设置工程名称、人员、基本资料等计算书信息")
        btn_proj_settings.setFixedHeight(36)
        btn_proj_settings.clicked.connect(self._open_project_settings)
        btn_proj_settings.setStyleSheet(f"""
            QPushButton {{
                background: #E8F4FD; color: {P};
                border: 1px solid #B3D7F0; border-radius: 6px;
                font-size: 12px; font-weight: bold;
                text-align: center; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #CCE8FA; }}
        """)
        nav_lay.addWidget(btn_proj_settings)
        nav_lay.addSpacing(4)

        # 检查更新按钮
        btn_update = PushButton("\U0001F504 检查更新")
        btn_update.setToolTip("检查是否有新版本可用")
        btn_update.setFixedHeight(36)
        btn_update.clicked.connect(self._open_update_dialog)
        btn_update.setStyleSheet(f"""
            QPushButton {{
                background: #FFF3E0; color: #E65100;
                border: 1px solid #FFE0B2; border-radius: 6px;
                font-size: 12px; font-weight: bold;
                text-align: center; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #FFE0B2; }}
        """)
        nav_lay.addWidget(btn_update)
        nav_lay.addSpacing(4)

        # 版权信息
        author_lbl = QLabel("四川水发设计公司\n工程设计院\n© All Rights Reserved")
        author_lbl.setStyleSheet(f"font-size:11px;color:{T2};padding:6px 4px;")
        author_lbl.setAlignment(Qt.AlignCenter)
        nav_lay.addWidget(author_lbl)

        main_lay.addWidget(nav_panel)

        # ---- 右侧内容区 ----
        self.stack = QStackedWidget()
        main_lay.addWidget(self.stack, 1)

        # 注册模块面板
        self.open_channel_panel = OpenChannelPanel()
        self.aqueduct_panel = AqueductPanel()
        self.tunnel_panel = TunnelPanel()
        self.culvert_panel = CulvertPanel()
        self.siphon_panel = SiphonPanel()
        self.pressure_pipe_panel = PressurePipePanel()
        self.batch_panel = BatchPanel()
        self.water_profile_panel = WaterProfilePanel()
        self.stack.addWidget(self.open_channel_panel)
        self.stack.addWidget(self.aqueduct_panel)
        self.stack.addWidget(self.tunnel_panel)
        self.stack.addWidget(self.culvert_panel)
        self.stack.addWidget(self.siphon_panel)
        self.stack.addWidget(self.pressure_pipe_panel)
        self.stack.addWidget(self.batch_panel)
        self.stack.addWidget(self.water_profile_panel)
        if _EARTHWORK_AVAILABLE:
            self.earthwork_panel = EarthworkPanel()
            self.stack.addWidget(self.earthwork_panel)

        self.batch_panel.set_main_window(self)

    def _open_project_settings(self):
        dlg = ProjectSettingsDialog(self)
        dlg.exec()

    # ---- 更新相关 ----
    def _open_update_dialog(self):
        """打开更新对话框（手动检查）"""
        from 渠系断面设计.update_dialog import UpdateDialog
        dlg = UpdateDialog(self, auto_check=True)
        dlg.exec()

    def _start_silent_update_check(self):
        """启动时后台静默检查更新"""
        from 渠系断面设计.update_dialog import SilentUpdateChecker
        self._silent_checker = SilentUpdateChecker(self)
        self._silent_checker.update_available.connect(self._on_update_available)
        self._silent_checker.start()

    def _on_update_available(self, info):
        """静默检查发现新版本时，在状态栏/InfoBar 提示"""
        try:
            InfoBar.info(
                title=f"发现新版本 V{info.latest_version}",
                content="点击侧边栏「检查更新」按钮查看详情并下载。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=8000,
                parent=self,
            )
            self.statusBar().showMessage(
                f"✨ 新版本 V{info.latest_version} 可用！点击「检查更新」下载。"
            )
        except Exception:
            pass

    def closeEvent(self, event):
        """关闭窗口前先隐藏，避免 Matplotlib 画布销毁时反复重绘导致闪烁"""
        self.hide()
        try:
            import matplotlib.pyplot as plt
            plt.close('all')
        except Exception:
            pass
        super().closeEvent(event)

    def _switch_to(self, index: int):
        """切换到指定模块"""
        if index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_selected(i == index)
        names = ["明渠设计", "渡槽设计", "隧洞设计", "矩形暗涵设计", "倒虹吸设计", "有压管道设计", "批量计算", "推求水面线"]
        if index < len(names):
            self.statusBar().showMessage(f"当前模块: {names[index]}", 5000)


# ============================================================
# 入口
# ============================================================
def _setup_matplotlib_dpi():
    """配置 Matplotlib 全局 DPI 与中文字体，确保图表在高分屏下清晰"""
    try:
        import matplotlib
        matplotlib.use('QtAgg')
        import matplotlib.pyplot as plt

        scale = _get_dpi_scale()
        # 提高 Figure 默认 DPI，高分屏下图表更清晰
        fig_dpi = max(100, int(100 * scale))
        plt.rcParams['figure.dpi'] = fig_dpi
        plt.rcParams['savefig.dpi'] = 150  # 导出图片保持 150dpi

        # 字体大小随 DPI 微调
        base_font = max(10, int(10 * scale))
        plt.rcParams['font.size'] = base_font
        plt.rcParams['axes.titlesize'] = base_font + 2
        plt.rcParams['axes.labelsize'] = base_font
        plt.rcParams['xtick.labelsize'] = base_font - 1
        plt.rcParams['ytick.labelsize'] = base_font - 1
        plt.rcParams['legend.fontsize'] = base_font - 1

        # 中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
        plt.rcParams['axes.unicode_minus'] = False
    except Exception:
        pass


def main():
    # ---- 高DPI舍入策略（main.py 已提前调用；此处为直接运行 app.py 时的兜底）----
    # PassThrough: 保留精确缩放比（如1.25/1.5），Qt 6 默认值，
    # 支持非整数缩放比，确保 2K(125%)/4K(150%/200%) 正确渲染
    # 注意：若 QApplication 已存在（如首次激活弹窗后），此调用将被 Qt 静默忽略
    if not QApplication.instance():
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    # 基础字体：使用磅值（pt），天然 DPI 自适应
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(GLOBAL_STYLE)

    # Matplotlib 全局 DPI 适配
    _setup_matplotlib_dpi()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
