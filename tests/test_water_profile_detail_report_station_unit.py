"""详细报告区分补段落位与关联IP，且不修改原始计算结果。"""

import copy
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

import pytest

from app_渠系计算前端.water_profile.panel import WaterProfilePanel
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType


def _generate_report(nodes):
    captured = []
    panel = SimpleNamespace(
        detail_text=SimpleNamespace(setPlainText=captured.append),
        _describe_turn_radius_entry_usage=lambda _settings: "按各行值",
        _build_terminal_gate_backfill_report_lines=lambda _nodes: [],
    )
    settings = ProjectSettings(channel_name="飞龙", channel_level="分干渠")
    before = copy.deepcopy([node.to_dict() for node in nodes])
    WaterProfilePanel._generate_detail_report(panel, nodes, settings)
    assert [node.to_dict() for node in nodes] == before
    return captured[0], settings.get_station_prefix()


def _station_lines(node_block):
    return [line.strip() for line in node_block.splitlines() if "桩号:" in line]


def test_detail_report_locates_real_connection_separately_from_original_ip():
    # 飞龙真实全流程的两个桩号不同，不能把关联原IP误作补段落位。
    original = ChannelNode(
        name="花朝门", structure_type=StructureType.TUNNEL_ARCH,
        station_ip=2687.8701649798395, station_MC=2687.867,
    )
    connection = ChannelNode(
        name="-", structure_type=StructureType.MINGQU_RECTANGULAR,
        is_auto_inserted_channel=True,
        station_ip=2687.8701649798395, station_MC=2693.6728479675817,
        water_level=358.192342, head_loss_total=0.000219,
    )
    transition = ChannelNode(
        name="-", is_transition=True,
        station_ip=2687.8701649798395, station_MC=2687.867,
    )
    text, prefix = _generate_report([original, connection, transition])
    blocks = text.split("--- 节点 ")[1:]
    assert _station_lines(blocks[0]) == [f"桩号: {prefix}2+687.870"]
    assert _station_lines(blocks[1]) == [
        f"中心桩号: {prefix}2+693.673", f"关联IP桩号: {prefix}2+687.870",
    ]
    assert _station_lines(blocks[2]) == [f"关联IP桩号: {prefix}2+687.870"]
    assert "水位 Z = 358.192 m" in blocks[1]
    assert "总损失 = 0.0002 m" in blocks[1]


@pytest.mark.parametrize("center, expected", [(0.0, "0+000.000"), (999.9996, "1+000.000")])
def test_detail_report_keeps_valid_zero_and_millimetre_rollover_for_connection(center, expected):
    connection = ChannelNode(
        name="-", structure_type=StructureType.MINGQU_RECTANGULAR,
        is_auto_inserted_channel=True, station_ip=0.0, station_MC=center,
    )
    text, prefix = _generate_report([connection])
    assert f"中心桩号: {prefix}{expected}" in text
    assert f"关联IP桩号: {prefix}0+000.000" in text


def test_detail_report_does_not_invent_location_when_connection_center_is_missing():
    connection = ChannelNode(
        name="-", structure_type=StructureType.MINGQU_RECTANGULAR,
        is_auto_inserted_channel=True, station_ip=123.456, station_MC=None,
    )
    text, prefix = _generate_report([connection])
    block = text.split("--- 节点 ", 1)[1]
    assert _station_lines(block) == [f"关联IP桩号: {prefix}0+123.456"]
