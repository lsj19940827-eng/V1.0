"""Exact tangent lines and circular IP fillets for a continuous route.

An IP stays in provenance. Its route station is the midpoint of its fillet,
which is an explicit allocation convention rather than a claim that the
rounded alignment passes through the original IP.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
import math


def _xy(point):
    values = (float(point["x"]), float(point["y"]))
    if not all(math.isfinite(v) for v in values):
        raise ValueError("IP坐标必须是有限数")
    return values


class NetworkAlignment:
    """Query exact analytic elements; never query a sampled display polyline."""

    def __init__(self, elements, ip_points, adjustments=None, *, start_station=0.0):
        self.elements = deepcopy(elements)
        self.ip_points = deepcopy(ip_points)
        self.adjustments = deepcopy(adjustments or [])
        self._starts = [e["station_start"] for e in self.elements]
        self.start_station = float(start_station)
        self.end_station = float(self.elements[-1]["station_end"])
        self.total_length = self.end_station-self.start_station
        self.primitive_break_stations = sorted({e[k] for e in self.elements for k in ("station_start", "station_end")})
        self.event_stations = self.primitive_break_stations[:]

    def _element(self, station):
        station = float(station)
        if not math.isfinite(station) or station < self.start_station-1e-7 or station > self.end_station+1e-7:
            raise ValueError("查询桩号超出真实路线，禁止外推")
        station = min(max(station, self.start_station), self.end_station)
        index = min(max(bisect_right(self._starts, station)-1, 0), len(self.elements)-1)
        return self.elements[index], station

    def get_xy_at_station(self, station):
        e, s = self._element(station)
        t = (s-e["station_start"])/e["length"]
        if e["kind"] == "line":
            return tuple(a+(b-a)*t for a, b in zip(e["start_xy"], e["end_xy"]))
        angle = e["start_angle"]+e["sweep_angle"]*t
        return (e["center_xy"][0]+e["radius"]*math.cos(angle),
                e["center_xy"][1]+e["radius"]*math.sin(angle))

    def get_tangent_angle_at_station(self, station):
        e, s = self._element(station)
        if e["kind"] == "line":
            return e["tangent_angle"]
        angle = e["start_angle"]+e["sweep_angle"]*(s-e["station_start"])/e["length"]
        return angle+math.copysign(math.pi/2, e["sweep_angle"])

    def get_curvature_at_station(self, station):
        e, _ = self._element(station)
        return 0.0 if e["kind"] == "line" else math.copysign(1/e["radius"], e["sweep_angle"])

    curvature_at = get_curvature_at_station

    def get_normal_direction(self, station):
        return self.get_tangent_angle_at_station(station)+math.pi/2

    def sample_stations(self, interval, extra_stations=None):
        interval = float(interval)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("采样间距必须为正")
        count = math.floor(self.total_length/interval)
        stations = [self.start_station+i*interval for i in range(count+1)]
        stations += [self.end_station]
        stations += [e[key] for e in self.elements for key in ("station_start", "station_end")]
        stations += list(extra_stations or [])
        return sorted({float(s) for s in stations if self.start_station <= float(s) <= self.end_station})

    def to_dict(self):
        return {"schema_version": "1.0", "geometry_kind": "analytic_tangent_line_circular_arc",
                "station_basis": "true_plan_arclength", "start_station": self.start_station,
                "end_station": self.end_station, "length": self.total_length,
                "elements": deepcopy(self.elements), "ip_points": deepcopy(self.ip_points),
                "test_radius_adjustments": deepcopy(self.adjustments),
                "ip_station_convention": "rounded_corner_arc_midpoint; original_IP_XY_preserved_separately"}

    @classmethod
    def from_dict(cls, value):
        return cls(value["elements"], value["ip_points"], value.get("test_radius_adjustments"),
                   start_station=value["start_station"])


def build_ip_alignment(points, *, start_station=0.0, allow_test_radius_adjustment=False,
                       minimum_straight=0.05):
    """Fillet every nonzero-radius IP; reject overlap unless TEST is explicit.

    TEST adjustments proportionally reduce the two competing tangent lengths
    on each chord. Reductions only decrease radii and are recorded per IP.
    """
    points = deepcopy(list(points))
    if len(points) < 2:
        raise ValueError("路线至少需要两个真实IP")
    xy = [_xy(p) for p in points]
    lengths, directions = [], []
    for a, b in zip(xy, xy[1:]):
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        if length <= 1e-8:
            raise ValueError("相邻IP坐标重复，须明确处理后再生成真线形")
        lengths.append(length)
        directions.append(((b[0]-a[0])/length, (b[1]-a[1])/length))
    radii = [float(p.get("turn_radius") or 0) for p in points]
    if any(not math.isfinite(r) or r < 0 for r in radii):
        raise ValueError("IP转弯半径必须为非负有限数")
    original = radii[:]
    angles, signs, tangents = [0.0]*len(points), [0.0]*len(points), [0.0]*len(points)
    for i in range(1, len(points)-1):
        u, v = directions[i-1], directions[i]
        cross = u[0]*v[1]-u[1]*v[0]
        angle = math.atan2(abs(cross), max(-1.0, min(1.0, u[0]*v[0]+u[1]*v[1])))
        if angle >= math.pi-1e-7:
            raise ValueError("路线含反向折返，不能用零长度或假圆弧代替")
        angles[i], signs[i] = angle, math.copysign(1.0, cross)
        tangents[i] = radii[i]*math.tan(angle/2) if angle > 1e-10 else 0.0
    # Endpoints have no two-sided tangent construction; retain their raw radii
    # only as provenance, not as fictitious endpoint arcs.
    radii[0] = radii[-1] = 0.0
    reasons = {}
    for _ in range(4*len(points)):
        changed = False
        for i, length in enumerate(lengths):
            used = tangents[i]+tangents[i+1]
            reserve = min(float(minimum_straight), length*0.01)
            available = length-reserve
            if used <= available+1e-10:
                continue
            if not allow_test_radius_adjustment:
                raise ValueError(f"IP圆弧切线重叠：原行{points[i].get('source_row', i)}至{points[i+1].get('source_row', i+1)}")
            factor = available/used
            for j in (i, i+1):
                if tangents[j]:
                    tangents[j] *= factor
                    radii[j] *= factor
                    reasons.setdefault(j, set()).add(i)
            changed = True
        if not changed:
            break
    else:
        raise ValueError("TEST半径调整未收敛")
    adjustments = [{"source_row": points[i].get("source_row"), "ip_index": i,
                    "original_radius": original[i], "test_radius": radii[i],
                    "reason": "TEST相邻切线长度超过原IP间距，按竞争切线等比例缩小并保留最小直线",
                    "conflicting_chords": sorted(chords), "test_only": True}
                   for i, chords in sorted(reasons.items())]
    elements, ip_output = [], []
    station = float(start_station)
    cursor = xy[0]
    ip_stations = [station]+[None]*(len(points)-2)+[None]
    def line_to(target):
        nonlocal station, cursor
        length = math.hypot(target[0]-cursor[0], target[1]-cursor[1])
        if length > 1e-9:
            elements.append({"kind": "line", "station_start": station, "station_end": station+length,
                             "length": length, "start_xy": list(cursor), "end_xy": list(target),
                             "tangent_angle": math.atan2(target[1]-cursor[1], target[0]-cursor[0])})
            station += length
        cursor = target
    for i in range(1, len(points)-1):
        if tangents[i] <= 1e-10 or angles[i] <= 1e-10:
            line_to(xy[i])
            ip_stations[i] = station
            continue
        u, v, ip, t, radius, sign = directions[i-1], directions[i], xy[i], tangents[i], radii[i], signs[i]
        bc = (ip[0]-u[0]*t, ip[1]-u[1]*t)
        ec = (ip[0]+v[0]*t, ip[1]+v[1]*t)
        center = (bc[0]-u[1]*sign*radius, bc[1]+u[0]*sign*radius)
        line_to(bc)
        length = radius*angles[i]
        elements.append({"kind": "arc", "station_start": station, "station_end": station+length,
                         "length": length, "start_xy": list(bc), "end_xy": list(ec),
                         "center_xy": list(center), "radius": radius, "original_ip_radius": original[i],
                         "start_angle": math.atan2(bc[1]-center[1], bc[0]-center[0]),
                         "sweep_angle": sign*angles[i], "ip_index": i, "source_row": points[i].get("source_row")})
        ip_stations[i] = station+length/2
        station += length
        cursor = ec
    line_to(xy[-1])
    ip_stations[-1] = station
    for i, p in enumerate(points):
        ip_output.append({**p, "ip_index": i, "original_radius": original[i], "effective_radius": radii[i],
                          "route_station": ip_stations[i], "original_xy": list(xy[i])})
    return NetworkAlignment(elements, ip_output, adjustments, start_station=start_station)
