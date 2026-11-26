"""Run the quantity workbench without starting the hydraulic or Rhino app."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    from app_渠系计算前端.runtime_platform import ensure_safe_windows_platform_queries
    ensure_safe_windows_platform_queries()
    parser = argparse.ArgumentParser(description="独立挖填算量")
    parser.add_argument("--terrain", help="已有 Rhino 地形 3DM 或网格文件")
    parser.add_argument("--mesh-index", type=int, help="多网格 3DM 中的地形网格序号，从 0 开始")
    parser.add_argument("--project", help="打开已保存的独立工程")
    parser.add_argument("--request", help="输入快照 JSON（后台计算）")
    parser.add_argument("--output", help="后台计算成果 XLSX/CSV/DXF/JSON")
    arguments = parser.parse_args(argv)
    if arguments.request:
        if not arguments.terrain or not arguments.output:
            parser.error("后台计算需要 --terrain 和 --output")
        from .io.independent_terrain import load_terrain
        from .services.independent_project import calculate_request
        from .io.independent_exporter import export_result
        request = json.loads(Path(arguments.request).read_text(encoding="utf-8-sig"))
        _, payload = calculate_request(load_terrain(arguments.terrain, mesh_index=arguments.mesh_index), request)
        export_result(payload, arguments.output)
        print(json.dumps(payload["quantities"], ensure_ascii=False))
        return 0
    from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
    from app_渠系计算前端.earthwork.independent_panel import IndependentEarthworkPanel
    from app_渠系计算前端.styles import COMBO_BOX_POPUP_STYLE
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("独立挖填算量")
    app.setStyleSheet(app.styleSheet() + COMBO_BOX_POPUP_STYLE)
    panel = IndependentEarthworkPanel()
    from app_渠系计算前端.earthwork.network_panel import NetworkEarthworkPanel
    network_panel = NetworkEarthworkPanel()
    window = QMainWindow()
    window.setWindowTitle("独立挖填算量 · Rhino 地形网格")
    window.resize(1280, 940)
    tabs = QTabWidget()
    tabs.addTab(panel, "直段与基坑")
    tabs.addTab(network_panel, "全线与多结构")
    window.setCentralWidget(tabs)
    app.aboutToQuit.connect(panel.shutdown)
    app.aboutToQuit.connect(network_panel.shutdown)
    window.show()
    if arguments.project:
        panel.from_project_dict(json.loads(Path(arguments.project).read_text(encoding="utf-8-sig")))
    if arguments.terrain:
        panel.load_terrain(arguments.terrain, mesh_index=arguments.mesh_index)
    result = app.exec()
    panel.runner.invalidate()
    panel.runner.wait(10000)
    network_panel.runner.invalidate()
    network_panel.runner.wait(10000)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
