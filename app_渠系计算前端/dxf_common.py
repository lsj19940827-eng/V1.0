# -*- coding: utf-8 -*-
"""Shared DXF helpers for section exports."""

from __future__ import annotations

import math
from typing import Iterable


BASE_SECTION_LAYER_DEFS = (
    ("轮廓线", 7, 50),
    ("设计水位", 5, 25),
    ("加大水位", 4, 25),
    ("拉杆控制", 30, 18),
    ("尺寸标注", 2, 18),
    ("参数文字", 3, 18),
)

DEFAULT_SCALE_OPTIONS = ("1:20", "1:50", "1:100", "1:200", "1:500")
DXF_TEXT_WIDTH_FACTOR = 0.7

_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUBSCRIPT_CHARS = set("₀₁₂₃₄₅₆₇₈₉")
_SUPERSCRIPT_MAP = str.maketrans("¹²³⁰⁴⁵⁶⁷⁸⁹", "1230456789")
_SUPERSCRIPT_CHARS = set("¹²³⁰⁴⁵⁶⁷⁸⁹")
_SCRIPT_CHARS = _SUBSCRIPT_CHARS | _SUPERSCRIPT_CHARS


def _prefixed_layer(name: str, layer_prefix: str = "") -> str:
    return f"{layer_prefix}{name}" if layer_prefix else name


def _copy_dxfattribs(dxfattribs=None, *, layer_prefix: str = ""):
    attrs = dict(dxfattribs or {})
    layer_name = attrs.get("layer")
    if layer_name:
        attrs["layer"] = _prefixed_layer(layer_name, layer_prefix)
    return attrs


def has_dxf_script_chars(text: object) -> bool:
    """判断文本是否包含 DXF 需要特殊处理的上下标字符。"""
    if text is None:
        return False
    return any(char in _SCRIPT_CHARS for char in str(text))


def to_dxf_mtext_script(text: object) -> str:
    """把 Unicode 上下标转换成 AutoCAD MTEXT 堆叠控制码。"""
    if text is None:
        return ""
    result = []
    raw_text = str(text)
    idx = 0
    while idx < len(raw_text):
        char = raw_text[idx]
        if char in _SUBSCRIPT_CHARS:
            sub_chars = []
            while idx < len(raw_text) and raw_text[idx] in _SUBSCRIPT_CHARS:
                sub_chars.append(raw_text[idx].translate(_SUBSCRIPT_MAP))
                idx += 1
            result.append("{\\H0.7x;\\S^ " + "".join(sub_chars) + ";}")
            continue
        if char in _SUPERSCRIPT_CHARS:
            sup_chars = []
            while idx < len(raw_text) and raw_text[idx] in _SUPERSCRIPT_CHARS:
                sup_chars.append(raw_text[idx].translate(_SUPERSCRIPT_MAP))
                idx += 1
            result.append("{\\H0.7x;\\S" + "".join(sup_chars) + "^ ;}")
            continue
        result.append(char)
        idx += 1
    return "".join(result)


def add_centered_dxf_text(
    msp,
    text: object,
    cx: float,
    cy: float,
    height: float,
    layer: str = "参数文字",
    style: str = "FANGSONG",
):
    """在单元格中心写入 DXF 文字，含上下标时使用 MTEXT。"""
    text = str(text)
    attrs = {"layer": layer, "char_height": float(height), "style": style}
    if has_dxf_script_chars(text):
        draw_msp = msp
        insert = (float(cx), float(cy))
        if isinstance(msp, TrackedSectionMsp):
            draw_msp = msp._msp
            attrs = _copy_dxfattribs(attrs, layer_prefix=msp.layer_prefix)
            insert = msp._apply_point(insert)
            msp._track_text_box(
                text,
                {"align_point": (float(cx), float(cy)), "height": float(height), "halign": 1},
            )
        entity = draw_msp.add_mtext(to_dxf_mtext_script(text), dxfattribs=attrs)
        entity.set_location(insert=insert, attachment_point=5)
        return entity
    return msp.add_text(
        text,
        dxfattribs={
            "layer": layer,
            "height": float(height),
            "width": DXF_TEXT_WIDTH_FACTOR,
            "style": style,
            "insert": (float(cx), float(cy)),
            "align_point": (float(cx), float(cy)),
            "halign": 1,
            "valign": 2,
        },
    )


