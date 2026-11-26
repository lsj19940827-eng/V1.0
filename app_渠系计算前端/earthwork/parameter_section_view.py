"""Interactive, dimensioned section of the currently adopted construction."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsSimpleTextItem
from shapely.geometry import box
from 土石方计算.services.dedicated_structure_geometry import TUNNEL_TYPES
from 土石方计算.services.pipe_construction_defaults import PIPE_BACKFILL_HEIGHT_PATH
from 土石方计算.services.pipe_dimensions import CONSTRUCTION_WALL, MATERIAL_OUTER
from 土石方计算.services.section_scheme_catalog import drawing_workspace_dimension, encasement_uniform_dimension
from 土石方计算.services.section_scheme_components import PROFILE_FIELDS

from .parameter_section_geometry import PIPE_COVER_TARGETS, parameter_geometry, supports_parameter_section
from .pipe_standard_drawing_details import (
    ENCASEMENT_B1_LABEL, ENCASEMENT_SIDE, displayed_pipe_parameters, shared_encasement_thickness,
)
from .section_scheme_view import SectionSchemeView


_INK = "#28485B"
_DIM = "#3D687B"
_ACTIVE = "#BA4D17"
_ROLE = {
    "pipe": ("管身", "#C7DCEC", "#477997"),
    "concrete": ("结构", "#CCD9E1", "#547389"),
    "pipe_seat": ("管座", "#B6D5CC", "#467C70"),
    "pipe_encasement": ("包封", "#B6D5CC", "#467C70"),
    "bedding": ("垫层", "#F3DAA7", "#997432"),
    "foundation_replacement": ("换填", "#DBCBB8", "#8A6E51"),
    "component": ("材料", "#DCCFE6", "#7C668B"),
    "manual_backfill": ("土石回填（人工夯填）", "#E7CAB8", "#92664E"),
    "mechanical_backfill": ("土石填筑（机械夯填）", "#DAE6D5", "#637E58"),
    "embankment": ("新增填筑", "#CFE4E8", "#567D87"),
}
_WIDTH = "construction.foundation_replacement_width"
_DEPTH = "construction.foundation_replacement_thickness"
_SLOPE = "construction.foundation_replacement.side_slope"
_FINISH_DEPTH = "construction.final_cover_depth"
_FINISH_EDGE = "#405E67"


def _fmt(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "待补"
    return (f"{number:.6f}".rstrip("0").rstrip(".") or "0") if math.isfinite(number) else "待补"


def _graphic_path(shape, point):
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    def add(part):
        if part.is_empty:
            return
        if part.geom_type == "Polygon":
            for ring in (part.exterior, *part.interiors):
                coords = iter(ring.coords)
                path.moveTo(point(*next(coords)))
                for xy in coords:
                    path.lineTo(point(*xy))
                path.closeSubpath()
        elif part.geom_type in {"LineString", "LinearRing"}:
            coords = iter(part.coords)
            path.moveTo(point(*next(coords)))
            for xy in coords:
                path.lineTo(point(*xy))
        elif hasattr(part, "geoms"):
            for child in part.geoms:
                add(child)
    add(shape)
    return path


class _ParameterEdge(QGraphicsPathItem):
    """Thin drafting line with a wider pointer target at the fitted scale."""
    def shape(self):
        stroke = QPainterPathStroker()
        stroke.setWidth(9)
        return stroke.createStroke(self.path())

    def boundingRect(self):
        return super().boundingRect().adjusted(-4.5,-4.5,4.5,4.5)


class ParameterSectionView(SectionSchemeView):
    parameterRequested = Signal(str)

    def __init__(self, parent=None, *, show_pipe_trench=False):
        super().__init__(parent)
        self._show_pipe_trench = show_pipe_trench
        self._pipe_terrain_case = None
        self._last_parameters = None
        self.setMinimumSize(230, 165)
        self.setAccessibleName("当前参数构造断面")
        self.setToolTip("点击尺寸或材料定位参数，滚轮缩放，按住拖动平移")
        self._selected_path = ""
        self._items = []
        self._details = {}
        self._overlay = []
        self._default_dimensions = []
        self._angles = {}
        self._gaps = []
        self._press_position = None
        self.geometry_model = None
        self.set_section_parameters({})

    def _bind(self, item, primary, related=(), title=""):
        if not primary:
            return item
        item.setData(0, primary)
        if title:
            item.setToolTip(title)
        item.setCursor(Qt.PointingHandCursor)
        original = item.brush() if isinstance(item, QGraphicsSimpleTextItem) else item.pen()
        self._items.append((item, (primary, *related), original))
        return item

    def _label(self, text, pos, *, center=False, color=_INK, path="", related=(), bold=False):
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(bold)
        item = self.scene().addSimpleText(text, font)
        item.setBrush(QBrush(QColor(color)))
        rect = item.boundingRect()
        item.setPos(pos - (QPointF(rect.width()/2, rect.height()/2) if center else QPointF()))
        item.setZValue(8)
        return self._bind(item, path, related, text)

    def _place_label(self, item, *, outward=0):
        layer = self.geometry_model.pipe_backfill if self.geometry_model else None
        if layer is None or layer.completion is None:
            return False
        bounds = item.sceneBoundingRect()
        occupied = [other.sceneBoundingRect().adjusted(-4, -3, 4, 3)
                    for other in self.scene().items()
                    if other is not item and isinstance(other, QGraphicsSimpleTextItem) and other.isVisible()]
        if not any(bounds.intersects(rect) for rect in occupied):
            return False
        row = bounds.height() + 4
        sidestep = outward * (bounds.width() / 2 + 6)
        offsets = (QPointF(sidestep, 0), QPointF(0, -row), QPointF(0, row),
                   QPointF(sidestep, -row), QPointF(sidestep, row))
        for offset in offsets:
            if not any(bounds.translated(offset).intersects(rect) for rect in occupied):
                item.setPos(item.pos() + offset)
                return True
        top = min(rect.top() for rect in occupied if rect.right() >= bounds.left() and rect.left() <= bounds.right())
        item.moveBy(0, top - bounds.bottom() - 1)
        return True

    def _stroke(self, points, path="", *, color=_DIM, width=1., style=Qt.SolidLine, related=(), z=4):
        curve = QPainterPath(points[0])
        for point in points[1:]:
            curve.lineTo(point)
        item = self.scene().addPath(curve, self._pen(color, width, style))
        item.setZValue(z)
        return self._bind(item, path, related)

    def _leader(self, origin, label, path, *, color=_DIM, related=()):
        bounds = label.sceneBoundingRect().adjusted(-2, -1, 2, 1)
        end = QPointF(max(bounds.left(), min(origin.x(), bounds.right())),
                      max(bounds.top(), min(origin.y(), bounds.bottom())))
        if (end - origin).manhattanLength() > 2:
            return self._stroke([origin, end], path, color=color, related=related, z=5)

    def _region(self, shape, role, field, related=(), *, fill=True, z=1, provisional=False, outline=True):
        if shape is None or shape.is_empty:
            return
        title, tint, edge = _ROLE.get(role, _ROLE["component"])
        brush = QBrush(QColor(tint), Qt.BDiagPattern if provisional else Qt.SolidPattern) if fill else QBrush(Qt.NoBrush)
        pen = self._pen(edge, 1.4, Qt.DashLine if provisional else Qt.SolidLine) if outline else Qt.NoPen
        item = self.scene().addPath(_graphic_path(shape, self._point), pen, brush)
        item.setZValue(z)
        return self._bind(item, field, related, title)

    def _measurement(self, endpoints, label, path, related=(), *, active=False, extension=None, outward=0):
        first, last = [self._point(*xy) for xy in endpoints]
        color = _ACTIVE if active else _DIM
        a, b = (first + extension, last + extension) if extension is not None else (first, last)
        items = []
        ends = [(a, first)]
        if a != b:
            items.append(self._stroke([a, b], path, related=related, color=color, z=5))
            ends.append((b, last))
        for p, actual in ends:
            if p != actual:
                items.append(self._stroke([actual, p], path, related=related, color=color, width=.7, z=5))
            items.append(self._stroke([p-QPointF(2.8, -3), p+QPointF(2.8, -3)], path, related=related, color=color, z=5))
        vertical = bool(extension.x()) if extension is not None else abs(a.x()-b.x()) < abs(a.y()-b.y())
        anchor = (a+b)/2
        if vertical and extension is not None:
            anchor = a*.75 + b*.25
            text = self._label(label, anchor, center=True, color=color, path=path, related=related, bold=active)
            text.moveBy(outward * (text.boundingRect().width()/2 + 6), 0)
        else:
            center = anchor + (QPointF(8, 0) if vertical else QPointF(0, -10))
            text = self._label(label, center, center=not vertical, color=color, path=path, related=related, bold=active)
        if self._place_label(text, outward=outward):
            leader = self._leader(anchor, text, path, color=color, related=related)
            if leader is not None:
                items.append(leader)
        # An opaque label background keeps dimensions readable over material hatching and edges.
        backing = self.scene().addRect(text.sceneBoundingRect().adjusted(-2, 0, 2, 0), Qt.NoPen, QBrush(QColor("#FDFEFE")))
        backing.setZValue(7)
        items.extend((text, backing))
        return items

    def _detail(self, path, endpoints, label, *aliases):
        for key in (path, *aliases):
            self._details[key] = (endpoints, label)

    def _edge_target(self, points, path, title, color):
        curve = QPainterPath(self._point(*points[0]))
        for p in points[1:]:
            curve.lineTo(self._point(*p))
        item = _ParameterEdge(curve)
        item.setPen(self._pen(color, 1.1))
        item.setZValue(4.5)
        self.scene().addItem(item)
        self._bind(item, path, title=title)

    def _pipe_body(self, s):
        outer, opening = s["outer"], s["net_void"]
        _, bottom, _, top = outer.bounds
        for i, (pipe, (cx, cz)) in enumerate(zip(s["pipes"], s["pipe_centers"]), 1):
            od = pipe["outer_diameter"]
            radius = od/2
            actual_radius = (pipe.get(MATERIAL_OUTER) or od) / 2
            prefix = f"section.pipes[{i}]."
            primary = prefix + "outer_diameter"
            fields = ("outer_diameter", "inner_diameter", "wall_thickness", "lining_thickness",
                      "nominal_diameter_m", CONSTRUCTION_WALL, "material", "lining_material", "earthwork_envelope_only")
            aliases = ["section.pipe_count", "section.pipes", *(prefix + key for key in fields)]
            if i == 1:
                aliases.extend("section." + key for key in fields)
            clip = box(cx-radius, bottom-1, cx+radius, top+1)
            outside = outer.intersection(clip)
            inside = opening.intersection(clip)
            envelope = pipe.get("earthwork_envelope_only")
            body = outside if envelope else outside.difference(inside)
            if not envelope and actual_radius < radius - 1e-8:
                self._region(outside, "pipe", primary, aliases, fill=False, provisional=True, z=3)
                body = s["pipe_material_regions"][i-1].union(s["pipe_wall_regions"][i-1])
                body = body.union(s["pipe_lining_regions"][i-1])
            self._region(body, "pipe", primary, aliases, fill=not envelope, z=3)
            if pipe.get("lining_thickness"):
                # The quantity engine already splits the lining off the pipe wall.
                lining = s.get("pipe_lining_regions", [])[i-1]
                self._region(lining, "component", prefix+"lining_thickness", [prefix+"lining_material"], z=3.2)
            od_points = ((cx-radius, cz), (cx+radius, cz))
            self._detail(primary, od_points, "外径 " + _fmt(od) + " m", prefix+"nominal_diameter_m",
                         *(("section.outer_diameter", "section.nominal_diameter_m") if i == 1 else ()))
            if not envelope:
                for field, title, start, end in (
                    ("inner_diameter", "内径", cx-pipe["inner_diameter"]/2, cx+pipe["inner_diameter"]/2),
                    ("wall_thickness", "壁厚", cx+actual_radius-pipe["wall_thickness"], cx+actual_radius),
                    ("lining_thickness", "衬厚", cx+pipe["inner_diameter"]/2, cx+actual_radius-pipe["wall_thickness"]),
                ):
                    self._detail(prefix+field, ((start,cz),(end,cz)), title+" "+_fmt(end-start)+" m",
                                 *(("section."+field,) if i == 1 else ()))
            if len(s["pipes"]) == 1 or od*self._scale > 74:
                dimension = self._measurement(od_points, "Ø " + _fmt(od) + " m", primary, related=aliases)
                self._default_dimensions.append(dimension)
            if i < len(s["pipes"]):
                nxt = s["pipes"][i]
                x1, x2 = cx+radius, s["pipe_centers"][i][0]-nxt["outer_diameter"]/2
                self._gaps.append((((x1,cz),(x2,cz)), "净距 "+_fmt(x2-x1)+" m"))

    def _structure_body(self, s, section):
        outer, void = s.get("outer"), s.get("net_void")
        if s.get("pipes"):
            self._pipe_body(s)
            return
        kind = s["section_type"]
        path = "section.wall_thickness_left" if section.get("wall_thickness_left") is not None else "section.wall_thickness"
        if kind in TUNNEL_TYPES:
            path = "section.lining_thickness"
        aliases = ["section." + key for key in section if isinstance(section[key], (int, float))]
        for role, area in s.get("materials", {}).items():
            if role == "concrete":
                self._region(area, "concrete", path, aliases, z=2)
        if void is None or void.is_empty:
            if outer is not None:
                self._region(outer, "concrete", "section.foundation_width", aliases)
            return
        left, base, right, crest = void.bounds
        opening_path = ("section.inner_radius" if kind in {"u_channel","aqueduct_u","horseshoe_tunnel"} else
                        "section.inner_diameter" if kind in {"circular_tunnel","flat_bottom_tunnel"} else "section.inner_width")
        if outer is None or not outer.difference(void).area:
            outline = void
            if kind.endswith("channel") or kind.startswith("aqueduct"):
                from 土石方计算.services.section_geometry import _component_surface
                outline = _component_surface(void, open_crown=True)
            self._region(outline, "concrete", opening_path, aliases, fill=False)
        h = crest-base
        width_types = {"rectangular_culvert","arch_culvert","rectangular_channel","trapezoidal_channel",
                       "compound_trapezoidal_channel","aqueduct_rectangular","arch_tunnel"}
        if kind in width_types and section.get("inner_width"):
            width = float(section["inner_width"])
            x = (left+right)/2 if not s.get("section_type","").endswith("channel") else 0.
            y = base+h*.40 if kind in {"rectangular_culvert","rectangular_channel","aqueduct_rectangular"} else base
            points = ((x-width/2,y),(x+width/2,y))
            self._default_dimensions.append(self._measurement(points, "净宽 "+_fmt(width)+" m", "section.inner_width"))
            self._detail("section.inner_width", points, "净宽 "+_fmt(width)+" m")
        elif kind in {"u_channel", "aqueduct_u"} and section.get("inner_radius"):
            radius = float(section["inner_radius"])
            points = ((0,base), (0,base+radius))
            self._default_dimensions.append(self._measurement(points, "R "+_fmt(radius)+" m", opening_path))
            self._detail(opening_path, points, "R "+_fmt(radius)+" m")
        elif kind == "circular_tunnel":
            points = ((left,(base+crest)/2),(right,(base+crest)/2))
            self._default_dimensions.append(self._measurement(points, "净径 "+_fmt(right-left)+" m", opening_path))
            self._detail(opening_path, points, "净径 "+_fmt(right-left)+" m")
        elif kind in {"horseshoe_tunnel", "flat_bottom_tunnel"}:
            # Both profiles are controlled by several real arcs. Their outside
            # bounding width must not be reported as a bottom width or diameter.
            self._default_dimensions.append(self._measurement(((0,base),(0,crest)), "净高 "+_fmt(h)+" m", opening_path))
        self._detail("section.inner_height", ((0,base),(0,crest)), "净高 "+_fmt(h)+" m")
        if outer is not None:
            a, b, d, e = outer.bounds
            for field, endpoints, label in (
                ("base_thickness", ((0,b),(0,base)), "底厚"),
                ("roof_thickness", ((0,crest),(0,e)), "顶厚"),
                ("wall_thickness_left", ((a,base),(left,base)), "左墙"),
                ("wall_thickness_right", ((right,base),(d,base)), "右墙"),
            ):
                if section.get(field) is not None and kind in {"rectangular_culvert","rectangular_channel","aqueduct_rectangular"}:
                    self._detail("section."+field, endpoints, label+" "+_fmt(section[field])+" m")

    def _materials(self, model, scheme):
        s, c = model.structure, model.construction
        legend = []
        if "outer" not in s:
            return legend
        left, base, right, crest = s["outer"].bounds
        cx = (left+right)/2
        regions = {key: (spec.get("name") or "构造材料", spec["geometry"]) for key, spec in s.get("component_regions", {}).items()}
        bedding = s.get("materials", {}).get("bedding")
        if bedding is not None and not bedding.is_empty:
            regions["bedding"] = ("垫层", bedding)
        for role, (name, area) in regions.items():
            if area.is_empty:
                continue
            al, ab, ar, at = area.bounds
            aliases = []
            if role == "pipe_seat":
                prefix = "construction.pipe_seat."
                seat = c.get("pipe_seat") or c.get("pipe_support") or {}
                path = prefix+"base_thickness"
                aliases = [prefix+k for k in seat]
                thickness = seat.get("base_thickness", 0)
                self._detail(path, ((cx,ab),(cx,base)), "座底 "+_fmt(thickness)+" m")
                if len(s.get("pipes", [])) == 1:
                    self._detail(prefix+"bottom_width", ((al,ab),(ar,ab)), "座宽 "+_fmt(ar-al)+" m", prefix+"bottom_width_mode")
                    self._edge_target(((al,ab),(ar,ab)), prefix+"bottom_width_mode", "管座底宽", _ROLE[role][2])
                    angle = seat.get("support_angle")
                    if angle and seat.get("height") is None:
                        radius = s["pipes"][0]["outer_diameter"]/2
                        x, z = s["pipe_centers"][0]
                        self._angles[prefix+"support_angle"] = (x,z,radius,float(angle))
                    extension = seat.get("extension")
                    if extension is not None and seat.get("bottom_width_mode") in {"support_chord_plus_sides","inner_diameter_offset"}:
                        self._detail(prefix+"extension", ((ar-float(extension),ab),(ar,ab)), "单侧外伸 "+_fmt(extension)+" m")
                grade = seat.get("grade")
                name = (f"{grade} 管座" if grade and model.drawing_details else "管座") + (
                    "  " + _fmt(seat["support_angle"]) + "°" if seat.get("support_angle") else ""
                )
            elif role == "pipe_encasement":
                prefix = "construction.encasement."
                path = prefix+"top_thickness"
                mid = (base+crest)/2
                for field, points, title, value in (
                    ("top_thickness", ((cx,crest),(cx,at)), "顶厚", at-crest),
                    ("bottom_thickness", ((cx,ab),(cx,base)), "底厚", base-ab),
                    ("left_thickness", ((al,mid),(left,mid)), "左厚", left-al),
                    ("right_thickness", ((right,mid),(ar,mid)), "右厚", ar-right),
                ):
                    aliases.append(prefix+field)
                    self._detail(prefix+field, points, title+" "+_fmt(value)+" m",
                                 *((prefix+"side_thickness",) if field == "left_thickness" else ()))
                aliases.extend((prefix+"side_thickness",prefix+"enabled"))
                name = "包封  "+_fmt(at-crest)+" m 顶厚"
                shared = encasement_uniform_dimension(scheme)
                if shared and all(math.isclose(at-crest, v, abs_tol=1e-8) for v in (base-ab,left-al,ar-right)):
                    name = "包封  "+shared+" "+_fmt(at-crest)+" m"
                    self._detail(prefix+"side_thickness", ((cx,crest),(cx,at)), shared+" "+_fmt(at-crest)+" m",
                                 prefix+"top_thickness",prefix+"bottom_thickness",prefix+"left_thickness",prefix+"right_thickness")
                for field, edge in (("top_thickness",((al,at),(ar,at))), ("bottom_thickness",((al,ab),(ar,ab))),
                                    ("left_thickness",((al,ab),(al,at))), ("right_thickness",((ar,ab),(ar,at)))):
                    self._edge_target(edge, prefix+field, self._details[prefix+field][1], _ROLE[role][2])
                grade = (c.get("encasement") or c.get("pipe_encasement") or {}).get("grade")
                if grade and model.drawing_details:
                    name = grade + " " + name
            elif role == "foundation_replacement":
                path = _DEPTH
                aliases = [_WIDTH, _SLOPE, "construction.foundation_replacement.thickness", "construction.foundation_replacement.width"]
                self._detail(path, ((cx,ab),(cx,at)), "换填厚 "+_fmt(at-ab)+" m", aliases[2])
                self._detail(_WIDTH, ((al,at),(ar,at)), "上宽 "+_fmt(ar-al)+" m", aliases[3])
                slope = float((c.get("foundation_replacement") or {}).get("side_slope") or 0)
                self._detail(_SLOPE, ((al,at),(al+(at-ab)*slope,ab)), "收坡 1∶"+_fmt(slope))
                self._edge_target(((al,at),(ar,at)), _WIDTH, "换填上宽", _ROLE[role][2])
                self._edge_target(((al,at),(al+(at-ab)*slope,ab)), _SLOPE, "换填收坡", _ROLE[role][2])
                self._edge_target(((ar,at),(ar-(at-ab)*slope,ab)), _SLOPE, "换填收坡", _ROLE[role][2])
                material = s["component_regions"][role].get("material")
                name = ("石渣换填" if material == "rockfill" and model.drawing_details else "换填") + "  " + _fmt(at-ab) + " m"
            elif role == "bedding":
                path = "construction.bedding_thickness"
                aliases = ["construction.bedding_extension", "construction.bedding_reference"]
                thickness = c.get("bedding_thickness")
                if thickness:
                    bottom = ab if c.get("bedding_reference") == "pipe_seat_bottom" else base-float(thickness)
                    self._detail(path, ((cx,bottom),(cx,bottom+float(thickness))), "垫厚 "+_fmt(thickness)+" m")
                    name = "垫层  "+_fmt(thickness)+" m"
                seat = c.get("pipe_seat") or c.get("pipe_support") or {}
                if seat.get("enabled", True) and seat.get("material_role") == "bedding":
                    prefix = "construction.pipe_seat."
                    path = prefix+"base_thickness"
                    aliases = ["construction.bedding_thickness", *aliases] if thickness else []
                    aliases.extend(prefix+k for k in seat)
                    depth = float(seat.get("base_thickness") or 0)
                    self._detail(path, ((cx,base-depth),(cx,base)), "底厚 "+_fmt(depth)+" m")
                    name = (seat.get("name") or "包角垫层") + "  " +_fmt(depth)+" m"
                    angle = seat.get("support_angle")
                    if angle and model.drawing_details:
                        name += " / " + _fmt(angle) + "°"
                    if angle and len(s.get("pipes", ())) == 1 and (seat.get("height") is None or seat.get("bottom_width_mode") == "trench_bottom"):
                        x, z = s["pipe_centers"][0]
                        self._angles[prefix+"support_angle"] = (x, z, s["pipes"][0]["outer_diameter"]/2, float(angle))
            else:
                profile = next((field for field,(cid,_,_) in PROFILE_FIELDS.items() if cid == role), None)
                path = "section."+profile if profile else "section.component_specs"
                if role == "tunnel_shotcrete":
                    path = "section.shotcrete_thickness"
            provisional = role == "bedding" and bool(s.get("bedding_excavation_closure"))
            item = self._region(area, role, path, aliases, provisional=provisional)
            title, tint, edge = _ROLE.get(role, _ROLE["component"])
            if item:
                item.setToolTip(name)
            legend.append((name, path, aliases, tint, edge))
        for spec in s.get("component_surfaces", {}).values():
            self._region(spec["geometry"], "component", "section.component_specs", fill=False, z=4)
        return legend

    def _edges(self, model, scheme):
        if model.floor:
            self._stroke([self._point(*p) for p in model.floor], color="#698278", width=1.15, style=Qt.DashLine)
        if model.trench_top:
            self._pipe_surfaces(model)
        for side, (points, grades) in model.slopes.items():
            name = "左" if side == "left" else "右"
            staged = model.construction.get("excavation_stages_"+side)
            path = "construction.excavation_" + ("stages_" if staged else "slope_") + side
            self._stroke([self._point(*xy) for xy in points], path, color="#43816F", style=Qt.DashLine, width=1.6)
            p = self._point(*points[-1])
            label = self._label(name+"坡 "+"/".join("1∶"+_fmt(g) for g in grades), p+QPointF(0,-12),
                                center=True, color="#386C5E", path=path)
            if self._place_label(label, outward=-1 if side == "left" else 1):
                self._leader(p, label, path, color="#386C5E")
        spaces = model.work_spaces
        shared_space = drawing_workspace_dimension(scheme)
        if len(spaces) != 2 or not math.isclose(abs(spaces["left"][1]-spaces["left"][0]), abs(spaces["right"][1]-spaces["right"][0]), abs_tol=1e-8):
            shared_space = None
        for side, (a,b,z) in spaces.items():
            if a == b:
                continue
            name = "左" if side == "left" else "右"
            path = "construction.working_space_"+side
            y = z-19/self._scale
            related = ("construction.working_space_left","construction.working_space_right") if shared_space else ()
            self._measurement(((a,y),(b,y)), (shared_space or name)+" "+_fmt(abs(b-a))+" m", path, related,
                              outward=-1 if side == "left" else 1)
        outline = model.structure.get("tunnel_excavation_outline")
        self._region(outline, "pipe_seat", "construction.excavation_clearance", fill=False, z=4)

    def _pipe_surfaces(self, model):
        layer = model.pipe_backfill
        details = model.drawing_details
        original = layer.original_surface if layer else model.trench_top
        finished = layer.finished_surface if layer else original
        original_points = [self._point(*point) for point in original]
        raw_color, finished_color = "#75664F", _FINISH_EDGE
        self._stroke(original_points, color=raw_color, width=1.05,
                     style=Qt.DashLine if original != finished else Qt.SolidLine)
        if layer and model.construction.get("target_mode") in PIPE_COVER_TARGETS:
            raw_anchor = original_points[0] * .70 + original_points[-1] * .30
            title = "原地面及回填完成面（示意）" if original == finished else "原地面（示意）"
            label = self._label(title, raw_anchor + QPointF(0, -12), center=True, color=raw_color)
            if self._place_label(label, outward=-1):
                self._leader(raw_anchor, label, "", color=raw_color)
            if original != finished:
                self._stroke([self._point(*point) for point in finished], _FINISH_DEPTH, color=finished_color, width=1.2)
                anchor = self._point(*layer.completion.platforms["right"][1])
                label = self._label("回填完成面", anchor + QPointF(12, -15), color=finished_color, path=_FINISH_DEPTH)
                self._place_label(label, outward=1)
                self._leader(anchor, label, _FINISH_DEPTH, color=finished_color)
            return
        if original == finished:
            title = " / ".join(details.surface_labels) if details else "示意地面"
            self._label(title, (original_points[0] + original_points[-1]) / 2 + QPointF(0, -12),
                        center=True, color=raw_color)
            return
        final_points = [self._point(*point) for point in finished]
        self._stroke(final_points, color=finished_color, width=1.2)
        if details.surface == "hillside_mixed":
            raw_anchor = (original_points[0] + original_points[1]) / 2 + QPointF(0, 14)
        elif details.surface == "hillside_cut":
            raw_anchor = (original_points[-2] + original_points[-1]) / 2 + QPointF(0, -11)
        elif details.surface == "restore_ground":
            raw_anchor = original_points[2] + QPointF(0, -12)
        else:
            raw_anchor = original_points[0] * .70 + original_points[-1] * .30
            raw_anchor += QPointF(0, -12 if details.surface == "roadbed" else 12)
        length = len(final_points)
        finish_anchor = (final_points[(length - 1) // 2] + final_points[length // 2]) / 2
        if details.surface == "hillside_mixed":
            finish_anchor = (final_points[-2] + final_points[-1]) / 2 + QPointF(0, -12)
        elif details.surface in {"roadbed", "restore_ground"}:
            finish_anchor = final_points[0] * .28 + final_points[-1] * .72 + QPointF(0, 10)
        else:
            finish_anchor += QPointF(0, -12)
        self._label(details.surface_labels[0], raw_anchor, center=True, color=raw_color)
        self._label(details.surface_labels[1], finish_anchor, center=True, color=finished_color)
        if layer.fill_slope:
            midpoint, ratio = layer.fill_slope
            offset = 13 if details.surface == "hillside_mixed" else -30
            self._label("填坡 1∶" + _fmt(ratio), self._point(*midpoint) + QPointF(0, offset),
                        center=True, color=finished_color)

    def _completion_dimensions(self, model):
        layer = model.pipe_backfill
        if layer is None or layer.completion is None:
            return
        completion = layer.completion
        crown, crest = completion.cover
        left, _, right, _ = model.structure["outer"].bounds
        cover_side = 1 if crown[0] < (left + right) / 2 else -1
        self._measurement(completion.cover, "管外顶至完成面 " + _fmt(crest[1] - crown[1]) + " m",
                          _FINISH_DEPTH, extension=QPointF(7 * cover_side, 0), outward=cover_side)
        for side, name, direction in (("left", "左", -1), ("right", "右", 1)):
            endpoints = completion.platforms[side]
            width = abs(endpoints[1][0] - endpoints[0][0])
            self._measurement(endpoints, name + "平台 " + _fmt(width) + " m", "construction.bank_top_width_" + side,
                              extension=QPointF(0, -22), outward=direction)
            if side in completion.fill_slopes:
                anchor, grades = completion.fill_slopes[side]
                path = "construction.bank_" + ("stages_" if model.construction.get("bank_stages_" + side) else "slope_") + side
                title = name + "填坡 " + "/".join("1∶" + _fmt(ratio) for ratio in grades)
                origin = self._point(*anchor)
                label = self._label(title, origin, center=True, color=_FINISH_EDGE, path=path)
                label.moveBy(direction * (label.boundingRect().width() / 2 + 10), -3)
                self._place_label(label, outward=direction)
                self._leader(origin, label, path, color=_FINISH_EDGE)

    def _pipe_backfill(self, model):
        layer = model.pipe_backfill
        if layer is None:
            return []
        path = PIPE_BACKFILL_HEIGHT_PATH
        entries = []
        for role, shape in layer.regions.items():
            if shape.is_empty:
                continue
            title, tint, edge = _ROLE[role]
            target = "" if role == "embankment" else path
            item = self._region(shape, role, target, z=.7, outline=False)
            item.setToolTip(title)
            entries.append((title, target, (), tint, edge))
        if layer.encasement_interface is not None and not layer.encasement_interface.is_empty:
            item = self._region(layer.encasement_interface, "pipe_encasement", "construction.encasement.top_thickness",
                                fill=False, z=3.5, provisional=True)
            item.setToolTip("包封顶线")
        source_marks_split = bool(model.drawing_details and model.drawing_details.shows_crown_partition)
        divider = self._region(layer.interface, "mechanical_backfill", path, fill=False, z=4,
                               provisional=not source_marks_split)
        if divider is not None:
            divider.setToolTip("人工与机械夯填分界" if source_marks_split else "当前采用的人工与机械夯填分界")
        if layer.height > 0:
            label = "管顶＋" + _fmt(layer.height) + " m"
            self._detail(path, layer.dimension, label)
            self._default_dimensions.append(self._measurement(layer.dimension, label, path))
        return entries

    def _legend(self, entries):
        if not entries:
            return
        bounds = self.scene().itemsBoundingRect()
        max_width = max(250., bounds.width())
        x = start = bounds.center().x()-max_width/2
        y = bounds.bottom()+12
        for name, path, aliases, tint, edge in entries:
            label = self._label(name, QPointF(), path=path, related=aliases)
            w = label.boundingRect().width()+24
            if x > start and x+w > start+max_width+1:
                x, y = start, y+20
            label.setPos(x+15,y)
            swatch = self.scene().addRect(QRectF(x, y+4, 10, 9), self._pen(edge, 1), QBrush(QColor(tint)))
            self._bind(swatch, path, aliases, name)
            x += w

    def _drawing_features(self, entries):
        bounds = self.scene().itemsBoundingRect()
        left, right = bounds.left(), bounds.right()
        x, y = left, bounds.bottom() + 6
        for text in entries:
            item = self._label(text, QPointF(), color="#77624C")
            width = item.boundingRect().width()
            if x > left and x + width > right:
                x, y = left, y + 17
            item.setPos(x, y)
            x += width + 14

    def set_pipe_terrain_case(self, case):
        if case == self._pipe_terrain_case:
            return
        self._pipe_terrain_case = case
        if self._last_parameters is not None:
            self.set_section_parameters(*self._last_parameters)

    def set_section_parameters(self, asset, scheme=None, pending_paths=()):
        pending_paths = tuple(pending_paths or ())
        self._last_parameters = (asset, scheme, pending_paths)
        previous_scale = self._scale
        previous_center = self.mapToScene(self.viewport().rect().center()) / previous_scale
        self._items.clear()
        self._details.clear()
        self._overlay.clear()
        self._default_dimensions.clear()
        self._angles.clear()
        self._gaps.clear()
        self.scene().clear()
        self.geometry_model = model = parameter_geometry(
            asset or {}, scheme, pending_paths, show_pipe_trench=self._show_pipe_trench,
            pipe_terrain_case=self._pipe_terrain_case,
        )
        s = model.structure
        shape = s.get("outer")
        if shape is None:
            shape = s.get("net_void")
        if shape is None or shape.is_empty:
            self._label("补充结构尺寸后显示构造断面" if supports_parameter_section(asset) else "请选择可预览的断面", QPointF())
        else:
            envelope = s.get("occupancy",shape)
            l, b, r, t = envelope.bounds
            points = [p for p in model.floor]
            for pts, _ in model.slopes.values():
                points.extend(pts)
            if model.pipe_backfill:
                points.extend(model.pipe_backfill.original_surface)
                points.extend(model.pipe_backfill.finished_surface)
            if points:
                l, b = min(l, *(p[0] for p in points)), min(b, *(p[1] for p in points))
                r, t = max(r, *(p[0] for p in points)), max(t, *(p[1] for p in points))
            self._scale = min(315/max(r-l, .001), 215/max(t-b, .001))
            self._structure_body(s, asset.get("section") or {})
            entries = [*self._pipe_backfill(model), *self._materials(model, scheme)]
            self._edges(model, scheme)
            self._completion_dimensions(model)
            self._legend(entries)
            if model.drawing_details and model.drawing_details.feature_labels:
                self._drawing_features(model.drawing_details.feature_labels)
        if model.pending or model.notices:
            from .engineering_drawings_dialog import _field_label
            for note in model.notices:
                bounds = self.scene().itemsBoundingRect()
                self._label(note, QPointF(bounds.left(),bounds.bottom()+5), color="#81683F")
            if model.pending:
                bounds = self.scene().itemsBoundingRect()
                y = bounds.bottom()+5
                paths = displayed_pipe_parameters(asset or {}, scheme, sorted(model.pending))
                shared = shared_encasement_thickness(asset or {}, scheme)
                title = self._label(f"待补 {len(paths)} 项", QPointF(bounds.left(),y), color="#81683F")
                x = start = title.sceneBoundingRect().right()+7
                shown = 0
                for path in paths:
                    label = (ENCASEMENT_B1_LABEL if shared and path == ENCASEMENT_SIDE else
                             _field_label(path).split("（")[0].replace("管床 · ", ""))
                    if not any("\u4e00" <= ch <= "\u9fff" for ch in label) or "_" in label:
                        continue
                    item = self._label(label, QPointF(), path=path, color="#9A6627")
                    w = item.boundingRect().width()+8
                    if x > start and x+w > bounds.left()+max(250, bounds.width()):
                        x,y = start,y+18
                    item.setPos(x,y)
                    x += w
                    shown += 1
                    if shown == 3:
                        break
        self._drawing_rect = self.scene().itemsBoundingRect().adjusted(-14,-13,14,13)
        self.scene().setSceneRect(self._drawing_rect)
        if self._auto_fit:
            self.fit_to_window()
        else:
            self.scale(previous_scale/self._scale, previous_scale/self._scale)
            self.centerOn(previous_center*self._scale)
        self.focusParameter(self._selected_path)

    def show_message(self, message):
        self._last_parameters = None
        self._items.clear()
        self._details.clear()
        self._overlay.clear()
        self._default_dimensions.clear()
        self._angles.clear()
        self._gaps.clear()
        self._drawing_rect = None
        self.geometry_model = None
        super().show_message(message)

    def focusParameter(self, path):
        """Select a form parameter without sending a second navigation request."""
        self._selected_path = path or ""
        for item in self._overlay:
            self.scene().removeItem(item)
        if self._overlay:
            self._items = [entry for entry in self._items if entry[0] not in self._overlay]
        self._overlay.clear()
        for dimension in self._default_dimensions:
            for item in dimension:
                item.setVisible(True)
        found = False
        for item, paths, original in self._items:
            active = self._selected_path in paths
            found = found or active
            if isinstance(item,QGraphicsSimpleTextItem):
                item.setBrush(QBrush(QColor(_ACTIVE)) if active else original)
            else:
                item.setPen(self._pen(_ACTIVE,2.5) if active else original)
        detail = self._details.get(self._selected_path)
        if detail:
            layer = self.geometry_model.pipe_backfill
            completion_visible = layer is not None and layer.completion is not None
            if completion_visible:
                selected = {item for item, paths, _ in self._items if self._selected_path in paths}
                for dimension in self._default_dimensions:
                    if selected.intersection(dimension):
                        for item in dimension:
                            item.setVisible(False)
            self._overlay = self._measurement(*detail, self._selected_path, active=True)
            if not completion_visible:
                bounds = self._overlay[-1].sceneBoundingRect().adjusted(-2,-2,2,2)
                for dimension in self._default_dimensions:
                    if any(bounds.intersects(item.sceneBoundingRect()) for item in dimension):
                        for item in dimension:
                            item.setVisible(False)
        if path in self._angles:
            x,z,r,angle = self._angles[path]
            rad = math.radians(angle/2)
            def position(theta, distance):
                return self._point(x+math.sin(theta)*distance, z-math.cos(theta)*distance)
            center = self._point(x,z)
            for theta in (-rad,rad):
                self._overlay.append(self._stroke([center,position(theta,r)],path,color=_ACTIVE))
            arc = [position(-rad+2*rad*i/32, r*.52) for i in range(33)]
            self._overlay.append(self._stroke(arc,path,color=_ACTIVE,width=1.8))
            label = self._label(_fmt(angle)+"°",position(0,r*.73),center=True,color=_ACTIVE,path=path,bold=True)
            self._place_label(label)
            self._overlay.append(label)
        gaps_selected = path == "section.pipe_spacing" and self._gaps
        if gaps_selected:
            for points, label in self._gaps:
                self._overlay.extend(self._measurement(points,label,path,active=True))
        if self._drawing_rect is not None:
            rect = QRectF(self._drawing_rect)
            for item in self._overlay:
                rect = rect.united(item.sceneBoundingRect().adjusted(-7,-7,7,7))
            if rect != self.sceneRect():
                self.scene().setSceneRect(rect)
                if self._auto_fit:
                    self.fit_to_window()
        return bool(found or detail or path in self._angles or gaps_selected)

    def mousePressEvent(self, event):
        self._press_position = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        clicked = (event.button() == Qt.LeftButton and self._press_position is not None
                   and (pos-self._press_position).manhattanLength() < QApplication.startDragDistance())
        self._press_position = None
        super().mouseReleaseEvent(event)
        if clicked:
            for item in self.items(pos):
                path = item.data(0)
                if path:
                    self.focusParameter(path)
                    self.parameterRequested.emit(path)
                    break
