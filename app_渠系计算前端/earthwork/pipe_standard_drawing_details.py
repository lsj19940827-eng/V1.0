"""Features shown by the Tingzikou phase II pipe section drawings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from 土石方计算.services.section_scheme_catalog import encasement_uniform_dimension


@dataclass(frozen=True)
class PipeStandardDrawingDetails:
    surface: Literal["restore_ground", "roadbed", "raised_fill", "river_crossing",
                     "hillside_cut", "hillside_mixed"] = "restore_ground"
    shows_crown_partition: bool = True
    new_fill_slope_ratio: float | None = None
    surface_labels: tuple[str, str] = ("原地面线", "回填线")
    feature_labels: tuple[str, ...] = ()


_HILLSIDE = "tzk_pipe_hillside"
_HILLSIDE_CASES = {"cut": "全挖", "mixed": "半挖半填"}
ENCASEMENT_SIDE = "construction.encasement.side_thickness"
ENCASEMENT_B1_LABEL = "均匀包封厚度 b1"
ENCASEMENT_THICKNESSES = {f"construction.encasement.{face}_thickness"
                         for face in ("left", "right", "top", "bottom", "side")}


def shared_encasement_thickness(asset, scheme):
    if not encasement_uniform_dimension(scheme or {}):
        return False
    encasement = (asset.get("construction") or {}).get("encasement") or {}
    side = encasement.get("side_thickness")
    sides = [encasement.get(f"{face}_thickness") for face in ("left", "right")]
    values = [side if value is None else value for value in sides]
    values.extend(encasement.get(f"{face}_thickness") for face in ("top", "bottom"))
    return len({value for value in values if value is not None}) <= 1


def displayed_pipe_parameters(asset, scheme, paths):
    if shared_encasement_thickness(asset, scheme):
        return list(dict.fromkeys(ENCASEMENT_SIDE if path in ENCASEMENT_THICKNESSES else path for path in paths))
    return list(paths)

# The road drawings mark the subgrade and road surface separately (1353C/1353D,
# 87B0/87B1). Their horizontal boundary at the top of encasement has no 50 cm callout.
_ROADBED = PipeStandardDrawingDetails(
    surface="roadbed",
    shows_crown_partition=False,
    surface_labels=("原路面高程", "路基高程"),
    feature_labels=("按原路面结构恢复",),
)

# Inverted siphon A/E show 1:2 fill slopes and a height limit at the centerline,
# rather than a specified final level (1D107/1D109/1D1D4 and 8C74/8C76/1D372).
_RAISED_FILL = PipeStandardDrawingDetails(
    surface="raised_fill",
    new_fill_slope_ratio=2.0,
    feature_labels=("填筑顶面高差 ≤ 20 cm",),
)

# F/G show a drainage ditch with a lining and refer minimum cover to the pipe
# design (13BA3/13BAF/13BB0 and 14350/1435A/1435B).
_HILLSIDE_FEATURES = ("最小埋深按设计", "C20 排水沟 50×50 cm · 衬厚 20 cm")
_DETAILS = {
    # The 50 cm dimensions start at the pipe's outside crown (130A6, 1CB4B, 131CB).
    "tzk_pipe_a": PipeStandardDrawingDetails(),
    "tzk_pipe_b": PipeStandardDrawingDetails(),
    "tzk_pipe_c": PipeStandardDrawingDetails(),
    "tzk_pipe_d": _ROADBED,
    # E uses the top of its encasement as the drawn reference (139C0).
    "tzk_pipe_e": PipeStandardDrawingDetails(shows_crown_partition=False),
    "tzk_pipe_f": PipeStandardDrawingDetails(
        surface="hillside_cut",
        shows_crown_partition=False,
        feature_labels=_HILLSIDE_FEATURES,
    ),
    "tzk_pipe_g": PipeStandardDrawingDetails(
        surface="hillside_mixed",
        shows_crown_partition=False,
        new_fill_slope_ratio=2.0,
        # G shows a 1:2 fill slope with grid-beam protection and a platform from
        # the pipe centerline to the fill break (14361/14362/14363).
        feature_labels=(*_HILLSIDE_FEATURES, "框格梁护坡", "填筑侧平台宽 ≥ 2 m"),
    ),
    "tzk_pipe_paddy": PipeStandardDrawingDetails(
        # The section marks vertical excavation and temporary sheet piles (1F857/1FBB2).
        feature_labels=("直挖", "钢板桩临时支护"),
    ),
    "tzk_siphon_a": _RAISED_FILL,
    "tzk_siphon_b": PipeStandardDrawingDetails(),
    "tzk_siphon_c": PipeStandardDrawingDetails(
        surface="river_crossing",
        feature_labels=("格宾石笼", "防冲深度按设计"),  # 8A34/1AB22
    ),
    "tzk_siphon_d": _ROADBED,
    "tzk_siphon_e": _RAISED_FILL,
}


def pipe_standard_drawing_details(
    scheme: dict | None, terrain_case: str | None = None
) -> PipeStandardDrawingDetails | None:
    """Return the drafting features of a scheme and its selected terrain case."""
    scheme = scheme or {}
    if scheme.get("drawing_id") not in (None, "tzk"):
        return None
    scheme_id = scheme.get("scheme_id")
    if scheme_id == _HILLSIDE:
        scheme_id = "tzk_pipe_g" if terrain_case == "mixed" else "tzk_pipe_f"
    return _DETAILS.get(scheme_id)


def pipe_standard_drawing_variants(scheme: dict | None) -> tuple[tuple[str, str], ...]:
    """Return only hillside cases that have an original drawing to browse."""
    if not scheme or scheme.get("scheme_id") != _HILLSIDE:
        return ()
    variants = scheme.get("terrain_variants") or {}
    return tuple(
        (key, variants[key].get("label") or label)
        for key, label in _HILLSIDE_CASES.items()
        if variants.get(key, {}).get("source_preview")
    )


def pipe_standard_drawing_source(
    scheme: dict | None, terrain_case: str | None = None
) -> str | dict | None:
    """Resolve the source reference without changing the project's drawing data."""
    if not scheme:
        return None
    if scheme.get("scheme_id") == _HILLSIDE:
        variants = scheme.get("terrain_variants") or {}
        variant = variants.get(terrain_case or "cut") or {}
        if reference := variant.get("source_preview"):
            return reference
    return scheme.get("source_preview")
