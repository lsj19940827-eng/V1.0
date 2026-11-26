"""Scalable source and calculated section drawings, sharing quantity geometry."""
from __future__ import annotations

import math
import hashlib
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


def pipe_cut_note(pipes):
    """Describe the vertical construction cut and its pipe-normal dimension."""
    if not pipes:
        return ""
    note = "竖直施工剖切"
    if len(pipes) != 1:
        return note + " · 管径沿各管轴法向量取"
    pipe = pipes[0]
    if pipe.get("earthwork_envelope_only"):
        diameter = pipe.get("outer_diameter")
        nominal = pipe.get("nominal_diameter_m")
        designation = f"DN{1000 * nominal:g} " if nominal else ""
        label = designation + "施工占位直径"
    else:
        diameter = pipe.get("inner_diameter")
        label = "管轴法向净内径"
    return note + (f" · {label} Ø{diameter:.3f} m" if diameter else "")


class SectionSchemeView(QGraphicsView):
    """One zoom/pan surface for SVG evidence and actual calculation polygons."""

    COLORS = {"excavation": "#D98A73", "overburden": "#D5AA76", "bedrock": "#B68A91",
              "backfill": "#E4C472", "embankment": "#8EBBD5", "concrete": "#9AA8B3",
              "bedding": "#C9B4D8", "pipe_wall": "#8798AC", "lining": "#81B9A4",
              "outer": "#25394B", "net_void": "#25394B"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#FFFFFF"))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMinimumSize(480, 310)
        self._auto_fit = True
        self._renderer = None
        self.section_record = None
        self.source_path = None
        self._origin_z = 0.0
        self._scale = 100.0

    def _reset(self):
        self.scene().clear()
        self._renderer = None
        self.section_record = None
        self.source_path = None
        self._auto_fit = True
        self.resetTransform()

    def show_message(self, message):
        self._reset()
        item = self.scene().addText(str(message), QFont("Microsoft YaHei", 13))
        item.setDefaultTextColor(QColor("#52677B"))
        item.setTextWidth(650)
        self._finish()

    def set_image(self, path=None):
        """Keep a compatible entry point; SVG remains vector at every zoom."""
        self._reset()
        path = Path(path) if path else None
        if path is None or not path.is_file():
            self.show_message("该断面的原图尚未就绪。请先选择其他方案。")
            return
        if path.suffix.lower() == ".svg":
            renderer = QSvgRenderer(str(path))
            if not renderer.isValid():
                self.show_message("原图无法读取，请核对该方案的来源文件。")
                return
            self._renderer = renderer
            item = QGraphicsSvgItem()
            item.setSharedRenderer(renderer)
            self.scene().addItem(item)
        else:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.show_message("原图无法读取，请核对该方案的来源文件。")
                return
            self.scene().addPixmap(pixmap)
        self.source_path = str(path)
        self._finish()

    def show_scheme_drawing(self, scheme, reference, library_root, input_files):
        """Prefer the exact drawing saved with the project over the library copy."""
        from 土石方计算.services.section_scheme_catalog import is_selectable_section_scheme
        if not is_selectable_section_scheme(scheme):
            self.show_message("请从当前图纸库选择断面型号。")
            return "选择断面型号"
        if isinstance(reference, dict):
            reference = reference.get("path")
        root = Path(library_root).resolve()
        path = (root / reference).resolve() if reference else None
        if path is not None and not path.is_relative_to(root):
            path = None
        saved = next((item for item in input_files
                      if item.get("role") == "section_scheme_preview"
                      and item.get("scheme_id") == scheme.get("scheme_id")
                      and item.get("source_preview") == reference), None)
        if saved:
            path = Path(saved.get("path") or "")
            if not path.is_file():
                self.show_message("随工程保存的原图文件未找到。请恢复工程依据文件后查看。")
                return "已采用原图文件缺失"
            if saved.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != saved["sha256"]:
                self.show_message("随工程保存的原图文件已变化。请恢复原文件或重新核对来源。")
                return "已采用原图校验不一致"
        self.set_image(path)
        return "原图对照 · 图中示例尺寸不代表当前工程取值"

    def _point(self, x, z):
        return QPointF(float(x) * self._scale, (self._origin_z - float(z)) * self._scale)

    def _pen(self, color, width=1.4, style=Qt.SolidLine):
        pen = QPen(QColor(color), width, style)
        pen.setCosmetic(True)
        return pen

    def _line(self, points, color, width=1.4, style=Qt.SolidLine):
        values = list(points)
        if len(values) < 2:
            return
        path = QPainterPath(self._point(*values[0]))
        for point in values[1:]:
            path.lineTo(self._point(*point))
        self.scene().addPath(path, self._pen(color, width, style))

    def _text(self, text, x, z, *, centered=False, color="#364F63", size=12):
        item = self.scene().addSimpleText(str(text), QFont("Microsoft YaHei", size))
        item.setBrush(QBrush(QColor(color)))
        p = self._point(x, z)
        if centered:
            p -= QPointF(item.boundingRect().width() / 2, item.boundingRect().height() / 2)
        item.setPos(p)
        item.setZValue(10)
        return item

    def _dimension(self, first, last, label, *, vertical=False):
        self._line([first, last], "#586F83", 1)
        x1, z1 = first
        x2, z2 = last
        tick = 5 / self._scale
        for x, z in (first, last):
            self._line([(x - tick, z - tick), (x + tick, z + tick)], "#586F83", 1)
        if vertical:
            self._text(label, x1 + 12 / self._scale, (z1 + z2) / 2 + 7 / self._scale)
        else:
            self._text(label, (x1 + x2) / 2, z1 + 14 / self._scale, centered=True)

    def set_gate_section(self, section):
        width, height = section.get("inner_width"), section.get("inner_height")
        if not width or not height:
            self.show_message("填入闸室净宽和边墙净高后，显示参数化断面。")
            return
        self._reset()
        left = section.get("wall_thickness_left") or 0.0
        right = section.get("wall_thickness_right") or 0.0
        base = section.get("base_thickness") or 0.0
        extent = max(width + left + right, height + base, 1.0)
        if not math.isfinite(extent):
            self.show_message("闸室尺寸超出绘图范围。")
            return
        self._scale = 420.0 / extent
        self._origin_z = 0.0
        for x1, z1, x2, z2 in ((-left, -base, width + right, 0),
                                (-left, 0, 0, height), (width, 0, width + right, height)):
            if x2 > x1 and z2 > z1:
                rect = QRectF(self._point(x1, z2), self._point(x2, z1))
                self.scene().addRect(rect, self._pen("#354F63"), QBrush(QColor("#B4C7D5")))
        self._line([(0, height), (0, 0), (width, 0), (width, height)], "#354F63", style=Qt.DashLine)
        offset = 32 / self._scale
        self._dimension((0, height + offset), (width, height + offset), f"净宽 {width:.3f} m")
        self._dimension((width + right + offset, 0), (width + right + offset, height),
                        f"净高 {height:.3f} m", vertical=True)
        self._finish()

    def set_section(self, section, *, elevation_reference=None):
        from shapely.geometry import LineString, Point, box
        from shapely.ops import unary_union
        from 土石方计算.io.workbench_drawings import (
            NAMES, _component_role, _construction_segments, component_lines, construction_lines,
            geometry_items, ground_parts, interface_parts, polygons, section_limits,
        )
        self._reset()
        self.section_record = section
        left, right, bottom, top = section_limits(section)
        width, height = max(right - left, 1.), max(top - bottom, 1.)
        self._scale = max(8., min(120., 1000. / width))
        self._origin_z = bottom
        groups = {}
        asset = section.get("effective_asset", {})
        section_parameters = asset.get("section", {})
        structure = section.get("structure_geometry") or {}
        kind = asset.get("section_type") or structure.get("section_type")
        pipes = structure.get("pipes") or []
        short_names = {}
        for collection in ("component_regions", "component_surfaces"):
            for spec in section.get("structure_geometry", {}).get(collection, {}).values():
                name = str(spec.get("name") or {"mortar":"砂浆", "membrane":"防渗膜", "geomembrane":"防渗膜", "geotextile":"土工布"}.get(spec.get("material"), "断面材料"))
                grade = str(spec.get("grade") or "")
                if spec.get("material") in {"membrane", "geomembrane"}:
                    thickness = re.search(r"([\d.]+)\s*mm", name + " " + grade, re.I)
                    name = "复合土工膜" + (" " + thickness.group(1) + " mm" if thickness else "")
                elif grade and grade not in name:
                    name = grade + " " + name
                short_names[_component_role(spec)] = name.replace("_", " ")[:28]
        for role, polygon, fill in geometry_items(section):
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for ring in (polygon.exterior, *polygon.interiors):
                coordinates = list(ring.coords)
                path.moveTo(self._point(*coordinates[0]))
                for point in coordinates[1:]:
                    path.lineTo(self._point(*point))
                path.closeSubpath()
            color = QColor(self.COLORS.get(role, "#BCA5C8"))
            color.setAlpha(125 if fill else 255)
            item = self.scene().addPath(path, self._pen(color.name(), 1.5),
                                       QBrush(color) if fill else QBrush(Qt.NoBrush))
            item.setZValue(0 if fill else 2)
            if fill and role not in groups:
                groups[role] = polygon
        window = box(left, bottom - height, right, top + height)
        for parts, color, style, weight in (
            (ground_parts(section), "#79552E", Qt.SolidLine, 2.2),
            (interface_parts(section), "#AB885D", Qt.DashDotLine, 1.4),
        ):
            for line in parts:
                geometry = LineString(line).intersection(window)
                segments = [geometry] if geometry.geom_type == "LineString" else getattr(geometry, "geoms", [])
                for segment in segments:
                    if segment.geom_type == "LineString":
                        self._line(segment.coords, color, weight, style)
        for line in construction_lines(section, (left, right, bottom, top)):
            self._line(line, "#258C81", 1.7, Qt.DashLine)
        for role, line in component_lines(section):
            self._line(line, "#8E558F", 1.8, Qt.DashDotLine)
            groups.setdefault(role, None)
        self._line([(0, bottom), (0, top + height * .08)], "#A6B3BE", 1., Qt.DashDotLine)

        # Measurements come from the same actual section geometry as quantities.
        voids = polygons(structure.get("net_void"))
        envelope_only = any(pipe.get("earthwork_envelope_only") for pipe in pipes)
        outlines = polygons(structure.get("outer")) if envelope_only else voids
        dim_space = max(.3, 38. / self._scale)
        if outlines:
            outline = min(outlines, key=lambda p: abs(p.centroid.x))
            vl, vb, vr, vt = outline.bounds
            if pipes:
                width_label, height_label = ("竖切外包宽", "竖切外包高") if envelope_only else ("竖切净宽", "竖切净高")
            else:
                width_label, height_label = ("渠顶净宽" if kind == "u_channel" else "净宽"), "净高"
            dz = bottom - dim_space
            self._line([(vl, vb), (vl, dz - dim_space * .2)], "#90A0AF", 1.)
            self._line([(vr, vb), (vr, dz - dim_space * .2)], "#90A0AF", 1.)
            self._dimension((vl, dz), (vr, dz), f"{width_label} {vr-vl:.3f} m")
            dx = right + dim_space * .35
            self._line([(vr, vb), (dx + dim_space * .2, vb)], "#90A0AF", 1.)
            self._line([(vr, vt), (dx + dim_space * .2, vt)], "#90A0AF", 1.)
            self._dimension((dx, vb), (dx, vt), f"{height_label} {vt-vb:.3f} m", vertical=True)

        level = section.get("design_elevation")
        if level is not None and math.isfinite(float(level)):
            label_z = bottom - dim_space * 2.0
            x = 0.
            datum = "内底高程"
            if pipes:
                first = pipes[0]
                reference = structure.get("reference") or elevation_reference
                axis_elevation = first.get("axis_elevation")
                if reference is None and axis_elevation is not None and math.isclose(
                        float(level), float(axis_elevation), rel_tol=0., abs_tol=1e-7):
                    reference = "pipe_axis"
                datum = {
                    "pipe_axis": "管轴高程" if len(pipes) == 1 else "首管轴高程",
                    "inner_invert": "内底高程",
                    "common_outer_bottom": "共同外管底高程",
                }.get(reference, "设计基准高程")
                if reference:
                    x = first.get("offset", 0.)
                    if reference == "common_outer_bottom":
                        x = first.get("outer_bottom_offset", x)
            self._line([(x, level), (left + width * .15, label_z), (left, label_z)], "#536E84", 1.)
            self._text(f"{datum} ▽{float(level):.3f} m", left, label_z + 20 / self._scale)
        if kind == "u_channel" and voids:
            radius = section_parameters.get("inner_radius")
            if radius is not None:
                self._text(f"底弧内半径 R{float(radius):.3f} m", left, bottom - dim_space * 3., size=11)
            thicknesses = []
            for key, name in (("wall_thickness_left", "左衬砌"), ("wall_thickness_right", "右衬砌"),
                              ("u_bottom_thickness", "底弧")):
                value = section_parameters.get(key, section_parameters.get("wall_thickness") if "wall" in key else section_parameters.get("base_thickness"))
                if value is not None:
                    thicknesses.append(f"{name} {float(value):.3f} m")
            if thicknesses:
                self._text(" · ".join(thicknesses), left, bottom - dim_space * 3.8, size=11)

        # Lane labels outside the geometry avoid crowding narrow material layers.
        legend_z = top + max(.5, 60 / self._scale)
        legend_x = left
        if list(ground_parts(section)):
            groups["ground"] = None
        for role in groups:
            label = short_names.get(role, NAMES.get(role, role))
            item = self._text(("— " if role == "ground" else "■ ") + label, legend_x, legend_z,
                              color="#79552E" if role == "ground" else self.COLORS.get(role, "#8E558F"), size=11)
            legend_x += (item.boundingRect().width() + 24) / self._scale
            if legend_x > right - width * .25:
                legend_x = left
                legend_z += 25 / self._scale
        if pipes:
            self._text(pipe_cut_note(pipes), left, legend_z + 30 / self._scale, size=11)
        # Only actual earthwork edges outside the structural envelope are slopes.
        # Excavation-domain polygons also contain the channel wall and ground
        # fragments: annotating every edge would mislabel them as excavation.
        outer = polygons(section.get("structure_geometry", {}).get("outer"))
        outer_left = min((p.bounds[0] for p in outer), default=0.)
        outer_right = max((p.bounds[2] for p in outer), default=0.)
        fill_polygons = polygons(section.get("roles", {}).get("embankment", {}).get("geometry"))
        cut_polygons = polygons(section.get("roles", {}).get("excavation", {}).get("geometry"))
        if not cut_polygons:
            cut_polygons = [p for role in ("overburden", "bedrock") for p in polygons(section.get("roles", {}).get(role, {}).get("geometry"))]
        role_boundaries = [(name, unary_union(parts).boundary)
                           for name, parts in (("填坡", fill_polygons), ("挖坡", cut_polygons)) if parts]
        grounds = [LineString(p) for p in ground_parts(section)]
        ground_line = unary_union(grounds)
        labels, seen = [], set()
        for _, line in _construction_segments(section, (left, right, bottom, top)):
            for a, b in zip(line[:-1], line[1:]):
                dx, dz = float(b[0]-a[0]), float(b[1]-a[1])
                point = (a+b)/2
                if abs(dx) < 1e-7 or abs(dz) < 1e-7 or math.hypot(dx,dz) < max(.15,width*.02):
                    continue
                if outer_left-1e-6 < point[0] < outer_right+1e-6:
                    continue
                midpoint = Point(point)
                if not ground_line.is_empty and midpoint.distance(ground_line) < 1e-6:
                    continue
                role = next((name for name, edge in role_boundaries if edge is not None and not edge.is_empty and midpoint.distance(edge) < 1e-6), None)
                if role is None:
                    continue
                side = -1 if point[0] < 0 else 1
                text = f"{role} 1:{abs(dx/dz):.3g}"
                key = side, text
                if key not in seen:
                    seen.add(key)
                    labels.append((point,text,abs(dx)+abs(dz)))
        side_count = {-1: 0, 1: 0}
        for point, label, _ in sorted(labels, key=lambda v: v[0][1], reverse=True):
            side = -1 if point[0] < 0 else 1
            index = side_count[side]
            if index >= 2:
                continue
            side_count[side] += 1
            x = left - 1.7 * dim_space if side < 0 else right + dim_space * 3.2
            z = top - index * 27 / self._scale
            self._line([point, (x, z)], "#69918B", 1.)
            self._text(label, x, z + 19 / self._scale, color="#287C72", size=10)
        self._finish()

    def _finish(self):
        bounds = self.scene().itemsBoundingRect()
        if bounds.isEmpty():
            bounds = QRectF(0, 0, 800, 400)
        self.scene().setSceneRect(bounds.adjusted(-30, -30, 30, 30))
        self.fit_to_window()

    def fit_to_window(self):
        self._auto_fit = True
        self.fitInView(self._fit_bounds(), Qt.KeepAspectRatio)

    def _fit_bounds(self):
        return self.sceneRect()

    def zoom(self, factor):
        if .015 < self.transform().m11() * factor < 100:
            self._auto_fit = False
            self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.fitInView(self._fit_bounds(), Qt.KeepAspectRatio)


DrawingPreview = SectionSchemeView
