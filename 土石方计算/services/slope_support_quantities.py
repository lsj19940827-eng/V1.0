"""Independent, traceable quantities for explicitly entered slope lengths.

The support schedule supplements a channel/pipe section. It neither replaces
that section nor creates excavation or solid geometry. A reusable template
contains the cross-slope dimensions or user-confirmed quantities per metre;
each schedule row supplies its single-side length and number of equal sides.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re

from .contracts import ConstructionInputError, finite_number


SCHEMA = "slope_support_quantities_1.0"
TYPE_LABELS = {
    "A": "A型土质边坡（图示≤3m，草皮护坡）",
    "B": "B型土质边坡（图示>3m，框格梁护坡）",
    "C": "C型岩质边坡（≤6m，10cm喷砼锚护）",
    "D": "D型岩质边坡（>6m，15cm挂网喷砼锚护）",
}
SUPPORT_TYPES = TYPE_LABELS
COMPONENT_LABELS = {
    "vegetation": "草皮/喷播绿化", "shotcrete": "喷生态混凝土",
    "mesh": "挂网", "drain_concrete": "C20排水沟混凝土",
    "frame_beam": "C25框格梁混凝土", "planting_soil": "回填耕植土",
    "anchors_3m": "φ22、L=3m锚杆", "anchors_6m": "φ22、L=6m锚杆",
    "pvc_drainage": "D5cm、L=2m PVC排水孔", "frame_rebar": "框格梁钢筋",
    "mesh_lap_loss": "挂网搭接及损耗", "anchor_grouting": "锚杆水泥砂浆注浆",
}
COMPONENT_DEFAULTS = {
    "vegetation": {"material": "vegetation", "unit": "m2"},
    "shotcrete": {"material": "shotcrete", "grade": "C25W8F100", "unit": "m3"},
    "mesh": {"material": "steel_mesh", "grade": "φ6@20cm", "unit": "m2"},
    "drain_concrete": {"material": "concrete", "grade": "C20", "unit": "m3"},
    "frame_beam": {"material": "concrete", "grade": "C25", "unit": "m3"},
    "planting_soil": {"material": "planting_soil", "unit": "m3"},
    "anchors_3m": {"material": "steel_anchor", "grade": "φ22 L=3m", "unit": "m"},
    "anchors_6m": {"material": "steel_anchor", "grade": "φ22 L=6m", "unit": "m"},
    "pvc_drainage": {"material": "PVC", "grade": "D5cm L=2m", "unit": "m"},
    "frame_rebar": {"material": "steel", "unit": "kg"},
    "mesh_lap_loss": {"material": "steel_mesh", "grade": "φ6@20cm", "unit": "m2"},
    "anchor_grouting": {"material": "cement_mortar", "unit": "m3"},
}
_UNITS = frozenset({"m3", "m2", "m", "kg", "count"})
_COMPONENT_UNITS = {
    "vegetation": {"m2"}, "shotcrete": {"m3"}, "mesh": {"m2", "kg"},
    "drain_concrete": {"m3"}, "frame_beam": {"m3"}, "planting_soil": {"m3"},
    "anchors_3m": {"m", "count", "kg"}, "anchors_6m": {"m", "count", "kg"},
    "pvc_drainage": {"m", "count"}, "frame_rebar": {"kg"},
    "mesh_lap_loss": {"m2", "kg"}, "anchor_grouting": {"m3"},
}
_REQUIRED = {
    "A": ("vegetation", "drain_concrete"),
    "B": ("vegetation", "frame_beam", "planting_soil", "frame_rebar", "drain_concrete"),
    "C": ("shotcrete", "anchors_3m", "pvc_drainage", "anchor_grouting", "drain_concrete"),
    "D": ("shotcrete", "mesh", "anchors_3m", "anchors_6m", "pvc_drainage",
          "anchor_grouting", "mesh_lap_loss", "drain_concrete"),
}
_SOURCE_SHA256 = "6ed245d8e5261051cbe34d50e0520cbcfda28c336274d24a971cf4914b35d6a9"
_SOURCE_HANDLES = {
    "A": ["18D74", "18E96", "18EA0", "18EA1", "18EEB"],
    "B": ["18C46", "18B7F", "18B8D", "18B9F", "1F23E", "1C146"],
    "C": ["18C87", "18CCD", "18CD2", "18CDA", "18CDB", "1E119"],
    "D": ["18F3B", "18478", "18479", "18483", "18487", "1849A", "1849F", "1F294", "1F295", "1F2E2"],
}


def _type(value):
    if not isinstance(value, str) or value not in TYPE_LABELS:
        raise ConstructionInputError("支护类型须为 A、B、C 或 D")
    return value


def default_slope_support_parameters(support_type):
    """Only dimensions explicitly labelled in the source are defaults."""
    support_type = _type(support_type)
    result = {"drain_enabled": True}
    if support_type in {"A", "C", "D"}:
        result.update(drain_inner_width_m=.5, drain_inner_depth_m=.5, drain_thickness_m=.2)
    if support_type in {"C", "D"}:
        result["shotcrete_thickness_m"] = .1 if support_type == "C" else .15
    return result


def _id(value, label, *, component=False):
    pattern = r"[A-Za-z][A-Za-z0-9_]{0,79}" if component else r"[A-Za-z0-9_-]{1,100}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ConstructionInputError(label + "须为稳定的字母、数字或下划线编号")
    return value


def _number(value, label, *, zero=False):
    number = finite_number(value, label)
    if number < 0 or (not zero and number == 0):
        raise ConstructionInputError(label + ("须为非负数" if zero else "须为正数"))
    return number


def _present(value):
    return value is not None and value != ""


def _parameters(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConstructionInputError("支护 parameters 须为参数字典")
    result = deepcopy(value)
    for key in ("slope_width_m", "height_m", "slope_ratio", "shotcrete_thickness_m",
                "drain_inner_width_m", "drain_inner_depth_m", "drain_thickness_m"):
        if _present(result.get(key)):
            _number(result[key], "支护 " + key, zero=key == "slope_ratio")
    if "drain_enabled" in result and not isinstance(result["drain_enabled"], bool):
        raise ConstructionInputError("支护 drain_enabled 须为布尔值")
    return result


def _manual_items(value):
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ConstructionInputError("支护 per_m_items 须为每延米分项列表")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise ConstructionInputError("每延米支护分项须为字典")
        cid = _id(item.get("component_id"), "支护构件编号", component=True)
        if cid in result:
            raise ConstructionInputError("每延米支护构件编号重复：" + cid)
        spec = {**COMPONENT_DEFAULTS.get(cid, {}), **deepcopy(item)}
        if spec.get("unit") not in _UNITS:
            raise ConstructionInputError("支护分项单位须为 m3、m2、m、kg 或 count")
        if cid in _COMPONENT_UNITS and spec["unit"] not in _COMPONENT_UNITS[cid]:
            raise ConstructionInputError(COMPONENT_LABELS[cid] + "的计量单位不匹配")
        for key in ("name", "material"):
            fallback = COMPONENT_LABELS.get(cid) if key == "name" else None
            if not spec.get(key) and fallback:
                spec[key] = fallback
            if not isinstance(spec.get(key), str) or not spec[key].strip():
                raise ConstructionInputError("每延米支护分项缺少" + {"name": "名称", "material": "材料"}[key])
        if _present(spec.get("quantity_per_m")):
            _number(spec["quantity_per_m"], spec["name"] + "每延米系数", zero=True)
        result[cid] = spec
    return result


def _templates(value):
    if not isinstance(value, list):
        raise ConstructionInputError("slope_support_templates 须为可复用模板列表")
    result = {}
    for template in value:
        if not isinstance(template, dict):
            raise ConstructionInputError("每个支护模板须为字典")
        identifier = _id(template.get("id"), "支护模板编号")
        if identifier in result:
            raise ConstructionInputError("支护模板编号重复：" + identifier)
        _type(template.get("type"))
        _parameters(template.get("parameters"))
        _manual_items(template.get("per_m_items"))
        result[identifier] = deepcopy(template)
    return result


def _width(parameters):
    if _present(parameters.get("slope_width_m")):
        return _number(parameters["slope_width_m"], "坡面展开宽"), "slope_width_m"
    if _present(parameters.get("height_m")) and _present(parameters.get("slope_ratio")):
        height = _number(parameters["height_m"], "坡高")
        slope = _number(parameters["slope_ratio"], "坡比 m", zero=True)
        return _number(height * math.hypot(1., slope), "坡面展开宽"), "height_m × sqrt(1 + slope_ratio²)"
    return None, "待填坡面展开宽，或坡高和坡比"


def _automatic_items(support_type, parameters):
    width, width_formula = _width(parameters)
    result = {}
    if width is not None:
        if support_type == "A":
            result["vegetation"] = {"quantity_per_m": width, "formula": width_formula,
                                    "name": "草皮护坡", "material": "turf"}
        if support_type in {"C", "D"} and _present(parameters.get("shotcrete_thickness_m")):
            result["shotcrete"] = {
                "quantity_per_m": width * _number(parameters["shotcrete_thickness_m"], "喷砼厚度"),
                "formula": "(" + width_formula + ") × shotcrete_thickness_m"}
        if support_type == "D":
            result["mesh"] = {"quantity_per_m": width, "formula": width_formula}
    drain_keys = ("drain_inner_width_m", "drain_inner_depth_m", "drain_thickness_m")
    if parameters.get("drain_enabled", True) and all(_present(parameters.get(key)) for key in drain_keys):
        width, depth, thickness = (_number(parameters[key], "排水沟 " + key) for key in drain_keys)
        result["drain_concrete"] = {
            "quantity_per_m": (width + 2 * thickness) * (depth + thickness) - width * depth,
            "formula": "(drain_inner_width_m + 2 × drain_thickness_m) × "
                       "(drain_inner_depth_m + drain_thickness_m) - drain_inner_width_m × drain_inner_depth_m"}
    return result


def calculate_slope_support_quantities(inputs):
    """Return quantities and explicit missing scope without mutating inputs.

    Missing cross-slope dimensions or blank per-metre rates produce missing
    scope, never zero quantities. Invalid numbers, repeated identities and
    malformed templates stop calculation. A positive manual rate replaces
    the automatic rate of the same component, so it cannot be counted twice.
    """
    if not isinstance(inputs, dict):
        raise ConstructionInputError("支护算量输入须为字典")
    templates = _templates(inputs.get("slope_support_templates", []))
    rows = inputs.get("slope_support_rows", [])
    if not isinstance(rows, list):
        raise ConstructionInputError("slope_support_rows 须为支护长度清单")
    result = {"schema": SCHEMA, "quantity_items": [], "scope_issues": [], "rows": [],
              "templates": deepcopy(list(templates.values())), "scope_complete": True}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ConstructionInputError("支护长度清单每行须为字典")
        identifier = _id(row.get("id"), "支护行编号")
        if identifier in seen:
            raise ConstructionInputError("支护行编号重复：" + identifier)
        seen.add(identifier)
        template_id = row.get("template_id")
        if template_id and template_id not in templates:
            raise ConstructionInputError("支护行引用的模板不存在：" + str(template_id))
        template = templates.get(template_id, {})
        support_type = _type(row.get("type", template.get("type")))
        if template and template["type"] != support_type:
            raise ConstructionInputError("支护行类型与引用模板不一致")
        length = _number(row.get("length_m"), "支护单侧长度 length_m")
        sides = finite_number(row.get("side_count", 1), "支护侧数 side_count")
        if sides not in {1., 2.}:
            raise ConstructionInputError("支护侧数须为 1 或 2")
        _number(length * sides, "支护各侧累计长度")
        parameters = {**default_slope_support_parameters(support_type),
                      **_parameters(template.get("parameters")), **_parameters(row.get("parameters"))}
        manual = {**_manual_items(template.get("per_m_items")), **_manual_items(row.get("per_m_items"))}
        automatic = _automatic_items(support_type, parameters)
        name = str(row.get("name") or template.get("name") or TYPE_LABELS[support_type])
        asset_id = "slope_support:" + identifier
        required = list(_REQUIRED[support_type])
        if not parameters.get("drain_enabled", True):
            if "drain_concrete" in manual and _present(manual["drain_concrete"].get("quantity_per_m")):
                raise ConstructionInputError("已关闭排水沟，不能同时填写排水沟每延米工程量")
            required.remove("drain_concrete")
            manual.pop("drain_concrete", None)
        rates = {cid: {**COMPONENT_DEFAULTS[cid], "name": COMPONENT_LABELS[cid], **spec}
                 for cid, spec in automatic.items()}
        for cid, spec in manual.items():
            rates[cid] = {**spec, "formula": "用户明确的 quantity_per_m"}
        included = []
        for cid, spec in rates.items():
            coefficient = spec.get("quantity_per_m")
            if not _present(coefficient) or float(coefficient) == 0:
                continue
            coefficient = _number(coefficient, spec["name"] + "每延米系数")
            quantity = coefficient * length * sides
            if not math.isfinite(quantity):
                raise ConstructionInputError("支护工程量超出有限数值范围")
            included.append(cid)
            result["quantity_items"].append({
                "asset_id": asset_id, "asset_name": name, "support_row_id": identifier,
                "support_type": support_type, "component_id": "slope_" + cid,
                "support_component_id": cid, "name": spec["name"], "material": spec["material"],
                "grade": spec.get("grade") or "", "unit": spec["unit"], "quantity": quantity,
                "length_m": length, "side_count": int(sides), "quantity_per_m": coefficient,
                "method": "independent_slope_support_per_metre_schedule", "geometry_included": False,
                "formula": "(" + spec["formula"] + ") × length_m × side_count",
                "input_snapshot": {"row": deepcopy(row), "template": deepcopy(template),
                                   "resolved_parameters": deepcopy(parameters), "resolved_per_m_item": deepcopy(spec)},
                "drawing_id": "tzk", "template_id": "tzk_slope_" + support_type.lower(),
                "source_sha256": _SOURCE_SHA256, "source_ids": ["tzk_slope_" + support_type.lower()],
                "source_handles": deepcopy(_SOURCE_HANDLES[support_type]),
                "source_preview": "section_previews/tzk_slope_" + support_type.lower() + ".svg",
                "status": "user_defined_slope_support_schedule",
            })
        missing = [cid for cid in dict.fromkeys([*required, *manual]) if cid not in included]
        for cid in missing:
            reason = "待补每延米工程量；原图未给出足以确定实际数量的完整布置或构造参数"
            if cid in {"vegetation", "shotcrete", "mesh"} and support_type != "B":
                reason = "待填坡面展开宽（不含马道），或坡高和坡比；也可明确每延米工程量"
            if cid == "drain_concrete":
                reason = "待填排水沟净宽、净深及衬砌厚度，或明确每延米混凝土量"
            if cid in manual:
                reason = "明确填写的每延米系数为空或为0，尚未形成有效工程量"
            label = COMPONENT_LABELS.get(cid, manual[cid]["name"] if cid in manual else cid)
            result["scope_issues"].append({
                "asset_id": asset_id, "name": name, "support_row_id": identifier,
                "support_type": support_type, "scope_category": cid,
                "component_id": "slope_" + cid, "code": "slope_support_not_counted",
                "status": "not_counted", "message": label + "：未计；" + reason,
            })
        result["rows"].append({"id": identifier, "type": support_type, "name": name,
            "length_m": length, "side_count": int(sides), "total_length_m": length * sides,
            "template_id": template_id, "parameters": deepcopy(parameters),
            "included_components": included, "missing_components": missing, "scope_complete": not missing})
    result["scope_complete"] = not result["scope_issues"]
    return result
