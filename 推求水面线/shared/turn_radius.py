"""One editable nD default for blank or zero circular-pipe bend radii."""
from __future__ import annotations

import math

DEFAULT_PIPE_TURN_RADIUS_N = 3.0
DEFAULT_SOURCE = "default_3d"
_PIPE_TYPES = {"有压管道", "倒虹吸", "定向钻", "顶管", "明渠-圆形", "圆管涵", "圆形暗涵",
               "circular_culvert", "circular_channel", "circular_siphon", "pipe", "pressure_pipe", "siphon"}


class DefaultTurnRadiusGeometryError(ValueError):
    code = "default_turn_radius_does_not_fit"

    def __init__(self, diagnostic):
        self.diagnostics = [diagnostic]
        self.diagnostic = diagnostic
        super().__init__(diagnostic["message"])


def _get(node, key, default=None):
    return node.get(key, default) if isinstance(node, dict) else getattr(node, key, default)


def _set(node, key, value):
    if isinstance(node, dict):
        node[key] = value
    else:
        setattr(node, key, value)


def _number(value):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def pipe_structure(node):
    value = _get(node, "structure_type", _get(node, "source_type", _get(node, "section_type", "")))
    return str(getattr(value, "value", value) or "")


def is_pipe_radius_node(node):
    return (not _get(node, "is_transition", False) and not _get(node, "is_auto_inserted_channel", False)
            and (pipe_structure(node) in _PIPE_TYPES or _get(node, "is_pressure_pipe", False)
                 or _get(node, "is_inverted_siphon", False)))


def pipe_diameter(node):
    """Read an actual diameter; hydraulic radius R never supplies a diameter."""
    params = _get(node, "section_params", {}) or {}
    section = _get(node, "section", {}) or {}
    for value in (params.get("D"), params.get("直径D"), params.get("inner_diameter"),
                  section.get("nominal_diameter_m"), section.get("inner_diameter"), _get(node, "D")):
        number = _number(value)
        if number is not None and number > 0:
            return number
    return None


def resolve_turn_radius(node, *, multiplier=DEFAULT_PIPE_TURN_RADIUS_N, diameter=None, update=True):
    """Keep positive manual values and link blank/zero pipe radii to nD.

    A generated value remains a default while it equals its saved generated
    value. A positive direct edit becomes an explicit manual override; zero
    resets a pipe to the current nD default, including old explicit-zero rows.
    Calling this function never turns blank non-pipe geometry into a bend.
    """
    raw_radius = _get(node, "turn_radius")
    number = _number(raw_radius)
    if raw_radius is not None and str(raw_radius).strip() and number is None:
        raise ValueError("转弯半径须为有限的0或正数")
    radius = 0. if number is None else number
    if radius < 0:
        raise ValueError("转弯半径只能填写0或正数")
    source = str(_get(node, "turn_radius_source", "") or "")
    text = str(_get(node, "turn_radius_text", "") or "").strip()
    explicit = bool(_get(node, "turn_radius_is_explicit", False)) or bool(text and source != DEFAULT_SOURCE)
    previous = _number(_get(node, "turn_radius_default_value"))
    changed_default = (source == DEFAULT_SOURCE and previous is not None
                       and not math.isclose(radius, previous, rel_tol=1e-12, abs_tol=1e-12))
    if is_pipe_radius_node(node) and radius == 0.:
        explicit = False
        changed_default = False
        source = DEFAULT_SOURCE
        if update:
            _set(node, "turn_radius_source", DEFAULT_SOURCE)
            _set(node, "turn_radius_is_explicit", False)
            _set(node, "turn_radius_text", "")
            _set(node, "turn_radius_default_value", 0.)
    if explicit or changed_default:
        if update and changed_default:
            _set(node, "turn_radius_is_explicit", True)
            _set(node, "turn_radius_text", format(radius, ".12g"))
            _set(node, "turn_radius_source", "manual")
        return radius
    if source != DEFAULT_SOURCE and radius > 0:
        return radius
    if not is_pipe_radius_node(node):
        return radius
    factor = _number(multiplier)
    if factor is None or factor <= 0:
        raise ValueError("管道默认转弯半径倍数须大于0")
    own_diameter = pipe_diameter(node)
    actual_diameter = own_diameter or _number(diameter)
    if (actual_diameter is None and source == DEFAULT_SOURCE
            and _get(node, "turn_radius_default_diameter_source") == "same_group"):
        actual_diameter = _number(_get(node, "turn_radius_default_diameter"))
    if actual_diameter is None or actual_diameter <= 0:
        # A removed diameter invalidates its generated value on recalculation.
        if source == DEFAULT_SOURCE and update:
            _set(node, "turn_radius", 0.)
            _set(node, "turn_radius_default_value", 0.)
            _set(node, "turn_radius_default_diameter", None)
        return 0.
    resolved = factor*actual_diameter
    if update:
        for key, value in {"turn_radius": resolved, "turn_radius_source": DEFAULT_SOURCE,
            "turn_radius_is_explicit": False, "turn_radius_text": "",
            "turn_radius_default_value": resolved, "turn_radius_default_diameter": actual_diameter,
            "turn_radius_default_diameter_source": "node" if own_diameter else "same_group",
            "turn_radius_default_multiplier": factor}.items():
            _set(node, key, value)
    return resolved


