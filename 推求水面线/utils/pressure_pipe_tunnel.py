"""连续管线夹带隧洞时的隐式洞口边界识别。"""

import copy


def structure_text(node):
    value = getattr(node, "structure_type", "")
    return str(getattr(value, "value", value) or "")


def iter_internal_tunnel_boundaries(nodes):
    """返回被同一流量段管道包围的隧洞块，不跨越明渠、闸或插入段。"""
    nodes = list(nodes or [])
    idx = 0
    pipe_types = {"有压管道", "定向钻", "顶管"}
    while idx < len(nodes):
        if "隧洞" not in structure_text(nodes[idx]):
            idx += 1
            continue
        start = idx
        while idx + 1 < len(nodes) and "隧洞" in structure_text(nodes[idx + 1]):
            idx += 1
        end = idx
        idx += 1
        if start == 0 or end + 1 >= len(nodes) or start == end:
            continue
        block = nodes[start - 1:end + 2]
        if any(getattr(n, "is_transition", False) or getattr(n, "is_auto_inserted_channel", False) for n in block):
            continue
        if structure_text(block[0]) not in pipe_types or structure_text(block[-1]) not in pipe_types:
            continue
        # 命名建筑物已有明确进出口，不能隐式延伸其边界。
        if str(getattr(block[0], "name", "") or "").strip() and str(getattr(block[-1], "name", "") or "").strip():
            continue
        sections = {str(getattr(n, "flow_section", "") or "").strip() for n in block}
        sections.discard("")
        if len(sections) > 1:
            continue
        yield start, end, start - 1, end + 1


def make_pipe_portal_node(pipe_node, portal_node):
    """仅为计算或绘图复制洞口管道端点，不修改用户输入或隧洞断面。"""
    node = copy.deepcopy(pipe_node)
    for attr in ("x", "y", "station_ip", "station_MC", "station_BC", "station_EC", "water_level", "ip_number", "display_ip_number"):
        if hasattr(portal_node, attr):
            setattr(node, attr, getattr(portal_node, attr))
    node.name = ""
    node.turn_angle = 0.0
    node.turn_radius = 0.0
    # 虚拟端点不能继承相邻管道行的计算身份或既有损失覆盖值。
    node.pressure_pipe_row_identity = ""
    node.pressure_pipe_window_override = {}
    if isinstance(getattr(node, "section_params", None), dict):
        node.section_params.pop("pressure_pipe_window_override", None)
    return node
