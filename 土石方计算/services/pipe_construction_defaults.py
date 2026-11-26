"""Conditional, editable pipe construction defaults from the supplied table 7.2.

The table supplies dimensions for alternative supports. It does not authorize
stacking sand, a concrete seat and encasement, or activating soil replacement.
Only live input dictionaries are touched; stored results and source snapshots
are never traversed. Existing values, including zero and False, always win.
"""
from __future__ import annotations

from copy import deepcopy
import math

POLICY = "pipe_construction_table_7_2_v1"
SOURCE = "用户提供表7.2：管道开挖及支承构造参数（2026-10-26）"
SOURCE_REFS = [
    "user_defaults_20261026/表7.2_管道支承计算尺寸.png",
    "user_defaults_20261026/回填分层控制标准.png",
]
GENERAL_SCHEME_IDS = frozenset({"tzk_pipe_b", "tzk_siphon_a"})
SUPPORT_MODES = frozenset({"sand_bedding", "concrete_seat", "encasement"})
DEFAULT_MANUAL_BACKFILL_HEIGHT_M = .5
PIPE_BACKFILL_HEIGHT_PATH = "construction.backfill_partition.above_crown_height_m"


def _positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0.
    except (TypeError, ValueError):
        return False


def pipe_construction_recommendations(diameter_m):
    """Return table bands in metres; sizes above 3 m are never extrapolated."""
    result = {"policy": POLICY, "source": SOURCE, "source_refs": deepcopy(SOURCE_REFS), "diameter_m": None,
        "diameter_basis": "adopted_pipe_outer_diameter_m", "status": "MISSING_DIAMETER",
        "working_space_m": None, "encasement_thickness_m": None,
        "concrete_seat_thickness_m": None, "sand_bedding_thickness_m": None,
        "foundation_replacement_thickness_m": .6,
        "foundation_replacement_enabled_by_default": False,
        "support_options_are_alternatives": True}
    if not _positive(diameter_m):
        result["message"] = "缺少有效施工外径，先核对Excel D或已明确实际外径；表7.2默认尺寸未加载"
        return result
    diameter = float(diameter_m)
    result["diameter_m"] = diameter
    if diameter > 3.:
        result.update(status="OUT_OF_RANGE", message="施工外径超过表7.2的3m适用范围，请输入实际施工尺寸")
        return result
    band = 0 if diameter <= .5 else 1 if diameter <= 1. else 2
    result.update(status="READY", band=("D≤0.5m", "0.5m＜D≤1m", "1m＜D≤3m")[band],
        working_space_m=(.5, .8, 1.)[band],
        encasement_thickness_m=.35 if diameter <= 1.4 else .4,
        concrete_seat_thickness_m=(.1, .2, .3)[band],
        sand_bedding_thickness_m=(.1, .15, .2)[band],
        message="按实际采用管外径分档；各支承方式分别采用，石渣换填仅作条件推荐")
    return result


def pipe_outer_diameter(asset):
    """Use adopted construction sizes, retaining all multi-pipe source sizes."""
    section = asset.get("section") or {}
    pipes = section.get("pipes") or [section]
    values = [pipe.get("outer_diameter", section.get("outer_diameter")) for pipe in pipes]
    if not values or not all(_positive(value) for value in values):
        return None
    return max(float(value) for value in values)


def _pipe_asset(asset):
    return asset.get("kind") != "tunnel" and (
        asset.get("kind") in {"pipe", "pressure_pipe", "siphon"}
        or asset.get("section_type") in {"circular_siphon", "circular_culvert", "circular_channel"})


def _protected_binding(asset):
    if asset.get("drawing_binding") or asset.get("drawing_bindings"):
        return True
    binding = asset.get("section_scheme_binding") or {}
    identifier = binding.get("scheme_id") or asset.get("section_scheme_id")
    if not identifier:
        return False
    snapshot = binding.get("scheme_snapshot") or {}
    return not (identifier in GENERAL_SCHEME_IDS and snapshot.get("pipe_construction_default_policy") == POLICY)