def apply_default_turn_radii(nodes, *, multiplier=DEFAULT_PIPE_TURN_RADIUS_N):
    """Apply blank/zero radii using own D or a unique D in a continuous group."""
    rows = list(nodes)
    reports = []
    groups = []
    for node in rows:
        key = (pipe_structure(node), str(_get(node, "name", "") or "").strip(),
               str(_get(node, "flow_section", "") or ""))
        if not is_pipe_radius_node(node):
            groups.append((None, [node])); continue
        if groups and groups[-1][0] == key:
            groups[-1][1].append(node)
        else:
            groups.append((key, [node]))
    for key, members in groups:
        if key is None:
            continue
        diameters = {round(value, 12) for node in members if (value := pipe_diameter(node)) is not None}
        inherited = next(iter(diameters)) if len(diameters) == 1 else None
        for node in members:
            if inherited is None and pipe_diameter(node) is None and _get(node, "turn_radius_source") == DEFAULT_SOURCE:
                _set(node, "turn_radius_default_diameter", None)
            before = (_get(node, "turn_radius"), _get(node, "turn_radius_source"))
            value = resolve_turn_radius(node, multiplier=multiplier, diameter=inherited)
            if _get(node, "turn_radius_source") == DEFAULT_SOURCE:
                reports.append({"profile_row_id": _get(node, "profile_row_id", ""),
                    "name": _get(node, "name", ""), "radius_m": value,
                    "diameter_m": _get(node, "turn_radius_default_diameter"), "multiplier": float(multiplier),
                    "source": DEFAULT_SOURCE, "changed": before != (value, DEFAULT_SOURCE)})
    return reports


def validate_default_turn_radius_fit(nodes):
    """Check tangent occupancy only where a generated nD bend participates.

    Real inlet/outlet nodes keep the official zero-turn convention. Historical
    explicit-radius anomalies remain available to the existing review tools.
    """
    real = [(index, node) for index, node in enumerate(nodes)
            if not _get(node, "is_transition", False) and not _get(node, "is_auto_inserted_channel", False)]
    for position, ((left_index, left), (right_index, right)) in enumerate(zip(real, real[1:])):
        def tangent(node, endpoint):
            in_out = _get(node, "in_out", "")
            if endpoint or str(getattr(in_out, "value", in_out)) in {"进", "出"}:
                return 0.
            return max(0., _number(_get(node, "tangent_length")) or 0.)
        left_t = tangent(left, position == 0)
        right_t = tangent(right, position+1 == len(real)-1)
        generated = [node for node, length in ((left, left_t), (right, right_t))
                     if length > 0 and _get(node, "turn_radius_source") == DEFAULT_SOURCE
                     and not _get(node, "turn_radius_is_explicit", False)]
        if not generated:
            continue
        distance = math.hypot(float(_get(right, "x", 0.))-float(_get(left, "x", 0.)),
                              float(_get(right, "y", 0.))-float(_get(left, "y", 0.)))
        occupied = left_t+right_t
        if occupied <= distance+max(1e-7, distance*1e-10):
            continue
        labels = []
        for index, node in ((left_index, left), (right_index, right)):
            if any(node is candidate for candidate in generated):
                identity = str(_get(node, "profile_row_id", "") or f"第{index+1}个IP")
                labels.append(f"{_get(node, 'name', '') or identity}（{identity}，R={float(_get(node, 'turn_radius', 0.)):g}m）")
        message = ("默认转弯半径放不下："+"、".join(labels)
            +f"，相邻IP间距{distance:.3f}m，小于两侧切线占用{occupied:.3f}m。请修改转弯半径或IP坐标后重新计算。")
        raise DefaultTurnRadiusGeometryError({"code": DefaultTurnRadiusGeometryError.code,
            "message": message, "left_row_index": left_index, "right_row_index": right_index,
            "left_profile_row_id": _get(left, "profile_row_id", ""),
            "right_profile_row_id": _get(right, "profile_row_id", ""),
            "available_length_m": distance, "occupied_tangent_length_m": occupied,
            "left_tangent_length_m": left_t, "right_tangent_length_m": right_t})