def _point_tuple(point):
    return (float(point[0]), float(point[1]))


def _arc_bbox(center, radius, start_angle, end_angle):
    cx, cy = _point_tuple(center)
    r = float(radius)
    start = float(start_angle) % 360.0
    end = float(end_angle) % 360.0

    def _in_sweep(angle):
        angle = float(angle) % 360.0
        if start <= end:
            return start <= angle <= end
        return angle >= start or angle <= end

    def _pt(angle):
        rad = math.radians(angle)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))

    samples = [_pt(start), _pt(end)]
    for angle in (0.0, 90.0, 180.0, 270.0):
        if _in_sweep(angle):
            samples.append(_pt(angle))
    xs = [pt[0] for pt in samples]
    ys = [pt[1] for pt in samples]
    return (min(xs), min(ys), max(xs), max(ys))


class _NullTextEntity:
    def set_placement(self, *_args, **_kwargs):
        return self


class _NullMTextEntity:
    def set_location(self, *_args, **_kwargs):
        return self


class _NullDimensionEntity:
    def render(self):
        return self


class _NullModelspace:
    def add_line(self, *_args, **_kwargs):
        return None

    def add_lwpolyline(self, *_args, **_kwargs):
        return None

    def add_circle(self, *_args, **_kwargs):
        return None

    def add_arc(self, *_args, **_kwargs):
        return None

    def add_text(self, *_args, **_kwargs):
        return _NullTextEntity()

    def add_mtext(self, *_args, **_kwargs):
        return _NullMTextEntity()

    def add_linear_dim(self, *_args, **_kwargs):
        return _NullDimensionEntity()


def create_measurement_msp(layer_prefix: str = ""):
    return TrackedSectionMsp(_NullModelspace(), layer_prefix=layer_prefix)


class _TrackedTextEntity:
    def __init__(self, entity, tracker: "TrackedSectionMsp"):
        self._entity = entity
        self._tracker = tracker

    def set_placement(self, point, align=None):
        self._tracker._track_text_box(
            "",
            {"align_point": point, "halign": 1 if align is not None else 0, "height": 3.5},
        )
        point = self._tracker._apply_point(point)
        if align is not None:
            return self._entity.set_placement(point, align=align)
        return self._entity.set_placement(point)


