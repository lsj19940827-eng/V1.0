"""工程重开后详细过程和真实Word导出应属于已保存的计算结果。"""

import copy
import json
import os
import zipfile
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

import pytest
from PySide6.QtWidgets import QApplication

from app_渠系计算前端.water_profile import panel as panel_module
from app_渠系计算前端.batch.panel import BatchPanel
from 推求水面线.core.calculator import WaterProfileCalculator
from 推求水面线.models.data_models import ChannelNode
from 推求水面线.models.enums import StructureType


@pytest.fixture
def calculated_panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(BatchPanel, "_load_user_prefs", lambda self: None)
    for name in ("warning", "error", "info", "success"):
        monkeypatch.setattr(panel_module.InfoBar, name, lambda *args, **kwargs: None)
    panel = panel_module.WaterProfilePanel()
    panel.channel_name_edit.setText("飞龙报告复验")
    panel.start_wl_edit.setText("100")
    panel.design_flow_edit.setText("2")
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    nodes = []
    for index, structure in enumerate((StructureType.MINGQU_RECTANGULAR, StructureType.CHECK_GATE, StructureType.MINGQU_RECTANGULAR)):
        node = ChannelNode(name=("上游明渠", "双桥报告闸", "下游明渠")[index], structure_type=structure, flow_section="1", x=index * 100, flow=2)
        if index != 1:
            node.water_depth = 1.2
            node.structure_height = 2.5
            node.slope_i = 0.001
            node.section_params = {"B": 2, "h": 1.2, "H": 2.5}
        nodes.append(node)
    settings = panel._build_settings()
    calculator = WaterProfileCalculator(settings)
    nodes = calculator.calculate_all(nodes)
    panel.nodes = panel.calculated_nodes = nodes
    panel._settings = settings
    panel._update_table_from_nodes_full(nodes)
    panel._generate_detail_report(nodes, settings, calculator)
    yield panel
    panel.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("legacy", [False, True])
def test_reopened_report_and_word_keep_saved_nodes_without_hydraulic_recalculation(calculated_panel, monkeypatch, tmp_path, legacy):
    panel = calculated_panel
    original_text = panel.detail_text.toPlainText()
    saved = json.loads(json.dumps(panel.to_project_dict()))
    if legacy:
        saved.pop("detail_report_text")
    expected_nodes = copy.deepcopy(saved["calculated_nodes"])
    monkeypatch.setattr(WaterProfileCalculator, "calculate_all", lambda *args: pytest.fail("重开不得重新推求水面线"))
    panel.detail_text.setPlainText("其他工程的旧计算过程")
    panel.from_project_dict(saved, skip_dirty_signal=True)
    text = panel.detail_text.toPlainText()
    assert "总节点数: 3" in text
    assert "双桥报告闸" in text
    # 先计100米上游明渠沿程损失，再扣过闸损失；重开只恢复成果。
    assert "闸前水位 = 99.900 m" in text
    assert "闸后水位 = 99.800 m" in text
    assert "其他工程" not in text
    assert "使用说明" not in text
    if legacy:
        assert "报告恢复时间:" in text
    else:
        assert text == original_text
    assert [node.to_project_dict() for node in panel.calculated_nodes] == expected_nodes
    path = tmp_path / "重开计算书.docx"
    panel._build_word_report(str(path))
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        xml = archive.read("word/document.xml").decode("utf-8")
    # 真实导出把等式转为OMML，按段落可见文本核对，不能依赖XML连续字串。
    root = ElementTree.fromstring(xml)
    paragraphs = ["".join("".join(item.itertext()).split()) for item in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")]
    for expected in ("详细计算过程", "双桥报告闸", "闸前水位=99.900m", "闸后水位=99.800m"):
        assert any(expected in text for text in paragraphs)
    assert root.find(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath") is not None
    assert "其他工程" not in xml


def test_loading_project_without_results_clears_previous_report(calculated_panel):
    panel = calculated_panel
    panel.from_project_dict({}, skip_dirty_signal=True)
    assert not panel.calculated_nodes
    assert panel.detail_text.toPlainText() == ""
    assert panel.to_project_dict()["detail_report_text"] == ""
