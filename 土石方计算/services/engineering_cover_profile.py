"""Practical, continuous single-pipe axes for the section quantity workflow."""
from bisect import bisect_right
import hashlib
import json
import math

import numpy as np


def generate_engineering_cover_profile(tin, alignment, pipes, *, cover_depth=2.5,
        cover_segments=None, sample_step=10., spacing=0., max_abs_slope=20., cancelled=None):
    from .design_profiles import (DesignProfileError, prepare_pipe_layout,
        normalize_design_profile, evaluate_profile, _arc_terrain_breaks, _check_cover_cancelled)
    from .network_project import select_network_terrain
    from .finite_pipe_sections import pipe_top_envelope
    from .workbench_identity import COMPUTATION_CONTRACT
    from ..core.tin_interpolator import TINInterpolator

    layout = prepare_pipe_layout(pipes, spacing)
    # Unequal parallel pipes still use the existing common-support convention.
    if len(layout) != 1 or abs(layout[0]["offset"]) > 1e-8:
        from .design_profiles import generate_cover_profile
        return generate_cover_profile(tin, alignment, pipes, cover_depth=cover_depth,
            cover_segments=cover_segments, sample_step=sample_step, spacing=spacing,
            max_abs_slope=max_abs_slope, sampling_policy="exact", cancelled=cancelled)
    depth, step = float(cover_depth), float(sample_step)
    if not math.isfinite(depth) or depth < 0 or not math.isfinite(step) or step <= 0:
        raise DesignProfileError("管顶覆土须非负，采样间距须为正")
    start, end = alignment.start_station, alignment.end_station
    segments = sorted(cover_segments or [{"station_start": start, "station_end": end,
                                           "cover_depth": depth}], key=lambda r:r["station_start"])
    cursor = start
    for row in segments:
        a,b,d = (float(row[k]) for k in ("station_start","station_end","cover_depth"))
        if not all(math.isfinite(v) for v in (a,b,d)) or abs(a-cursor)>1e-7 or b<=a or d<0 or b>end+1e-7:
            raise DesignProfileError("分段覆土须连续覆盖当前管段，且覆土不得为负")
        cursor = b
    if abs(cursor-end)>1e-7:
        raise DesignProfileError("分段覆土未覆盖管段末端")
    def requested(s):
        return max(float(r["cover_depth"]) for r in segments
                   if r["station_start"]-1e-7 <= s <= r["station_end"]+1e-7)

    # Keep original faces. Terrain events are coverage checks, not extra bends
    # in the pipe. A continuous axis datum avoids artificial jumps at grades.
    local = select_network_terrain(tin, {"alignment":alignment}, width=10.+layout[0]["outer_diameter"], cancelled=cancelled)
    interp = TINInterpolator(local)
    controls = [*np.linspace(start,end,max(1,math.ceil((end-start)/step))+1),
                *(r[k] for r in segments for k in ("station_start","station_end"))]
    controls = np.asarray(sorted(set(round(float(s),9) for s in controls)), dtype=float)
    controls[0],controls[-1] = start,end
    probes = [*controls,*alignment.sample_stations(step)]
    for e in alignment.elements:
        _check_cover_cancelled(cancelled)
        if e["kind"] == "line":
            theta = e["tangent_angle"]
            line = interp.section_line(e["start_xy"], (math.cos(theta),math.sin(theta)), 0.,e["length"])
            probes.extend(e["station_start"]+float(p[0]) for p in line)
            probes.extend(e["station_start"]+(float(a[0])+float(b[0]))/2 for a,b in zip(line,line[1:]))
        else:
            events,_ = _arc_terrain_breaks(local,e,layout[0])
            probes.extend(events)
    probes = np.asarray(sorted(set(round(max(start,min(end,float(s))),9) for s in probes)),dtype=float)
    probes = np.unique(np.r_[probes,(probes[:-1]+probes[1:])/2])
    probe_xy = np.asarray([alignment.get_xy_at_station(float(s)) for s in probes])
    ground = interp.query_batch(probe_xy)
    if not np.isfinite(ground).all():
        s=float(probes[np.flatnonzero(~np.isfinite(ground))[0]])
        raise DesignProfileError(f"桩号 {s:.3f} 管道上方缺测地形",code="missing_terrain",station=s)
    radius = layout[0]["outer_diameter"]/2
    control_ground = interp.query_batch(np.asarray([alignment.get_xy_at_station(float(s)) for s in controls]))
    clearance=.01  # Small construction allowance between terrain probes.
    axis = control_ground-np.asarray([requested(s) for s in controls])-radius-clearance
    cells = np.clip(np.searchsorted(controls,probes,side="right")-1,0,len(controls)-2)
    left_cells = np.clip(np.searchsorted(controls,probes,side="left")-1,0,len(controls)-2)
    targets = np.asarray([requested(float(s))+clearance for s in probes])
    starts = [e["station_start"] for e in alignment.elements]
    def element_at(s,side="right"):
        index=max(0,min(len(starts)-1,bisect_right(starts,float(s)+1e-8)-1))
        if side=="left" and index>0 and abs(float(s)-starts[index])<1e-7:index-=1
        return alignment.elements[index]
    def curvature(s,side="right"):
        e=element_at(s,side)
        return math.copysign(1/e["radius"],e["sweep_angle"]) if e["kind"]=="arc" else 0.
    for _ in range(32):
        _check_cover_cancelled(cancelled)
        slopes=np.diff(axis)/np.diff(controls)
        if np.max(np.abs(slopes))>float(max_abs_slope):
            raise DesignProfileError("地形生成管轴出现近竖直过渡，请核对地形或管道控制高程",code="near_vertical_profile")
        reductions=np.zeros(len(axis))
        minimum_cover=math.inf
        for side,active_cells in (("left",left_cells),("right",cells)):
            _check_cover_cancelled(cancelled)
            envelopes=[pipe_top_envelope(radius,0.,curvature(s,side),slopes[c]) for s,c in zip(probes,active_cells)]
            heights=np.asarray([e[0] for e in envelopes]);offsets=np.asarray([e[1] for e in envelopes])
            tangents=np.asarray([alignment.get_tangent_angle_at_station(float(s)) for s in probes])
            top_xy=probe_xy+np.column_stack([offsets*np.sin(tangents),-offsets*np.cos(tangents)])
            crown_ground=interp.query_batch(top_xy)
            if not np.isfinite(crown_ground).all():
                s=float(probes[np.flatnonzero(~np.isfinite(crown_ground))[0]])
                raise DesignProfileError(f"桩号 {s:.3f} 管顶上方缺测地形",code="missing_terrain",station=s)
            fractions=(probes-controls[active_cells])/(controls[active_cells+1]-controls[active_cells])
            elevations=axis[active_cells]*(1-fractions)+axis[active_cells+1]*fractions
            covers=crown_ground-elevations-heights
            minimum_cover=min(minimum_cover,float(np.min(covers)))
            deficits=np.maximum(0.,targets-covers)
            # Retain both real grade limits at each axis knot.
            np.maximum.at(reductions,active_cells,deficits)
            np.maximum.at(reductions,active_cells+1,deficits)
        if float(np.max(reductions))<1e-6:break
        axis-=reductions
    else:
        raise DesignProfileError("覆土纵断面未收敛，请核对管段地形",code="cover_profile_not_converged")
    points=[{"station":float(s),"elevation":float(z)} for s,z in zip(controls,axis)]
    profile=normalize_design_profile(points,reference="pipe_axis")
    samples=[]
    for s,z,g in zip(controls,axis,control_ground):
        _check_cover_cancelled(cancelled)
        _,left=evaluate_profile(profile,float(s),"left")
        _,right=evaluate_profile(profile,float(s),"right")
        height=max(pipe_top_envelope(radius,0.,curvature(s,side),k)[0] for side,k in (("left",left),("right",right)))
        samples.append({"station":float(s),"common_outer_bottom":float(z-height),"requested_cover":requested(s),
            "controlling_pipe_index":0,"pipes":[{"pipe_index":0,"offset":0.,"ground_elevation":float(g),
            "outer_bottom":float(z-height),"axis_elevation":float(z),"outer_top":float(z+height),
            "actual_cover":float(g-z-height)}]})
    identity=hashlib.sha256(json.dumps({"profile":profile,"pipes":layout,"depths":segments,
        "sampling_policy":"engineering","calculation_contract":COMPUTATION_CONTRACT},sort_keys=True,allow_nan=False).encode()).hexdigest()
    return {"design_profile":profile,"profile_points":points,"pipes":layout,"samples":samples,
        "confirmed":False,"valid":True,"source":"terrain_and_user_cover_depth","preview_sha256":identity,
        "calculation_contract":COMPUTATION_CONTRACT,"sampling_policy":"engineering",
        "coverage_probe_count":len(probes),"minimum_checked_cover":minimum_cover,"construction_clearance_m":clearance,
        "diagnostics":[{"code":"engineering_cover_profile","severity":"info",
        "message":"按地形及填写覆土生成连续管轴；常规间距控制高程，原地形折点用于覆土检查。"}]}