class TrackedSectionMsp:
    """Wrap a modelspace and keep local drawing bounds with optional offsets."""

    def __init__(self, msp, ox: float = 0.0, oy: float = 0.0, layer_prefix: str = ""):
        self._msp = msp
        self._ox = float(ox)
        self._oy = float(oy)
        self._layer_prefix = layer_prefix
        self._min_x = None
        self._min_y = None
        self._max_x = None
        self._max_y = None

    @property
    def layer_prefix(self) -> str:
        return self._layer_prefix

    def _apply_point(self, point):
        x, y = _point_tuple(point)
        return (x + self._ox, y + self._oy)

    def _track_point(self, point):
        x, y = _point_tuple(point)
        if self._min_x is None:
            self._min_x = self._max_x = x
            self._min_y = self._max_y = y
            return
        self._min_x = min(self._min_x, x)
        self._min_y = min(self._min_y, y)
        self._max_x = max(self._max_x, x)
        self._max_y = max(self._max_y, y)

    def _track_bbox(self, x1, y1, x2, y2):
        self._track_point((x1, y1))
        self._track_point((x2, y2))

    def _track_text_box(self, text, dxfattribs=None):
        attrs = dict(dxfattribs or {})
        height = float(attrs.get("height", 3.5) or 3.5)
        width_factor = float(attrs.get("width", DXF_TEXT_WIDTH_FACTOR) or DXF_TEXT_WIDTH_FACTOR)
        anchor = attrs.get("align_point") or attrs.get("insert") or (0.0, 0.0)
        x, y = _point_tuple(anchor)
        width = max(len(str(text)), 1) * height * width_factor
        halign = int(attrs.get("halign", 0) or 0)
        if halign == 1:
            x1, x2 = x - width / 2.0, x + width / 2.0
        elif halign == 2:
            x1, x2 = x - width, x
        else:
            x1, x2 = x, x + width
        self._track_bbox(x1, y - height, x2, y + height)

    def local_bounds(self):
        if self._min_x is None:
            return (0.0, 0.0, 0.0, 0.0)
        return (self._min_x, self._min_y, self._max_x, self._max_y)

    def size(self):
        min_x, min_y, max_x, max_y = self.local_bounds()
        return (max_x - min_x, max_y - min_y)

    def add_line(self, start, end, dxfattribs=None):
        self._track_point(start)
        self._track_point(end)
        return self._msp.add_line(
            self._apply_point(start),
            self._apply_point(end),
            dxfattribs=_copy_dxfattribs(dxfattribs, layer_prefix=self._layer_prefix),
        )

    def add_lwpolyline(self, points: Iterable, dxfattribs=None):
        local_points = [_point_tuple(point) for point in points]
        for point in local_points:
            self._track_point(point)
        return self._msp.add_lwpolyline(
            [self._apply_point(point) for point in local_points],
            dxfattribs=_copy_dxfattribs(dxfattribs, layer_prefix=self._layer_prefix),
        )

    def add_circle(self, center, radius, dxfattribs=None):
        cx, cy = _point_tuple(center)
        r = float(radius)
        self._track_bbox(cx - r, cy - r, cx + r, cy + r)
        return self._msp.add_circle(
            self._apply_point(center),
            r,
            dxfattribs=_copy_dxfattribs(dxfattribs, layer_prefix=self._layer_prefix),
        )

    def add_arc(self, center, radius, start_angle, end_angle, dxfattribs=None):
        self._track_bbox(*_arc_bbox(center, radius, start_angle, end_angle))
        return self._msp.add_arc(
            self._apply_point(center),
            float(radius),
            float(start_angle),
            float(end_angle),
            dxfattribs=_copy_dxfattribs(dxfattribs, layer_prefix=self._layer_prefix),
        )

    def add_text(self, text, dxfattribs=None):
        attrs = _copy_dxfattribs(dxfattribs, layer_prefix=self._layer_prefix)
        attrs.setdefault("width", DXF_TEXT_WIDTH_FACTOR)
        if "insert" in attrs:
            attrs["insert"] = self._apply_point(attrs["insert"])
        if "align_point" in attrs:
            attrs["align_point"] = self._apply_point(attrs["align_point"])
        self._track_text_box(text, dxfattribs or {})
        entity = self._msp.add_text(text, dxfattribs=attrs)
        return _TrackedTextEntity(entity, self)

    def add_linear_dim(self, *args, **kwargs):
        args = list(args)
        if args:
            args[0] = self._apply_point(args[0])
        kwargs = dict(kwargs)
        for key in ("base", "p1", "p2"):
            if key in kwargs:
                self._track_point(kwargs[key])
                kwargs[key] = self._apply_point(kwargs[key])
        if len(args) >= 3:
            self._track_point(args[0])
            self._track_point(args[1])
            self._track_point(args[2])
            args[1] = self._apply_point(args[1])
            args[2] = self._apply_point(args[2])
        kwargs["dxfattribs"] = _copy_dxfattribs(
            kwargs.get("dxfattribs"),
            layer_prefix=self._layer_prefix,
        )
        return self._msp.add_linear_dim(*args, **kwargs)


def ensure_tracked_msp(msp, *, layer_prefix: str = ""):
    if isinstance(msp, TrackedSectionMsp):
        return msp
    return TrackedSectionMsp(msp, layer_prefix=layer_prefix)


