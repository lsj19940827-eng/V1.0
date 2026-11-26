"""Construction thicknesses used by the water-profile section summary."""
import math


SECTION_SUMMARY_LINING_DEFAULTS = {
    "rect_channel": {"wall_t": .30},
    "trap_channel": {"wall_t": .30},
    "rect_culvert": {"t0": .40, "t1": .40, "t2": .40},
    "rect_culvert_arch": {"t0": .40, "t": .40},
}

SECTION_SUMMARY_LINING_TYPES = {
    "明渠-矩形": "rect_channel",
    "明渠-梯形": "trap_channel",
    "暗涵-矩形": "rect_culvert",
    "暗涵-圆拱直墙型": "rect_culvert_arch",
}


def lining_number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def section_summary_lining(section_kind, saved=None):
    """Use the saved thicknesses over the defaults shared with the summary table."""
    group = saved.get(section_kind) if isinstance(saved, dict) else None
    group = group if isinstance(group, dict) else {}
    return {key: value if (value := lining_number(group.get(key))) is not None else default
            for key, default in SECTION_SUMMARY_LINING_DEFAULTS.get(section_kind, {}).items()}


def gate_reference_lining(section_kind, saved=None):
    values = section_summary_lining(section_kind, saved)
    wall = next((values[key] for key in ("wall_t", "t1", "t") if key in values), None)
    if wall is None:
        return {}
    return {"base_thickness": values.get("t0", wall), "wall_thickness_left": wall, "wall_thickness_right": wall}
