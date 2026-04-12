# -*- coding: utf-8 -*-
"""连续承压链提取回归测试。"""

import os
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode
from models.enums import InOutType, StructureType
from utils.pressure_pipe_extractor import PressurePipeDataExtractor


def _make_node(
    row_index,
    flow_section,
    name,
    structure,
    in_out=InOutType.NORMAL,
    flow=1.8,
    diameter=1.0,
):
    """构造最小测试节点。"""
    node = ChannelNode()
    node.flow_section = flow_section
    node.name = name
    node.structure_type = StructureType.from_string(structure)
    node.in_out = in_out
    node.flow = flow
    node.x = float(row_index * 10)
    node.y = 0.0
    node.section_params = {
        "D": diameter,
        "in_out_raw": in_out.value if hasattr(in_out, "value") else str(in_out),
    }
    node.pressure_pipe_row_identity = f"flow{flow_section}-row{row_index + 1}"
    return node


def _make_settings(channel_level="干管"):
    """构造 xx管 级别设置。"""
    return SimpleNamespace(channel_level=channel_level)


def test_extract_continuous_pressure_chains_keeps_named_group_and_single_rows_in_one_chain():
    nodes = [
        _make_node(0, "2", "半兽人", "定向钻", InOutType.INLET),
        _make_node(1, "2", "半兽人", "定向钻", InOutType.OUTLET),
        _make_node(2, "2", "", "有压管道", InOutType.NORMAL),
        _make_node(3, "2", "隧洞段", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(4, "2", "饿了么", "顶管", InOutType.INLET),
        _make_node(5, "2", "饿了么", "顶管", InOutType.OUTLET),
        _make_node(6, "2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1

    chain = chains[0]
    assert chain.flow_section == "2"
    assert chain.start_row_index == 0
    assert chain.end_row_index == 5
    assert [member.member_type for member in chain.members] == [
        "named_group",
        "single_row",
        "single_row",
        "named_group",
    ]
    assert [member.display_name for member in chain.members] == [
        "半兽人",
        "流量段2 第3行有压管道",
        "隧洞段",
        "饿了么",
    ]
    assert chain.members[1].row_indices == [2]
    assert chain.members[2].row_indices == [3]
    assert chain.members[1].should_generate_row_loss is True
    assert chain.members[2].should_generate_row_loss is True


def test_extract_pipes_splits_same_name_runs_into_separate_groups():
    nodes = [
        _make_node(0, "2", "穿路段", "有压管道", InOutType.INLET),
        _make_node(1, "2", "穿路段", "有压管道", InOutType.OUTLET),
        _make_node(2, "2", "穿路段", "定向钻", InOutType.INLET),
        _make_node(3, "2", "穿路段", "定向钻", InOutType.OUTLET),
        _make_node(4, "2", "穿路段", "有压管道", InOutType.INLET),
        _make_node(5, "2", "穿路段", "有压管道", InOutType.OUTLET),
    ]

    groups = PressurePipeDataExtractor.extract_pipes(nodes, settings=_make_settings())

    assert [group.row_indices for group in groups] == [[0, 1], [2, 3], [4, 5]]
    assert [group.legacy_storage_key for group in groups] == ["穿路段", "穿路段", "穿路段"]
    assert [group.legacy_identity for group in groups] == [
        "2::穿路段",
        "2::穿路段",
        "2::穿路段",
    ]
    assert [group.storage_key for group in groups] == [
        "2::穿路段::rows1-2",
        "2::穿路段::rows3-4",
        "2::穿路段::rows5-6",
    ]
    assert [group.identity for group in groups] == [
        "2::穿路段::rows1-2",
        "2::穿路段::rows3-4",
        "2::穿路段::rows5-6",
    ]


def test_extract_continuous_pressure_chains_keeps_same_name_runs_as_distinct_named_members():
    nodes = [
        _make_node(0, "2", "穿路段", "有压管道", InOutType.INLET),
        _make_node(1, "2", "穿路段", "有压管道", InOutType.OUTLET),
        _make_node(2, "2", "穿路段", "定向钻", InOutType.INLET),
        _make_node(3, "2", "穿路段", "定向钻", InOutType.OUTLET),
        _make_node(4, "2", "穿路段", "有压管道", InOutType.INLET),
        _make_node(5, "2", "穿路段", "有压管道", InOutType.OUTLET),
        _make_node(6, "2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1

    chain = chains[0]
    assert [member.member_type for member in chain.members] == [
        "named_group",
        "named_group",
        "named_group",
    ]
    assert [member.row_indices for member in chain.members] == [[0, 1], [2, 3], [4, 5]]
    assert [member.display_name for member in chain.members] == [
        "穿路段（前段）",
        "穿路段（中段1）",
        "穿路段（后段）",
    ]
    assert [member.storage_key for member in chain.members] == [
        "flow2-row1",
        "flow2-row3",
        "flow2-row5",
    ]
    assert [member.identity for member in chain.members] == [
        "flow2-row1",
        "flow2-row3",
        "flow2-row5",
    ]
    assert [member.group.legacy_identity for member in chain.members] == [
        "2::穿路段",
        "2::穿路段",
        "2::穿路段",
    ]


def test_extract_continuous_pressure_chains_splits_named_tail_group_into_row_members_for_xxqu():
    nodes = [
        _make_node(0, "2", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.27),
        _make_node(1, "2", "洞梁村", "有压管道", InOutType.INLET, flow=0.27),
        _make_node(2, "2", "洞梁村", "有压管道", InOutType.NORMAL, flow=0.27),
        _make_node(3, "2", "洞梁村", "有压管道", InOutType.OUTLET, flow=0.27),
        _make_node(4, "2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.27),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert chain.start_row_index == 1
    assert chain.end_row_index == 3
    assert [member.member_type for member in chain.members] == [
        "single_row",
        "single_row",
        "single_row",
    ]
    assert [member.identity for member in chain.members] == [
        "flow2-row2",
        "flow2-row3",
        "flow2-row4",
    ]
    assert [member.target_row_index for member in chain.members] == [1, 2, 3]
    assert [member.upstream_row_index for member in chain.members] == [0, 1, 2]
    assert [member.base_display_name for member in chain.members] == [
        "洞梁村",
        "洞梁村",
        "洞梁村",
    ]
    assert all(getattr(member.group, "group_mode", "") == "named_row_segment" for member in chain.members)
    assert all(bool(getattr(member, "split_from_named_group", False)) for member in chain.members)
    assert all(getattr(member.group, "design_flow", 0.0) == pytest.approx(0.27) for member in chain.members)
    assert all(getattr(member.group, "diameter", 0.0) == pytest.approx(1.0) for member in chain.members)


def test_extract_continuous_pressure_chains_for_branch_channel_marks_leading_named_pressure_as_prefix_segment():
    nodes = [
        _make_node(0, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(1, "1", "大石包", "定向钻", InOutType.INLET),
        _make_node(2, "1", "大石包", "定向钻", InOutType.OUTLET),
        _make_node(3, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(4, "1", "苟家湾", "有压管道", InOutType.OUTLET),
        _make_node(5, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert [member.display_name for member in chain.members] == [
        "苟家湾（前缀段）",
        "大石包",
        "苟家湾（后段）",
    ]
    assert chain.members[0].member_type == "named_group"
    assert chain.members[0].member_role == "prefix_segment"
    assert chain.members[0].is_anchor_member is False
    assert chain.members[0].should_generate_row_loss is True
    assert chain.members[0].prefix_target_row_index == 0
    assert chain.members[0].prefix_end_row_index == 1
    assert chain.members[1].is_anchor_member is False
    assert chain.members[2].is_anchor_member is False


def test_extract_continuous_pressure_chains_for_branch_channel_keeps_anchor_when_next_member_is_not_special():
    nodes = [
        _make_node(0, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(1, "1", "", "有压管道", InOutType.NORMAL),
        _make_node(2, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(3, "1", "苟家湾", "有压管道", InOutType.OUTLET),
        _make_node(4, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert [member.display_name for member in chain.members] == [
        "苟家湾（起点锚点）",
        "流量段1 第2行有压管道",
        "苟家湾（后段）",
    ]
    assert chain.members[0].member_role == "anchor"
    assert chain.members[0].is_anchor_member is True
    assert chain.members[0].should_generate_row_loss is False
    assert chain.members[0].prefix_target_row_index == -1
    assert chain.members[0].prefix_end_row_index == -1


def test_extract_continuous_pressure_chains_for_branch_channel_keeps_real_leading_named_segment_calculable():
    nodes = [
        _make_node(0, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(1, "1", "苟家湾", "有压管道", InOutType.OUTLET),
        _make_node(2, "1", "大石包", "定向钻", InOutType.INLET),
        _make_node(3, "1", "大石包", "定向钻", InOutType.OUTLET),
        _make_node(4, "1", "苟家湾", "有压管道", InOutType.INLET),
        _make_node(5, "1", "苟家湾", "有压管道", InOutType.OUTLET),
        _make_node(6, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert [member.display_name for member in chain.members] == [
        "苟家湾（前段）",
        "大石包",
        "苟家湾（后段）",
    ]
    assert chain.members[0].is_anchor_member is False
    assert chain.members[0].should_generate_row_loss is True


def test_extract_continuous_pressure_chains_for_branch_tail_named_pressure_group_splits_into_row_members():
    nodes = [
        _make_node(0, "1", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
        _make_node(1, "1", "洞梁村", "有压管道", InOutType.INLET),
        _make_node(2, "1", "洞梁村", "有压管道", InOutType.NORMAL),
        _make_node(3, "1", "洞梁村", "有压管道", InOutType.OUTLET),
        _make_node(4, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert [member.member_type for member in chain.members] == [
        "single_row",
        "single_row",
        "single_row",
    ]
    assert [member.display_name for member in chain.members] == [
        "洞梁村（前段）",
        "洞梁村（中段1）",
        "洞梁村（后段）",
    ]
    assert [member.row_indices for member in chain.members] == [[1], [2], [3]]
    assert [member.target_row_index for member in chain.members] == [1, 2, 3]
    assert [member.upstream_row_index for member in chain.members] == [0, 1, 2]
    assert [member.identity for member in chain.members] == [
        "flow1-row2",
        "flow1-row3",
        "flow1-row4",
    ]
    assert all(member.group is not None for member in chain.members)


@pytest.mark.parametrize(
    "channel_level",
    ["总干管", "分干管", "干管", "支管", "分支管"],
)
def test_extract_continuous_pressure_chains_for_all_xxpipe_levels_splits_continuous_named_pressure_members_into_row_members(channel_level):
    nodes = [
        _make_node(0, "1", "前置隧洞", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(1, "1", "九龙右有压管道", "有压管道", InOutType.INLET, flow=0.27),
        _make_node(2, "1", "九龙右有压管道", "有压管道", InOutType.OUTLET, flow=0.27),
        _make_node(3, "1", "穿路段", "定向钻", InOutType.INLET, flow=0.27),
        _make_node(4, "1", "穿路段", "定向钻", InOutType.OUTLET, flow=0.27),
        _make_node(5, "1", "穿涵段", "顶管", InOutType.INLET, flow=0.27),
        _make_node(6, "1", "穿涵段", "顶管", InOutType.OUTLET, flow=0.27),
        _make_node(7, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level=channel_level),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert chain.start_row_index == 0
    assert chain.end_row_index == 6
    assert [member.member_type for member in chain.members] == [
        "single_row",
        "single_row",
        "single_row",
        "single_row",
        "single_row",
        "single_row",
        "single_row",
    ]
    assert [member.display_name for member in chain.members] == [
        "前置隧洞（起点锚点）",
        "九龙右有压管道（前段）",
        "九龙右有压管道（后段）",
        "穿路段（前段）",
        "穿路段（后段）",
        "穿涵段（前段）",
        "穿涵段（后段）",
    ]
    assert [member.identity for member in chain.members] == [
        "flow1-row1-隧洞_圆形",
        "flow1-row2",
        "flow1-row3",
        "flow1-row4",
        "flow1-row5",
        "flow1-row6",
        "flow1-row7",
    ]
    assert [member.target_row_index for member in chain.members] == [0, 1, 2, 3, 4, 5, 6]
    assert [member.upstream_row_index for member in chain.members] == [-1, 0, 1, 2, 3, 4, 5]
    assert chain.members[0].member_type == "single_row"
    assert chain.members[0].is_anchor_member is True
    assert chain.members[0].should_generate_row_loss is False
    assert all(getattr(member.group, "group_mode", "") == "named_row_segment" for member in chain.members[1:])
    assert all(bool(getattr(member, "split_from_named_group", False)) for member in chain.members[1:])


@pytest.mark.parametrize(
    "channel_level",
    ["总干管", "分干管", "干管", "支管", "分支管"],
)
def test_extract_dialog_pipe_groups_marks_all_xxpipe_continuous_named_pressure_groups_as_split_parents(channel_level):
    nodes = [
        _make_node(0, "1", "前置隧洞", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(1, "1", "九龙右有压管道", "有压管道", InOutType.INLET, flow=0.27),
        _make_node(2, "1", "九龙右有压管道", "有压管道", InOutType.OUTLET, flow=0.27),
        _make_node(3, "1", "穿路段", "定向钻", InOutType.INLET, flow=0.27),
        _make_node(4, "1", "穿路段", "定向钻", InOutType.OUTLET, flow=0.27),
        _make_node(5, "1", "穿涵段", "顶管", InOutType.INLET, flow=0.27),
        _make_node(6, "1", "穿涵段", "顶管", InOutType.OUTLET, flow=0.27),
        _make_node(7, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        nodes,
        settings=_make_settings(channel_level=channel_level),
    )

    named_groups = [group for group in groups if getattr(group, "group_mode", "") == "named_group"]
    assert [group.identity for group in named_groups] == [
        "1::九龙右有压管道::rows2-3",
        "1::穿路段::rows4-5",
        "1::穿涵段::rows6-7",
    ]
    assert [group.split_to_row_members for group in named_groups] == [True, True, True]
    assert [group.split_row_member_identities for group in named_groups] == [
        ["flow1-row2", "flow1-row3"],
        ["flow1-row4", "flow1-row5"],
        ["flow1-row6", "flow1-row7"],
    ]


def test_extract_dialog_pipe_groups_marks_branch_tail_named_pressure_group_as_split_parent():
    nodes = [
        _make_node(0, "1", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
        *[
            _make_node(
                row_index,
                "1",
                "洞梁村",
                "有压管道",
                InOutType.INLET if row_index == 1 else (
                    InOutType.OUTLET if row_index == 17 else InOutType.NORMAL
                ),
                flow=0.27,
            )
            for row_index in range(1, 18)
        ],
        _make_node(18, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.identity == "1::洞梁村::rows2-18"
    assert group.split_to_row_members is True
    assert group.split_row_member_identities == [
        f"flow1-row{row_index}"
        for row_index in range(2, 19)
    ]


def test_extract_dialog_pipe_groups_marks_same_name_long_tail_parent_as_split_parent_after_prefix_rewrite():
    nodes = [
        _make_node(0, "1", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
        _make_node(1, "1", "洞梁村", "有压管道", InOutType.INLET, flow=0.27),
        _make_node(2, "1", "洞梁村", "有压管道", InOutType.OUTLET, flow=0.27),
        _make_node(3, "1", "穿路段", "定向钻", InOutType.INLET, flow=0.27),
        _make_node(4, "1", "穿路段", "定向钻", InOutType.OUTLET, flow=0.27),
        *[
            _make_node(
                row_index,
                "1",
                "洞梁村",
                "有压管道",
                InOutType.INLET if row_index == 5 else (
                    InOutType.OUTLET if row_index == 21 else InOutType.NORMAL
                ),
                flow=0.27,
            )
            for row_index in range(5, 22)
        ],
        _make_node(22, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(groups) == 3
    assert groups[0].identity == "flow1-row2"

    tail_group = groups[-1]
    assert tail_group.row_indices == list(range(5, 22))
    assert tail_group.identity == "1::洞梁村::rows6-22"
    assert tail_group.legacy_identity == "1::洞梁村"
    assert tail_group.split_to_row_members is True
    assert tail_group.split_row_member_identities == [
        f"flow1-row{row_index}"
        for row_index in range(6, 23)
    ]


def test_extract_continuous_pressure_chains_marks_flow_section_start_single_row_as_anchor():
    nodes = [
        _make_node(0, "1", "", "有压管道", InOutType.NORMAL),
        _make_node(1, "1", "隧洞段", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(2, "1", "隔断", "倒虹吸", InOutType.NORMAL, flow=0.0),
        _make_node(3, "2", "", "有压管道", InOutType.NORMAL),
        _make_node(4, "2", "下游隧洞", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 2

    first_anchor = chains[0].members[0]
    assert first_anchor.row_indices == [0]
    assert first_anchor.is_anchor_member is True
    assert first_anchor.should_generate_row_loss is False

    second_anchor = chains[1].members[0]
    assert second_anchor.row_indices == [3]
    assert second_anchor.is_anchor_member is True
    assert second_anchor.should_generate_row_loss is False

    assert chains[0].members[1].is_anchor_member is False
    assert chains[0].members[1].should_generate_row_loss is True


def test_extract_continuous_pressure_chains_merges_members_across_flow_sections_when_continuous():
    nodes = [
        _make_node(0, "2", "穿路段", "定向钻", InOutType.INLET),
        _make_node(1, "2", "穿路段", "定向钻", InOutType.OUTLET),
        _make_node(2, "3", "跨段洞身", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(3, "3", "", "有压管道", InOutType.NORMAL),
        _make_node(4, "3", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(),
    )

    assert len(chains) == 1

    chain = chains[0]
    assert chain.start_row_index == 0
    assert chain.end_row_index == 3
    assert [member.display_name for member in chain.members] == [
        "穿路段（前段）",
        "穿路段（后段）",
        "跨段洞身",
        "流量段3 第4行有压管道",
    ]
    assert [member.member_type for member in chain.members] == [
        "single_row",
        "single_row",
        "single_row",
        "single_row",
    ]
    assert [member.row_indices for member in chain.members] == [[0], [1], [2], [3]]
    assert [member.flow_section for member in chain.members] == ["2", "2", "3", "3"]


@pytest.mark.parametrize("breaker_structure", ["明渠-梯形", "分水闸", "倒虹吸", "矩形暗涵"])
def test_extract_continuous_pressure_chains_breaks_on_non_chain_structures(breaker_structure):
    nodes = [
        _make_node(0, "3", "", "有压管道", InOutType.NORMAL),
        _make_node(1, "3", "断开结构", breaker_structure, InOutType.NORMAL, flow=0.0),
        _make_node(2, "3", "后续隧洞", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(),
    )

    assert len(chains) == 2
    assert [chain.start_row_index for chain in chains] == [0, 2]
    assert [chain.end_row_index for chain in chains] == [0, 2]


def test_extract_continuous_pressure_chains_supports_continuous_xxqu_run():
    nodes = [
        _make_node(0, "4", "半兽人", "定向钻", InOutType.INLET),
        _make_node(1, "4", "半兽人", "定向钻", InOutType.OUTLET),
        _make_node(2, "4", "", "有压管道", InOutType.NORMAL),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    assert chains[0].flow_section == "4"
    assert [member.display_name for member in chains[0].members] == [
        "半兽人",
        "流量段4 第3行有压管道",
    ]


def test_extract_continuous_pressure_chains_for_branch_channel_skips_leading_tunnels():
    nodes = [
        _make_node(0, "6", "前置隧洞1", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(1, "6", "前置隧洞2", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(2, "6", "三清庙", "有压管道", InOutType.INLET),
        _make_node(3, "6", "三清庙", "有压管道", InOutType.OUTLET),
        _make_node(4, "6", "后续洞身", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        _make_node(5, "6", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert len(chains) == 1
    chain = chains[0]
    assert chain.start_row_index == 2
    assert chain.end_row_index == 4
    assert [member.display_name for member in chain.members] == [
        "三清庙",
        "后续洞身",
    ]


def test_extract_continuous_pressure_chains_skips_noncontinuous_xxqu_group():
    nodes = [
        _make_node(0, "5", "单独管段", "定向钻", InOutType.INLET),
        _make_node(1, "5", "单独管段", "定向钻", InOutType.OUTLET),
        _make_node(2, "5", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=0.0),
    ]

    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
        nodes,
        settings=_make_settings(channel_level="支渠"),
    )

    assert chains == []