def _add_layer(doc, name, color, lw):
    layer_name = str(name)
    if layer_name in doc.layers:
        layer = doc.layers.get(layer_name)
        layer.color = color
        layer.lineweight = lw
        return layer
    layer = doc.layers.add(layer_name)
    layer.color = color
    layer.lineweight = lw
    return layer


def _setup_font_style(doc):
    """Register the shared section-font and dimension styles."""
    if "FANGSONG" not in doc.styles:
        style = doc.styles.add("FANGSONG", font="仿宋_GB2312")
    else:
        style = doc.styles.get("FANGSONG")
    style.dxf.width = DXF_TEXT_WIDTH_FACTOR
    if "CAD_DIM" not in doc.dimstyles:
        ds = doc.dimstyles.new("CAD_DIM")
        ds.dxf.dimtxsty = "FANGSONG"
        ds.dxf.dimtxt = 3.5
        ds.dxf.dimasz = 2.5
        ds.dxf.dimexo = 2.0
        ds.dxf.dimexe = 2.0
        ds.dxf.dimgap = 1.0
        ds.dxf.dimlunit = 2
        ds.dxf.dimdec = 3


def ensure_section_dxf_layers(doc, layer_prefix: str = ""):
    for name, color, lineweight in BASE_SECTION_LAYER_DEFS:
        _add_layer(doc, _prefixed_layer(name, layer_prefix), color, lineweight)
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern="A,.5,-.25")
    _setup_font_style(doc)


def setup_section_dxf_document(doc, scale_denom=100, layer_prefix: str = ""):
    sf = 1000.0 / float(scale_denom)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LTSCALE"] = sf * 0.5
    ensure_section_dxf_layers(doc, layer_prefix=layer_prefix)
    return sf


def _add_dim_h(msp, x1, x2, y_line, y_orig, label, txt_h, arr, layer):
    dim = msp.add_linear_dim(
        base=((x1 + x2) / 2.0, y_line),
        p1=(x1, y_orig),
        p2=(x2, y_orig),
        text=label,
        dimstyle="CAD_DIM",
        dxfattribs={"layer": layer},
    )
    dim.render()


def _add_dim_v(msp, y1, y2, x_line, x_orig, label, txt_h, arr, layer):
    dim = msp.add_linear_dim(
        base=(x_line, (y1 + y2) / 2.0),
        p1=(x_orig, y1),
        p2=(x_orig, y2),
        angle=90,
        text=label,
        dimstyle="CAD_DIM",
        dxfattribs={"layer": layer},
    )
    dim.render()


def _add_text_block(msp, x, y_start, lines, txt_h, layer):
    h_title = txt_h * 2.0
    h_section = round(txt_h / 0.7, 1)
    h_body = txt_h
    for line in lines:
        if not line:
            y_start -= h_body * 0.8
            continue
        is_main = line.startswith("【")
        is_section = line.startswith("[")
        if is_main:
            height = h_title
            indent = 0.0
        elif is_section:
            height = h_section
            indent = 0.0
        else:
            height = h_body
            indent = txt_h * 0.5
        msp.add_text(
            line,
            dxfattribs={
                "layer": layer,
                "height": height,
                "style": "FANGSONG",
                "width": DXF_TEXT_WIDTH_FACTOR,
                "insert": (x + indent, y_start),
            },
        )
        y_start -= height * 1.5


def add_case_title(msp, title, *, layer="参数文字", height=5.0, top_gap=12.0):
    if not title:
        return
    tracked = ensure_tracked_msp(msp)
    min_x, _min_y, max_x, max_y = tracked.local_bounds()
    center_x = (min_x + max_x) / 2.0
    title_y = max_y + top_gap
    tracked.add_text(
        title,
        dxfattribs={
            "layer": layer,
            "height": float(height),
            "style": "FANGSONG",
            "insert": (center_x, title_y),
            "align_point": (center_x, title_y),
            "halign": 1,
        },
    )


def compute_auto_grid(count: int):
    count = max(1, int(count))
    ncols = int(math.ceil(math.sqrt(count)))
    nrows = int(math.ceil(count / ncols))
    return ncols, nrows
