"""Explicit quantities for components which have no section entity.

``section.quantity_rules`` complements the swept structure and
``section.discrete_components``.  It never infers hydraulic dimensions,
foundation positions, excavation or backfill from a quantity.  Earthwork
requires an actual entity and terrain in the section calculator.

A rule has a stable ``id``, ``name``, ``material``, optional ``grade`` and
``unit`` (m3/m2/m/kg/count).  Use either an explicit total ``quantity``,
``quantity_per_unit`` times ``count``, or the dimensions for that unit.
``station`` or ``station_start``/``station_end`` identifies its scope;
omitting these uses the owning asset's actual station interval.  Dimensions
and quantities are supplied by the user, never copied from example net
dimensions in the reference drawings.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .component_quantities import _metadata, component_role
from .contracts import ConstructionInputError, finite_number


QUANTITY_RULE_UNITS = frozenset({"m3", "m2", "m", "kg", "count"})
QUANTITY_SCOPE_CATEGORIES = {
    "aqueduct": {"tie_rod": "拉杆", "support": "支座/支承", "pier": "墩台",
                 "foundation": "基础", "joint_waterstop": "接缝止水"},
    "tunnel": {"drainage": "排水", "anchors": "锚杆", "backfill_grouting": "回填灌浆",
               "consolidation_grouting": "固结灌浆", "joint_waterstop": "接缝止水",
               "bedding": "垫层"},
}


def _number(value, field, *, positive=False):
    result = finite_number(value, field)
    if result < 0 or (positive and result == 0):
        raise ConstructionInputError(f"{field}须为{'正' if positive else '非负'}数")
    return result


def _rules(asset):
    result = asset.get("section", {}).get("quantity_rules", [])
    if not isinstance(result, list):
        raise ConstructionInputError("section.quantity_rules 须为分项计量规则列表")
    return result


def _scope(asset, rule):
    if "station" in rule:
        if "station_start" in rule or "station_end" in rule:
            raise ConstructionInputError("分项规则不能同时填写单点桩号和桩号范围")
        start = end = finite_number(rule["station"], "分项桩号")
    else:
        # A half-entered explicit range must not silently borrow the other
        # endpoint from its parent and claim a different quantity scope.
        if ("station_start" in rule) != ("station_end" in rule):
            raise ConstructionInputError("分项起止桩号须同时填写")
        start = finite_number(rule.get("station_start", asset.get("station_start")), "分项起点桩号")
        end = finite_number(rule.get("station_end", asset.get("station_end")), "分项终点桩号")
    if end < start:
        raise ConstructionInputError("分项终点桩号不能小于起点")
    if asset.get("station_start") is not None and asset.get("station_end") is not None:
        lower = finite_number(asset["station_start"], "对象起点桩号")
        upper = finite_number(asset["station_end"], "对象终点桩号")
        if start < lower - 1e-8 or end > upper + 1e-8:
            raise ConstructionInputError("分项桩号范围超出所属施工对象")
    return start, end


def _reserved_ids(asset):
    section = asset.get("section", {})
    result = {"concrete", "bedding", "main_structure", "channel_body", "aqueduct_body", "tunnel_overbreak_fill"}
    for field in ("component_specs", "discrete_components"):
        for component in section.get(field, []):
            if isinstance(component, dict):
                value = component.get("component_id", component.get("id"))
                if value:
                    result.add(value)
    return result


def _identity(asset, rule):
    if not isinstance(rule, dict):
        raise ConstructionInputError("每条分项计量规则须为对象")
    cid = rule.get("id", rule.get("component_id"))
    component_role(cid)
    if rule.get("id") is not None and rule.get("component_id") not in (None, cid):
        raise ConstructionInputError("分项规则 id 与 component_id 不一致")
    if cid in _reserved_ids(asset) or rule.get("entity_component_id") or rule.get("covers_main_structure"):
        raise ConstructionInputError(f"分项 {cid} 已有结构/附属实体计量路径，不能重复计量")
    for key, label in (("name", "名称"), ("material", "材料")):
        if not isinstance(rule.get(key), str) or not rule[key].strip():
            raise ConstructionInputError("分项规则缺少" + label)
    if rule.get("unit") not in QUANTITY_RULE_UNITS:
        raise ConstructionInputError("分项单位仅支持 m3、m2、m、kg、count")
    if rule.get("status") in {"pending", "missing", "待补充", "待核对"}:
        raise ConstructionInputError("分项规则仍为待补充/待核对状态")
    return cid


def _quantity(rule):
    """Return the total and a reviewable calculation, without guessing count."""
    unit = rule["unit"]
    count = _number(rule.get("count", 1), "分项数量 count")
    if count != math.floor(count):
        raise ConstructionInputError("离散构件 count 须为非负整数")
    if "quantity" in rule:
        if "quantity_per_unit" in rule:
            raise ConstructionInputError("分项总量与单件量不能同时填写")
        return _number(rule["quantity"], "分项显式总量"), "用户明确的分项总量；不再乘 count"
    if "quantity_per_unit" in rule:
        value = _number(rule["quantity_per_unit"], "分项单件工程量")
        return value * count, "quantity_per_unit × count"

    def dimension(name):
        return _number(rule.get(name), "分项 " + name, positive=True)

    if unit == "m3":
        if "cross_section_area_m2" in rule:
            value = dimension("cross_section_area_m2") * dimension("length_m")
            formula = "cross_section_area_m2 × length_m × count"
        else:
            value = dimension("length_m") * dimension("width_m") * dimension("height_m")
            formula = "length_m × width_m × height_m × count"
    elif unit == "m2":
        value = dimension("length_m") * dimension("width_m")
        formula = "length_m × width_m × count"
    elif unit == "m":
        value = dimension("length_m")
        formula = "length_m × count"
    elif unit == "kg":
        value = dimension("mass_per_unit_kg")
        formula = "mass_per_unit_kg × count"
    else:
        if "count" not in rule:
            raise ConstructionInputError("计数分项须明确 count 或 quantity，不能默认一件")
        value = 1.
        formula = "count"
    quantity = value * count
    if not math.isfinite(quantity):
        raise ConstructionInputError("分项工程量超出有限数值范围")
    return quantity, formula


def quantity_rule_items(asset):
    """Return complete component_quantities items, once per owning asset.

    These totals must be appended once, not integrated again at every route
    section.  They intentionally do not affect earthwork or entity volumes.
    Disabled rules stay out of results and remain visible in the missing list.
    """
    result = []
    seen = set()
    for rule in _rules(asset):
        cid = _identity(asset, rule)
        if cid in seen:
            raise ConstructionInputError("分项计量规则编号重复：" + cid)
        seen.add(cid)
        if rule.get("enabled", True) is False:
            continue
        start, end = _scope(asset, rule)
        quantity, formula = _quantity(rule)
        if not math.isfinite(quantity):
            raise ConstructionInputError("分项工程量超出有限数值范围")
        spec = {**rule, "grade": rule.get("grade") or ""}
        metadata = _metadata(asset, spec, cid, rule["unit"], "explicit_user_quantity_rule")
        result.append({**metadata,
                       "asset_id": asset["asset_id"], "asset_name": asset.get("name", ""),
                       "station_start": start, "station_end": end,
                       "quantity": quantity, "formula": formula,
                       "input_snapshot": deepcopy(rule),
                       "geometry_included": False,
                       "status": "user_defined_quantity_rule"})
    return result


def quantity_rule_missing_items(asset):
    """Describe unresolved declared rules; an empty list is not full-scope proof."""
    try:
        rules = _rules(asset)
    except ConstructionInputError as error:
        return [str(error)]
    problems = []
    seen = set()
    for index, rule in enumerate(rules):
        name = rule.get("name", rule.get("id", str(index + 1))) if isinstance(rule, dict) else str(index + 1)
        try:
            cid = _identity(asset, rule)
            if cid in seen:
                raise ConstructionInputError("分项计量规则编号重复：" + cid)
            seen.add(cid)
            if rule.get("enabled", True) is False:
                raise ConstructionInputError("规则已停用，未纳入工程量")
            _scope(asset, rule)
            quantity, _ = _quantity(rule)
            if not math.isfinite(quantity):
                raise ConstructionInputError("分项工程量超出有限数值范围")
        except ConstructionInputError as error:
            problems.append(f"{name}：{error}")
    return problems


def aqueduct_quantity_items(asset):
    """Compatibility entry point; the same explicit rules also serve tunnels."""
    return quantity_rule_items(asset)


def aqueduct_missing_items(asset):
    return quantity_rule_missing_items(asset)


def _scope_kind(asset):
    typ = asset.get("section_type", "")
    if typ in {"aqueduct_u", "aqueduct_rectangular"}:
        return "aqueduct"
    if typ in {"arch_tunnel", "circular_tunnel", "flat_bottom_tunnel", "horseshoe_tunnel"}:
        return "tunnel"
    return asset.get("kind") if asset.get("kind") in QUANTITY_SCOPE_CATEGORIES else None


def _path_value(asset, path):
    import re
    value = asset
    for key in re.findall(r"[^.\[\]]+", str(path)):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def _unresolved_source(value):
    if value is None or value == "":
        return True
    if isinstance(value, str):
        text = value.strip().lower()
        return not text or text in {"pending", "missing", "unknown", "unconfirmed", "待定", "待核对", "未定", "未确认", "未提供"}
    if isinstance(value, dict):
        if value.get("confirmed") is False or value.get("resolved") is False:
            return True
        if "status" in value and _unresolved_source(value["status"]):
            return True
        if "value" in value:
            return _unresolved_source(value["value"])
    return False


def _source_issues(owner, asset):
    """Only check declared unresolved fields; never invent missing design data."""
    issues = []
    for key in ("missing_fields", "source_missing_fields"):
        for path in owner.get(key, []):
            # Importers retain source-missing history. A supplied current value
            # resolves that history; a zero is a real value, not missing data.
            if _unresolved_source(_path_value(owner, path)) and _unresolved_source(_path_value(asset, path)):
                issues.append(str(path))
    fields = owner.get("source_fields", {})
    if isinstance(fields, dict):
        issues.extend(str(path) for path, value in fields.items() if _unresolved_source(value))
    elif isinstance(fields, list):
        for field in fields:
            if isinstance(field, str):
                if _unresolved_source(_path_value(owner, field)) and _unresolved_source(_path_value(asset, field)):
                    issues.append(field)
            elif isinstance(field, dict) and _unresolved_source(field):
                issues.append(str(field.get("field", field.get("name", "来源参数"))))
    return sorted(set(issues))


def quantity_scope_coverage(asset, quantity_items=None):
    """Audit declared design scope against quantities actually in the result.

    Pass the finalized material quantity rows, including generated foundation
    items.  A nonempty entity/rule list alone proves no category complete.
    ``scope_category`` may be carried by an item or resolved through its
    component id (or ``parent_component_id`` for a generated foundation).
    An explicit list in ``section.quantity_scope_not_applicable`` is the only
    way to exclude an applicable category without a computed positive item.
    """
    kind = _scope_kind(asset)
    categories = QUANTITY_SCOPE_CATEGORIES.get(kind, {})
    aid = asset.get("asset_id")
    issues = []

    def issue(message, *, category=None, code="quantity_scope_missing", **extra):
        issues.append({"asset_id": aid, "name": asset.get("name", ""),
                       "scope_category": category, "code": code, "message": message, **extra})

    if not categories:
        return {"kind": kind, "required": [], "included": [], "not_applicable": [],
                "missing": [], "issues": []}
    section = asset.get("section", {})
    excluded = section.get("quantity_scope_not_applicable", [])
    if not isinstance(excluded, list) or any(not isinstance(x, str) for x in excluded):
        issue("不适用分项须为当前结构类型的类别列表", code="quantity_scope_invalid_exclusion")
        excluded = []
    for category in sorted(set(excluded) - set(categories)):
        issue("不适用分项类别未识别：" + category, category=category,
              code="quantity_scope_invalid_exclusion")
    not_applicable = set(excluded) & set(categories)
    declaration_map = {}
    for field in ("discrete_components", "quantity_rules", "component_specs"):
        for component in section.get(field, []):
            if not isinstance(component, dict):
                continue
            cid = component.get("component_id", component.get("id"))
            if cid:
                declaration_map[cid] = component
            category = component.get("scope_category")
            if category and category not in categories:
                issue("构件范围类别未识别：" + str(category), category=category,
                      code="quantity_scope_unknown_category", component_id=cid)
            for path in _source_issues(component, asset):
                issue(f"{component.get('name', cid)} 来源参数未定：{path}", category=category,
                      code="quantity_scope_unresolved_source", component_id=cid, field=path)
    for path in _source_issues(asset, asset):
        issue("来源参数未定：" + path, code="quantity_scope_unresolved_source", field=path)

    if quantity_items is None:
        # Standalone callers may inspect valid explicit rules, but declared
        # entity dimensions are not a substitute for integrated geometry.
        try:
            items = quantity_rule_items(asset)
        except ConstructionInputError:
            items = []
    else:
        items = quantity_items
    included = set()
    for item in items:
        owner = item.get("parent_asset_id", item.get("asset_id"))
        if owner != aid:
            continue
        try:
            quantity = finite_number(item.get("quantity"), "实际分项工程量")
        except ConstructionInputError:
            continue
        if quantity <= 0 or item.get("status") in {"pending", "missing", "excluded", "disabled"}:
            continue
        cid = item.get("parent_component_id", item.get("component_id"))
        declaration = declaration_map.get(cid, {})
        if declaration.get("enabled", True) is False or _source_issues(declaration, asset):
            continue
        category = item.get("scope_category") or declaration.get("scope_category")
        # The standard computed bedding role is already unambiguous, unlike
        # free-form component names which must never be guessed into a class.
        if not category and kind == "tunnel" and cid == "bedding":
            category = "bedding"
        if category in categories:
            included.add(category)
    for category in sorted(included & not_applicable):
        issue(categories[category] + "已有实际工程量，与用户标记不适用矛盾", category=category,
              code="quantity_scope_exclusion_conflict")
    missing = set(categories) - included - not_applicable
    for category in categories:
        if category in missing:
            issue(categories[category] + "尚无已纳入的实际构件/有效分项工程量，请补充或明确不适用", category=category)
    for message in quantity_rule_missing_items(asset):
        issue(message, code="quantity_rule_unresolved")
    return {"kind": kind, "required": list(categories),
            "included": sorted(included), "not_applicable": sorted(not_applicable),
            "missing": sorted(missing), "issues": issues}


def quantity_scope_issues(asset, quantity_items=None):
    return quantity_scope_coverage(asset, quantity_items)["issues"]
