"""首次导航不初始化隐藏公式卡片，真实悬停与页面销毁仍保持有效。"""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def test_first_navigation_defers_formula_tooltip_and_hover_reuses_it():
    """独立进程检验真正主窗口导航，避免前面测试预加载依赖掩盖问题。"""
    source = textwrap.dedent(r'''
        import importlib.abc
        import sys
        from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
        from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
        initialize_runtime_environment()
        ensure_qfluentwidgets_compat()
        app = ensure_application([])
        from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from app_渠系计算前端.app import MainWindow
        from app_渠系计算前端.startup_context import StartupContext

        class BlockUnusedFormulaImport(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'app_渠系计算前端.water_profile.formula_dialog':
                    raise AssertionError('首次导航不应加载未显示的公式卡片')

        blocker = BlockUnusedFormulaImport()
        sys.meta_path.insert(0, blocker)
        window = MainWindow(StartupContext('standard', None, False, False))
        window.project_manager._auto_save_timer.stop()
        window.show()
        QTest.qWait(20)
        QTest.mouseClick(window._nav_buttons[6], Qt.LeftButton)
        app.processEvents()
        panel = window._panel_registry.get_existing('water_profile')
        assert window.stack.currentWidget() is panel
        assert panel._formula_tooltip is None
        assert 'app_渠系计算前端.water_profile.formula_dialog' not in sys.modules
        header = panel._node_header
        # 没有提示对象时，离开表头也不能触发加载或访问空对象。
        QCoreApplication.sendEvent(header.viewport(), QEvent(QEvent.Leave))
        assert panel._formula_tooltip is None
        sys.meta_path.remove(blocker)
        panel._workspace_tabs.setCurrentWidget(panel._tab_water_profile)
        QTest.qWait(50)
        from app_渠系计算前端.water_profile.panel import NODE_ALL_HEADERS
        column = NODE_ALL_HEADERS.index('转角')
        panel.node_table.horizontalScrollBar().setValue(header.sectionPosition(column))
        app.processEvents()
        position = QPoint(header.sectionViewportPosition(column) + header.sectionSize(column)//2,
                          header.height()//2)
        assert header.logicalIndexAt(position) == column
        QCoreApplication.sendEvent(header.viewport(), QMouseEvent(
            QEvent.MouseMove, QPointF(position), QPointF(header.mapToGlobal(position)),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        app.processEvents()
        tooltip = panel._formula_tooltip
        assert tooltip is not None and tooltip.parent() is panel
        assert column in panel._formula_columns
        assert tooltip._pending_col == '转角'
        QTest.qWait(400)
        assert tooltip._current_col == '转角'
        assert tooltip.isVisible()
        assert tooltip._formula_label.pixmap() is not None
        assert not tooltip._formula_label.pixmap().isNull()
        assert panel._ensure_header_tooltip() is tooltip
        QCoreApplication.sendEvent(header.viewport(), QEvent(QEvent.Leave))
        QTest.qWait(250)
        assert not tooltip.isVisible()
        # 待显示计时器随页面销毁，不能遗留独立悬浮窗或回调异常。
        tooltip.show_for_column('转角', header.mapToGlobal(position))
        assert tooltip._show_timer.isActive()
        window.hide()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        import shiboken6
        assert not shiboken6.isValid(tooltip)
        QTest.qWait(400)
        print('LAZY_TOOLTIP_OK')
    ''')
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", CODEX_FORCE_QTEXTBROWSER="1",
                       PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", source], cwd=ROOT, env=environment,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LAZY_TOOLTIP_OK" in result.stdout
    assert "Traceback" not in result.stderr