def apply_pipe_construction_defaults(asset, *, support_mode=None):
    """Fill missing fields in one live asset; an explicit mode is a user action.

    Without a mode, an already enabled support controls the conditional values.
    A new, ordinary unbound pipe defaults to its established sand support. An
    explicit drawing/special/legacy binding is protected unless a support mode
    is deliberately supplied. Switching modes never disables a user's support;
    conflicting enabled supports are reported for the caller to resolve.
    """
    if support_mode is not None and support_mode not in SUPPORT_MODES:
        raise ValueError("支承方式须为sand_bedding、concrete_seat或encasement")
    report = {"changed": False, "applied_fields": [], "assumptions": [], "errors": [],
        "support_mode": None, "recommendations": pipe_construction_recommendations(pipe_outer_diameter(asset))}
    from .earthwork_scope import trenchless_method
    if (not _pipe_asset(asset) or not asset.get("enabled", True) or trenchless_method(asset)
            or (asset.get("construction") or {}).get("installation_mode", "buried") not in {None, "buried"}):
        report["status"] = "NOT_APPLICABLE"
        return report
    if support_mode is None and _protected_binding(asset):
        report["status"] = "EXPLICIT_BINDING_PRESERVED"
        return report
    c = asset.get("construction") or {}
    seat_key = "pipe_seat" if "pipe_seat" in c or "pipe_support" not in c else "pipe_support"
    enclosure_key = "encasement" if "encasement" in c or "pipe_encasement" not in c else "pipe_encasement"
    seat, enclosure = c.get(seat_key) or {}, c.get(enclosure_key) or {}
    seat_active = bool(seat) and seat.get("enabled", True)
    enclosure_active = bool(enclosure) and enclosure.get("enabled", True)
    if seat_active and enclosure_active:
        report.update(status="SUPPORT_CONFLICT", errors=["管座/砂垫层与外包混凝土同时启用，请先选择实际支承方式"])
        return report
    if enclosure_active:
        selected = "encasement"
    elif seat_active:
        selected = "sand_bedding" if seat.get("material_role", "concrete") == "bedding" else "concrete_seat"
    elif support_mode is not None:
        selected = support_mode
    elif seat.get("enabled") is False:
        selected = None
    else:
        selected = support_mode or "sand_bedding"
    if support_mode is not None and (seat_active or enclosure_active) and support_mode != selected:
        report.update(status="SUPPORT_CONFLICT", errors=["当前已启用的支承方式与加载方式不一致，请先在施工参数中切换"])
        return report
    report["support_mode"] = selected
    recommendations = report["recommendations"]

    def assign(path, value, reason):
        parts = path.split(".")
        node = asset
        for key in parts[:-1]:
            child = node.get(key)
            if child is None:
                child = node[key] = {}
            if not isinstance(child, dict):
                report["errors"].append(path + "的父级参数格式无效，已保留原值")
                return
            node = child
        key = parts[-1]
        if key in node and (node[key] is not None or value is None):
            return
        asset.setdefault("pipe_construction_default_source_values", {}).setdefault(path, {
            "present": key in node, "value": deepcopy(node.get(key)), "adopted_value": deepcopy(value)})
        node[key] = deepcopy(value)
        asset.setdefault("parameter_sources", {})[path] = "管道施工默认值：" + reason
        report["applied_fields"].append(path)
        report["assumptions"].append({"asset_id": asset.get("asset_id"), "name": asset.get("name"),
            "field": path, "value": deepcopy(value), "reason": reason})

    for key, value in recommendations.items():
        assign("construction.pipe_default_options." + key, value, SOURCE + "；条件推荐，不代表已启用")
    partition = {"above_crown_height_m": DEFAULT_MANUAL_BACKFILL_HEIGHT_M, "max_particle_size_mm": 50.,
        "applicability": "no_special_ground_load_requirements",
        "applicability_note": "仅适用于无特殊地面荷载要求的管道回填；特殊地面荷载按实际设计设置",
        "exclude_organic_material": True, "exclude_frozen_soil": True,
        "fine_soil_at_sensitive_locations": True,
        "sensitive_locations": ["管道接口", "防腐绝缘层周围", "电缆周围"],
        "manual_bottom_reference": "trench_bottom", "manual_top_reference": "pipe_outer_crown_plus_height",
        "mechanical_bottom_reference": "manual_fill_top", "mechanical_top_reference": "finished_ground"}
    for key, value in partition.items():
        assign("construction.backfill_partition." + key, value,
            "槽底至管外顶以上0.5m采用人工回填，其上机械回填；人工区不得含有机物、冻土或大于50mm硬块，接口/防腐层/电缆周围用细粒土")
    if recommendations["status"] != "READY":
        report.update(status=recommendations["status"], changed=bool(report["applied_fields"]))
        return report
    for side in ("left", "right"):
        assign("construction.working_space_" + side, recommendations["working_space_m"], SOURCE + "；单侧工作面b，按采用管外径分档")
    assign("construction.working_space_reference", "pipe_outer", "工作面从实际采用的管外壁起算")
    if selected == "sand_bedding":
        assign("construction." + seat_key + ".enabled", True, "当前一般埋管采用砂垫层支承")
        assign("construction." + seat_key + ".material_role", "bedding", "砂垫层计入垫层，其他支承方式不同时启用")
        assign("construction." + seat_key + ".base_thickness", recommendations["sand_bedding_thickness_m"], SOURCE + "；砂垫层厚度t1")
        # The general family owns its support angle and width. This table does
        # not create either dimension or an additional rectangular sand layer.
        assign("construction.bedding_thickness", 0., "砂垫层由pipe_seat统一计量，不另加矩形垫层")
        assign("construction.bedding_extension", 0., "表7.2未另给砂垫层外伸，不叠加第二层")
    elif selected == "concrete_seat":
        assign("construction." + seat_key + ".enabled", True, "当前选择混凝土基座支承")
        assign("construction." + seat_key + ".material_role", "concrete", "混凝土基座与砂垫层/外包混凝土分别采用")
        assign("construction." + seat_key + ".base_thickness", recommendations["concrete_seat_thickness_m"], SOURCE + "；管道外基座厚度B")
    elif selected == "encasement":
        assign("construction." + enclosure_key + ".enabled", True, "当前选择外包混凝土支承")
        side = enclosure.get("side_thickness")
        if side is None:
            side = enclosure.get("left_thickness")
        if side is None:
            side = recommendations["encasement_thickness_m"]
        keys = ("left_thickness", "right_thickness") if all(
            enclosure.get(key) is not None for key in ("left_thickness", "right_thickness")
        ) else ("side_thickness", "left_thickness", "right_thickness")
        for key in keys:
            assign("construction." + enclosure_key + "." + key, side,
                "沿用已给侧厚；缺项按" + SOURCE + "的外包混凝土厚度b1")
        for key in ("bottom_thickness", "top_thickness"):
            assign("construction." + enclosure_key + "." + key, recommendations["encasement_thickness_m"], SOURCE + "；外包混凝土厚度b1")
    if selected in {"concrete_seat", "encasement"}:
        assign("construction.bedding_thickness", 0., "当前采用混凝土支承；未另给砂垫层时不叠加砂垫层")
        assign("construction.bedding_extension", 0., "未另给砂垫层外伸时不叠加砂垫层")
    report.update(status="APPLIED" if report["applied_fields"] else "UNCHANGED", changed=bool(report["applied_fields"]))
    return report
